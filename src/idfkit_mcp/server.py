"""FastMCP server for idfkit — EnergyPlus model authoring, validation, and simulation."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from typing import Literal

from fastmcp import FastMCP

from idfkit_mcp.app import mcp
from idfkit_mcp.tools import docs as _docs
from idfkit_mcp.tools import read as _read
from idfkit_mcp.tools import schema as _schema
from idfkit_mcp.tools import simulation as _simulation
from idfkit_mcp.tools import validation as _validation
from idfkit_mcp.tools import weather as _weather
from idfkit_mcp.tools import write as _write

Transport = Literal["stdio", "sse", "http"]
_TRANSPORT_CHOICES = ("stdio", "sse", "http", "streamable-http")
_REGISTERED_MODULES = (_docs, _read, _schema, _simulation, _validation, _weather, _write)

_INSTRUCTIONS = (
    "EnergyPlus model editor powered by idfkit. "
    "Create, edit, validate, and simulate building energy models.\n\n"
    "Guidelines:\n"
    "- Use get_model_summary first to understand any loaded model\n"
    "- Call describe_object_type before creating/editing objects to know valid fields\n"
    "- Use batch_add_objects when creating multiple objects (minimizes round-trips)\n"
    "- Validate after modifications with validate_model\n"
    "- For reference fields, use get_available_references to see valid values\n"
    "- Check references before removing objects (remove_object warns by default)\n"
    "- Use lookup_documentation to get docs.idfkit.com URLs for any object type\n"
    "- Use search_docs to find relevant EnergyPlus documentation sections\n"
    "- Use get_doc_section to read the full content of a documentation section"
)


def create_server() -> FastMCP:
    """Return the configured FastMCP instance."""
    return mcp


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the idfkit MCP server.")
    parser.add_argument(
        "--transport",
        choices=_TRANSPORT_CHOICES,
        default=os.getenv("IDFKIT_MCP_TRANSPORT", "stdio"),
        help="MCP transport to run.",
    )
    parser.add_argument(
        "--log-level",
        choices=_LOG_LEVELS,
        default=os.getenv("IDFKIT_MCP_LOG_LEVEL", "INFO"),
        help="Log verbosity (default: INFO, env: IDFKIT_MCP_LOG_LEVEL).",
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
    args = parser.parse_args(argv)
    if args.transport == "streamable-http":
        args.transport = "http"
    return args


def main() -> None:
    """Run the MCP server with configurable transport."""
    import logging

    args = _parse_args()
    level = getattr(logging, args.log_level)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Capture idfkit core library logs (parser, schema, validation, geometry).
    # The library installs a NullHandler by default; setting a level here lets
    # its messages propagate through to the root handler configured above.
    logging.getLogger("idfkit").setLevel(level)
    server = create_server()

    transport: Transport = args.transport
    if transport == "stdio":
        server.run(transport=transport)
        return
    if args.mount_path is None:
        server.run(transport=transport, host=args.host, port=args.port)
        return
    server.run(transport=transport, host=args.host, port=args.port, mount_path=args.mount_path)


if __name__ == "__main__":
    main()
