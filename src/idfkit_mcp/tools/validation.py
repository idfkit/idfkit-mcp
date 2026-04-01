"""Model validation tools."""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
from idfkit_mcp.models import ValidationResult
from idfkit_mcp.serializers import serialize_validation_result
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=_READ_ONLY)
def validate_model(
    object_types: Annotated[list[str] | None, Field(description="Only validate specific types (default: all).")] = None,
    check_references: Annotated[bool, Field(description="Check reference integrity.")] = True,
) -> ValidationResult:
    """Schema-based pre-flight check — run after any model modifications.

    Checks field types, numeric ranges, required fields, enum values, singleton
    constraints (codes E001-E010, W001-W003), and cross-object reference integrity.

    IMPORTANT: This is schema validation only. It does not run EnergyPlus and cannot
    detect runtime faults such as convergence failures, zone connectivity issues, or
    autosizing problems. A model that passes this check may still fail to simulate.

    Preconditions: model loaded (load_model or new_model).
    Side effects: none — read-only.
    Next steps: check_model_integrity for domain-level QA, then save_model,
    then run_simulation for definitive runtime validation.
    """
    from idfkit import validate_document

    state = get_state()
    doc = state.require_model()
    if not list(doc.all_objects):
        logger.warning("validate_model: model has no objects")
    result = validate_document(doc, check_references=check_references, object_types=object_types)
    data = serialize_validation_result(result, version=doc.version)  # type: ignore[arg-type]
    logger.info(
        "Validation complete: %d errors, %d warnings",
        data.get("error_count", 0),
        data.get("warning_count", 0),
    )
    return ValidationResult.model_validate(data)
