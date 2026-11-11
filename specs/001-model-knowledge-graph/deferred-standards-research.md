# Deferred research: standards knowledge

These decisions were made while the standards layer was part of `001-model-knowledge-graph`. The layer was deferred
on 2026-11-11 (spec, Clarifications), and with it these entries. They are kept verbatim as input to the future
standards spec ([deferred-standards.md](deferred-standards.md)) and bind nothing in 001. Cross-references to other
R-numbers point into [research.md](research.md) as it stood before the deferral (commit `ccf9396`); R-14, R-15,
R-21 and R-23 have since been revised there without their standards parts.

---

## R-08 Reading PNNL's standards data

*Amended by R-26: the same loading rules apply to the 90.1 lighting tables, the 62.1 ventilation tables and the
space-type mapping tables, each loaded the first time its topic is asked for.*

**Decision.**
- **Locating the data.** idfkit finds the data directory with
  `importlib.util.find_spec("building_energy_standards_data")` and reads the JSON files under `database_files/`
  directly, lazily, one table at a time, caching each per process. It **never imports the package**.
- **Version.** It reads the data version from `importlib.metadata.version(...)` and puts it on every response.
- **The extra.** It is declared as `standards = ["building-energy-standards-data>=0.3.3,<0.4; python_version <
  '3.14'"]`.
- **Unavailable cases.** On Python 3.14, or without the extra, standards calls raise an actionable "unavailable"
  error naming the extra (Constitution Principle III).

**Rationale. checked during planning:**
- The package's `__init__.py` star-imports every submodule, and `client.py` opens a database and configures
  file logging at import. `find_spec` locates the data without running any of that: verified in a clean venv,
  where 139 files were found without importing the package.
- The wheel declares `Requires-Python >=3.10,<3.14`, while idfkit supports 3.10 to <4.0, so the marker is
  required.
- `envelope_requirements_90_1.json` has 6,315 rows, with templates `90-1975`, `90.1-2004`, `2007`, `2010`, `2013`,
  `2016`, `2019`, `2022` and `2025`. Values are in IP units (`Btu/h-ft2-F`, with 18 rows written `btu/h-ft2-F`).
- Climate zone sets are whole zones (`ClimateZone 3`) except for subtype rows (`ClimateZone 3A`, `3B`, `3C`).
- Surface types are the nine `intended_surface_type` values, and assembly classes are the
  `standards_construction_type` values (`Mass`, `SteelFramed`, `WoodFramed`, `Metal Building`, `IEAD`, `Attic and
  Other`, …).
- 6,015 rows carry an `annotation` citation such as "From 90.1-2019 Table 5.5-5". The 300 without one are
  `Adiabatic` building-category rows, which screening does not use.

**Correction to the spec, checked:** all 288 rows whose limits are heating-degree-day formulas belong to the
`90-1975` template. No 90.1 edition from 2004 to 2025 has one in this table. Report 02 had stated otherwise.
FR-033 and SC-006 were amended in this planning session to require the climate-zone subtype rule instead.

**Unit handling.** idfkit converts U from Btu/h·ft²·°F to W/m²·K using the factor 5.678263. It returns both
values, with the IP value taken verbatim from the row. Unit strings are compared case-insensitively.

**Alternatives considered.**
- The package's SQLite and query API. Rejected: it has import-time side effects, and an SQL layer is needed only
  for generic queries, which PNNL's own `besd-mcp` already offers.
- Vendoring the tables into idfkit. Rejected under FR-038, for licence posture and to avoid duplicated
  maintenance.

## R-09 Object roles needed by envelope screening

*Amended by R-27: zones also carry `space_type`, `lighting_space_type` and `ventilation_space_type`, which are
asserted only.*

**Decision.** `idfkit.standards.roles` computes roles from physics and structure only (FR-036).

- **Surface class.** One of the nine PNNL surface types, from surface type, boundary condition and tilt:
  - roof when tilt is 60° or less, floor when 120° or more, wall otherwise
  - `GroundContact*` from a ground boundary condition
  - `Skylight` for fenestration on a roof
  - `GlassDoor` for a glass door
