"""AI provider detection.

Only providers on a loopback address are used unless cloud use is allowed; an
API base pointing elsewhere counts as cloud because content would leave the
machine.
"""

import asyncio
import ipaddress
import logging
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_MARKERS = ("embed", "embedding")

LOCAL_SERVERS = [
    ("lmstudio", "LMSTUDIO_API_BASE", "http://localhost:1234", "/v1/models"),
    ("ollama", "OLLAMA_API_BASE", "http://localhost:11434", "/api/tags"),
    ("vllm", "VLLM_API_BASE", "http://localhost:8000", "/v1/models"),
    ("textgen_webui", "TEXTGEN_API_BASE", "http://localhost:5000", "/v1/models"),
    ("koboldcpp", "KOBOLDCPP_API_BASE", "http://localhost:5001", "/v1/models"),
]

CLOUD_PROVIDERS = [
    {
        "name": "openai",
        "key_env": "OPENAI_API_KEY",
        "embedding_models": ["text-embedding-3-small"],
        "chat_models": ["gpt-4o-mini"],
    },
    {
        "name": "anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "embedding_models": [],
        "chat_models": ["claude-3-5-haiku-latest"],
    },
    {
        "name": "gemini",
        "key_env": "GOOGLE_API_KEY",
        "embedding_models": ["text-embedding-004"],
        "chat_models": ["gemini-1.5-flash"],
    },
    {
        "name": "cohere",
        "key_env": "COHERE_API_KEY",
        "embedding_models": [],
        "chat_models": ["command-r"],
    },
    {
        "name": "groq",
        "key_env": "GROQ_API_KEY",
        "embedding_models": [],
        "chat_models": ["llama-3.1-8b-instant"],
    },
]


@dataclass
class AIProvider:
    """A reachable provider; `type` is "local" (loopback) or "cloud"."""

    name: str
    type: str
    api_base: str | None = None
    api_key: str | None = field(default=None, repr=False)
    embedding_models: list[str] = field(default_factory=list)
    chat_models: list[str] = field(default_factory=list)
    latency_ms: float | None = None


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_loopback(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return False
    return is_loopback_host(parsed.hostname or "")


class AIDetector:
    """Finds usable providers; cloud ones only when `allow_cloud` is set."""

    def __init__(self, allow_cloud: bool = False, timeout: float = 2.0, env=None):
        self.allow_cloud = allow_cloud
        self.timeout = timeout
        self.env = os.environ if env is None else env

    async def detect(self) -> list[AIProvider]:
        servers = []
        for name, base_env, default, models_path in LOCAL_SERVERS:
            base = self.env.get(base_env, default).rstrip("/")
            if not is_loopback(base) and not self.allow_cloud:
                logger.warning(
                    "%s is not a loopback address; ignored unless cloud use is allowed",
                    base_env,
                )
                continue
            servers.append((name, base, models_path))
        found = await asyncio.gather(*(self._probe(*server) for server in servers))
        providers = sorted(
            (p for p in found if p is not None), key=lambda p: p.latency_ms or 0.0
        )
        if self.allow_cloud:
            providers.extend(self._cloud_providers())
        return providers

    async def _probe(self, name: str, base: str, models_path: str):
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as http:
                response = await http.get(base + models_path)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.debug("%s not available: %s", name, type(error).__name__)
            return None
        entries = data.get("models" if name == "ollama" else "data", [])
        ids = [
            str(entry.get("name" if name == "ollama" else "id", ""))
            for entry in entries
            if isinstance(entry, dict)
        ]
        ids = [model for model in ids if model]
        embedding = [m for m in ids if any(k in m.lower() for k in EMBEDDING_MARKERS)]
        return AIProvider(
            name=name,
            type="local" if is_loopback(base) else "cloud",
            api_base=base,
            embedding_models=embedding,
            chat_models=[m for m in ids if m not in embedding],
            latency_ms=(time.monotonic() - start) * 1000,
        )

    def _cloud_providers(self) -> list[AIProvider]:
        providers = []
        for spec in CLOUD_PROVIDERS:
            key = self.env.get(spec["key_env"])
            if key:
                providers.append(
                    AIProvider(
                        name=spec["name"],
                        type="cloud",
                        api_key=key,
                        embedding_models=list(spec["embedding_models"]),
                        chat_models=list(spec["chat_models"]),
                    )
                )
        return providers


def pick(providers: list[AIProvider], kind: str) -> tuple[AIProvider, str] | None:
    """First provider offering a model of `kind` ("embedding" or "chat")."""
    for provider in providers:
        models = getattr(provider, f"{kind}_models")
        if models:
            return provider, models[0]
    return None
