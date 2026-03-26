"""Helpers for accessing registered FastMCP tools in tests."""

from __future__ import annotations

import asyncio
import typing
from dataclasses import dataclass
from typing import Any


def _deserialize_tool_result(tool: Any, result: Any) -> Any:
    """Convert a FastMCP ToolResult back into the tool's Python return type."""
    data = result.structured_content
    if data is None:
        return result.content

    return_type = typing.get_type_hints(tool.fn).get("return")
    if return_type is None:
        return data

    origin = typing.get_origin(return_type)
    if origin in {dict, list, tuple, set}:
        return data

    if isinstance(return_type, type) and hasattr(return_type, "model_validate"):
        return return_type.model_validate(data)

    return data


@dataclass(slots=True)
class SyncToolProxy:
    """Synchronous facade over FastMCP tool execution."""

    server: Any
    tool: Any

    def fn(self, **kwargs: Any) -> Any:
        result = asyncio.run(self.server.call_tool(self.tool.name, kwargs))
        return _deserialize_tool_result(self.tool, result)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tool, name)


@dataclass(slots=True)
class AsyncToolProxy:
    """Asynchronous facade over FastMCP tool execution."""

    server: Any
    tool: Any

    async def fn(self, **kwargs: Any) -> Any:
        result = await self.server.call_tool(self.tool.name, kwargs)
        return _deserialize_tool_result(self.tool, result)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tool, name)


def get_tool_sync(server: Any, name: str) -> Any:
    """Fetch a registered tool from a server in synchronous tests."""
    tool = asyncio.run(server._local_provider.get_tool(name))
    return SyncToolProxy(server=server, tool=tool)


def list_tools_sync(server: Any) -> dict[str, Any]:
    """Fetch all registered tools from a server in synchronous tests."""
    tools = asyncio.run(server._local_provider.list_tools())
    return {tool.name: tool for tool in tools}


async def get_tool_async(server: Any, name: str) -> Any:
    """Fetch a registered tool from a server in async tests."""
    tool = await server._local_provider.get_tool(name)
    return AsyncToolProxy(server=server, tool=tool)