- **Conditioned status.** `conditioned` when the zone has a thermostat and HVAC equipment, `unconditioned` when
  it has neither, and `unknown` otherwise. Semiheated is never inferred; it must be asserted.
- **Assembly class.**
  - `Mass` when the construction's heat capacity per area reaches the 90.1 mass-wall threshold of 7 Btu/ft²·°F
    (143 kJ/m²·K), computed from layer density, specific heat and thickness.
  - `IEAD` for a roof whose insulation layer lies entirely above a structural deck, with no attic zone.
  - `Metal Building`, `SteelFramed`, `WoodFramed` and `Attic and Other` are **never inferred**, because no field
    of an EnergyPlus construction distinguishes them. They are `unknown` unless asserted.
- **Name-based suggestions.** For example, a construction called "Steel Frame Wall". These are returned only as
  `unconfirmed` and are never used in a verdict.

**Rationale.** Constitution Principle III forbids values inferred from name patterns. Physics-based mass
detection is the one framing class a model can show. Anything else is a judgement the modeller owns, which is
what the assertion path (FR-037) is for.

**Alternatives considered.**
- Inferring steel or wood framing from layer materials. Rejected: framing is usually modelled as an equivalent
  layer with no metal or wood material present.

## R-10 Surface films

**Decision.** `calculate_r_value` and `calculate_u_value` gain an optional `surface_class` argument: `wall`,
`roof` or `floor`, defaulting to `wall`, so existing results do not change. Interior still-air films are wall
0.12, roof (heat flow up) 0.11 and floor (heat flow down) 0.16 m²·K/W. The exterior film is 0.03 m²·K/W. Below
grade, where the exterior film is zero, it is handled by surface class. Envelope screening always passes the
class.

**Rationale.** **checked:** `thermal/properties.py` applies the wall interior film to every surface (report 02,
§1.1). The values are physical constants from the ASHRAE Handbook of Fundamentals and match the 90.1 Appendix A
assumptions. Screening also honours PNNL's `u_value_includes_*_film_coefficient` flags per row.

## R-11 Climate zone and standards context

*Amended by R-29: the context gains the 62.1 edition, and the required items depend on the topic.*

**Decision.**
- **Source of the climate zone.** It comes from, in order:
  1. a user or agent assertion
  2. the weather station matching the session's weather file (by WMO, through the existing station index)
  3. unknown

  The source is reported. Station records labelled "could not be determined" count as unknown, since the index
  already flags them.
- **Standards context.** `{standard: "ASHRAE 90.1", edition, climate_zone, building_category}`, each with its
  source. It lives in idfkit-mcp session state and is persisted in the session file (R-15).
- **No defaults.** A screening with any required item missing fails with a message naming what to set (FR-032).

**Rationale.** **checked:** the station index already holds `ashrae_climate_zone`, and idfkit-mcp's
`WeatherStationModel` drops it.

---

## Re-planning after the 2026-11-11 clarification: lighting and ventilation

The spec now covers three standards topics: the envelope, lighting power (90.1, space-by-space method) and
outdoor-air ventilation (62.1). Every zone gets a space-type role, which is asserted, never computed (FR-031 to
FR-036). R-26 to R-30 are new. R-08, R-09, R-11, R-14, R-15, R-21 and R-23 carry short amendments that point here.
Every **checked** fact below was read from `building-energy-standards-data` 0.3.3, the wheel the earlier entries
used.

## R-26 Lighting and ventilation tables in the standards data

**Checked.**

| Table family | Files | Rows per edition | Units | Citation (`annotation`) |
|---|---|---|---|---|
| 90.1 lighting (`level_3_lighting_90_1_<edition>.json`) | 2004, 2007, 2010, 2013, 2016, 2019, 2022, 2025 | 126–158 | `W/ft2`, except 2 rows in `W/ft` in 2010, 2013 and 2016 | On all but at most one row per edition, for example "From 90.1-2019 Table 9.6.1" or "From 90.1-2022 Table 9.5.2.1-1" |
| 62.1 ventilation (`level_3_ventilation_62_1_<edition>.json`) | 1999, 2004, 2007, 2010, 2013, 2016, 2019, 2022 | 64–110 | `cfm/person` and `cfm/ft2`, except 3 rows in `cfm/room` in 1999 | **None.** Every row's `annotation` is empty |
| Space-type mapping | `level_1_space_types.json` (61 names), `level_2_lighting_space_types.json` (2,735 rows), `level_2_ventilation_space_types.json` (596 rows) | — | — | — |

