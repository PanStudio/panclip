# PanClip MCP Server

Give AI agents persistent memory with intelligent clipboard management.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-2026--07--28%20%2B%20legacy-orange.svg)](https://modelcontextprotocol.io)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

## Why PanClip?

When working with AI agents like Claude, context is lost between conversations. Code snippets, configurations, and solutions disappear. PanClip solves this by giving agents a persistent, searchable memory they can write to and read from across sessions.

**Built for developers who use AI agents to code.**

## Key Features

- **Persistent Memory**: Store code, configs, and solutions across sessions
- **Semantic Search**: Find content using natural language, with a local embedding model or offline word matching
- **Auto-Tagging**: Topic tags from a local chat model, or keyword rules offline
- **Local by Default**: Only AI servers on a loopback address (LM Studio, Ollama, vLLM, text-generation-webui, KoboldCpp) are used unless you allow cloud providers
- **Secret Redaction**: API keys, tokens, private keys and passwords are replaced with `[REDACTED:<kind>]` before anything is stored or sent to a model
- **Bounded Storage**: Size cap per clip, and count and age retention limits
- **MCP 2026-07-28 and earlier**: Serves both the stateless 2026-07-28 protocol and the `initialize` handshake of earlier revisions over stdio

## Installation

### For Claude Desktop Users

```bash
# Install from GitHub
claude mcp add panclip -- uvx --from git+https://github.com/PanStudio/panclip.git panclip

# Or clone and run locally
git clone https://github.com/PanStudio/panclip.git
cd panclip
claude mcp add panclip -- uv --directory "$(pwd)" run panclip
```

### For Development

```bash
git clone https://github.com/PanStudio/panclip.git
cd panclip
uv sync
uv run panclip
```

## Usage

Once connected to Claude Desktop, the agent can:

```text
Store: "Save this Docker configuration for Python microservices"
Search: "Find that nginx reverse proxy config from yesterday"
List: "Show my recent code snippets"
```

### Available MCP Tools

| Tool | What it does | Annotations |
| --- | --- | --- |
| `clip_add` | Stores text (redacted, tagged, embedded) and returns its id once the write is durable | writes |
| `clip_search` | Natural-language search, best match first; pages with `cursor` | read only |
| `clip_list` | Newest clips first with a short preview; pages with `cursor` | read only |
| `clip_remove` | Deletes one clip by id | destructive |
| `clip_stats` | Counts, top tags, provider mode and the limits in force | read only |

Every tool returns structured content with an output schema. Clip text comes back in a
`stored_content` field marked as stored data, cut to `max_chars` with a `truncated` flag.
Failures are tool errors (`isError`) with a recovery hint and never repeat the arguments.

## Configuration

PanClip is configured by environment variables and two flags; it reads no config file and
no `.env` file. Put variables in the `env` block of your MCP client's server entry.
[`.env.example`](.env.example) lists them all with their defaults.

| Setting | Default | Meaning |
| --- | --- | --- |
| `--data-dir` or `PANCLIP_DATA_DIR` | `$XDG_DATA_HOME/panclip`, else `~/.local/share/panclip` | Absolute data directory, the same whatever the launch directory |
| `--allow-cloud` or `PANCLIP_ALLOW_CLOUD` | off | Allow cloud providers and non-loopback servers |
| `PANCLIP_MAX_CONTENT_CHARS` | 50000 | Longest clip accepted |
| `PANCLIP_MAX_CLIPS` | 10000 | Oldest clips beyond this are deleted after each write; 0 keeps all |
| `PANCLIP_MAX_AGE_DAYS` | 0 | Clips older than this are deleted after each write; 0 keeps all |
| `PANCLIP_REDIS_URL` | unset | Shared search cache, for example `redis://:password@localhost:6379/0` |
| `PANCLIP_REQUEST_TIMEOUT`, `PANCLIP_MAX_RETRIES` | 30, 3 | Provider call timeout in seconds, and retries |
| `PANCLIP_LOG_LEVEL` | WARNING | Logs go to stderr; stdout carries only MCP messages |
| `LMSTUDIO_API_BASE`, `OLLAMA_API_BASE`, `VLLM_API_BASE`, `TEXTGEN_API_BASE`, `KOBOLDCPP_API_BASE` | the usual localhost ports | Local servers to probe |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `COHERE_API_KEY`, `GROQ_API_KEY` | unset | Read only when cloud use is allowed |

```bash
claude mcp add panclip --env PANCLIP_MAX_AGE_DAYS=90 -- uvx --from git+https://github.com/PanStudio/panclip.git panclip
```

### Providers and privacy

At start PanClip probes the local servers above in the background. The first one offering an
embedding model embeds clips, and the first offering a chat model tags them. With none running,
PanClip works offline. Search only compares clips embedded by the current model, and
`clip_stats` shows how many clips each model embedded. If the selected provider fails, the tool
returns an error and stores nothing, rather than mixing in vectors from another model.

A cloud API key or a non-loopback `*_API_BASE` is ignored unless `PANCLIP_ALLOW_CLOUD=true`.
With cloud use allowed, redacted clip text and search queries are sent to the provider, and
`clip_add` and `clip_search` are annotated as reaching outside the machine.

### Data

Clips live in a LanceDB table under `<data dir>/lancedb`, created readable by your user only.
Redis is used only when `PANCLIP_REDIS_URL` is set; cached search results contain clip text,
so use a password and a private Redis (non-loopback Redis URLs require
`PANCLIP_ALLOW_CLOUD=true`). Every write invalidates cached searches.

## Architecture

```
MCP client ───stdio───> PanClip ──> LanceDB (vectors)
                              │
                              └──> LiteLLM ──> AI Provider
```

- **MCP Protocol**: Native stdio communication with Claude
- **LanceDB**: Local vector database for semantic search
- **LiteLLM**: Calls the selected provider; imported only when one is found
- **Search Cache**: In-process, or Redis when configured; invalidated on every write

## Development

```bash
# Run tests
uv run pytest

# Format code
uv run black .

# Lint
uv run ruff check .
```

## Contributing

Contributions welcome! This aims to be a reference implementation for MCP servers.

1. Fork the repository
2. Create your feature branch
3. Add tests for your changes
4. Ensure tests pass
5. Submit a pull request

## Author

**Anthony Kougkas**
- GitHub: [@akougkas](https://github.com/akougkas)
- Website: [akougkas.io](https://akougkas.io)
- Issues: [github.com/PanStudio/panclip/issues](https://github.com/PanStudio/panclip/issues)
- Security reports: [private vulnerability reporting](https://github.com/PanStudio/panclip/security/advisories/new)

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2025-2026 PanStudio

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- [LanceDB](https://lancedb.com) for vector storage
- [LiteLLM](https://litellm.ai) for universal AI support