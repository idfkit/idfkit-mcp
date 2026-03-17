"""Server state management for the idfkit MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from idfkit import LATEST_VERSION, get_schema

if TYPE_CHECKING:
    from idfkit.document import IDFDocument
    from idfkit.schema import EpJSONSchema
    from idfkit.simulation.result import SimulationResult
    from idfkit.weather.index import StationIndex


@dataclass
class ServerState:
    """Holds the active document, schema, and simulation result.

    MCP stdio transport is single-threaded, so a module-level instance is safe.
    """

    document: IDFDocument | None = None
    schema: EpJSONSchema | None = None
    file_path: Path | None = None
    simulation_result: SimulationResult | None = None
    weather_file: Path | None = None
    station_index: StationIndex | None = None

    def require_model(self) -> IDFDocument:
        """Return the active document or raise a descriptive error."""
        if self.document is None:
            msg = "No model loaded. Use load_model or new_model first."
            raise RuntimeError(msg)
        return self.document

    def require_schema(self) -> EpJSONSchema:
        """Return the active schema or raise a descriptive error."""
        if self.schema is None:
            msg = "No schema loaded. Use load_model or new_model first."
            raise RuntimeError(msg)
        return self.schema

    def get_or_load_schema(self, version: tuple[int, int, int] | None = None) -> EpJSONSchema:
        """Return the active schema, or load one for the given version."""
        if version is not None:
            return get_schema(version)
        if self.schema is not None:
            return self.schema
        return get_schema(LATEST_VERSION)

    def get_or_load_station_index(self) -> StationIndex:
        """Return the cached station index, loading it on first use."""
        if self.station_index is None:
            from idfkit.weather import StationIndex

            self.station_index = StationIndex.load()
        return self.station_index

    def require_simulation_result(self) -> SimulationResult:
        """Return the simulation result or raise a descriptive error."""
        if self.simulation_result is None:
            msg = "No simulation results available. Use run_simulation first."
            raise RuntimeError(msg)
        return self.simulation_result


# Module-level singleton
_state = ServerState()


def get_state() -> ServerState:
    """Return the module-level server state."""
    return _state
