"""Shared FastMCP application instance."""

from __future__ import annotations

from fastmcp import FastMCP

from idfkit_mcp.errors import ToolExecutionMiddleware

_INSTRUCTIONS = """EnergyPlus model authoring via idfkit.

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
  describe_object_type → batch_add_objects → validate_model → check_model_integrity
  → save_model → run_simulation → read idfkit://simulation/results
  → fix issues → run_simulation again → repeat until qa_flags is empty

RESOURCES (read-only state, read any time):
  idfkit://model/summary                     — version, zones, object counts
  idfkit://model/objects/{type}/{name}       — all field values for one object
  idfkit://model/references/{name}           — bidirectional reference graph
  idfkit://docs/{type}                       — documentation URLs
  idfkit://simulation/results                — post-run QA diagnostics (primary QA signal)

TIPS:
  - Prefer batch_add_objects over repeated add_object calls
  - Call describe_object_type before adding any object to learn required fields
  - get_zone_properties gives a typed summary of zone geometry, surfaces, constructions, and HVAC
  - get_change_log shows recent mutations in the session
"""

mcp = FastMCP("idfkit", instructions=_INSTRUCTIONS)
mcp.add_middleware(ToolExecutionMiddleware())
