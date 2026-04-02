"""Shared FastMCP application instance."""

from __future__ import annotations

from fastmcp import FastMCP

from idfkit_mcp.errors import ToolExecutionMiddleware

_INSTRUCTIONS = (
    "EnergyPlus model authoring via idfkit.\n\n"
    "Workflow: describe_object_type -> batch_add_objects -> validate_model -> save_model.\n"
    "Read model state via resources: idfkit://model/summary, idfkit://model/objects/{type}/{name}, "
    "idfkit://model/references/{name}, idfkit://docs/{type}, idfkit://simulation/results.\n"
    "Prefer batch_add_objects over repeated add_object calls."
)

mcp = FastMCP("idfkit", instructions=_INSTRUCTIONS)
mcp.add_middleware(ToolExecutionMiddleware())
