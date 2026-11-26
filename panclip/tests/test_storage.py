"""Tests for LanceDB storage backend."""

import shutil
import tempfile
from unittest.mock import patch

import pytest

from panclip.core.storage import ClipStorage


@pytest.fixture
def temp_db_path(monkeypatch):
    """Create a temporary directory for the LanceDB database and set the env var."""
    temp_dir = tempfile.mkdtemp()
    # Patch getcwd to make ClipStorage use the temp directory
    monkeypatch.setattr("os.getcwd", lambda: temp_dir)
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestClipStorage:
    """Test LanceDB storage functionality."""

    @pytest.mark.asyncio
    async def test_storage_initialization(self, temp_db_path):
        """Test storage initialization creates the database and table."""
        storage = ClipStorage()
        await storage._ensure_initialized()
        assert storage._initialized is True
        assert storage.table.count_rows() == 0

    @pytest.mark.asyncio
    async def test_store_and_search_clip(self, temp_db_path):
        """Test storing a clip and then searching for it."""
        storage = ClipStorage()
        await storage._ensure_initialized()

        clip_id = "test_clip_1"
        content = "This is a test clip for storage and search."
        embedding = [0.1] * 768
        tags = ["test", "lancedb"]
        metadata = {"source": "manual", "timestamp": 100}

        store_result = await storage.store(clip_id, content, embedding, tags, metadata)
        assert store_result is True

        search_results = await storage.search(embedding, limit=1)
        assert len(search_results) == 1
        assert search_results[0]["id"] == clip_id

    @pytest.mark.asyncio
    async def test_store_clip_without_embedding(self, temp_db_path):
        """Test storing clip without embedding uses zero-vector fallback."""
        storage = ClipStorage()
        await storage._ensure_initialized()
        
        with patch.object(storage.table, "add") as mock_add:
            result = await storage.store("test_clip", "content", None, [], {"timestamp": 100})
            assert result is True
            
            call_args = mock_add.call_args[0][0][0]
            assert call_args["embedding"] == [0.0] * 768

    @pytest.mark.asyncio
    async def test_list_recent_clips(self, temp_db_path):
        """Test listing recent clips with proper sorting."""
        storage = ClipStorage()
        await storage._ensure_initialized()

        await storage.store("c1", "first", [0.1]*768, [], {"timestamp": 100})
        await storage.store("c2", "second", [0.2]*768, [], {"timestamp": 200})
        await storage.store("c3", "third", [0.3]*768, [], {"timestamp": 150})

        results = await storage.list_recent(limit=2)
        assert len(results) == 2
        assert results[0]["id"] == "c2"

    @pytest.mark.asyncio
    async def test_remove_clip(self, temp_db_path):
        """Test clip removal functionality."""
        storage = ClipStorage()
        await storage._ensure_initialized()

        clip_id = "clip_to_remove"
        await storage.store(clip_id, "content", [0.1]*768, [], {"timestamp": 100})

        remove_result = await storage.remove(clip_id)
        assert remove_result is True

        count = storage.table.count_rows()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, temp_db_path):
        """Test statistics generation."""
        storage = ClipStorage()
        await storage._ensure_initialized()

        await storage.store("c1", "short", [0.1]*768, ["a"], {"source": "agent", "is_agent": True, "timestamp": 100})
        await storage.store("c2", "longer", [0.2]*768, ["a", "b"], {"source": "agent", "is_agent": True, "timestamp": 200})
        await storage.store("c3", "longest", [0.3]*768, ["b"], {"source": "manual", "is_agent": False, "timestamp": 150})

        stats = await storage.get_stats()

        assert stats["total_clips"] == 3
        assert stats["agent_clips"] == 2
        assert stats["manual_clips"] == 1
