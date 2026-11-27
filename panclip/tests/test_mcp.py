import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest
from mcp import Client

from panclip.config import Settings
from panclip.core import intelligence as intel_module
from panclip.core.ai_detector import AIDetector, AIProvider
from panclip.mcp_server import build_server

MODES = ["2026-07-28", "legacy"]
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "raw-test", "version": "0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def client(tmp_path, mode="2026-07-28", **overrides):
    app = build_server(Settings(data_dir=tmp_path, **overrides))
    return Client(app, mode=mode, read_timeout_seconds=10)


async def call(session, tool, **arguments):
    return await session.call_tool(tool, arguments)


def error_text(result):
    assert result.is_error
    return result.content[0].text


@pytest.mark.parametrize("mode", MODES)
async def test_tool_metadata(tmp_path, mode):
    async with client(tmp_path, mode) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
    assert set(tools) == {
        "clip_add",
        "clip_search",
        "clip_list",
        "clip_remove",
        "clip_stats",
    }
    assert all(tool.title and tool.output_schema for tool in tools.values())
    assert tools["clip_remove"].annotations.destructive_hint is True
    for name in ("clip_search", "clip_list", "clip_stats"):
        assert tools[name].annotations.read_only_hint is True
    assert not any(tool.annotations.open_world_hint for tool in tools.values())
    content = tools["clip_add"].input_schema["properties"]["content"]
    assert content["maxLength"] == 50_000


async def test_cloud_allowed_marks_provider_tools_open_world(tmp_path):
    async with client(tmp_path, allow_cloud=True) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
    open_world = {
        name for name, tool in tools.items() if tool.annotations.open_world_hint
    }
    assert open_world == {"clip_add", "clip_search"}


@pytest.mark.parametrize("mode", MODES)
async def test_add_search_list_remove_cycle(tmp_path, mode):
    async with client(tmp_path, mode) as session:
        secret_note = "deploy with token ghp_" + "a1" * 18
        added = await call(
            session,
            "clip_add",
            content=secret_note,
            tags=["Ops", "AKIAIOSFODNN7EXAMPLE"],
            source="agent",
        )
        assert not added.is_error
        clip = added.structured_content
        assert clip["status"] == "stored"
        assert clip["redactions"] == {"github_token": 1, "aws_access_key": 1}
        assert clip["tags"][:2] == ["ops", "[REDACTED:aws_access_key]"]
        assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(clip)
        for i in range(3):
            await call(session, "clip_add", content=f"note {i} " + "y" * 300)

        found = await call(session, "clip_search", query="how do I deploy", limit=1)
        hits = found.structured_content["results"]
        assert hits and "[REDACTED:github_token]" in hits[0]["stored_content"]["text"]
        assert "ghp_" not in json.dumps(found.structured_content)

        listed = (
            await call(session, "clip_list", limit=3, max_chars=50)
        ).structured_content
        assert len(listed["clips"]) == 3
        assert listed["clips"][0]["stored_content"]["truncated"]
        rest = await call(session, "clip_list", limit=3, cursor=listed["next_cursor"])
        assert [c["id"] for c in rest.structured_content["clips"]] == [clip["id"]]
        assert rest.structured_content["next_cursor"] is None

        removed = await call(session, "clip_remove", clip_id=clip["id"])
        assert removed.structured_content == {"id": clip["id"], "removed": True}
        assert "no clip has that id" in error_text(
            await call(session, "clip_remove", clip_id=clip["id"])
        )
        stats = (await call(session, "clip_stats")).structured_content
        assert stats["total_clips"] == 3
        assert stats["agent_clips"] == 0
        assert stats["provider_mode"] == "offline"
        assert str(tmp_path) not in json.dumps(stats)


async def test_search_cache_sees_removals(tmp_path):
    async with client(tmp_path) as session:
        clip_id = (
            await call(session, "clip_add", content="cache me")
        ).structured_content["id"]
        first = await call(session, "clip_search", query="cache me")
        assert first.structured_content["results"]
        await call(session, "clip_remove", clip_id=clip_id)
        again = await call(session, "clip_search", query="cache me")
        assert again.structured_content["results"] == []


async def test_crafted_id_is_refused_and_deletes_nothing(tmp_path):
    async with client(tmp_path) as session:
        await call(session, "clip_add", content="one")
        await call(session, "clip_add", content="two")
        result = await call(session, "clip_remove", clip_id="x' OR '1'='1")
        assert "clip_id" in error_text(result)
        assert "OR" not in error_text(result)
        stats = await call(session, "clip_stats")
        assert stats.structured_content["total_clips"] == 2


async def test_errors_never_echo_arguments(tmp_path):
    marker = "SECRET-MARKER-42"
    async with client(tmp_path, max_content_chars=100) as session:
        too_long = await call(session, "clip_add", content=marker * 20)
        bad_source = await call(session, "clip_add", content="x", source=marker)
        bad_cursor = await call(session, "clip_list", cursor=marker)
        for result in (too_long, bad_source, bad_cursor):
            text = error_text(result)
            assert marker not in text
            assert "retry" in text or "next_cursor" in text


