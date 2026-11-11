# Deferred: standards knowledge (ASHRAE 90.1 and 62.1 screening)

**Status**: Deferred on 2026-11-11 from [spec.md](spec.md) to a future spec, to bring the scope of
`001-model-knowledge-graph` down to the topology and results layers and the evaluation.

**What this file is.** The standards requirements as they stood when they were deferred, kept verbatim so that the
future spec starts from them instead of from memory. It is an input to `/speckit-specify`, not a commitment. Nothing
here binds `001-model-knowledge-graph`. Requirement numbers (FR-030 to FR-038a, SC-006, SC-007) are retired in that
spec and should be renumbered in the new one.

**Research.** The evidence is unchanged: [background/02-standards-and-ontologies.md](background/02-standards-and-ontologies.md),
and research decisions R-08 to R-11 and R-26 to R-30 in [research.md](research.md).

## What the future spec should settle first

- **Python 3.14 and later.** The data source declares support only below Python 3.14. Decide whether the layer may
  ship unavailable there, or must wait for an upstream fix or a licensed copy of the data files (FR-038a below).
- **What it builds on.** Lighting and ventilation verdicts attach to zones, and later HVAC topics (efficiency,
  economizers) need the topology and results layers of 001. Writing the new spec after 001's evaluation reports
  shows which of those layers help agents.
- **What it adds to the graph.** 001's combined graph view has no `verdict` node or edge kind. The future spec adds
  them, under the versioning rule of 001's FR-053 and FR-057.
