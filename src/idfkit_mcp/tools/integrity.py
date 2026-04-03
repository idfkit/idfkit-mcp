"""Domain-level model integrity checks (pre-simulation QA)."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from idfkit_mcp.models import IntegrityIssue, ModelIntegrityResult
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# EnergyPlus schedule object types that are top-level (directly referenced by loads/controls).
# Week and day sub-schedules are internal and intentionally excluded.
_SCHEDULE_TYPES = (
    "Schedule:Compact",
    "Schedule:Constant",
    "Schedule:Year",
    "Schedule:File",
)

# Required singleton control objects — every simulation-ready model needs these.
_REQUIRED_CONTROLS = (
    "Version",
    "Building",
    "Timestep",
    "RunPeriod",
    "SimulationControl",
)


def _check_zones_with_no_surfaces(doc: Any) -> list[IntegrityIssue]:
    """Every Zone must have at least one BuildingSurface:Detailed."""
    issues: list[IntegrityIssue] = []
    if "Zone" not in doc:
        return issues

    # Collect zone names referenced by surfaces
    surface_zones: set[str] = set()
    if "BuildingSurface:Detailed" in doc:
        for surface in doc.get_collection("BuildingSurface:Detailed"):
            zn = surface.data.get("zone_name")
            if zn:
                surface_zones.add(zn.lower())

    for zone in doc.get_collection("Zone"):
        if zone.name.lower() not in surface_zones:
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="geometry",
                    object_type="Zone",
                    object_name=zone.name,
                    message=f"Zone '{zone.name}' has no BuildingSurface:Detailed surfaces.",
                )
            )
    return issues


def _check_required_controls(doc: Any) -> list[IntegrityIssue]:
    """Required singleton control objects must be present."""
    issues: list[IntegrityIssue] = []
    for obj_type in _REQUIRED_CONTROLS:
        if obj_type not in doc or len(doc.get_collection(obj_type)) == 0:
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="controls",
                    object_type=obj_type,
                    object_name=None,
                    message=f"Required object '{obj_type}' is missing from the model.",
                )
            )
    return issues


def _check_orphan_schedules(doc: Any) -> list[IntegrityIssue]:
    """Schedules defined but not referenced by any other object."""
    issues: list[IntegrityIssue] = []
    for sched_type in _SCHEDULE_TYPES:
        if sched_type not in doc:
            continue
        for sched in doc.get_collection(sched_type):
            if not sched.name:
                continue
            if not doc.references.is_referenced(sched.name):
                issues.append(
                    IntegrityIssue(
                        severity="warning",
                        category="schedules",
                        object_type=sched_type,
                        object_name=sched.name,
                        message=f"Schedule '{sched.name}' is defined but not referenced by any object.",
                    )
                )
    return issues


def _check_surface_boundary_mismatches(doc: Any) -> list[IntegrityIssue]:
    """Surfaces with outside_boundary_condition='Surface' must have a valid, reciprocal partner."""
    issues: list[IntegrityIssue] = []
    if "BuildingSurface:Detailed" not in doc:
        return issues

    collection = doc.get_collection("BuildingSurface:Detailed")
    for surface in collection:
        obc = surface.data.get("outside_boundary_condition", "")
        if obc.lower() != "surface":
            continue
        partner_name = surface.data.get("outside_boundary_condition_object", "")
        if not partner_name:
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="geometry",
                    object_type="BuildingSurface:Detailed",
                    object_name=surface.name,
                    message=(
                        f"Surface '{surface.name}' has outside_boundary_condition='Surface' "
                        "but outside_boundary_condition_object is not set."
                    ),
                )
            )
            continue
        partner = collection.get(partner_name)
        if partner is None:
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="geometry",
                    object_type="BuildingSurface:Detailed",
                    object_name=surface.name,
                    message=(
                        f"Surface '{surface.name}' references partner '{partner_name}' "
                        "which does not exist in BuildingSurface:Detailed."
                    ),
                )
            )
            continue
        # Check reciprocal reference
        partner_obc_obj = partner.data.get("outside_boundary_condition_object", "")
        if partner_obc_obj.lower() != surface.name.lower():
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="geometry",
                    object_type="BuildingSurface:Detailed",
                    object_name=surface.name,
                    message=(
                        f"Surface '{surface.name}' and partner '{partner_name}' "
                        "do not have reciprocal outside_boundary_condition_object references."
                    ),
                )
            )
    return issues


def _check_fenestration_hosts(doc: Any) -> list[IntegrityIssue]:
    """FenestrationSurface:Detailed must reference an existing BuildingSurface:Detailed."""
    issues: list[IntegrityIssue] = []
    if "FenestrationSurface:Detailed" not in doc:
        return issues
    surface_names: set[str] = set()
    if "BuildingSurface:Detailed" in doc:
        surface_names = {s.name.lower() for s in doc.get_collection("BuildingSurface:Detailed")}
    for fen in doc.get_collection("FenestrationSurface:Detailed"):
        host = fen.data.get("building_surface_name", "")
        if host and host.lower() not in surface_names:
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="geometry",
                    object_type="FenestrationSurface:Detailed",
                    object_name=fen.name,
                    message=(
                        f"FenestrationSurface '{fen.name}' references host surface '{host}' "
                        "which does not exist in BuildingSurface:Detailed."
                    ),
                )
            )
    return issues


def _check_hvac_zone_references(doc: Any) -> list[IntegrityIssue]:
    """ZoneHVAC:EquipmentConnections zone_name must reference an existing Zone."""
    issues: list[IntegrityIssue] = []
    if "ZoneHVAC:EquipmentConnections" not in doc:
        return issues
    zone_names: set[str] = set()
    if "Zone" in doc:
        zone_names = {z.name.lower() for z in doc.get_collection("Zone")}
    for conn in doc.get_collection("ZoneHVAC:EquipmentConnections"):
        zn = conn.data.get("zone_name", "")
        if zn and zn.lower() not in zone_names:
            issues.append(
                IntegrityIssue(
                    severity="error",
                    category="hvac",
                    object_type="ZoneHVAC:EquipmentConnections",
                    object_name=conn.name,
                    message=(
                        f"ZoneHVAC:EquipmentConnections '{conn.name}' references zone '{zn}' which does not exist."
                    ),
                )
            )
    return issues


@tool(annotations=_READ_ONLY)
def check_model_integrity() -> ModelIntegrityResult:
    """Domain-level pre-simulation QA — catches issues schema validation cannot.

    Runs six checks against the loaded model:
    - Zones with no BuildingSurface:Detailed surfaces
    - Missing required simulation control objects (Version, Building, Timestep, RunPeriod, SimulationControl)
    - Orphan schedules (defined but not referenced by any object)
    - Surface boundary condition mismatches (non-reciprocal 'Surface' pairs)
    - Fenestration surfaces referencing non-existent host surfaces
    - ZoneHVAC:EquipmentConnections referencing non-existent zones

    Use this after validate_model and before run_simulation. A model can pass
    validate_model but still fail these checks.

    Preconditions: model loaded.
    Side effects: none — read-only.
    """
    state = get_state()
    doc = state.require_model()

    checks: list[tuple[str, Any]] = [
        ("zones_with_no_surfaces", _check_zones_with_no_surfaces),
        ("required_simulation_controls", _check_required_controls),
        ("orphan_schedules", _check_orphan_schedules),
        ("surface_boundary_mismatches", _check_surface_boundary_mismatches),
        ("fenestration_host_check", _check_fenestration_hosts),
        ("hvac_zone_references", _check_hvac_zone_references),
    ]

    all_issues: list[IntegrityIssue] = []
    checks_run: list[str] = []

    for name, fn in checks:
        checks_run.append(name)
        try:
            all_issues.extend(fn(doc))
        except Exception:
            logger.exception("Integrity check '%s' failed unexpectedly", name)

    error_count = sum(1 for i in all_issues if i.severity == "error")
    warning_count = sum(1 for i in all_issues if i.severity == "warning")

    logger.info(
        "check_model_integrity: %d errors, %d warnings across %d checks",
        error_count,
        warning_count,
        len(checks_run),
    )

    return ModelIntegrityResult(
        passed=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        issues=all_issues,
        checks_run=checks_run,
    )