Further facts that shape the design:
- Each lighting row has a `method`: `BA` (building area), `SS` (space-by-space, building-specific) or `CS` (common
  space types). The space-by-space method uses the `SS` and `CS` rows.
- Lighting rows from 2010 onwards carry `rcr_threshold` (room cavity ratio), on 94 to 121 rows per edition. They
  also carry control requirements (daylight-responsive, partial-off, full-off, scheduled shutoff).
- 62.1-2004 has 7 rows where a rate is null.
- A ventilation row gives `ventilation_rate_occupant` (Rp), `ventilation_rate_area` (Ra), a default occupant
  density and an air class.

**Decision.**
- **Lighting.** The lighting check reads only the `SS` and `CS` rows of the requested 90.1 edition. It converts
  W/ft² to W/m² by multiplying by 10.7639, and returns the IP value verbatim from the row. `BA` rows are never read
  (Clarifications). A row in `W/ft` is a per-length allowance that cannot be compared with a zone's power per area,
  so a zone that maps to one is `cannot_tell` with that reason.
- **Ventilation.** It converts cfm/person to L/s·person (× 0.471947) and cfm/ft² to L/s·m² (× 5.08). A row with a
  null rate, or in `cfm/room`, yields `cannot_tell` with the reason. It never yields a zero.
- **Ventilation citation.** The data carries none, so FR-033 cannot be met from the data alone. idfkit keeps a
  small reviewed table that maps each 62.1 edition to the number of its minimum ventilation rate table. It holds
  eight entries and no values. Each verdict records whether its citation came from the data source or from that
  table (`citation_source: "data" | "idfkit"`). Each entry is checked by a person against the published edition as
  part of the SC-006 sample, and the table numbers are not trusted before that check. This is a citation, not a
  copy of the standard's text, so FR-038 holds.
- **Not evaluated, and listed in `not_checked`:**
  - lighting: room-cavity-ratio adjustments, additional allowances (decorative, retail display), control
    requirements, exterior lighting
  - ventilation: zone air distribution effectiveness (Ez), the system-level outdoor-air intake (Vot) and its
    efficiency, demand-controlled ventilation, the IAQ procedure, exhaust requirements

**Rationale.** The lighting rows cite their tables, as the envelope rows do. The ventilation rows do not, and
inventing a citation silently would break Principle III. Labelling the source of the citation keeps the gap
visible.

**Alternatives considered.**
- Leaving ventilation verdicts without a citation. Rejected: FR-033 and FR-034 require one.
- Supporting only 62.1 editions whose rows carry a citation. Rejected: none do.

## R-27 The space-type role and how it resolves to a requirement row

**Checked.** PNNL's mapping runs in three levels:

1. A level-1 space type (61 names, for example `office` or `corridor`) names a lighting space type and a
   ventilation space type.
2. A level-2 row maps a lighting space type (119 names) or a ventilation space type (98 names) to a row in each
   edition's level-3 table, through `level_3_*_definition_id`.
3. The package's table code declares that id as the level-3 table's `INTEGER PRIMARY KEY`, assigned in insertion
   order. In the JSON, that is the 1-based row position.

The 1-based reading resolves most mappings plausibly. Measured with a token match between the space-type name and
the row's labels, it agrees for 95–104 of 119 lighting mappings from 2004 to 2019, but only for 71 of 119 in 2022
and 2025, and for about 60% of ventilation mappings. Spot checks find:
- **correct:** `office_open_plan_lighting` → 2019 "Office / Open plan", `corridor_lighting` → 2019 "Corridor"
- **a proxy chosen by PNNL:** `airport_concourse_ventilation` → 2019 "Office Buildings / Reception areas"
- **plainly wrong:** `airport_concourse_lighting` → 2019 "Sports Arena: Playing Area / Class IV facility"

