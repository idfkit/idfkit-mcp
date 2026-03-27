"""MCP resources exposing read-only model, schema, simulation, and documentation data."""

from __future__ import annotations

import json
from typing import Any

from fastmcp.resources.resource import ResourceContent, ResourceResult
from pydantic import BaseModel

from idfkit_mcp.app import mcp
from idfkit_mcp.serializers import serialize_object
from idfkit_mcp.state import get_state
from idfkit_mcp.tools import resolve_object
from idfkit_mcp.tools.docs import build_documentation_urls
from idfkit_mcp.tools.read import build_model_summary, build_references
from idfkit_mcp.tools.schema import describe_object_type
from idfkit_mcp.tools.simulation import get_results_summary

JSON_MIME = "application/json"


def _to_resource_json(value: BaseModel | dict[str, Any]) -> ResourceResult:
    """Serialize resource payloads as JSON with correct MIME type.

    Returns a ResourceResult directly to work around a FastMCP bug where
    ResourceTemplate.convert_result() drops the registered mime_type for
    template resources (URIs with parameters), defaulting to text/plain.
    """
    if isinstance(value, BaseModel):
        text = value.model_dump_json(indent=2)
    else:
        text = json.dumps(value, indent=2, sort_keys=True, default=str)
    return ResourceResult([ResourceContent(text, mime_type=JSON_MIME)])


@mcp.resource(
    "idfkit://model/summary",
    name="model_summary",
    title="Model Summary",
    description="Version, zones, object counts, and groups for the loaded model.",
    mime_type="application/json",
)
def model_summary() -> ResourceResult:
    """Current model summary as JSON."""
    state = get_state()
    doc = state.require_model()
    return _to_resource_json(build_model_summary(doc, state))


@mcp.resource(
    "idfkit://schema/{object_type}",
    name="object_schema",
    title="Object Schema",
    description="Full field schema for an EnergyPlus object type.",
    mime_type="application/json",
)
def object_schema(object_type: str) -> ResourceResult:
    """Full schema description for an EnergyPlus object type as JSON."""
    return _to_resource_json(describe_object_type(object_type))


@mcp.resource(
    "idfkit://model/objects/{object_type}/{name}",
    name="object_data",
    title="Object Data",
    description="All field values for a specific EnergyPlus object.",
    mime_type="application/json",
)
def object_data(object_type: str, name: str) -> ResourceResult:
    """Serialized model object data as JSON."""
    state = get_state()
    doc = state.require_model()
    obj = resolve_object(doc, object_type, name)
    return _to_resource_json(serialize_object(obj))


@mcp.resource(
    "idfkit://simulation/results",
    name="simulation_results",
    title="Simulation Results",
    description="Energy metrics, errors, and tables from the last simulation.",
    mime_type="application/json",
)
def simulation_results() -> ResourceResult:
    """Latest simulation results summary as JSON."""
    return _to_resource_json(get_results_summary())


@mcp.resource(
    "idfkit://docs/{object_type}",
    name="documentation_urls",
    title="Documentation URLs",
    description="I/O Reference, Engineering Reference, and search URLs for an object type.",
    mime_type="application/json",
)
def documentation_urls(object_type: str) -> ResourceResult:
    """Documentation URLs for an EnergyPlus object type as JSON."""
    return _to_resource_json(build_documentation_urls(object_type))


@mcp.resource(
    "idfkit://model/references/{name}",
    name="object_references",
    title="Object References",
    description="Bidirectional references: who references this object and what it references.",
    mime_type="application/json",
)
def object_references(name: str) -> ResourceResult:
    """Bidirectional reference graph for an object as JSON."""
    state = get_state()
    doc = state.require_model()
    return _to_resource_json(build_references(doc, name))
