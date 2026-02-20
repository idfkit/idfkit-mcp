"""FastMCP server for idfkit — EnergyPlus model authoring, validation, and simulation."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from typing import Literal, get_args

from mcp.server.fastmcp import FastMCP

from idfkit_mcp.tools import read, schema, simulation, validation, weather, write

Transport = Literal["stdio", "sse", "streamable-http"]

_INSTRUCTIONS = (
    "EnergyPlus model editor powered by idfkit. "
    "Create, edit, validate, and simulate building energy models.\n\n"
    "Guidelines:\n"
    "- Use get_model_summary first to understand any loaded model\n"
    "- Call describe_object_type before creating/editing objects to know valid fields\n"
    "- Use batch_add_objects when creating multiple objects (minimizes round-trips)\n"
    "- Validate after modifications with validate_model\n"
    "- For reference fields, use get_available_references to see valid values\n"
    "- Check references before removing objects (remove_object warns by default)"
)


def create_server(host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    """Create a configured FastMCP instance and register all tools."""
    server = FastMCP("idfkit", instructions=_INSTRUCTIONS, host=host, port=port)

    schema.register(server)
    read.register(server)
    write.register(server)
    validation.register(server)
    simulation.register(server)
    weather.register(server)
    return server


# Module-level instance used by tests to introspect registered tools.
mcp = create_server()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the idfkit MCP server.")
    parser.add_argument(
        "--transport",
        choices=get_args(Transport),
        default=os.getenv("IDFKIT_MCP_TRANSPORT", "stdio"),
        help="MCP transport to run.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("IDFKIT_MCP_HOST", "127.0.0.1"),
        help="Host for HTTP/SSE transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("IDFKIT_MCP_PORT", "8000")),
        help="Port for HTTP/SSE transports.",
    )
    parser.add_argument(
        "--mount-path",
        default=os.getenv("IDFKIT_MCP_MOUNT_PATH"),
        help="Optional mount path for SSE transport.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Run the MCP server with configurable transport."""
    args = _parse_args()
    server = create_server(host=args.host, port=args.port)

    run_kwargs: dict[str, str | None] = {"transport": args.transport}
    if args.transport != "stdio" and args.mount_path is not None:
        run_kwargs["mount_path"] = args.mount_path

    server.run(**run_kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