The level-2 mapping is therefore PNNL's modelling convention, partly stale against the current level-3 files. It
is not the standard.

**Decision.**
- **Roles.** Each zone gets three roles:
  - `space_type`, from the level-1 vocabulary (61 names)
  - optionally, `lighting_space_type` and `ventilation_space_type`, from the level-2 vocabularies, for finer
    distinctions such as enclosed versus open-plan office. A topic-specific role wins over `space_type` for its
    topic.

  All three are only ever asserted (FR-036). Name-based suggestions are returned with origin `unconfirmed` and are
  never used.
- **Resolution.** A role is resolved through the data source's mapping, never through idfkit's own judgement: level
  1 to level 2 by name, then level 2 to the level-3 row by 1-based id. Each verdict carries the resolved row's
  labels (primary and secondary space type, and method), the citation, and the assumption "space type resolved
  through the data source's space-type mapping (level 1 → level 2 → row N)". An agent and a modeller can then see
  which row was used, and challenge it.
- **Mapping qualification.** idfkit runs a test with the extra installed. For every supported edition, it resolves
  every level-2 mapping and checks that the id is in range and that the row's `method` is `SS` or `CS` for
  lighting.
  - A person reviews the resolved labels once per data version. Any mapping judged wrong is recorded in a reviewed
    file, `idfkit/standards/_mapping_review.py`, with the data version and a reason, and is reported upstream to
    PNNL. The file holds no values.
  - A zone whose role resolves through a mapping on that list is `cannot_tell`, with the reason "the data source's
    mapping for this space type is under review", and the hint is to assert a finer topic-specific space type.
  - A mapping is never corrected locally. A local correction would be idfkit's own standards judgement (FR-038).
  - A new data version reruns the test, and the review list is kept only for mappings that still resolve the same
    way.
- **No building area method.** No role for building type is added (Clarifications).

**Rationale.** One assertion per zone is what the clarification chose. The level-1 vocabulary keeps it to one, and
the topic-specific roles cover cases where the level-1 name is too coarse. Showing the resolved row honours FR-005,
and the review list keeps a known-bad mapping from producing a confident verdict (Principle III).

**Alternatives considered.**
- Asserting the edition's own row labels directly. Rejected: the labels change between editions, as "Atrium:
  First Three Floors" in 2004 became "Atrium / < 20 ft in height" in 2019, so one assertion would not carry across
  editions.
- Trusting the level-2 mapping blindly. Rejected on the spot checks above.
- Matching level-3 labels by text. Rejected: free-text matching is weak (FR-005) and could never feed a verdict.

## R-28 Model-side lighting power and outdoor air

**Checked.** Neither idfkit nor idfkit-mcp computes a zone's lighting power density or design outdoor air today.
idfkit has `geometry.calculate_zone_floor_area`, and nothing reads `Lights`, `People` or
`DesignSpecification:OutdoorAir` for standards purposes.

**Decision.** `idfkit.standards` gains two model-side functions that need no extra (FR-006):
- **`zone_lighting(doc)`**, for each zone:
  - Sums installed interior lighting power over every `Lights` object that applies to the zone, directly or
    through a `ZoneList`, `Space` or `SpaceList`.
  - Converts by the object's calculation method: `LightingLevel` as given, `Watts/Area` times the zone or space
    floor area, and `Watts/Person` times the design number of people from `People`.
  - Divides by the zone floor area, giving W/m² and W/ft².
  - Schedules are ignored, because the allowance concerns installed power. That is stated as an assumption.
  - The zone multiplier is carried (FR-025), and it does not change a density.
