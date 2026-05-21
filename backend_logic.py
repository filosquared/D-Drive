import re
import discord
import threading
import asyncio
import os
import file_splitter
import tempfile
import shutil
import time
import io
from collections import deque

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Speed / Progress helpers
# ---------------------------------------------------------------------------

class SpeedTracker:
    """Thread-safe tracker that measures I/O throughput over a rolling window."""

    def __init__(self, max_history: int = 60):
        self.history: deque = deque(maxlen=max_history)
        self.current_speed: float = 0.0
        self.last_update: float = time.time()
        self.bytes_since_last: int = 0
        self.bytes_done: int = 0
        self.total_bytes: int = 0
        self._lock = threading.Lock()

    def reset(self, total_bytes: int = 0):
        """Reset the tracker for a new operation."""
        with self._lock:
            self.current_speed = 0.0
            self.last_update = time.time()
            self.bytes_since_last = 0
            self.bytes_done = 0
            self.total_bytes = total_bytes
            self.history.clear()

    def update(self, byte_count: int):
        with self._lock:
            self.bytes_since_last += byte_count
            self.bytes_done += byte_count
            now = time.time()
            elapsed = now - self.last_update
            if elapsed >= 1.0:
                self.current_speed = self.bytes_since_last / elapsed
                self.history.append((now, self.current_speed))
                self.bytes_since_last = 0
                self.last_update = now

    def get_status(self) -> dict:
        with self._lock:
            # If idle for more than 2 s, report zero speed
            if time.time() - self.last_update > 2.0 and self.bytes_since_last == 0:
                self.current_speed = 0.0

            return {
                "current_speed": self.current_speed,
                "bytes_done": self.bytes_done,
                "total_bytes": self.total_bytes,
                "history": list(self.history),
            }


class _ProgressIOBase(io.RawIOBase):
    """
    Shared base for progress-tracking file wrappers.
    Delegates everything to a real file object and calls tracker.update()
    on reads/writes.
    """

    def __init__(self, file_path: str, mode: str, tracker: SpeedTracker):
        super().__init__()
        self._fp = open(file_path, mode)
        self._tracker = tracker

    # --- delegation ---------------------------------------------------------

    def seekable(self) -> bool:
        return self._fp.seekable()

    def readable(self) -> bool:
        return self._fp.readable()

    def writable(self) -> bool:
        return self._fp.writable()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._fp.seek(offset, whence)

    def tell(self) -> int:
        return self._fp.tell()

    def __getattr__(self, name):
        return getattr(self._fp, name)

    # --- lifecycle ----------------------------------------------------------

    def close(self):
        if not self.closed:
            try:
                self._fp.close()
            finally:
                super().close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ProgressReader(_ProgressIOBase):
    """Read-tracking wrapper for upload progress."""

    def __init__(self, file_path: str, tracker: SpeedTracker):
        super().__init__(file_path, "rb", tracker)

    def read(self, size: int = -1) -> bytes:
        data = self._fp.read(size)
        if data:
            self._tracker.update(len(data))
        return data

    def readinto(self, b) -> int:
        n = self._fp.readinto(b)
        if n:
            self._tracker.update(n)
        return n


class ProgressWriter(_ProgressIOBase):
    """Write-tracking wrapper for download progress."""

    def __init__(self, file_path: str, tracker: SpeedTracker):
        super().__init__(file_path, "wb", tracker)

    def write(self, data: bytes) -> int:
        written = self._fp.write(data)
        if written:
            self._tracker.update(written)
        return written


# ---------------------------------------------------------------------------
# Discord Manager
# ---------------------------------------------------------------------------

_PART_RE = re.compile(r"\.part\d+$")


