"""Pydantic response models for structured MCP tool output.

Each tool function declares one of these models as its return type so that
FastMCP can populate both ``content`` (text) and ``structuredContent``
(typed JSON) in MCP responses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Shared / reusable sub-models
# ---------------------------------------------------------------------------


class FieldDescriptionModel(BaseModel):
    """Schema description of a single EnergyPlus field."""

    name: str
    field_type: str
    required: bool
    default: object = None
    units: str | None = None
    enum_values: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    is_reference: bool | None = None
    object_list: list[str] | None = None


class ValidationErrorModel(BaseModel):
    """A single validation diagnostic."""

    severity: str
    object_type: str | None
    object_name: str | None
    field: str | None
    message: str
    code: str | None


class ObjectBrief(BaseModel):
    """Minimal object identification."""

    object_type: str
    name: str


class WeatherStationModel(BaseModel):
    """Weather station metadata."""

    wmo: str
    city: str
    state: str
    country: str
    latitude: float
    longitude: float
    timezone: float
    elevation: float
    source: str
    url: str


# ---------------------------------------------------------------------------
# Schema tool responses
# ---------------------------------------------------------------------------


class GroupInfo(BaseModel):
    """Object-type group summary."""

    count: int
    types: list[str] | None = None


class ListObjectTypesResult(BaseModel):
    """Response from ``list_object_types``."""

    total_types: int
    truncated: bool
    groups: dict[str, GroupInfo]


class ExtensibleGroupInfo(BaseModel):
    """Describes the array wrapper key for an object type's extensible group.

    ``add_object`` expects items to be passed under ``key`` as a list of dicts
    matching ``item_fields`` — e.g. ``{"vertices": [{"vertex_x_coordinate": ...},
    {"vertex_x_coordinate": ...}, ...]}``. ``example`` is a literal payload an
    agent can copy and adapt.
    """

    key: str
    item_fields: list[FieldDescriptionModel]
    example: dict[str, list[dict[str, object]]]
    note: str


class DescribeObjectTypeResult(BaseModel):
    """Response from ``describe_object_type``."""

    object_type: str
    memo: str | None
    has_name: bool
    is_extensible: bool
    extensible_size: int | None
    required_fields: list[str]
    fields: list[FieldDescriptionModel]
    extensible_group: ExtensibleGroupInfo | None = None
    doc_url: str | None = None


class SchemaMatch(BaseModel):
    """A single search-schema match."""

    object_type: str
    group: str
    memo: str | None
    doc_url: str | None = None


class SearchSchemaResult(BaseModel):
    """Response from ``search_schema``."""

    query: str
    count: int
    limit: int
    matches: list[SchemaMatch]


class LookupDocumentationResult(BaseModel):
    """Response from ``lookup_documentation``."""

    object_type: str
    version: str
    io_reference_url: str | None = None
    engineering_reference_url: str | None = None
    search_url: str | None = None


class DocSearchHit(BaseModel):
    """A single documentation search hit."""

    location: str
    title: str
    path: list[str]
    tags: list[str]
    text: str
    score: float
    doc_url: str


class SearchDocsResult(BaseModel):
    """Response from ``search_docs``."""

    query: str
    version: str
    count: int
    results: list[DocSearchHit]


class GetDocSectionResult(BaseModel):
    """Response from ``get_doc_section``."""

    location: str
    title: str
    path: list[str]
    tags: list[str]
    text: str
    doc_url: str
    version: str
    truncated: bool = False


class AvailableReferencesResult(BaseModel):
    """Response from ``get_available_references``."""

    object_type: str
    field_name: str
    available_names: list[str]
    by_reference_list: dict[str, list[str]]


# ---------------------------------------------------------------------------
# Read tool responses
# ---------------------------------------------------------------------------


class GroupSummary(BaseModel):
    """Per-group summary in a model overview."""

    count: int
    types: dict[str, int]


class ModelSummary(BaseModel):
    """Response from ``get_model_summary`` and ``load_model``."""

    version: str
    file_path: str | None
    total_objects: int
    zone_count: int
    groups: dict[str, GroupSummary]


class ConvertOsmResult(ModelSummary):
    """Response from ``convert_osm_to_idf``."""

    status: str
    osm_path: str
    output_path: str
    openstudio_version: str
    allow_newer_versions: bool
    translator_warnings_count: int
    translator_errors_count: int


class ListObjectsResult(BaseModel):
    """Response from ``list_objects``."""

    object_type: str
    total: int
    returned: int
    objects: list[dict[str, object]]


class SearchObjectsMatch(BaseModel):
    """A single search-objects match."""

    object_type: str
    name: str


class SearchObjectsResult(BaseModel):
    """Response from ``search_objects``."""

    query: str
    count: int
    matches: list[SearchObjectsMatch]


class ReferencesResult(BaseModel):
    """Response from ``get_references``."""

    name: str
    referenced_by: list[ObjectBrief]
    referenced_by_count: int
    references: list[str]
    references_count: int


# ---------------------------------------------------------------------------
# Write tool responses
# ---------------------------------------------------------------------------


class NewModelResult(BaseModel):
    """Response from ``new_model``."""

    status: str
    version: str


class BatchAddResult(BaseModel):
    """Response from ``batch_add_objects``."""

    total: int
    success: int
    errors: int
    results: list[dict[str, object]]


class RemoveObjectResult(BaseModel):
    """Response from ``remove_object``."""

    status: str
    object_type: str
    name: str


class RenameObjectResult(BaseModel):
    """Response from ``rename_object``."""

    status: str
    object_type: str
    old_name: str
    new_name: str
    references_updated: int


class SaveModelResult(BaseModel):
    """Response from ``save_model``."""

    status: str
    file_path: str
    format: str


# ---------------------------------------------------------------------------
# Validation tool responses
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Response from ``validate_model``."""

    is_valid: bool
    error_count: int
    warning_count: int
    info_count: int
    errors: list[ValidationErrorModel]
    warnings: list[ValidationErrorModel]
    errors_truncated: bool = False
    warnings_truncated: bool = False


