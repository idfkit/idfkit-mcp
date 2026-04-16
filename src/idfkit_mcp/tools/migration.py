"""Forward-migrate the loaded model across EnergyPlus versions.

Drives :func:`idfkit.async_migrate` through the transition binaries shipped
with the installed EnergyPlus. On success the migrated document replaces
``state.document``; ``state.file_path`` is left untouched so the agent must
call ``save_model(path=...)`` to persist.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

import idfkit
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from idfkit import IDFDocument
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.models import (
    FieldDeltaModel,
    MigrateModelResult,
    MigrationDiffSummary,
    MigrationStepBrief,
)
from idfkit_mcp.state import get_state

if TYPE_CHECKING:
    from idfkit.migration import MigrationReport
    from idfkit.migration.progress import MigrationProgress

logger = logging.getLogger(__name__)

_MIGRATE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

_STDERR_TAIL_CHARS = 500
"""How much of a failed step's stderr to include in the ToolError message."""

_STREAM_TRUNCATE_CHARS = 4000
"""Per-step stdout/stderr cap when serializing the full report for the resource."""


def _parse_target_version(value: str) -> tuple[int, int, int]:
    """Parse a user-supplied ``target_version`` string via idfkit's validator."""
    from idfkit.simulation.config import normalize_version

    try:
        return normalize_version(value)
    except ValueError as exc:
        msg = f"Invalid target_version {value!r}: {exc}"
        raise ToolError(msg) from exc


def _vstr(version: tuple[int, int, int]) -> str:
    """Format a ``(major, minor, patch)`` tuple as ``"X.Y.Z"``."""
    return f"{version[0]}.{version[1]}.{version[2]}"


def _build_progress_handler(ctx: Context | None) -> Any:
    """Build an async progress callback that mirrors simulation tool conventions."""

    async def on_progress(event: MigrationProgress) -> None:
        if ctx is not None and event.percent is not None:
            await ctx.report_progress(progress=event.percent, total=100.0)
        if ctx is not None:
            if event.from_version is not None and event.to_version is not None:
                message = f"[{event.phase}] {_vstr(event.from_version)} -> {_vstr(event.to_version)}: {event.message}"
            else:
                message = f"[{event.phase}] {event.message}"
            await ctx.info(message)

    return on_progress


def _build_result(report: MigrationReport) -> MigrateModelResult:
    """Project a ``MigrationReport`` onto the ``MigrateModelResult`` shape."""
    steps = [
        MigrationStepBrief(
            from_version=_vstr(s.from_version),
            to_version=_vstr(s.to_version),
            success=s.success,
            runtime_seconds=round(s.runtime_seconds, 3),
            binary=str(s.binary) if s.binary is not None else None,
        )
        for s in report.steps
    ]
    diff = MigrationDiffSummary(
        added_object_types=list(report.diff.added_object_types),
        removed_object_types=list(report.diff.removed_object_types),
        object_count_delta=dict(report.diff.object_count_delta),
        field_changes={
            t: FieldDeltaModel(added=list(fd.added), removed=list(fd.removed))
            for t, fd in report.diff.field_changes.items()
        },
    )
    return MigrateModelResult(
        success=report.success,
        source_version=_vstr(report.source_version),
        target_version=_vstr(report.target_version),
        requested_target=_vstr(report.requested_target),
        steps=steps,
        diff=diff,
        summary=report.summary(),
    )


def serialize_report_for_resource(report: MigrationReport) -> dict[str, Any]:
    """Serialize a ``MigrationReport`` for the ``idfkit://migration/report`` resource.

    Exposes per-step ``stdout``/``stderr``/``audit_text`` truncated to
    :data:`_STREAM_TRUNCATE_CHARS` — useful for debugging, but capped so a
    chatty transition binary does not blow up the resource payload.
    """

    def _tail_truncate(text: str) -> str:
        if len(text) <= _STREAM_TRUNCATE_CHARS:
            return text
        return text[-_STREAM_TRUNCATE_CHARS:]

    return {
        "success": report.success,
        "source_version": _vstr(report.source_version),
        "target_version": _vstr(report.target_version),
        "requested_target": _vstr(report.requested_target),
        "summary": report.summary(),
        "steps": [
            {
                "from_version": _vstr(s.from_version),
                "to_version": _vstr(s.to_version),
                "success": s.success,
                "runtime_seconds": round(s.runtime_seconds, 3),
                "binary": str(s.binary) if s.binary is not None else None,
                "stdout": _tail_truncate(s.stdout),
                "stderr": _tail_truncate(s.stderr),
                "audit_text": _tail_truncate(s.audit_text) if s.audit_text is not None else None,
            }
            for s in report.steps
        ],
        "diff": {
            "added_object_types": list(report.diff.added_object_types),
            "removed_object_types": list(report.diff.removed_object_types),
            "object_count_delta": dict(report.diff.object_count_delta),
            "field_changes": {
                t: {"added": list(fd.added), "removed": list(fd.removed)} for t, fd in report.diff.field_changes.items()
            },
        },
    }


