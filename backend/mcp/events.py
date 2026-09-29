"""MCP streaming events для Socket.IO (B-22)."""

from __future__ import annotations

import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

McpEventCallback = Callable[[Dict[str, Any]], Awaitable[None]]


async def emit_mcp_tool_start(
    callback: Optional[McpEventCallback],
    *,
    server_id: str,
    tool: str,
    qualified_name: str,
    call_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> None:
    if not callback:
        return
    payload: Dict[str, Any] = {
        "type": "mcp_tool_start",
        "server_id": server_id,
        "tool": tool,
        "qualified_name": qualified_name,
        "call_id": call_id or uuid.uuid4().hex,
        "timestamp": time.time(),
    }
    if arguments is not None:
        payload["arguments"] = arguments
    await callback(payload)


async def emit_mcp_tool_end(
    callback: Optional[McpEventCallback],
    *,
    server_id: str,
    tool: str,
    qualified_name: str,
    success: bool,
    duration_ms: int,
    error: Optional[str] = None,
    result_preview: Optional[str] = None,
    has_image: bool = False,
    has_audio: bool = False,
    has_resource: bool = False,
    download_urls: Optional[List[Dict[str, str]]] = None,
    call_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    result: Optional[str] = None,
    document_search: Optional[Dict[str, Any]] = None,
) -> None:
    if not callback:
        return
    payload: Dict[str, Any] = {
        "type": "mcp_tool_end",
        "server_id": server_id,
        "tool": tool,
        "qualified_name": qualified_name,
        "call_id": call_id or uuid.uuid4().hex,
        "success": success,
        "duration_ms": duration_ms,
        "timestamp": time.time(),
    }
    if arguments is not None:
        payload["arguments"] = arguments
    if result:
        payload["result"] = result
    if error:
        payload["error"] = error
    if result_preview:
        payload["result_preview"] = result_preview
    if has_image:
        payload["has_image"] = True
    if has_audio:
        payload["has_audio"] = True
    if has_resource:
        payload["has_resource"] = True
    if download_urls:
        payload["download_urls"] = download_urls
    if document_search:
        payload["document_search"] = document_search
    await callback(payload)
