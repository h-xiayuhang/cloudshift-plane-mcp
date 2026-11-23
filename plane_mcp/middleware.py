"""Custom FastMCP middleware for the Plane MCP Server."""

from __future__ import annotations

import contextvars
import copy
import re
from collections.abc import Sequence

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from mcp.types import ToolAnnotations


class PlaneLoggingMiddleware(StructuredLoggingMiddleware):
    """StructuredLoggingMiddleware that also records the tool name."""

    def _with_tool_name(self, context: MiddlewareContext, message: dict) -> dict:
        if context.method == "tools/call":
            message["tool"] = getattr(context.message, "name", "unknown")
        return message

    def _create_after_message(self, context: MiddlewareContext, start_time: float) -> dict:
        return self._with_tool_name(context, super()._create_after_message(context, start_time))

    def _create_error_message(self, context: MiddlewareContext, start_time: float, error: Exception) -> dict:
        return self._with_tool_name(context, super()._create_error_message(context, start_time, error))


_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?$")
# cloudshift_plane_* 报告工具全部只读（见 docs/reports.md）
_READ_PREFIXES = ("list_", "retrieve_", "get_", "search_", "resolve_", "cloudshift_plane_")

# 本次工具调用的 workspace，由 WorkspaceArgMiddleware 设置，get_plane_client_context() 优先使用。
call_workspace_slug: contextvars.ContextVar[str | None] = contextvars.ContextVar("call_workspace_slug", default=None)


class WorkspaceArgMiddleware(Middleware):
    """给每个工具加必填的 workspace_slug 参数（一个 key 可跨多个 workspace），并按名字前缀补 readOnlyHint。

    cloudshift_plane_* 报告工具同样适用：它们通过 cloudshift.services.plane_fetch.caller_client()
    读取调用者的 key 和这里设置的 slug。
    """

    async def on_list_tools(self, context: MiddlewareContext, call_next) -> Sequence:
        out = []
        for t in await call_next(context):
            params = copy.deepcopy(t.parameters)
            params["properties"] = {
                "workspace_slug": {
                    "type": "string",
                    "description": (
                        "Plane workspace slug: the first path segment of a Plane URL, "
                        'e.g. "acme" in https://plane.example.com/acme/browse/PROJ-1/'
                    ),
                },
                **params.get("properties", {}),
            }
            params["required"] = ["workspace_slug", *params.get("required", [])]
            update = {"parameters": params}
            # 上游没有给工具标注只读，bot-lite 会把无标注工具一律当写操作审批
            if t.annotations is None and t.name.startswith(_READ_PREFIXES):
                update["annotations"] = ToolAnnotations(readOnlyHint=True)
            out.append(t.model_copy(update=update))
        return out

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        args = dict(context.message.arguments or {})
        slug = args.pop("workspace_slug", None)
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            raise ToolError("workspace_slug is required (letters, digits, '-' or '_' only)")
        token = call_workspace_slug.set(slug)
        try:
            msg = context.message.model_copy(update={"arguments": args})
            return await call_next(context.copy(message=msg))
        finally:
            call_workspace_slug.reset(token)
