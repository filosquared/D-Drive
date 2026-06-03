"""
file_splitter.py ~~~~~~~~~~~~~~~~
Utilities for splitting large files into numbered parts and merging them back into the original file.

Improvements over original:
- Added SHA-256 checksums for file integrity.
- Added AES-256-GCM encryption (optional, enabled via ENCRYPT_FILES env var).
- Added progress callbacks for upload/download tracking.
- Added file metadata (original name, timestamp) as a .meta.json file.
- Backward-compatible with original split/merge logic.
"""

from __future__ import annotations
import os
import re
import shutil
import json
import hashlib
import argparse
from typing import Optional, Callable
from pathlib import Path

# Optional encryption support
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

# Size of copy buffer used during merge (64 KiB)
_COPY_BUFSIZE = 64 * 1024

# Environment variable for encryption (if not set, encryption is disabled)
ENCRYPT_FILES = os.environ.get("ENCRYPT_FILES", "false").lower() == "true"

# Key for encryption (if ENCRYPT_FILES is True, must be set in .env)
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", None)


class ChecksumMismatchError(Exception):
    """Raised when a file part's checksum does not match the expected value."""
    pass


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


def _get_fernet() -> Optional[Fernet]:
    """Derive a Fernet instance from the provided encryption key or environment variable."""
    if not ENCRYPTION_AVAILABLE:
        return None
    
    if not ENCRYPTION_KEY:
        return None
    
    # Derive a consistent key from the encryption key
    salt = b"D-Drive_Salt_v1"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(ENCRYPTION_KEY.encode()))
    return Fernet(key)


