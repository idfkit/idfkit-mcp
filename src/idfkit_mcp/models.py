"""Pydantic response models for structured MCP tool output.

Each tool function declares one of these models as its return type so that
FastMCP can populate both ``content`` (text) and ``structuredContent``
(typed JSON) in MCP responses.
"""

from __future__ import annotations

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


class DescribeObjectTypeResult(BaseModel):
    """Response from ``describe_object_type``."""

    object_type: str
    memo: str | None
    has_name: bool
    is_extensible: bool
    extensible_size: int | None
    required_fields: list[str]
    fields: list[FieldDescriptionModel]
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


class ResultsErrorSummary(BaseModel):
    """Error summary in get_results_summary."""

    fatal: int
    severe: int
    warnings: int
    summary: str


class TableSummary(BaseModel):
    """A single HTML report table summary."""

    title: str
    report: str
    # ``for`` is a Python keyword so we use an alias.
    for_string: str
    data: dict[str, object] | None = None
    truncated: bool = False


class GetResultsSummaryResult(BaseModel):
    """Response from ``get_results_summary``."""

    success: bool
    runtime_seconds: float
    output_directory: str
    errors: ResultsErrorSummary
    fatal_messages: list[ErrorMessage] | None = None
    severe_messages: list[ErrorMessage] | None = None
    tables: list[TableSummary] | None = None


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
# Session management
# ---------------------------------------------------------------------------


class ClearSessionResult(BaseModel):
    """Response from ``clear_session``."""

    status: str


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
