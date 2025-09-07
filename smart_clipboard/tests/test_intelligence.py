"""Tests for LiteLLM intelligence layer."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from smart_clipboard.core.ai_detector import AIProvider
from smart_clipboard.core.intelligence import UniversalIntelligence


@pytest.fixture
def mock_provider():
    """Fixture for a mock AI provider."""
    provider = Mock(spec=AIProvider)
    provider.name = "mock_provider"
    provider.type = "local"
    provider.api_base = "http://localhost:1234"
    provider.embedding_models = ["mock-embedding-model"]
    provider.chat_models = ["mock-chat-model"]
    return provider


@pytest.fixture
def intelligence(mock_provider):
    """Fixture to create a UniversalIntelligence instance with a mocked detector and router."""
    with patch("smart_clipboard.core.intelligence.AIDetector") as mock_ai_detector, \
         patch("smart_clipboard.core.intelligence.Router") as mock_router:

        # Configure the mock AI detector
        mock_detector_instance = mock_ai_detector.return_value
        mock_detector_instance.detect_all_providers = AsyncMock(return_value=[mock_provider])
        mock_detector_instance.get_best_providers.return_value = {
            "local_embedding": mock_provider,
            "cloud_embedding": None,
            "local_chat": mock_provider,
            "cloud_chat": None,
        }

        # Configure the mock Router
        mock_router_instance = mock_router.return_value
        mock_router_instance.aembedding = AsyncMock()
        mock_router_instance.acompletion = AsyncMock()

        # Initialize UniversalIntelligence
        intel = UniversalIntelligence()
        return intel


class TestClipIntelligence:
    """Test AI intelligence functionality."""

    @pytest.mark.asyncio
    async def test_generate_embedding_success(self, intelligence):
        """Test successful embedding generation."""
        mock_response = Mock()
        mock_response.data = [{"embedding": [0.1, 0.2, 0.3]}]
        intelligence.router.aembedding.return_value = mock_response

        result = await intelligence.generate_embedding("test content that is long enough")

        assert result == [0.1, 0.2, 0.3]
        intelligence.router.aembedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_embedding_fallback(self, intelligence):
        """Test embedding fallback when LiteLLM fails."""
        intelligence.router.aembedding.side_effect = Exception("API Error")

        result = await intelligence.generate_embedding("test content that is long enough")

        assert result is not None
        assert len(result) == 768
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_generate_embedding_without_litellm(self):
        """Test embedding generation when LiteLLM is not available."""
        with patch("smart_clipboard.core.intelligence.LITELLM_AVAILABLE", False):
            intel = UniversalIntelligence()
            result = await intel.generate_embedding("test content that is long enough")

            assert result is not None
            assert len(result) == 768

    @pytest.mark.asyncio
    async def test_generate_tags_success(self, intelligence):
        """Test successful tag generation."""
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = '''["python", "web", "tutorial"]'''
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        intelligence.router.acompletion.return_value = mock_response

        result = await intelligence.generate_tags("Python web development tutorial")

        assert result == ["python", "web", "tutorial"]
        intelligence.router.acompletion.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_tags_malformed_json(self, intelligence):
        """Test tag generation with malformed JSON response."""
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = '''Tags: "python", "web", "tutorial"'''
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        intelligence.router.acompletion.return_value = mock_response

        result = await intelligence.generate_tags("Python web development tutorial")

        assert "python" in result
        assert "web" in result
        assert "tutorial" in result

    @pytest.mark.asyncio
    async def test_generate_tags_fallback(self, intelligence):
        """Test tag generation fallback."""
        intelligence.router.acompletion.side_effect = Exception("API Error")

        result = await intelligence.generate_tags(
            "def hello_world(): print('Hello, World!') # A python function"
        )

        assert "python" in result

    @pytest.mark.asyncio
    async def test_should_store_valuable_content(self, intelligence):
        """Test content value assessment for agent mode."""
        code_content = "def calculate_fibonacci(n):\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)"
        assert await intelligence.should_store(code_content) is True

        tutorial_content = "How to set up Docker for your project: first, create a Dockerfile and then run docker build."
        assert await intelligence.should_store(tutorial_content) is True

    def test_fallback_tags_logic(self, intelligence):
        """Test the rule-based tag generation logic."""
        assert "python" in intelligence._fallback_tags("import os")
        assert "javascript" in intelligence._fallback_tags("function hello()")
        assert "docker" in intelligence._fallback_tags("docker-compose up")
        assert "git" in intelligence._fallback_tags("git commit -m 'fix'")
        assert "troubleshooting" in intelligence._fallback_tags("Error: file not found")

    @pytest.mark.asyncio
    async def test_long_content_truncation(self, intelligence):
        """Test that long content is properly truncated for embedding."""
        long_content = "x" * 9000
        intelligence.router.aembedding.return_value = Mock(
            data=[{"embedding": [0.1] * 768}]
        )

        await intelligence.generate_embedding(long_content)

        call_args = intelligence.router.aembedding.call_args
        assert "input" in call_args.kwargs
        assert len(call_args.kwargs["input"]) == 8000

    @pytest.mark.asyncio
    async def test_tag_generation_limit(self, intelligence):
        """Test that tag generation respects limits."""
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = '''["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"]'''
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        intelligence.router.acompletion.return_value = mock_response

        result = await intelligence.generate_tags("test content that is long enough")

        assert len(result) == 5
