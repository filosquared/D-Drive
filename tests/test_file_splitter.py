"""
Unit tests for file_splitter.py
"""
import os
import tempfile
import shutil
import pytest
import hashlib
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_splitter import (
    split_file, merge_file, 
    ChecksumMismatchError, EncryptionError,
    _compute_checksum, _get_metadata_path
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample file for testing."""
    sample_path = os.path.join(temp_dir, "sample.txt")
    with open(sample_path, "w") as f:
        f.write("Hello, World! This is a test file." * 1000)
    return sample_path


class TestSplitMerge:
    """Test splitting and merging files."""
    
    def test_split_and_merge_basic(self, temp_dir, sample_file):
        """Test basic split and merge functionality."""
        chunk_size = 1024  # 1KB chunks
        output_dir = os.path.join(temp_dir, "split")
        
        # Split the file
        parts = split_file(sample_file, chunk_size=chunk_size, output_dir=output_dir)
        assert len(parts) > 0
        
        # Merge the parts
        original_name, merged_path = merge_file(parts, output_dir=temp_dir)
        assert original_name == "sample.txt"
        assert merged_path is not None
        assert os.path.exists(merged_path)
        
        # Verify merged file matches original
        with open(sample_file, "rb") as f1, open(merged_path, "rb") as f2:
            assert f1.read() == f2.read()
    
    def test_split_merge_with_metadata(self, temp_dir, sample_file):
        """Test that metadata is created and used."""
        chunk_size = 1024
        output_dir = os.path.join(temp_dir, "split")
        
        # Split the file
        parts = split_file(sample_file, chunk_size=chunk_size, output_dir=output_dir)
        
        # Check metadata file exists
        metadata_path = os.path.join(output_dir, _get_metadata_path("sample.txt"))
        assert os.path.exists(metadata_path)
        
        # Verify metadata content
        import json
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        assert metadata["original_filename"] == "sample.txt"
        assert metadata["total_parts"] == len(parts)
    
    def test_split_merge_with_checksums(self, temp_dir, sample_file):
        """Test that checksums are created and verified."""
        chunk_size = 1024
        output_dir = os.path.join(temp_dir, "split")
        
        # Split the file
        parts = split_file(sample_file, chunk_size=chunk_size, output_dir=output_dir)
        
        # Check that checksum files exist
        for part in parts:
            checksum_path = f"{part}.sha256"
            assert os.path.exists(checksum_path)
            
            # Verify checksum content
            with open(part, "rb") as f:
                part_data = f.read()
            expected_checksum = hashlib.sha256(part_data).hexdigest()
            with open(checksum_path, "r") as f:
                assert f.read().strip() == expected_checksum
        
        # Merge should work with valid checksums
        original_name, merged_path = merge_file(parts, output_dir=temp_dir)
        assert merged_path is not None
    
    def test_merge_with_invalid_checksum(self, temp_dir):
        """Test that merge fails with invalid checksum."""
        # Create a part file and a checksum file with mismatched content
        part_dir = os.path.join(temp_dir, "parts")
        os.makedirs(part_dir, exist_ok=True)
        
        part_path = os.path.join(part_dir, "test.txt.part001")
        with open(part_path, "wb") as f:
            f.write(b"test content")
        
        # Write an incorrect checksum
        with open(f"{part_path}.sha256", "w") as f:
            f.write("invalid_checksum")
        
        # Merge should fail with ChecksumMismatchError
        with pytest.raises(ChecksumMismatchError):
            merge_file([part_path], output_dir=temp_dir)
    
    def test_non_existent_file(self, temp_dir):
        """Test that split_file raises FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            split_file("/nonexistent/file.txt", output_dir=temp_dir)
    
    def test_empty_parts_list(self, temp_dir):
        """Test that merge_file raises ValueError for empty parts list."""
        with pytest.raises(ValueError):
            merge_file([], output_dir=temp_dir)


class TestChecksums:
    """Test checksum functionality."""
    
    def test_compute_checksum(self, temp_dir):
        """Test computing checksum of a file."""
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, "wb") as f:
            f.write(b"test content")
        
        expected_checksum = hashlib.sha256(b"test content").hexdigest()
        actual_checksum = _compute_checksum(test_file)
        
        assert actual_checksum == expected_checksum
    
    def test_checksum_consistency(self, temp_dir, sample_file):
        """Test that checksums are consistent across multiple runs."""
        checksum1 = _compute_checksum(sample_file)
        checksum2 = _compute_checksum(sample_file)
        
        assert checksum1 == checksum2


class TestMetadata:
    """Test metadata functionality."""
    
    def test_get_metadata_path(self):
        """Test generating metadata path."""
        assert _get_metadata_path("test.txt") == "test.txt.meta.json"
        assert _get_metadata_path("archive.zip") == "archive.zip.meta.json"


class TestEdgeCases:
    """Test edge cases."""
    
    def test_split_large_chunk_size(self, temp_dir, sample_file):
        """Test splitting with a chunk size larger than the file."""
        chunk_size = 1024 * 1024  # 1MB (larger than sample file)
        output_dir = os.path.join(temp_dir, "split")
        
        parts = split_file(sample_file, chunk_size=chunk_size, output_dir=output_dir)
        
        # Should create exactly 1 part
        assert len(parts) == 1
        
        # Merge should work
        original_name, merged_path = merge_file(parts, output_dir=temp_dir)
        assert merged_path is not None
    
    def test_split_small_chunk_size(self, temp_dir, sample_file):
        """Test splitting with a very small chunk size."""
        chunk_size = 10  # 10 bytes
        output_dir = os.path.join(temp_dir, "split")
        
        parts = split_file(sample_file, chunk_size=chunk_size, output_dir=output_dir)
        
        # Should create many parts
        assert len(parts) > 1
        
        # Merge should work
        original_name, merged_path = merge_file(parts, output_dir=temp_dir)
        assert merged_path is not None
    
    def test_merge_to_existing_file(self, temp_dir, sample_file):
        """Test merging to a directory where the output file already exists."""
        chunk_size = 1024
        output_dir = os.path.join(temp_dir, "split")
        
        # Split the file
        parts = split_file(sample_file, chunk_size=chunk_size, output_dir=output_dir)
        
        # Create a file with the same name in the output directory
        existing_file = os.path.join(temp_dir, "sample.txt")
        with open(existing_file, "w") as f:
            f.write("existing content")
        
        # Merge should create a new file with _restored suffix
        original_name, merged_path = merge_file(parts, output_dir=temp_dir)
        assert merged_path is not None
        assert os.path.basename(merged_path) == "sample_restored.txt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
