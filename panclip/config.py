"""Runtime settings, read once at startup from the command line and the environment."""

import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from panclip import __version__

TRUE = {"1", "true", "yes", "on"}
FALSE = {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    allow_cloud: bool = False
    max_content_chars: int = 50_000
    max_clips: int = 10_000
    max_age_days: float = 0
    redis_url: str | None = None
    log_level: str = "WARNING"
    request_timeout: float = 30.0
    max_retries: int = 3

    @classmethod
    def load(
        cls, argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
    ) -> "Settings":
        env = os.environ if env is None else env
        parser = argparse.ArgumentParser(
            prog="panclip",
            description="PanClip MCP server: a local, searchable memory for AI agents (stdio).",
            epilog="Every other setting is an environment variable; see README.md.",
        )
        parser.add_argument(
            "--version", action="version", version=f"panclip {__version__}"
        )
        parser.add_argument(
            "--data-dir",
            help="Absolute data directory (default $PANCLIP_DATA_DIR, else $XDG_DATA_HOME/panclip, else ~/.local/share/panclip)",
        )
        parser.add_argument(
            "--allow-cloud",
            action="store_true",
            help="Allow cloud AI providers and non-loopback endpoints (default $PANCLIP_ALLOW_CLOUD, else off)",
        )
        args = parser.parse_args(argv)

        def number(name: str, kind: type, default: float, low: float, high: float):
            raw = env.get(name, "").strip()
            if not raw:
                return default
            try:
                value = kind(raw)
            except ValueError:
                parser.error(f"{name} must be a number")
            if not low <= value <= high:
                parser.error(f"{name} must be between {low} and {high}")
            return value

        raw_cloud = env.get("PANCLIP_ALLOW_CLOUD", "").strip().lower()
        if raw_cloud not in TRUE | FALSE:
            parser.error("PANCLIP_ALLOW_CLOUD must be true or false")

        raw_dir = args.data_dir or env.get("PANCLIP_DATA_DIR", "").strip()
        if raw_dir:
            data_dir = Path(raw_dir).expanduser()
            if not data_dir.is_absolute():
                parser.error("the data directory must be an absolute path")
        else:
            xdg = env.get("XDG_DATA_HOME", "").strip()
            base = (
                Path(xdg)
                if xdg and Path(xdg).is_absolute()
                else Path.home() / ".local" / "share"
            )
            data_dir = base / "panclip"

        log_level = env.get("PANCLIP_LOG_LEVEL", "WARNING").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            parser.error("PANCLIP_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")

        return cls(
            data_dir=data_dir,
            allow_cloud=args.allow_cloud or raw_cloud in TRUE,
            max_content_chars=number(
                "PANCLIP_MAX_CONTENT_CHARS", int, 50_000, 1, 1_000_000
            ),
            max_clips=number("PANCLIP_MAX_CLIPS", int, 10_000, 0, 10_000_000),
            max_age_days=number("PANCLIP_MAX_AGE_DAYS", float, 0, 0, 36_500),
            redis_url=env.get("PANCLIP_REDIS_URL", "").strip() or None,
            log_level=log_level,
            request_timeout=number("PANCLIP_REQUEST_TIMEOUT", float, 30.0, 1, 600),
            max_retries=number("PANCLIP_MAX_RETRIES", int, 3, 0, 10),
        )
