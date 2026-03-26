"""Shared FastMCP application instance."""

from __future__ import annotations

from fastmcp import FastMCP

from idfkit_mcp.errors import ToolExecutionMiddleware

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

mcp = FastMCP("idfkit", instructions=_INSTRUCTIONS)
mcp.add_middleware(ToolExecutionMiddleware())