class DanglingReference(BaseModel):
    """A single dangling-reference entry."""

    source_type: str
    source_name: str
    field: str
    missing_target: str


class CheckReferencesResult(BaseModel):
    """Response from ``check_references``."""

    dangling_count: int
    returned: int
    dangling_references: list[DanglingReference]


# ---------------------------------------------------------------------------
# Simulation diagnostics sub-models (used in GetResultsSummaryResult)
# ---------------------------------------------------------------------------


class UnmetHoursRow(BaseModel):
    """Unmet heating/cooling hours for one zone."""

    zone: str
    heating_hours: float
    cooling_hours: float


class EndUseRow(BaseModel):
    """Energy end-use broken down by fuel type (kWh, converted from GJ)."""

    end_use: str
    electricity_kwh: float | None = None
    natural_gas_kwh: float | None = None
    district_cooling_kwh: float | None = None
    district_heating_kwh: float | None = None
    other_kwh: float | None = None  # all remaining fuel types combined


class ClassifiedWarning(BaseModel):
    """A simulation warning classified by domain category."""

    category: str  # "convergence" | "geometry" | "unusual_value" | "hvac" | "other"
    message: str
    details: list[str]


class SimulationQAFlag(BaseModel):
    """A high-level QA observation derived from simulation results."""

    severity: str  # "info" | "warning" | "critical"
    flag: str
    message: str


# ---------------------------------------------------------------------------
# Simulation tool responses
# ---------------------------------------------------------------------------


class EnergyPlusInfo(BaseModel):
    """EnergyPlus installation metadata."""

    version: str
    install_dir: str
    executable: str


class ErrorMessage(BaseModel):
    """A single simulation error/warning message."""

    message: str
    details: list[str]


class SimulationErrorDetail(BaseModel):
    """Error summary from a simulation run."""

    fatal: int
    severe: int
    warnings: int
    fatal_messages: list[ErrorMessage] | None = None
    severe_messages: list[ErrorMessage] | None = None
    warning_messages: list[ErrorMessage] | None = None


class RunSimulationResult(BaseModel):
    """Response from ``run_simulation``."""

    success: bool
    runtime_seconds: float
    output_directory: str
    energyplus: EnergyPlusInfo
    errors: SimulationErrorDetail
    simulation_complete: bool


class UploadSimulationResultResult(RunSimulationResult):
    """Response from ``upload_simulation_result``.

    Mirrors ``RunSimulationResult`` so clients can consume either response
    generically. Adds ``mode="upload"`` to distinguish client-produced runs
    from server-executed ones, and ``artifacts_written`` to echo which
    files actually landed on disk.
    """

    mode: Literal["upload"] = "upload"
    artifacts_written: list[str] = []


class RunInBrowserHandoff(BaseModel):
    """Response from ``run_simulation_in_browser``.

    Minimal agent-facing handoff. The IDF / EPW payload and the iframe
    wiring live on the tool-call ``_meta`` dict (key ``browser_run``) so the
    agent transcript stays small while the UI resource still receives
    everything it needs.
    """

    mode: Literal["browser_handoff"] = "browser_handoff"
    run_id: str
    message: str