class DiscordManager:
    """
    Manages all Discord operations: upload, scan, and download.

    Thread-safety notes
    -------------------
    * ``is_busy`` is guarded by ``_busy_lock``.  A caller must hold the lock
      while both checking and setting the flag to avoid TOCTOU races.
    * ``logs`` is a bounded deque (max 5 000 entries) to prevent unbounded
      memory growth.
    * All Discord activity runs on a dedicated asyncio event loop in a
      background daemon thread so Flask's request threads are never blocked.
    """

    _MAX_LOGS = 5_000

    def __init__(self):
        self._TOKEN: str = os.environ["DISCORD_TOKEN"]
        self._SERVER_ID: int = int(os.environ["DISCORD_SERVER_ID"])

        self.logs: deque = deque(maxlen=self._MAX_LOGS)
        self.channels: list[str] = []
        self.speed_tracker = SpeedTracker()

        self._busy_lock = threading.Lock()
        self._is_busy = False

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def log(self, message: str):
        entry = f"{time.strftime('[%H:%M:%S]')} {message}"
        self.logs.append(entry)
        print(entry)

    def get_logs(self, start_index: int = 0) -> list[str]:
        logs_list = list(self.logs)
        if start_index >= len(logs_list):
            return []
        return logs_list[start_index:]

    def get_status(self) -> dict:
        status = self.speed_tracker.get_status()
        with self._busy_lock:
            status["is_busy"] = self._is_busy
        return status

    # ------------------------------------------------------------------
    # Busy-lock helpers
    # ------------------------------------------------------------------

    def _try_acquire_busy(self) -> bool:
        """Atomically check and set the busy flag. Returns True on success."""
        with self._busy_lock:
            if self._is_busy:
                return False
            self._is_busy = True
            return True

    def _release_busy(self):
        with self._busy_lock:
            self._is_busy = False

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def split_and_upload(self, file_path: str) -> tuple[bool, str]:
        if not self._try_acquire_busy():
            return False, "Operation already in progress."
        threading.Thread(
            target=self._run_upload_logic, args=(file_path,), daemon=True
        ).start()
        return True, "Started upload process."

    def _run_upload_logic(self, file_path: str):
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                self.log(f"Splitting file: {file_path}")
                parts = file_splitter.split_file(file_path, output_dir=temp_dir)

                if not parts:
                    self.log("Error: No parts created.")
                    return

                # Pre-compute total upload size for progress tracking
                total = sum(os.path.getsize(p) for p in parts)
                self.speed_tracker.reset(total_bytes=total)

                self.log(f"Created {len(parts)} parts ({total / 1_048_576:.1f} MB). Starting upload…")
                asyncio.run(self._discord_upload(file_path, parts))
                self.log("Upload complete. Temp files cleaned up.")
        except Exception as exc:
            self.log(f"Upload error: {exc}")
        finally:
            self._release_busy()

    async def _discord_upload(self, original_file_path: str, file_parts: list[str]):
        intents = discord.Intents.default()
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            try:
                guild = client.get_guild(self._SERVER_ID) or await client.fetch_guild(
                    self._SERVER_ID
                )

                base_name = os.path.basename(original_file_path)
                channel_name = re.sub(r"[^a-z0-9\-_]", "", base_name.lower().replace(" ", "-"))[:100]

                self.log(f"Creating channel: #{channel_name}…")
                channel = await guild.create_text_channel(channel_name)

                for i, part in enumerate(file_parts, start=1):
                    self.log(f"Uploading part {i}/{len(file_parts)}: {os.path.basename(part)}")
                    with ProgressReader(part, self.speed_tracker) as reader:
                        await channel.send(
                            file=discord.File(fp=reader, filename=os.path.basename(part))
                        )

                self.log(f"Done! Uploaded {len(file_parts)} parts to #{channel.name}")
            except Exception as exc:
                self.log(f"Upload failed: {exc}")
            finally:
                await client.close()

        await client.start(self._TOKEN)

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan_server(self) -> tuple[bool, str]:
        if not self._try_acquire_busy():
            return False, "Operation already in progress."
        threading.Thread(target=self._run_scan_logic, daemon=True).start()
        return True, "Started scan process."

    def _run_scan_logic(self):
        try:
            asyncio.run(self._discord_scan())
        except Exception as exc:
            self.log(f"Scan error: {exc}")
        finally:
            self._release_busy()

    async def _discord_scan(self):
        intents = discord.Intents.default()
        intents.guilds = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            try:
                guild = client.get_guild(self._SERVER_ID) or await client.fetch_guild(
                    self._SERVER_ID
                )
                self.channels = [c.name for c in guild.text_channels]
                self.log(f"Found {len(self.channels)} text channels.")
            except Exception as exc:
                self.log(f"Scan failed: {exc}")
            finally:
                await client.close()

        await client.start(self._TOKEN)

    # ------------------------------------------------------------------
    # Download + merge
    # ------------------------------------------------------------------

    def download_and_merge(self, channel_name: str, save_dir: str) -> tuple[bool, str]:
        if not self._try_acquire_busy():
            return False, "Operation already in progress."
        threading.Thread(
            target=self._run_download_logic, args=(channel_name, save_dir), daemon=True
        ).start()
        return True, "Started download process."

    def _run_download_logic(self, channel_name: str, save_dir: str):
        try:
            asyncio.run(self._discord_download(channel_name, save_dir))
        except Exception as exc:
            self.log(f"Download error: {exc}")
        finally:
            self._release_busy()

    async def _discord_download(self, channel_name: str, save_dir: str):
        intents = discord.Intents.default()
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            try:
                guild = client.get_guild(self._SERVER_ID) or await client.fetch_guild(
                    self._SERVER_ID
                )
                channel = discord.utils.get(guild.text_channels, name=channel_name)

                if not channel:
                    self.log(f"Error: Channel '{channel_name}' not found.")
                    return

                with tempfile.TemporaryDirectory() as temp_dir:
                    self.log(f"Scanning messages in #{channel.name}…")

                    # Collect attachment metadata first (no limit — fetch everything)
                    attachments = []
                    async for message in channel.history(limit=None, oldest_first=True):
                        for att in message.attachments:
                            if _PART_RE.search(att.filename):
                                attachments.append(att)

                    if not attachments:
                        self.log("No .part files found in this channel.")
                        return

                    # Account for total download size
                    total_bytes = sum(a.size for a in attachments)
                    self.speed_tracker.reset(total_bytes=total_bytes)
                    self.log(
                        f"Found {len(attachments)} parts "
                        f"({total_bytes / 1_048_576:.1f} MB). Downloading…"
                    )

                    part_paths: list[str] = []
                    for att in attachments:
                        local_path = os.path.join(temp_dir, att.filename)
                        self.log(f"  ↓ {att.filename}")
                        with ProgressWriter(local_path, self.speed_tracker) as writer:
                            await att.save(writer)
                        part_paths.append(local_path)

                    self.log("All parts downloaded. Merging…")
                    original_name, final_path = file_splitter.merge_file(
                        part_paths, output_dir=save_dir
                    )
                    if final_path:
                        self.log(f"Success! Saved to: {final_path}")
                    else:
                        self.log("Error: Merge failed (no output produced).")

            except Exception as exc:
                self.log(f"Download failed: {exc}")
            finally:
                await client.close()

        await client.start(self._TOKEN)
