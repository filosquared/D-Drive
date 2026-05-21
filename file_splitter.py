"""
file_splitter.py
~~~~~~~~~~~~~~~~
Utilities for splitting large files into numbered parts and merging
them back into the original file.

Changes from original
---------------------
* merge_file() now accepts the already-collected list of part paths
  (no filesystem scanning) and an explicit output directory.
* merge_file() uses chunked-copy (shutil.copyfileobj) instead of
  reading entire chunks into memory.
* split_file() raises exceptions instead of silently printing errors.
* Sorting uses the embedded part number as an integer so
  part9 < part10 (not lexicographic).
"""

from __future__ import annotations

import os
import re
import shutil
import argparse

# Size of copy buffer used during merge (64 KiB)
_COPY_BUFSIZE = 64 * 1024


def split_file(
    file_path: str,
    chunk_size: int = 10 * 1024 * 1024,
    output_dir: str | None = None,
) -> list[str]:
    """
    Split *file_path* into chunks of *chunk_size* bytes.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the source file.
    chunk_size:
        Maximum size of each chunk in bytes.  Default: 10 MB.
    output_dir:
        Directory where part files are written.  Defaults to the
        directory that contains the source file.

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
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Source file not found: {file_path!r}")

    file_name = os.path.basename(file_path)
    base_dir = output_dir if output_dir else os.path.dirname(os.path.abspath(file_path))

    os.makedirs(base_dir, exist_ok=True)

    created_parts: list[str] = []
    with open(file_path, "rb") as f:
        part_num = 1
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break

            part_name = f"{file_name}.part{part_num:03d}"
            part_path = os.path.join(base_dir, part_name)

            with open(part_path, "wb") as part_file:
                part_file.write(chunk)

            created_parts.append(part_path)
            part_num += 1

    return created_parts


def merge_file(
    parts: list[str],
    output_dir: str | None = None,
    output_name: str | None = None,
) -> tuple[str, str | None]:
    """
    Merge a sorted list of part files back into a single file.

    Parameters
    ----------
    parts:
        List of **absolute** paths to the part files.  They are sorted
        by their embedded part number before merging so you can pass
        them in any order.
    output_dir:
        Directory where the merged file is written.  Defaults to the
        directory of the first part file.
    output_name:
        Override for the output file name.  Defaults to the original
        file name derived from the first part.

    Returns
    -------
    (original_name, output_path)
        *original_name* is the reconstructed original filename.
        *output_path* is the absolute path to the merged file, or
        ``None`` if the merge failed.
    """
    if not parts:
        raise ValueError("No part files supplied to merge_file().")

    # Derive the original name from any part filename
    first_base = os.path.basename(parts[0])
    original_name = re.sub(r"\.part\d+$", "", first_base)

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

    try:
        with open(output_path, "wb") as outfile:
            for part in sorted_parts:
                with open(part, "rb") as infile:
                    # Chunked copy – avoids loading the whole chunk into RAM
                    shutil.copyfileobj(infile, outfile, length=_COPY_BUFSIZE)
    except Exception:
        return original_name, None

    return original_name, output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
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
            print(f"  {p}")

    elif args.command == "merge":
        _, out = merge_file(args.parts, args.output_dir, args.output)
        if out:
            print(f"Merged file: {out}")
        else:
            print("Merge failed.")
    else:
        parser.print_help()
