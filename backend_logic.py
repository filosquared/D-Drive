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
import sqlite3
from collections import deque
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

# ---------------------------------------------------------------------------
# Database for Resume Support
# ---------------------------------------------------------------------------

class UploadTracker:
    """Track upload/download progress in SQLite for resume support."""
    
    def __init__(self, db_path: str = "d_drive.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uploads (
                    file_id TEXT PRIMARY KEY,
                    original_path TEXT NOT NULL,
                    total_parts INTEGER NOT NULL,
                    uploaded_parts INTEGER DEFAULT 0,
                    chunk_size INTEGER NOT NULL,
                    channel_name TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS upload_progress (
                    file_id TEXT,
                    part_num INTEGER,
                    uploaded BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (file_id, part_num)
                )
            """)
            conn.commit()
    
    def create_upload_session(self, file_path: str, total_parts: int, chunk_size: int) -> str:
        """Create a new upload session."""
        file_id = hashlib.sha256(file_path.encode()).hexdigest()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO uploads 
                (file_id, original_path, total_parts, uploaded_parts, chunk_size, status)
                VALUES (?, ?, ?, 0, ?, 'uploading')
            """, (file_id, file_path, total_parts, chunk_size))
            conn.commit()
        return file_id
    
    def mark_part_uploaded(self, file_id: str, part_num: int):
        """Mark a part as uploaded."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO upload_progress (file_id, part_num, uploaded)
                VALUES (?, ?, TRUE)
            """, (file_id, part_num))
            cursor.execute("""
                UPDATE uploads 
                SET uploaded_parts = (
                    SELECT COUNT(*) FROM upload_progress 
                    WHERE file_id = ? AND uploaded = TRUE
                ) 
                WHERE file_id = ?
            """, (file_id, file_id))
            conn.commit()
    
    def get_upload_progress(self, file_id: str) -> dict:
        """Get upload progress for a file."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM uploads WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            if not row:
                return {"file_id": file_id, "status": "not_found"}
            
            columns = [desc[0] for desc in cursor.description]
            result = dict(zip(columns, row))
            
            # Get uploaded parts
            cursor.execute("""
                SELECT part_num FROM upload_progress 
                WHERE file_id = ? AND uploaded = TRUE
            """, (file_id,))
            uploaded_parts = [row[0] for row in cursor.fetchall()]
            result["uploaded_parts"] = uploaded_parts
            
            return result
    
    def clear_upload(self, file_id: str):
        """Clear upload session."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM uploads WHERE file_id = ?", (file_id,))
            cursor.execute("DELETE FROM upload_progress WHERE file_id = ?", (file_id,))
            conn.commit()


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
    """Shared base for progress-tracking file wrappers."""
    
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
    * ``is_busy`` is guarded by ``_busy_lock``.
    * ``logs`` is a bounded deque (max 5 000 entries).
    * All Discord activity runs on a dedicated asyncio event loop in a background daemon thread.
    """
    
    _MAX_LOGS = 5_000
    _MAX_CONCURRENT_UPLOADS = 5  # Discord rate limit friendly
    
    def __init__(self):
        self._TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
        self._SERVER_ID: int = int(os.environ.get("DISCORD_SERVER_ID", 0))
        
        if not self._TOKEN:
            raise ValueError("DISCORD_TOKEN environment variable is required.")
        if not self._SERVER_ID:
            raise ValueError("DISCORD_SERVER_ID environment variable is required.")
        
        self.logs: deque = deque(maxlen=self._MAX_LOGS)
        self.channels: list[str] = []
        self.speed_tracker = SpeedTracker()
        self._busy_lock = threading.Lock()
        self._is_busy = False
        self.upload_tracker = UploadTracker()
    
    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    
    def log(self, message: str):
        entry = f"[{time.strftime('%H:%M:%S')}] {message}"
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
    # Upload (with parallel support)
    # ------------------------------------------------------------------
    
    def split_and_upload(self, file_path: str) -> tuple[bool, str]:
        if not self._try_acquire_busy():
            return False, "Operation already in progress."
        threading.Thread(
            target=self._run_upload_logic,
            args=(file_path,),
            daemon=True
        ).start()
        return True, "Started upload process."
    
    def _run_upload_logic(self, file_path: str):
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                self.log(f"Splitting file: {file_path}")
                
                # Split file with checksums
                parts = file_splitter.split_file(
                    file_path,
                    output_dir=temp_dir,
                    callback=lambda msg, pct: self.log(f"{msg} ({pct}%)")
                )
                
                if not parts:
                    self.log("Error: No parts created.")
                    return
                
                # Pre-compute total upload size for progress tracking
                total = sum(os.path.getsize(p) for p in parts)
                self.speed_tracker.reset(total_bytes=total)
                
                # Create upload session for resume support
                file_id = self.upload_tracker.create_upload_session(
                    file_path, len(parts), file_splitter.CHUNK_SIZE
                )
                
                self.log(f"Created {len(parts)} parts ({total / 1_048_576:.1f} MB). Starting upload…")
                
                # Upload with parallel support
                asyncio.run(self._discord_upload(file_path, parts, file_id))
                self.log("Upload complete. Temp files cleaned up.")
        except Exception as exc:
            self.log(f"Upload error: {exc}")
        finally:
            self._release_busy()
    
    async def _discord_upload(self, original_file_path: str, file_parts: list[str], file_id: str):
        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        
        @client.event
        async def on_ready():
            try:
                guild = client.get_guild(self._SERVER_ID) or await client.fetch_guild(self._SERVER_ID)
                base_name = os.path.basename(original_file_path)
                channel_name = re.sub(r"[^a-z0-9\-_-]", "", base_name.lower().replace(" ", "-"))[:100]
                self.log(f"Creating channel: #{channel_name}…")
                
                # Check if channel already exists
                existing_channel = discord.utils.get(guild.text_channels, name=channel_name)
                if existing_channel:
                    channel = existing_channel
                    self.log(f"Using existing channel: #{channel.name}")
                else:
                    channel = await guild.create_text_channel(channel_name)
                
                # Parallel upload with ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=self._MAX_CONCURRENT_UPLOADS) as executor:
                    futures = []
                    for i, part in enumerate(file_parts, start=1):
                        part_name = os.path.basename(part)
                        future = executor.submit(
                            self._upload_single_part,
                            client, channel, part, part_name, file_id, i
                        )
                        futures.append(future)
                    
                    for future in as_completed(futures):
                        try:
                            await future
                        except Exception as e:
                            self.log(f"Upload failed for a part: {e}")
                
                self.log(f"Done! Uploaded {len(file_parts)} parts to #{channel.name}")
                
                # Clear upload session
                self.upload_tracker.clear_upload(file_id)
                
            except Exception as exc:
                self.log(f"Upload failed: {exc}")
            finally:
                await client.close()
        
        await client.start(self._TOKEN)
    
    async def _upload_single_part(
        self, client: discord.Client, channel: discord.TextChannel, 
        part_path: str, part_name: str, file_id: str, part_num: int
    ):
        """Upload a single part file to Discord."""
        try:
            self.log(f"Uploading part {part_num}: {part_name}")
            with ProgressReader(part_path, self.speed_tracker) as reader:
                await channel.send(
                    file=discord.File(fp=reader, filename=part_name)
                )
            # Mark part as uploaded for resume support
            self.upload_tracker.mark_part_uploaded(file_id, part_num)
            self.log(f"Uploaded part {part_num}")
        except Exception as e:
            self.log(f"Failed to upload part {part_num}: {e}")
            raise
    
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
                guild = client.get_guild(self._SERVER_ID) or await client.fetch_guild(self._SERVER_ID)
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
            target=self._run_download_logic,
            args=(channel_name, save_dir),
            daemon=True
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
                guild = client.get_guild(self._SERVER_ID) or await client.fetch_guild(self._SERVER_ID)
                channel = discord.utils.get(guild.text_channels, name=channel_name)
                
                if not channel:
                    self.log(f"Error: Channel '{channel_name}' not found.")
                    return
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    self.log(f"Scanning messages in #{channel.name}…")
                    
                    # Collect attachment metadata first
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
                    
                    # Parallel download
                    with ThreadPoolExecutor(max_workers=self._MAX_CONCURRENT_UPLOADS) as executor:
                        futures = []
                        for i, att in enumerate(attachments):
                            future = executor.submit(
                                self._download_single_part,
                                att, temp_dir, i + 1, len(attachments)
                            )
                            futures.append(future)
                        
                        for future in as_completed(futures):
                            try:
                                part_path = future.result()
                                if part_path:
                                    part_paths.append(part_path)
                            except Exception as e:
                                self.log(f"Failed to download part: {e}")
                    
                    if not part_paths:
                        self.log("No parts downloaded successfully.")
                        return
                    
                    self.log("All parts downloaded. Merging…")
                    
                    # Merge with checksum verification
                    original_name, final_path = file_splitter.merge_file(
                        part_paths,
                        output_dir=save_dir,
                        callback=lambda msg, pct: self.log(f"{msg} ({pct}%)")
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
    
    async def _download_single_part(
        self, attachment: discord.Attachment, temp_dir: str, part_num: int, total_parts: int
    ) -> Optional[str]:
        """Download a single part file from Discord."""
        try:
            local_path = os.path.join(temp_dir, attachment.filename)
            self.log(f" ↓ {attachment.filename} ({part_num}/{total_parts})")
            
            with ProgressWriter(local_path, self.speed_tracker) as writer:
                await attachment.save(writer)
            
            return local_path
        except Exception as e:
            self.log(f"Failed to download {attachment.filename}: {e}")
            return None


# Import base64 for Fernet key generation
import base64
import hashlib