async def test_cursor_is_bound_to_its_query(tmp_path):
    async with client(tmp_path) as session:
        for i in range(3):
            await call(session, "clip_add", content=f"alpha {i}")
        page = await call(session, "clip_search", query="alpha", limit=1)
        cursor = page.structured_content["next_cursor"]
        assert cursor
        wrong = await call(session, "clip_search", query="beta", cursor=cursor)
        assert "different query" in error_text(wrong)


async def test_provider_failure_stores_nothing(tmp_path, monkeypatch):
    async def detect(self):
        return [
            AIProvider(
                name="lmstudio",
                type="local",
                api_base="http://localhost:1",
                embedding_models=["embed"],
            )
        ]

    async def aembedding(**kwargs):
        raise ConnectionError("refused")

    monkeypatch.setattr(AIDetector, "detect", detect)
    monkeypatch.setattr(
        intel_module, "_import_litellm", lambda: SimpleNamespace(aembedding=aembedding)
    )
    async with client(tmp_path) as session:
        result = await call(session, "clip_add", content="private words")
        assert "lmstudio/embed" in error_text(result)
        assert "private words" not in error_text(result)
        stats = await call(session, "clip_stats")
        assert stats.structured_content["total_clips"] == 0


async def test_retention_limit_applies_on_write(tmp_path):
    async with client(tmp_path, max_clips=2) as session:
        for i in range(3):
            result = await call(session, "clip_add", content=f"clip {i}")
        assert result.structured_content["retention_removed"] == 1
        listed = await call(session, "clip_list")
        texts = [
            c["stored_content"]["text"] for c in listed.structured_content["clips"]
        ]
        assert texts == ["clip 2", "clip 1"]


class RawServer:
    """The server as a subprocess, read line by line so stray stdout output is caught."""

    def __init__(self, process):
        self.process = process
        self.next_id = 0

    async def send(self, method, params=None, notify=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.next_id += 1
            message["id"] = self.next_id
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()
        if notify:
            return None
        line = await asyncio.wait_for(self.process.stdout.readline(), 20)
        reply = json.loads(line)
        assert reply["jsonrpc"] == "2.0" and reply["id"] == self.next_id, line
        return reply

    async def close(self):
        self.process.stdin.close()
        rest = await asyncio.wait_for(self.process.stdout.read(), 20)
        await self.process.wait()
        stderr = await self.process.stderr.read()
        return rest, stderr


async def start_raw(tmp_path):
    env = {
        **os.environ,
        "PANCLIP_DATA_DIR": str(tmp_path / "data"),
        "PANCLIP_LOG_LEVEL": "DEBUG",
        "LMSTUDIO_API_BASE": "http://127.0.0.1:9",
        "OLLAMA_API_BASE": "http://127.0.0.1:9",
        "VLLM_API_BASE": "http://127.0.0.1:9",
        "TEXTGEN_API_BASE": "http://127.0.0.1:9",
        "KOBOLDCPP_API_BASE": "http://127.0.0.1:9",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "panclip.mcp_server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=tmp_path,
        env=env,
    )
    return RawServer(process)


async def cycle(server, meta):
    def params(**extra):
        return {**extra, "_meta": meta} if meta else extra

    added = await server.send(
        "tools/call", params(name="clip_add", arguments={"content": "raw stdio check"})
    )
    clip_id = added["result"]["structuredContent"]["id"]
    for name, arguments in [
        ("clip_search", {"query": "raw stdio"}),
        ("clip_list", {}),
        ("clip_stats", {}),
        ("clip_remove", {"clip_id": clip_id}),
    ]:
        reply = await server.send("tools/call", params(name=name, arguments=arguments))
        assert reply["result"].get("isError") is not True, reply


async def test_stdout_carries_only_protocol_frames_modern(tmp_path):
    server = await start_raw(tmp_path)
    discovered = await server.send("server/discover", {"_meta": MODERN_META})
    assert "2026-07-28" in json.dumps(discovered["result"])
    tools = await server.send("tools/list", {"_meta": MODERN_META})
    assert len(tools["result"]["tools"]) == 5
    await cycle(server, MODERN_META)
    rest, stderr = await server.close()
    assert rest.strip() == b""
    assert stderr, "logging goes to stderr"
    assert not (tmp_path / ".panclip").exists()
    assert (tmp_path / "data" / "lancedb").is_dir()


async def test_stdout_carries_only_protocol_frames_legacy(tmp_path):
    server = await start_raw(tmp_path)
    init = await server.send(
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "raw-test", "version": "0"},
        },
    )
    assert init["result"]["serverInfo"]["name"] == "panclip"
    await server.send("notifications/initialized", notify=True)
    await cycle(server, None)
    rest, _ = await server.close()
    assert rest.strip() == b""