class EnergyPlusAssetResult(BaseModel):
    """Response from ``fetch_energyplus_asset``.

    Returns one EnergyPlus WASM asset (glue JS, binary, IDD, or a dataset
    file) base64-encoded so the browser iframe can load it through the
    MCP Apps SDK's tool-call channel, bypassing cross-origin fetch /
    CSP / mixed-content constraints that block direct HTTP access in
    sandboxed MCP App iframes.

    Supports range fetching: when ``offset`` / ``chunk_size`` are set, the
    response carries only that slice. The iframe uses this to pull the
    30 MB WASM binary in ~1 MB chunks so its progress bar can advance on
    bytes received rather than only between files.
    """

    filename: str
    content_base64: str
    # Bytes returned in this response (may be less than chunk_size when
    # offset + chunk_size exceeds the file size).
    size: int
    # Byte offset this chunk starts at within the full file.
    offset: int = 0
    # Total size of the source file in bytes — lets the iframe compute %.
    total_size: int = 0
    # True when this chunk is the last one for the given file.
    is_last: bool = True


class ResultsErrorSummary(BaseModel):
    """Error summary in get_results_summary."""

    fatal: int
    severe: int
    warnings: int
    summary: str


class GetResultsSummaryResult(BaseModel):
    """Response from ``get_results_summary`` and ``idfkit://simulation/results`` resource.

    Combines raw simulation output with structured QA diagnostics to drive the
    agent QA loop: simulate → read this resource → identify issues → fix → repeat.
    """

    success: bool
    runtime_seconds: float
    output_directory: str
    errors: ResultsErrorSummary
    fatal_messages: list[ErrorMessage] | None = None
    severe_messages: list[ErrorMessage] | None = None
    # --- QA diagnostics (populated when SQL output is available) ---
    sql_available: bool = False
    unmet_hours: list[UnmetHoursRow] | None = None
    total_unmet_heating_hours: float | None = None
    total_unmet_cooling_hours: float | None = None
    end_uses: list[EndUseRow] | None = None
    classified_warnings: list[ClassifiedWarning] | None = None
    qa_flags: list[SimulationQAFlag] | None = None
    notes: list[str] | None = None


class OutputVariableEntry(BaseModel):
    """A single output variable or meter entry."""

    name: str
    units: str
    key: str | None = None
    type: str


class ListOutputVariablesResult(BaseModel):
    """Response from ``list_output_variables``."""

    total_available: int
    returned: int
    variables: list[OutputVariableEntry]


class TimeseriesRow(BaseModel):
    """A single time-series data point."""

    timestamp: str
    value: float


class QueryTimeseriesResult(BaseModel):
    """Response from ``query_timeseries``."""

    variable_name: str
    key_value: str | None = None
    units: str
    frequency: str
    total_points: int
    returned: int
    data: list[TimeseriesRow]


class ExportTimeseriesResult(BaseModel):
    """Response from ``export_timeseries``."""

    path: str
    variable_name: str
    key_value: str | None = None
    units: str
    frequency: str
    rows: int


class TabularRow(BaseModel):
    """A single row from an EnergyPlus tabular report."""

    report_name: str
    report_for: str
    table_name: str
    row_name: str
    column_name: str
    units: str
    value: str


class QuerySimulationTableResult(BaseModel):
    """Response from ``query_simulation_table``."""

    report_name: str
    table_name: str | None
    row_count: int
    rows: list[TabularRow]


# ---------------------------------------------------------------------------
# Migration tool responses
# ---------------------------------------------------------------------------


class MigrationStepBrief(BaseModel):
    """One transition step from a ``migrate_model`` run."""

    from_version: str
    to_version: str
    success: bool
    runtime_seconds: float
    binary: str | None = None


class FieldDeltaModel(BaseModel):
    """Schema-level field changes between two versions of an object type."""

    added: list[str]
    removed: list[str]


class MigrationDiffSummary(BaseModel):
    """Structural diff between the source and migrated documents."""

    added_object_types: list[str]
    removed_object_types: list[str]
    object_count_delta: dict[str, int]
    field_changes: dict[str, FieldDeltaModel]


class MigrateModelResult(BaseModel):
    """Response from ``migrate_model``."""

    success: bool
    source_version: str
    target_version: str
    requested_target: str
    steps: list[MigrationStepBrief]
    diff: MigrationDiffSummary
    summary: str


# ---------------------------------------------------------------------------
# Weather tool responses
# ---------------------------------------------------------------------------


class SpatialStationResult(WeatherStationModel):
    """Weather station with distance from search point."""

    distance_km: float


class TextStationResult(WeatherStationModel):
    """Weather station with text-match score."""

    score: float
    match_field: str


