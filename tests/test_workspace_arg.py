"""Per-call workspace_slug: schema injection, validation, and propagation to tools."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cloudshift.services.plane_fetch import caller_client
from plane_mcp.auth.plane_header_auth_provider import PlaneHeaderAuthProvider
from plane_mcp.client import get_plane_client_context
from plane_mcp.middleware import WorkspaceArgMiddleware


def _server() -> FastMCP:
    mcp = FastMCP("t")
    mcp.add_middleware(WorkspaceArgMiddleware())

    @mcp.tool
    def list_things(project_id: str) -> dict:
        # 同步工具在线程池里跑：同时验证 ContextVar 能传过去
        return {"slug": get_plane_client_context().workspace_slug, "project_id": project_id}

    @mcp.tool
    def create_thing(name: str) -> dict:
        return {"slug": get_plane_client_context().workspace_slug, "name": name}

    @mcp.tool
    def cloudshift_plane_daily_report() -> dict:
        # 与真实报告工具一样走 caller_client()：同步函数，在线程池里运行
        c = caller_client()
        return {"slug": c.workspace_slug, "key": c.api_key}

    return mcp


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLANE_BASE_URL", "http://plane.invalid")
    monkeypatch.setenv("PLANE_API_KEY", "server-key")
    monkeypatch.delenv("PLANE_WORKSPACE_SLUG", raising=False)


def test_schema_has_required_slug_and_read_hint():
    async def run():
        async with Client(_server()) as c:
            return {t.name: t for t in await c.list_tools()}

    tools = asyncio.run(run())
    for name in ("list_things", "create_thing"):
        schema = tools[name].inputSchema
        assert "workspace_slug" in schema["properties"]
        assert "workspace_slug" in schema["required"]
    assert tools["list_things"].annotations and tools["list_things"].annotations.readOnlyHint is True
    assert not (tools["create_thing"].annotations and tools["create_thing"].annotations.readOnlyHint)
    report = tools["cloudshift_plane_daily_report"]
    assert "workspace_slug" in report.inputSchema["required"]
    assert report.annotations and report.annotations.readOnlyHint is True


def test_slug_reaches_tool_and_is_not_a_tool_argument():
    async def run():
        async with Client(_server()) as c:
            a = await c.call_tool("list_things", {"workspace_slug": "team-a", "project_id": "p1"})
            b = await c.call_tool("create_thing", {"workspace_slug": "team-b", "name": "x"})
            return a.data, b.data

    a, b = asyncio.run(run())
    assert a == {"slug": "team-a", "project_id": "p1"}
    assert b == {"slug": "team-b", "name": "x"}


def test_report_tool_uses_call_slug_not_server_slug(monkeypatch):
    # 没有 HTTP 认证上下文时 key 退回环境变量；slug 必须是本次调用传入的，而不是服务端配置的
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "server-ws")

    async def run():
        async with Client(_server()) as c:
            return (await c.call_tool("cloudshift_plane_daily_report", {"workspace_slug": "team-c"})).data

    assert asyncio.run(run())["slug"] == "team-c"


@pytest.mark.parametrize("bad", [None, "", "../x", "a b", "a/b"])
def test_missing_or_unsafe_slug_is_rejected(bad):
    args = {"project_id": "p1"}
    if bad is not None:
        args["workspace_slug"] = bad

    async def run():
        async with Client(_server()) as c:
            await c.call_tool("list_things", args)

    with pytest.raises(ToolError, match="workspace_slug"):
        asyncio.run(run())


def test_verify_token_without_slug_uses_users_me_only():
    provider = PlaneHeaderAuthProvider()
    seen = {}

    async def fake_validate(token, workspace_slug=None):
        seen["slug"] = workspace_slug
        return token == "good"

    async def run(tok):
        with patch.object(provider, "_validate_api_key", new=AsyncMock(side_effect=fake_validate)):
            with patch("fastmcp.server.dependencies.get_http_headers", return_value={}):
                return await provider.verify_token(tok)

    assert asyncio.run(run("good")) is not None
    assert seen["slug"] is None
    assert asyncio.run(run("bad")) is None
