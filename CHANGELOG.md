# Changelog

## Unreleased

### Breaking

- Data moved to `$XDG_DATA_HOME/panclip` (default `~/.local/share/panclip`), or the
  directory given by `--data-dir` or `PANCLIP_DATA_DIR`. PanClip 1.0.0 kept its store in
  `<launch directory>/.panclip/lancedb`, which depended on where the client started the
  server. Old stores are not read or migrated; delete them when you no longer need them.
- Clip ids are uuid4 strings. The 16-character ids of 1.0.0 are refused.
- Configuration is environment variables plus `--data-dir` and `--allow-cloud`.
  `config.yaml` (never read) is removed, and PanClip no longer loads a `.env` file from the
  launch directory. Unused `PANCLIP_*` variables are gone; see `.env.example`.
- Cloud providers and non-loopback servers are used only with `PANCLIP_ALLOW_CLOUD=true`.
- Redis is used only when `PANCLIP_REDIS_URL` is set, instead of any server on
  `localhost:6379`.
- A failing AI provider makes `clip_add` and `clip_search` return an error instead of
  silently using a different embedding.
- Tool results are structured: clip text is in `stored_content.text`, cut to `max_chars`.
  `clip_search` takes at most 20 results per page; both list tools page with `cursor`.
- Requires mcp 2.x and lancedb 0.41 or later.

### Added

- MCP 2026-07-28 over stdio alongside the earlier `initialize` handshake.
- Secret redaction before storing and before any provider call.
- `PANCLIP_MAX_CONTENT_CHARS`, `PANCLIP_MAX_CLIPS` and `PANCLIP_MAX_AGE_DAYS` limits.
- Tool titles, annotations (`clip_remove` is destructive), input bounds, output schemas and
  server instructions.
- Offline search ranks by shared words.

### Fixed

- Output printed to stdout corrupted the stdio protocol.
- A crafted `clip_id` could make `clip_remove` delete other clips.
- Errors were returned as successful results that repeated the arguments.
- `clip_add` reported a clip as stored before it was written.
- Cached searches kept returning removed clips.
