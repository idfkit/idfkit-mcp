"""FastMCP server for idfkit — EnergyPlus model authoring, validation, and simulation."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

from fastmcp.server.lifespan import lifespan
from fastmcp.server.providers import FileSystemProvider

from idfkit_mcp.errors import ToolExecutionMiddleware
from idfkit_mcp.uploads import IdfUploadStore

_INSTRUCTIONS = """\
EnergyPlus model authoring via idfkit.

VALIDATION LEVELS — two distinct gates, both required for confidence:
  1. Schema validation (fast, no EnergyPlus required):
       validate_model        — field types, ranges, required fields, reference integrity (schema only)
       check_model_integrity — domain QA: orphan objects, missing controls, boundary mismatches
     Passing these does NOT guarantee a successful simulation.
  2. Runtime validation (requires EnergyPlus installation):
       run_simulation        — executes EnergyPlus; fatal errors mean the model is not simulation-ready
       idfkit://simulation/results — read this resource after every run for the full QA picture:
         unmet hours by zone, end-use energy breakdown, classified warnings, and actionable QA flags

QA LOOP — the recommended agent workflow:
  describe_object_type -> batch_add_objects -> validate_model -> check_model_integrity
  -> save_model -> run_simulation -> read idfkit://simulation/results
  -> fix issues -> run_simulation again -> repeat until qa_flags is empty

RESOURCES (read-only state, read any time):
  idfkit://model/summary                     — version, zones, object counts
  idfkit://model/objects/{type}/{name}       — all field values for one object
  idfkit://model/references/{name}           — bidirectional reference graph
  idfkit://docs/{type}                       — documentation URLs
  idfkit://simulation/results                — post-run QA diagnostics (primary QA signal)
  idfkit://simulation/peak-loads             — peak heating/cooling load decomposition

TIPS:
  - Prefer batch_add_objects over repeated add_object calls
  - Call describe_object_type before adding any object to learn required fields
  - get_zone_properties gives a typed summary of zone geometry, surfaces, constructions, and HVAC
  - analyze_peak_loads decomposes facility/zone peaks into components and flags QA issues
  - get_change_log shows recent mutations in the session
  - Remote clients with no shared filesystem can upload a file via the file_manager UI tool,
    then call load_model(upload_name=...) to load it.
"""


@lifespan
async def _configure_logging(_server: FastMCP) -> AsyncIterator[None]:
    """Configure logging for idfkit and the MCP server."""
    log_level = os.getenv("IDFKIT_MCP_LOG_LEVEL", "INFO")
    level = getattr(logging, log_level)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("idfkit").setLevel(level)
    yield


_upload_dir_env = os.environ.get("IDFKIT_MCP_UPLOAD_DIR")
uploads = IdfUploadStore(
    root=Path(_upload_dir_env) if _upload_dir_env else None,
    name="IDFFiles",
    title="Upload an EnergyPlus model",
    description="Drop an .idf or .epJSON file. Then call load_model(upload_name=...) to load it.",
    drop_label="Drop .idf / .epJSON here",
    max_file_size=50 * 1024 * 1024,
)

mcp = FastMCP(
    "idfkit",
    instructions=_INSTRUCTIONS,
    lifespan=_configure_logging,
    providers=[FileSystemProvider(Path(__file__).parent / "tools"), uploads],
)
mcp.add_middleware(ToolExecutionMiddleware())


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request: Request) -> Response:
    """Health check endpoint for load balancer probes."""
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok"})


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the idfkit MCP server."""
    parser = argparse.ArgumentParser(description="Run the idfkit MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "http", "streamable-http"),
        default=os.getenv("IDFKIT_MCP_TRANSPORT", "stdio"),
        help="MCP transport (default: stdio, env: IDFKIT_MCP_TRANSPORT).",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("IDFKIT_MCP_HOST", "127.0.0.1"),
        help="Host for HTTP/SSE transports (env: IDFKIT_MCP_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("IDFKIT_MCP_PORT", "8000")),
        help="Port for HTTP/SSE transports (env: IDFKIT_MCP_PORT).",
    )
    args = parser.parse_args()
    if args.transport == "streamable-http":
        args.transport = "http"
    return args


def main() -> None:
    """CLI entry point with configurable transport."""
    args = _parse_args()
    kwargs: dict[str, object] = {"transport": args.transport}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port
    mcp.run(**kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
