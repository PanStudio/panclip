import pytest

from panclip.core.ai_detector import AIDetector


@pytest.fixture(autouse=True)
def no_provider_probes(monkeypatch):
    """Tests never probe real ports; a test that needs providers patches detect itself."""

    async def detect(self):
        return []

    monkeypatch.setattr(AIDetector, "detect", detect)