class SearchWeatherStationsResult(BaseModel):
    """Response from ``search_weather_stations``."""

    search_type: str
    query: str | None = None
    count: int
    stations: list[dict[str, object]]


class DownloadWeatherFileResult(BaseModel):
    """Response from ``download_weather_file``."""

    status: str
    station: WeatherStationModel
    epw_path: str
    ddy_path: str


# ---------------------------------------------------------------------------
# Peak load analysis
# ---------------------------------------------------------------------------


class PeakLoadComponent(BaseModel):
    """A single component contributing to a peak load."""

    name: str
    value_w: float
    percent: float | None = None


class ZonePeakLoad(BaseModel):
    """Peak load decomposition for a single zone."""

    zone_name: str
    peak_w: float
    peak_w_per_m2: float | None = None
    floor_area_m2: float | None = None
    multiplier: int = 1
    peak_timestamp: str | None = None
    components: list[PeakLoadComponent] = []


class FacilityPeakSummary(BaseModel):
    """Facility-level peak load with component breakdown and zone ranking."""

    peak_w: float
    peak_w_per_m2: float | None = None
    peak_timestamp: str | None = None
    components: list[PeakLoadComponent] = []
    zones: list[ZonePeakLoad] = []


class DesignDaySizing(BaseModel):
    """Design-day sizing result for a single zone."""

    zone_name: str
    calculated_load_w: float | None = None
    user_load_w: float | None = None
    load_w_per_m2: float | None = None
    design_day: str | None = None
    peak_timestamp: str | None = None


class PeakLoadAnalysisResult(BaseModel):
    """Complete peak load QA/QC analysis."""

    cooling: FacilityPeakSummary
    heating: FacilityPeakSummary
    sizing_cooling: list[DesignDaySizing] = []
    sizing_heating: list[DesignDaySizing] = []
    total_floor_area_m2: float
    flags: list[str] = []


# ---------------------------------------------------------------------------
# Simulation report viewer
# ---------------------------------------------------------------------------


class ReportTableRow(BaseModel):
    """A single row in a tabular report table."""

    label: str
    values: list[str]


class ReportTable(BaseModel):
    """A single table within a report section."""

    table_name: str
    columns: list[str]
    rows: list[ReportTableRow]


class ReportSection(BaseModel):
    """A report section (one report + for_string combination)."""

    report_name: str
    for_string: str
    tables: list[ReportTable]


class SimulationReportResult(BaseModel):
    """Full simulation report for the interactive viewer."""

    building_name: str
    environment: str
    energyplus_version: str
    timestamp: str
    report_count: int
    table_count: int
    reports: list[ReportSection]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class ClearSessionResult(BaseModel):
    """Response from ``clear_session``."""

    status: str


# ---------------------------------------------------------------------------
# Zone properties tool responses
# ---------------------------------------------------------------------------


class SurfaceTypeCounts(BaseModel):
    """Surface counts by type for a zone."""

    walls: int = 0
    floors: int = 0
    ceilings: int = 0
    roofs: int = 0
    windows: int = 0
    doors: int = 0
    other: int = 0


class ZoneProperties(BaseModel):
    """Typed summary for one EnergyPlus zone."""

    name: str
    floor_area_m2: float | None = None
    volume_m3: float | None = None
    height_m: float | None = None
    surface_counts: SurfaceTypeCounts
    constructions: list[str]
    schedules: list[str]
    hvac_connections: list[str]
    thermostats: list[str]


class GetZonePropertiesResult(BaseModel):
    """Response from ``get_zone_properties``."""

    zone_count: int
    zones: list[ZoneProperties]


# ---------------------------------------------------------------------------
# Model integrity tool responses
# ---------------------------------------------------------------------------


class IntegrityIssue(BaseModel):
    """A single domain-level integrity issue found by check_model_integrity."""

    severity: str  # "error" | "warning" | "info"
    category: str  # "geometry" | "controls" | "references" | "hvac" | "schedules"
    object_type: str | None = None
    object_name: str | None = None
    message: str


class ModelIntegrityResult(BaseModel):
    """Response from ``check_model_integrity``."""

    passed: bool
    error_count: int
    warning_count: int
    issues: list[IntegrityIssue]
    checks_run: list[str]


# ---------------------------------------------------------------------------
# Change log tool responses
# ---------------------------------------------------------------------------


class ChangeLogEntry(BaseModel):
    """A single recorded model mutation."""

    tool: str
    at: str  # ISO 8601 timestamp
    summary: str | None = None


class GetChangeLogResult(BaseModel):
    """Response from ``get_change_log``."""

    entry_count: int
    entries: list[ChangeLogEntry]