- **`zone_outdoor_air(doc)`**, for each zone:
  - Reads the `DesignSpecification:OutdoorAir` or `DesignSpecification:OutdoorAir:SpaceList` named by the zone's
    `Sizing:Zone`.
  - Computes the design breathing-zone outdoor air in L/s from its method: `Flow/Person`, `Flow/Area`,
    `Flow/Zone`, `AirChanges/Hour`, `Sum` or `Maximum`.
  - Takes the design occupancy from `People` and the floor area and volume from geometry.
  - A zone with no specification gets no value and the reason. A method that cannot be expressed as a design flow
    (`IndoorAirQualityProcedure` and the proportional-control methods) gets no value and the reason, never a guess.
- **Ventilation verdict.**
  - It compares the model's breathing-zone outdoor air with the required Vbz = Rp·Pz + Ra·Az. Pz is the model's
    design occupancy and Az the zone floor area.
  - When the model gives separate per-person and per-area rates (the `Sum` method), each is also reported against
    Rp and Ra as evidence.
  - The verdict states the assumptions: Pz is taken from `People`, the schedules are ignored, and Ez is not
    applied.

**Rationale.** These are physics and bookkeeping, not standards knowledge, so they stay usable without the data.
They live in `idfkit.standards` because screening is their only consumer in this feature. Using the model's own
occupancy, rather than the table's default density, keeps the check about the model as designed.

**Alternatives considered.**
- Using the table's default occupant density for Pz. Rejected: it checks a hypothetical occupancy, not the model's.
  The default is reported alongside the verdict for comparison.
- Reading lighting power from simulation output. Rejected: it would make a model-only check depend on a run
  (FR-006).

## R-29 One screening entry point, by topic

**Decision.**
- **idfkit.**
  - `screen(doc, context, *, topics=None, asserted=None) -> ScreeningReport` replaces the planned
    `screen_envelope`, which was never released. `topics` takes values from `"envelope"`, `"lighting"` and
    `"ventilation"`. `None` means every topic whose required context items are present.
  - `lookup_envelope`, `lookup_lighting` and `lookup_ventilation` replace the single envelope lookup.
  - `StandardsContext` becomes a public frozen dataclass in `idfkit.standards`. It was already an argument of
    `ModelGraph`, but was missing from the contract.
- **Context items required, by topic:**
  - envelope: 90.1 edition, climate zone and building category
  - lighting: 90.1 edition
  - ventilation: 62.1 edition, a new context field (FR-032)

  A topic the caller names with any item missing fails, naming each missing item. With `topics=None`, a topic whose
  items are missing is listed in the report's `not_evaluated` with what to set. A screening that would evaluate no
  topic fails (Principle III).
- **idfkit-mcp.** A single tool, `screen_standards(topics=None, limit=20)`, replaces `screen_envelope`. This
  saves one tool description against SC-010. `lookup_standard` takes `topic` from the same three values, with
  `space_type` required for lighting and ventilation.

**Rationale.** One entry point and one report shape, with verdicts on constructions and zones, keep the graph's
`verdict` kind uniform. One tool keeps the tool listing small.

**Alternatives considered.**
- Three tools, one per topic. Rejected: they cost more in the listing for no gain in precision, because `topics`
  filters.
- Keeping `screen_envelope` beside a generic `screen`. Rejected: it was never released, and two names would mean
  two ways to do the same thing.

## R-30 Evaluation, fixtures and budgets for the new topics

**Decision.**
- **Fault catalogue.** It grows to 13 fault types. The standards layer gains "lighting power above the allowance
  for the asserted space type". The prompt states the space type, so the task does not depend on the agent
  guessing it. FR-040 and FR-041 still hold.
- **Hand-check sample (SC-006).** It gains at least five lighting and five ventilation verdicts against asserted
  space types. It includes at least one 62.1 citation from idfkit's citation table, and at least one zone whose
  mapping is under review, to show the `cannot_tell` path.
- **Budgets.** The lighting and ventilation tables are 54–160 KB per edition, and the level-2 lighting mapping
  is 1.5 MB. The first standards call stays within ≤ 150 ms (R-21), to be confirmed by `bench_standards.py` in the
  slice. A full three-topic screening of a loaded model stays within ≤ 20 ms. Each table is loaded only when its
  topic is first asked for.