@tool(annotations=_MIGRATE)
async def migrate_model(
    target_version: Annotated[
        str | None,
        Field(
            description=(
                'Target EnergyPlus version "X.Y.Z". If omitted, uses the installed '
                "EnergyPlus version (the migration binaries ship with EnergyPlus, so "
                "an install is required regardless)."
            ),
        ),
    ] = None,
    energyplus_dir: Annotated[
        str | None,
        Field(description="EnergyPlus install dir. Autodetected if None."),
    ] = None,
    keep_work_dir: Annotated[
        bool,
        Field(description="Retain the per-step transition work directory for debugging."),
    ] = False,
    ctx: Context | None = None,
) -> MigrateModelResult:
    """Forward-migrate the loaded model to a newer EnergyPlus version.

    Drives the EnergyPlus IDFVersionUpdater transition binaries through the
    required chain of steps and replaces the session document with the migrated
    one. ``state.file_path`` is unchanged — call ``save_model(path=...)`` to
    persist the migrated model.

    Preconditions: model loaded; target version >= current model version.
    Side effects: replaces the in-memory document; records a change-log entry.
    Next step: validate_model + check_model_integrity, then save_model.

    Read ``idfkit://migration/report`` for per-step stdout/stderr and the
    structural diff after the call.
    """
    from idfkit.exceptions import (
        EnergyPlusNotFoundError,
        MigrationError,
        UnsupportedVersionError,
        VersionMismatchError,
    )
    from idfkit.simulation.config import find_energyplus

    state = get_state()

    if state.migration_lock.locked():
        raise ToolError("A migration is already in progress for this session. Wait for it to finish.")

    async with state.migration_lock:
        doc = state.require_model()

        requested_target = _parse_target_version(target_version) if target_version else None

        try:
            config = find_energyplus(path=energyplus_dir)
        except EnergyPlusNotFoundError as exc:
            raise ToolError(
                "EnergyPlus installation not found. Install EnergyPlus matching the target "
                "version or pass energyplus_dir pointing at the install root."
            ) from exc

        target = requested_target if requested_target is not None else config.version
        on_progress = _build_progress_handler(ctx)

        try:
            report = await idfkit.async_migrate(
                doc,
                target,
                energyplus=config,
                keep_work_dir=keep_work_dir,
                on_progress=on_progress,
            )
        except VersionMismatchError as exc:
            current: tuple[int, int, int] = exc.current
            dest: tuple[int, int, int] = exc.target
            chain = ", ".join(f"{_vstr(a)} -> {_vstr(b)}" for a, b in exc.migration_chain)
            raise ToolError(
                f"Cannot migrate {_vstr(current)} -> {_vstr(dest)}: direction is "
                f"{exc.direction}. " + (f"Migration chain: [{chain}]." if chain else "No migration path is available.")
            ) from exc
        except MigrationError as exc:
            completed = ", ".join(f"{_vstr(a)} -> {_vstr(b)}" for a, b in exc.completed_steps) or "none"
            tail = (exc.stderr or "")[-_STDERR_TAIL_CHARS:]
            from_v = _vstr(exc.from_version) if exc.from_version is not None else "?"
            to_v = _vstr(exc.to_version) if exc.to_version is not None else "?"
            raise ToolError(
                f"Migration failed at {from_v} -> {to_v} "
                f"(exit {exc.exit_code}). Completed steps before failure: [{completed}]. "
                f"stderr tail: {tail!r}"
            ) from exc
        except UnsupportedVersionError as exc:
            raise ToolError(str(exc)) from exc

        migrated_doc = cast("IDFDocument[Literal[True]] | None", report.migrated_model)
        state.document = migrated_doc
        if migrated_doc is not None:
            state.schema = migrated_doc.schema
        state.migration_report = report
        state.record_change(
            "migrate_model",
            f"{_vstr(report.source_version)} -> {_vstr(report.target_version)}",
        )
        state.save_session()

        logger.info(
            "Migrated model %s -> %s (%d step%s)",
            _vstr(report.source_version),
            _vstr(report.target_version),
            len(report.steps),
            "" if len(report.steps) == 1 else "s",
        )

        return _build_result(report)