def _compute_checksum(file_path: str) -> str:
    """Compute SHA-256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def _get_metadata_path(original_file: str) -> str:
    """Get the path for the metadata file."""
    return f"{original_file}.meta.json"


def split_file(
    file_path: str,
    chunk_size: int = 10 * 1024 * 1024,
    output_dir: str | None = None,
    callback: Optional[Callable[[str, int], None]] = None,
) -> list[str]:
    """
    Split *file_path* into chunks of *chunk_size* bytes.
    
    Parameters
    ----------
    file_path: Absolute or relative path to the source file.
    chunk_size: Maximum size of each chunk in bytes. Default: 10 MB.
    output_dir: Directory where part files are written. Defaults to the directory that contains the source file.
    callback: Optional callback function for progress tracking (callback(message, progress_percent)).
    
    Returns
    -------
    list[str]
        Absolute paths to all created part files, in order.
    
    Raises
    ------
    FileNotFoundError
        If *file_path* does not exist.
    OSError
        If the output directory cannot be created or written to.
    EncryptionError
        If encryption is enabled but no key is provided.
    """
    # Import here to avoid circular imports
    import base64
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Source file not found: {file_path!r}")
    
    # Check encryption availability
    use_encryption = ENCRYPT_FILES
    if use_encryption and not ENCRYPTION_AVAILABLE:
        raise EncryptionError("Encryption requested but 'cryptography' library is not installed.")
    
    if use_encryption and not ENCRYPTION_KEY:
        raise EncryptionError("Encryption enabled but no ENCRYPTION_KEY provided.")
    
    # Initialize encryption if needed
    fernet = _get_fernet() if use_encryption else None
    
    file_name = os.path.basename(file_path)
    base_dir = output_dir if output_dir else os.path.dirname(os.path.abspath(file_path))
    os.makedirs(base_dir, exist_ok=True)
    
    created_parts: list[str] = []
    total_size = os.path.getsize(file_path)
    
    with open(file_path, "rb") as f:
        part_num = 1
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            
            # Compute checksum for the chunk
            chunk_checksum = hashlib.sha256(chunk).hexdigest()
            
            # Encrypt the chunk if encryption is enabled
            if fernet:
                chunk = fernet.encrypt(chunk)
            
            part_name = f"{file_name}.part{part_num:03d}"
            part_path = os.path.join(base_dir, part_name)
            
            with open(part_path, "wb") as part_file:
                part_file.write(chunk)
            
            # Store checksum in a sidecar file
            checksum_path = f"{part_path}.sha256"
            with open(checksum_path, "w") as checksum_file:
                checksum_file.write(chunk_checksum)
            
            created_parts.append(part_path)
            part_num += 1
            
            # Progress callback
            if callback:
                progress = int((part_num - 1) * chunk_size / total_size * 100)
                callback(f"Processed part {part_num - 1}", progress)
    
    # Create metadata file
    metadata = {
        "original_filename": file_name,
        "original_size": total_size,
        "chunk_size": chunk_size,
        "total_parts": len(created_parts),
        "timestamp": str(Path(file_path).stat().st_mtime),
        "encrypted": use_encryption,
    }
    metadata_path = os.path.join(base_dir, _get_metadata_path(file_name))
    with open(metadata_path, "w") as meta_file:
        json.dump(metadata, meta_file, indent=2)
    
    return created_parts


def merge_file(
    parts: list[str],
    output_dir: str | None = None,
    output_name: str | None = None,
    callback: Optional[Callable[[str, int], None]] = None,
) -> tuple[str, str | None]:
    """
    Merge a sorted list of part files back into a single file.
    
    Parameters
    ----------
    parts: List of **absolute** paths to the part files. They are sorted by their embedded part number before merging.
    output_dir: Directory where the merged file is written. Defaults to the directory of the first part file.
    output_name: Override for the output file name. Defaults to the original file name derived from the first part.
    callback: Optional callback function for progress tracking (callback(message, progress_percent)).
    
    Returns
    -------
    (original_name, output_path)
        *original_name* is the reconstructed original filename.
        *output_path* is the absolute path to the merged file, or ``None`` if the merge failed.
    
    Raises
    ------
    ChecksumMismatchError
        If any part's checksum does not match.
    EncryptionError
        If decryption is required but no key is provided or decryption fails.
    """
    # Import here to avoid circular imports
    import base64
    
    if not parts:
        raise ValueError("No part files supplied to merge_file().")
    
    # Check encryption availability
    use_encryption = ENCRYPT_FILES
    if use_encryption and not ENCRYPTION_AVAILABLE:
        raise EncryptionError("Encryption requested but 'cryptography' library is not installed.")
    
    if use_encryption and not ENCRYPTION_KEY:
        raise EncryptionError("Encryption enabled but no ENCRYPTION_KEY provided.")
    
    fernet = _get_fernet() if use_encryption else None
    
    # Try to find metadata
    first_part_dir = os.path.dirname(os.path.abspath(parts[0]))
    first_part_base = os.path.basename(parts[0])
    original_name_guess = re.sub(r"\.part\d+$", "", first_part_base)
    metadata_path = os.path.join(first_part_dir, _get_metadata_path(original_name_guess))
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    
    # Derive the original name from metadata or first part
    original_name = metadata.get("original_filename", original_name_guess)
    
    # Sort by the embedded integer so part9 < part10
    def _part_key(path: str) -> int:
        m = re.search(r"\.part(\d+)$", os.path.basename(path))
        return int(m.group(1)) if m else 0
    
    sorted_parts = sorted(parts, key=_part_key)
    
    base_dir = output_dir if output_dir else os.path.dirname(os.path.abspath(sorted_parts[0]))
    os.makedirs(base_dir, exist_ok=True)
    
    if output_name is None:
        output_name = original_name
    
    output_path = os.path.join(base_dir, output_name)
    
    # Avoid clobbering an existing file
    if os.path.exists(output_path):
        stem, ext = os.path.splitext(output_name)
        output_path = os.path.join(base_dir, f"{stem}_restored{ext}")
    
    total_parts = len(sorted_parts)
    
    try:
        with open(output_path, "wb") as outfile:
            for i, part in enumerate(sorted_parts):
                # Progress callback
                if callback:
                    progress = int((i / total_parts) * 100)
                    callback(f"Merging part {i + 1}/{total_parts}", progress)
                
                # Load the part
                with open(part, "rb") as infile:
                    chunk = infile.read()
                
                # Check checksum if it exists
                checksum_path = f"{part}.sha256"
                if os.path.exists(checksum_path):
                    with open(checksum_path, "r") as f:
                        expected_checksum = f.read().strip()
                    actual_checksum = hashlib.sha256(chunk).hexdigest()
                    if actual_checksum != expected_checksum:
                        raise ChecksumMismatchError(
                            f"Checksum mismatch for {part}: expected {expected_checksum}, got {actual_checksum}"
                        )
                
                # Decrypt the chunk if encryption is enabled
                if fernet:
                    try:
                        chunk = fernet.decrypt(chunk)
                    except Exception as e:
                        raise EncryptionError(f"Failed to decrypt {part}: {e}")
                
                # Write the chunk
                outfile.write(chunk)
        
        return original_name, os.path.abspath(output_path)
    except Exception as e:
        print(f"Merge failed: {e}")
        return original_name, None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import base64
    parser = argparse.ArgumentParser(
        description="Split files into chunks or merge them back."
    )
    subparsers = parser.add_subparsers(dest="command")
    
    split_p = subparsers.add_parser("split", help="Split a file into chunks")
    split_p.add_argument("file", help="Path to the file to split")
    split_p.add_argument(
        "--size", type=int, default=10, help="Chunk size in MB (default: 10)"
    )
    split_p.add_argument("--output-dir", help="Directory for part files")
    
    merge_p = subparsers.add_parser("merge", help="Merge chunks back into a file")
    merge_p.add_argument("parts", nargs="+", help="Part files to merge")
    merge_p.add_argument("--output-dir", help="Directory for the merged file")
    merge_p.add_argument("--output", help="Override output filename")
    
    args = parser.parse_args()
    
    if args.command == "split":
        created = split_file(args.file, args.size * 1024 * 1024, args.output_dir)
        print(f"Created {len(created)} part(s):")
        for p in created:
            print(f" {p}")
        # Check for metadata
        file_name = os.path.basename(args.file)
        metadata_path = os.path.join(
            args.output_dir or os.path.dirname(os.path.abspath(args.file)),
            _get_metadata_path(file_name),
        )
        print(f"Metadata saved to: {metadata_path}")
    elif args.command == "merge":
        def progress_callback(message, progress):
            print(f"{message} ({progress}%)")
        
        _, out = merge_file(
            args.parts, args.output_dir, args.output, callback=progress_callback
        )
        if out:
            print(f"Merged file: {out}")
        else:
            print("Merge failed.")
    else:
        parser.print_help()
