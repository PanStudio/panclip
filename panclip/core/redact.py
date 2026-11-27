"""Secret detection and redaction, applied before content is stored or sent to a provider."""

import math
import re
from collections import Counter

KNOWN_FORMATS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?"
            r"(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
            re.S,
        ),
    ),
    ("jwt", re.compile(r"\beyJ[\w-]{5,}\.eyJ[\w-]{5,}\.[\w-]{10,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_\w{22,255})\b"),
    ),
    ("gitlab_token", re.compile(r"\bglpat-[\w-]{20,}")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[\w-]{35}")),
    ("stripe_key", re.compile(r"\b[spr]k_(?:live|test)_[0-9A-Za-z]{16,}")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("api_key", re.compile(r"\bsk-(?:ant-|proj-|svcacct-|admin-)?[\w-]{20,}")),
]
URL_PASSWORD = re.compile(r"\b([a-z][a-z0-9+.-]*://[^\s:/?#@]*:)([^\s@/?#]+)(@)", re.I)
AUTH_HEADER = re.compile(
    r"\b((?:authorization|proxy-authorization)[\"']?\s*[:=]\s*[\"']?"
    r"(?:bearer|basic|token|digest)\s+)([\w.~+/=-]{8,})",
    re.I,
)
SECRET_KEY = re.compile(
    r"(?:secret|token|passw(?:or)?d|passwd|pwd|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credential|auth[_-]?key)",
    re.I,
)
ASSIGNMENT = re.compile(
    r"(?P<key>\b[A-Za-z_][\w.-]{0,63})(?P<sep>[\"']?\s*[:=]\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted>[^\s\"']{6,})(?P=quote)"
    r"|(?P<bare>[^\s\"'`,;()\[\]{}<>]{6,})(?=$|[\s\"'`,;)\]}>]))",
    re.M,
)
QUERY_SECRET = re.compile(
    r"([?&;](?:access_token|refresh_token|id_token|token|secret|client_secret|"
    r"password|passwd|pwd|api_key|apikey|key|sig|signature)=)([^&#\s\"'`]{6,})",
    re.I,
)
WORD_RUN = re.compile(r"[A-Z]?[a-z]{3,}")


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Replace secrets with `[REDACTED:<kind>]`; return the text and a count per kind."""
    counts: Counter[str] = Counter()

    def mark(kind: str) -> str:
        counts[kind] += 1
        return f"[REDACTED:{kind}]"

    for kind, pattern in KNOWN_FORMATS:
        text = pattern.sub(lambda _m, kind=kind: mark(kind), text)
    text = URL_PASSWORD.sub(lambda m: m[1] + mark("url_password") + m[3], text)
    text = AUTH_HEADER.sub(lambda m: m[1] + mark("auth_header"), text)
    text = QUERY_SECRET.sub(lambda m: m[1] + mark("url_query_secret"), text)

    def assignment(match: re.Match[str]) -> str:
        value = match["quoted"] or match["bare"]
        if value.startswith("[REDACTED:"):
            return match[0]
        if SECRET_KEY.search(match["key"]) and (
            match["quoted"]
            or match["key"].isupper()
            or not any(ch.isspace() for ch in match["sep"])
            or any(ch.isdigit() for ch in value)
        ):
            return _replace_value(match, mark("secret_assignment"))
        if _looks_random(value):
            return _replace_value(match, mark("high_entropy"))
        return match[0]

    text = ASSIGNMENT.sub(assignment, text)
    return text, dict(counts)


def _replace_value(match: re.Match[str], replacement: str) -> str:
    quote = match["quote"] or ""
    return f"{match['key']}{match['sep']}{quote}{replacement}{quote}"


def _looks_random(value: str) -> bool:
    """A long token mixing cases and digits, with high entropy and few word-like runs."""
    if len(value) < 20:
        return False
    if not (
        any(ch.islower() for ch in value)
        and any(ch.isupper() for ch in value)
        and any(ch.isdigit() for ch in value)
    ):
        return False
    counts = Counter(value)
    entropy = -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())
    words = sum(len(run) for run in WORD_RUN.findall(value))
    return entropy >= 3.5 and words / len(value) < 0.5
