"""Tests for MCP server functionality."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from panclip.mcp_server import PanClipMCPServer


@pytest.fixture
def server():
    """Create a test server instance with mocked dependencies."""
    with (
        patch("panclip.mcp_server.ClipStorage"),
        patch("panclip.mcp_server.UniversalIntelligence"),
        patch("panclip.mcp_server.ClipCache"),
    ):

        server_instance = PanClipMCPServer()

        # Replace dependencies with AsyncMocks
        server_instance.storage = AsyncMock()
        server_instance.ai = AsyncMock()
        server_instance.cache = AsyncMock()

        yield server_instance


class TestPanClipServer:
    """Test the main MCP server functionality."""

    @pytest.mark.asyncio
    async def test_handle_clip_add(self, server):
        """Test that clip_add returns quickly and queues background processing."""
        server.ai.should_store.return_value = True

        original_create_task = asyncio.create_task
        background_task = None

        def capture_task(coro):
            nonlocal background_task
            # Use the original function to avoid recursion
            background_task = original_create_task(coro)
            return background_task

        with patch("asyncio.create_task", side_effect=capture_task) as mock_create_task:
            content = "Test content for fast response"
            args = {"content": content, "source": "manual"}

            result = await server._handle_clip_add(args)

            assert result["status"] == "stored"
            assert "id" in result
            server.cache.set.assert_called_once()
            mock_create_task.assert_called_once()

            assert background_task is not None
            # Allow the background task to run
            await asyncio.sleep(0)
            # Now we can be sure the task is finished if it had no awaits
            # or we can check its done status
            assert background_task.done()

    @pytest.mark.asyncio
    async def test_handle_clip_search_cache_hit(self, server):
        """Test that clip_search returns from cache when available."""
        cached_result = {"query": "test", "results": [], "from_cache": False}
        server.cache.get.return_value = cached_result

        result = await server._handle_clip_search({"query": "test"})

        assert result["from_cache"] is True
        server.ai.generate_embedding.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_clip_search_cache_miss(self, server):
        """Test that clip_search queries storage on cache miss."""
        server.cache.get.return_value = None
        server.ai.generate_embedding.return_value = [0.1] * 768
        server.storage.search.return_value = [{"id": "a"}]

        result = await server._handle_clip_search({"query": "test"})

        assert result["from_cache"] is False
        server.ai.generate_embedding.assert_called_once()
        server.storage.search.assert_called_once()
        server.cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_clip_list(self, server):
        """Test listing clips functionality."""
        mock_clips = [{"id": "1"}, {"id": "2"}]
        server.storage.list_recent.return_value = mock_clips

        result = await server._handle_clip_list({"limit": 10})

        assert result["count"] == 2
        server.storage.list_recent.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_handle_clip_remove(self, server):
        """Test clip removal functionality."""
        clip_id = "test_clip_123"
        server.storage.remove.return_value = True

        result = await server._handle_clip_remove({"clip_id": clip_id})

        assert result["status"] == "removed"
        server.storage.remove.assert_called_once_with(clip_id)
        server.cache.delete.assert_called_once_with(clip_id)

    @pytest.mark.asyncio
    async def test_handle_clip_stats(self, server):
        """Test statistics functionality."""
        mock_stats = {"total_clips": 10}
        server.storage.get_stats.return_value = mock_stats

        result = await server._handle_clip_stats({})

        assert result == mock_stats
        server.storage.get_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_clip_background(self, server):
        """Test the full background processing pipeline."""
        clip_id = "test_id"
        clip_data = {
            "content": "some code to test `def main()`",
            "manual_tags": ["manual"],
            "source": "test",
            "timestamp": 123,
        }
        server.ai.generate_embedding.return_value = [0.5] * 768
        server.ai.generate_tags.return_value = ["auto_tag"]

        await server._process_clip_background(clip_id, clip_data)

        server.ai.generate_embedding.assert_called_once_with(clip_data["content"])
        server.ai.generate_tags.assert_called_once_with(clip_data["content"])
        server.storage.store.assert_called_once()

        # Check that tags are combined
        stored_tags = server.storage.store.call_args.kwargs["tags"]
        assert "manual" in stored_tags
        assert "auto_tag" in stored_tags

    def test_is_agent_source(self, server):
        """Test agent source detection."""
        assert server._is_agent_source("agent") is True
        assert server._is_agent_source("claude") is True
        assert server._is_agent_source("AI Assistant") is True
        assert server._is_agent_source("manual") is False

    def test_generate_clip_id(self, server):
        """Test clip ID generation is consistent and correct length."""
        content = "Test content"
        # Patch time to be constant
        with patch("time.time", return_value=12345.6789):
            clip_id1 = server._generate_clip_id(content)
            clip_id2 = server._generate_clip_id(content)
            assert clip_id1 == clip_id2
            assert len(clip_id1) == 16