- **The shipped unit error does not wait.** The 5.7× roof-target error in idfkit-plugin's envelope guidance is a
  correction outside any spec ([background/README.md](background/README.md#corrections-that-do-not-wait-for-this-feature)).

## Problem statement (from 001's introduction)

**Domain expectations.** Nothing tells the agent what a value *should* be. Agents recite standards tables from
memory, and the guidance shipped to them today contains a unit error that makes roof targets about 5.7 times too
strict.

## Clarifications (Session 2026-11-11)

- Q: When a modeller or agent asserts an object's role, where should that assertion be saved? → A: In the session
  only. It survives server restarts but not the end of the session, and nothing is written to model files.
- Q: Which ASHRAE 90.1 editions should the first envelope screening support? → A: Every 90.1 edition the standards
  data source covers (currently 2004 through 2025). *Correction during planning:* the original wording also
  required limits given as heating-degree-day formulas. In the data source those rows belong only to 90-1975, not
  to any 90.1 edition from 2004 to 2025, so that requirement was replaced by the climate-zone subtype rule
  (FR-033, SC-006). See research.md, R-08.
- Q: Which standards topics should this feature link to model objects in the knowledge graph? → A: The envelope
  (U, C and F factors and SHGC), lighting power and 62.1 ventilation. A zone space-type role is added, which can be
  asserted, and name-based suggestions are labelled unconfirmed. HVAC minimum efficiency, economizer and system
  requirements, IECC and 189.1 are later work, because they depend on the topology and results layers being
  finished.
- Q: Which ASHRAE 90.1 lighting method should the lighting check use: per space type, or one allowance for the whole
  building? → A: The space-by-space method only. Each zone gets one lighting verdict from its asserted space type,
  the same role ventilation uses. The building area method is later work.

## User story

### User Story 5 - Screen the model against a chosen energy standard (Priority: P2)

A modeller asks "does this envelope meet ASHRAE 90.1-2019 in Chicago?". The agent establishes the climate zone and
where it came from, and confirms the standard edition. It then requests a screening. Each opaque construction and
window type gets a verdict (meets, does not meet, or cannot tell), with the computed value and the requirement in
both SI and inch-pound units. Each verdict cites the standard's table, lists the assumptions it rests on, and lists
what was not checked. The screening is labelled as a screening, not a compliance determination.

The same screening covers lighting power and outdoor-air ventilation for each zone. Each of those needs the zone's
space type, which the model does not record. The agent can propose space types, for example from zone names, but a
proposal stays unconfirmed until the modeller or the agent asserts it. Until then those zones are "cannot tell".

**Why this priority**: Agents do this from memory today, and the guidance shipped to them is wrong. The roof
targets in the plugin's envelope agent are inch-pound values labelled as SI. An openly licensed (BSD-2),
maintained, machine-readable source of the requirement tables exists. idfkit already computes most of the model
side. What nobody provides is the step that matches each model value to the right table row. That matching is this
story.

**Independent Test**: For a model with a known roof construction and a weather location in climate zone 5A, run the
screening against 90.1-2019. The roof verdict reports a U-factor computed with the film appropriate to a roof, the
requirement from the cited table in both unit systems, and a verdict matching a hand calculation.

**Acceptance Scenarios**:

1. **Given** a model with a weather location, **When** the agent asks for the standards context, **Then** the response
   gives the climate zone and its source, or states that it is unknown and how to supply it.
2. **Given** no standard edition has been chosen, **When** the agent requests a screening, **Then** the request fails
   and asks for the edition. It does not assume one.
3. **Given** a construction whose assembly class (mass, steel-framed, wood-framed and so on) cannot be determined from
   its layers, **When** the screening runs, **Then** that construction is reported as "cannot tell" with the reason
   and how to resolve it. It is not given a guessed verdict.
4. **Given** the agent or modeller asserts an assembly class, **When** the screening runs again, **Then** the verdict
   uses the asserted value and records it as asserted, not inferred.
5. **Given** any screening response, **When** it is returned, **Then** it states the standard, the edition, the data
   source and its version, and the provisions it did not evaluate.
6. **Given** a zone with no asserted space type, **When** the screening runs, **Then** its lighting and ventilation
   checks are "cannot tell", with any name-based suggestion labelled unconfirmed and the request that would assert
   it.
7. **Given** a zone whose space type has been asserted, **When** the screening runs, **Then** its lighting power and
   its outdoor-air rates are compared with the allowance and minimum for that space type, in both unit systems,
   each with the cited table.

---

## Edge cases

- **No space type**: Lighting and ventilation requirements depend on a space type the model does not record. A
  zone without an asserted space type is "cannot tell" for those checks, never matched by name.
- **No weather location**: Without a weather location the climate zone is unknown, and the screening says so rather
  than guessing.
- **Standards gaps**: A requirement the data source does not cover is reported as not evaluated, not as a pass.

## Functional requirements

- **FR-030**: An agent MUST be able to obtain the model's climate zone together with its source (weather station
  record, weather file, or user assertion). Weather station search MUST report the climate zone and allow filtering
  by it.
- **FR-031**: An agent MUST be able to obtain, for each construction used on the building's exterior, its thermal
  transmittance. Fenestration also gets solar heat gain coefficient. Surface films MUST be the ones appropriate to
  the surface's orientation (wall, roof, floor). For each zone, the agent MUST also be able to obtain its installed
  lighting power per floor area and its design outdoor-air rates per person and per floor area, each computed from
  the model with zone multipliers carried.
- **FR-032**: An agent or modeller MUST be able to set the standard, edition, climate zone and building category for
  a session, and the ASHRAE 62.1 edition used for ventilation. A screening MUST fail with an actionable message when any required item is missing, rather than
  assuming a default.
- **FR-033**: An agent MUST be able to look up requirement values for envelope assemblies by standard, edition,
  climate zone and assembly class. Results come back in SI and inch-pound units with the standard's table cited.
  A lookup without the filters needed to keep it bounded MUST be refused with guidance. Lookups and screenings MUST
  support every ASHRAE 90.1 edition the data source covers (currently 2004 through 2025). Where a limit is given
  for a whole climate zone and also for its moist, dry or marine subtype (for example "3" and "3A"), the subtype
  row MUST be used. A requested edition the data source does not cover MUST be refused, with the covered editions
  named. The agent MUST also be able to look up lighting power allowances by 90.1 edition and space type, using the
  space-by-space method only (the building area method is not part of this feature), and
  outdoor-air minimums by 62.1 edition and space type, for every edition the data source covers (currently 90.1
  2004 through 2025 and 62.1 1999 through 2022), in both unit systems with the table cited.
- **FR-034**: An agent MUST be able to request a screening covering three topics: the envelope, lighting power and
  ventilation. Each opaque construction and fenestration type receives an envelope verdict. Each zone receives a
  lighting verdict and a ventilation verdict. A verdict is one of meets, does not meet or cannot tell. The agent MUST
  be able to limit a screening to one topic. Each verdict comes with:
  - the computed value
  - the requirement in both unit systems
  - the margin
  - the area concerned (exterior area for constructions, floor area for zones)
  - the cited table
  - the assumptions used
- **FR-035**: Every screening response MUST state the data source and its version. It MUST list the provisions it does
  not evaluate (mandatory provisions, exceptions, trade-off paths), and MUST call itself a screening, not a
  compliance determination.
- **FR-036**: Object roles that a screening depends on MUST be derived only from model physics and structure, or
  asserted by the agent or modeller. These roles are surface class, conditioned status, assembly class and zone
  space type. Space type is never computed: it is asserted, or reported as unknown with any name-based suggestion
  labelled unconfirmed. Space types use the data source's own vocabulary. A role
  that cannot be determined MUST be reported as unknown. Any suggestion based on names MUST be labelled unconfirmed
  and MUST NOT be used in a verdict until it is confirmed.
- **FR-037**: An asserted role MUST be recorded in the session change log and kept in the session's persisted state.
  It MUST survive object renames and server restarts within the same session. It MUST NOT be written into the model
  file or any file beside it. When the session ends, or the model is loaded in a new session, asserted roles are
  gone, and screenings report the affected objects as "cannot tell" until roles are asserted again.
- **FR-038**: Requirement data MUST come from an openly licensed, maintained third-party source. Neither idfkit nor
  idfkit-mcp may copy standards text, exceptions or footnotes, or reproduce requirement tables of their own.
- **FR-038a**: The standards capabilities MUST state, on every Python version idfkit supports, whether they are
  available. The data source currently declares support only below Python 3.14, while idfkit supports 3.10 and
  later and 3.14 is a current release. [NEEDS CLARIFICATION: Is it acceptable to release the standards layer
  unavailable on Python 3.14 and later, or must it be available on every supported Python before release (for
  example through an upstream fix by the data source, or by shipping an unmodified, licensed copy of its data
  files, which FR-038 would then need to allow)?]

Requirements in 001 that also covered standards before the deferral, and which the future spec should restate:

- FR-002 (every verdict names its object), FR-006 (standards lookup and screening work offline, without
  EnergyPlus), FR-008 (no screening is described as proof of compliance), FR-054 (asserted roles and the standards
  context are passed in by the caller), FR-055 and FR-056 (verdict nodes and edges in the combined view, present
  only with the data installed and a context supplied).
- SC-013's first-call budget: the first standards question in a server process is answered in under 0.5 s, and
  every later one in under 0.05 s.
- Evaluation fault types: roof insulation below the limit, window SHGC above the limit, and a lighting fault
  (research R-14, R-30).
- User Story 7's independent test screened the envelope with the standards extra installed.

## Success criteria

- **SC-006**: For every screening verdict in a hand-checked sample of at least 30, the requirement and its units match
  the cited table, and the computed value matches a hand calculation within 2%. The sample includes at least three
  verdicts from every supported 90.1 edition, and at least one climate zone whose limits differ by subtype
  (3A, 3B or 3C). The sample also includes at least five lighting verdicts and at least five ventilation verdicts,
  checked the same way against an asserted space type.
- **SC-007**: No screening verdict rests on a role inferred from a name. Every verdict cites its source and lists its
  assumptions.

## Key entities

- **Standards context**: The standard, edition, climate zone and building category in force for a session, each
  with its source.
- **Requirement**: One requirement value with its units, its applicability (climate zone, assembly class, building
  category) and its citation.
- **Object role**: A classification of an object (surface class, conditioned status, assembly class, space type)
  with its origin: computed, asserted or unconfirmed suggestion. Asserted roles belong to the session, not to
  the model.
- **Screening verdict**: Meets, does not meet or cannot tell, for one construction (envelope) or one zone (lighting,
  ventilation) against one requirement, with value, margin, area, citation and assumptions.

## Assumptions

- **Standards topics in this feature: envelope, lighting power and 62.1 ventilation** (confirmed in Clarifications,
  2026-11-11). Lighting uses the space-by-space method. The building area method, HVAC minimum efficiency,
  economizer and system requirements, other codes (IECC, 189.1, NECB) and
  typical-value benchmarks are later work. HVAC efficiency and system requirements wait for the topology and results
  layers they depend on. All of them reuse the
  standards context, roles and verdict shape defined here.
- **The standards source is PNNL's building-energy-standards-data.** It is BSD-2 licensed, has no dependencies,
  covers ASHRAE 90.1 2004–2025, 62.1, IECC and 189.1, and cites the source table on every row. It is added as an
  optional dependency, so the core of idfkit keeps zero third-party dependencies. Version 0.3.3 was checked.
- **Climate zone comes from the existing weather station index.** It is already curated in idfkit and currently
  dropped by idfkit-mcp.

## Research findings that drove these requirements

| Finding | Source | Requirement it drives |
|---|---|---|
| Agents recite standards from memory. Shipped guidance has a 5.7× unit error | Report 02, §1.3; checked independently | FR-033–FR-036 |
| An openly licensed, dependency-free, maintained source of requirement tables exists (PNNL, BSD-2) | Report 02, §2.2 | FR-038, Assumptions |
| idfkit's U-value calculation uses one interior film for all surfaces | Report 02, §1.1 | FR-031 |
| The standards table takes 43 ms to load once | Performance measurements | SC-013 |
