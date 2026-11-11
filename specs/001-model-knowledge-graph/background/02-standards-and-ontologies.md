# Linking idfkit models to ontologies and standards knowledge

Research report, 2026-11-10. Neither repository was modified. Lines marked **[speculation]** are judgement, not checked fact.

## TL;DR

- **The data problem is already solved, and the licence allows reuse.** PNNL's `building-energy-standards-data` (BESD) is on PyPI. It has a BSD-2 licence, no runtime dependencies, and its JSON tables cover ASHRAE 90.1-2004 through 2025 (including the Appendix G PRM tables), 62.1-1999 through 2022, IECC 2006 through 2024 and 189.1. It is the data source behind openstudio-standards. Version 0.3.3 (2026-10-22) even ships its own MCP server, `besd-mcp`, which runs generic SQL over the tables.
- **What nobody provides is the join.** No tool takes the model's computed facts (assembly U-factor per surface type, LPD per zone, outdoor air per zone, climate zone) and lines them up with the matching table row. idfkit already holds most of the facts. This join is where idfkit can add value.
- **The LLM gets this wrong from memory today.** The plugin's `envelope-analyst` agent states that roof U-factor targets are "0.027-0.063 W/m2·K". Those are IP values (Btu/h·ft²·°F) labelled as SI, so they are about 5.7 times too strict. The correct SI range is roughly 0.15–0.36 W/m²·K.
- **The ontology export (Brick/223P) is low value for this user base right now.** 223P is still in its second public review, with publication expected by the end of 2026. No IDF→Brick translator exists. An energy model has almost none of the points, sensors and BAS objects that Brick and 223P are about. Defer it.
- **ASHRAE 229 (RPD/RCT) is the long-term route to real compliance checking,** but the standard is unpublished and both tools describe themselves as unstable. Track it. Do not build on it yet.
- **Smallest valuable step:** expose the climate zone in MCP (already in the station index), add a `standard_context` tool and a `check_prescriptive` tool backed by an optional `idfkit[standards]` extra that depends on BESD, and give each object a lightweight, inferred "semantic role" (surface class, space type) that the LLM can confirm or override. Treat it as an advisory screen, not a compliance determination.

---

## 1. Current state

### 1.1 Domain knowledge already in idfkit (core, zero dependencies)

| Capability | Location | Notes |
|---|---|---|
| Structural reference graph | `src/idfkit/references.py:23` (`ReferenceGraph`), `get_referencing` :160, `get_references` :211 | Names only. No typing beyond the schema `object_list`. No domain roles. |
| Assembly R / U / SHGC / VT | `src/idfkit/thermal/properties.py:299` `calculate_r_value`, :348 `calculate_u_value`, :363 `calculate_shgc`, :416 `calculate_visible_transmittance`, :446 `get_thermal_properties` | Opaque films are fixed at exterior 0.030 and interior 0.120 m²K/W (:44-49), which is the vertical-wall interior film. 90.1 Appendix A uses different interior films for roofs (heat flow up) and floors (heat flow down), so roof and floor U-values come out slightly off for compliance. There is no F-factor or C-factor handling for slabs and below-grade walls. |
| Gas-gap physics | `src/idfkit/thermal/gas.py:162`, :279 | |
| ASHRAE climate zone per weather station | `src/idfkit/weather/station.py:51` (`ashrae_climate_zone`), filter at `src/idfkit/weather/index.py:1004` (`climate_zone=`, `climate_zone_determined=`) | Already curated with care: 2,162 records labelled "could not be determined" (shown as 7A/8A) are treated as unknown. HDD18 and CDD10 are also on the record, and some 90.1 tables need HDD65. |
| ASHRAE sizing design days | `src/idfkit/weather/designday.py:504` `apply_ashrae_sizing(standard="90.1")` | The only existing standards-preset API. |
| ASHRAE 90.1 App. G perimeter depth | `src/idfkit/zoning.py:68` `ASHRAE_PERIMETER_DEPTH = 4.57` | |
| Zone floor area, WWR setter | `src/idfkit/geometry.py:862`, :1091 | These are the denominators that LPD, OA and WWR checks need. |
| Schedule evaluation | `src/idfkit/schedules/` | Can compute equivalent full-load hours, which is useful for "atypical schedule" checks. |
| Validation | `src/idfkit/validation.py` | Schema-only. |

`IDFObject` and `IDFDocument` use `__slots__` (`objects.py:478`, `document.py:130`) and have no free-form metadata slot. Any semantic tags therefore need a side table keyed by (type, name). That fits well, because the `ReferenceGraph` already re-keys names on rename (`references.py:277`).

### 1.2 What idfkit-mcp exposes

- `check_model_integrity` (`src/idfkit_mcp/tools/integrity.py:215-216`) runs structural checks only: zones with no surfaces, controls, orphan schedules, boundary mismatches, fenestration hosts and HVAC zone references (:38-190).
- `get_zone_properties` (`tools/zone_properties.py:147`; model at `models.py:738`) returns area, volume, height, surface counts, construction *names*, schedules, HVAC and thermostats. It returns **no U-values, LPD, people density, OA rate or WWR**.
- `analyze_peak_loads` (`tools/peak_loads.py:352-449`) uses hard-coded heuristic thresholds such as cooling over 300 W/m² and solar share over 40%. These are already "domain knowledge in code", but they have no source citation or building-type awareness.
- `_build_qa_flags` (`tools/simulation.py:455`) checks unmet hours and errors.
- Weather: `WeatherStationModel` (`models.py:52-64`) **drops `ashrae_climate_zone`**, and `search_weather_stations` (`tools/weather.py:24-31`) cannot filter by climate zone, even though the core supports both.
- `idfkit.thermal` is not used anywhere in idfkit-mcp (grep found no hits), so the LLM cannot get a U-value from MCP without writing Python.
- idfkit-mcp already depends on `openstudio==3.11.0` (pyproject `dependencies`). The Python wheel does not include the openstudio-standards Ruby gem's data, so this provides no standards tables.

### 1.3 What the LLM has to supply from memory today

The idfkit Claude plugin agents rely on recall:

- `agents/envelope-analyst.md:21` says "Compare against ASHRAE 90.1 prescriptive requirements for the climate zone", with no tool to do it. Line 27 gives "Roofs: U-factor target (0.027-0.063 W/m2·K for insulation above deck)". **That is wrong:** the values are IP. BESD's own row for 90.1-2019 CZ5 IEAD roof is `0.032 Btu/h-ft2-F` (from Table 5.5-5), which is 0.18 W/m²K. This one line shows the risk of encoding standards in prompts.
- `agents/energy-modeler.md:13,25` says to "Reference ASHRAE standards (90.1, 62.1, 55, 189.1)", again with no tool.
- `skills/energy-audit/SKILL.md:18` says to inspect Construction/Material objects for U/SHGC by hand.
- `agents/hvac-designer.md` contains no efficiency or OA tables. Minimum equipment efficiencies, economizer requirements and 62.1 OA rates all come from memory.

The LLM therefore has to: (1) find the climate zone, (2) classify each surface into a 90.1 assembly class (mass, steel-framed, wood-framed or metal-building wall; IEAD, attic or metal roof), (3) compute U including the right films, (4) recall the right table, edition, row and units, and (5) map zones to 90.1 or 62.1 space types. Step 3 is already in idfkit but not exposed. Step 4 is where hallucination happens. Steps 2 and 5 are classification judgements where an LLM actually helps.

---

## 2. Landscape

### 2.1 Semantic ontologies

| Ontology | Status (Nov 2026) | Licence | Tooling | Fit for EnergyPlus models |
|---|---|---|---|---|
| **Brick** | 1.4.x, harmonised with RealEstateCore 4.0 ([rc announcement](https://groups.google.com/g/brickschema/c/Ree1Jxwd5-c)); nightly builds mention 223P examples ([releases](https://science.ecosyste.ms/projects/76050/releases)) | BSD ([repo](https://github.com/BrickSchema/Brick)) | `brickschema` 0.8.0 (2026-09) needs rdflib, owlrl, pyshacl, pyshifty and the Rust `reasonable`, plus Python ≥3.11 ([PyPI](https://pypi.org/project/brickschema/)) | Partial. Equipment classes (AHU, VAV, Boiler, Chiller, Zone, Space) map to EnergyPlus objects, and `feeds`/`hasPart` can be derived from node and branch topology. Most of Brick's value is in points (sensors and setpoints bound to BAS timeseries), which an EnergyPlus model mostly lacks. Output:Variable and EMS sensors could become points. **[speculation]** |
| **ASHRAE 223P** | Not yet published. 1st public review Jun–Aug 2025 ([SA Jun 2025](https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20actions/sajun_27_2025.pdf)); 2nd ISC public review 24 Apr–8 Jun 2026 ([SA Apr 2026](https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20actions/sa-apr_24_2026.pdf)); publication expected by end of 2026 ([ACEEE 2026 paper](https://www.aceee.org/sites/default/files/proceedings/ssb26/pdfs/072_0959_1434_000095.pdf)) | Draft standard. The ontology is hosted at open223.info (could not fetch from this sandbox). | RDF/SHACL/SPARQL ([DOE 223P page](https://www.energy.gov/cmei/buildings/ashrae-standard-223p)); BuildingMOTIF | Strong conceptual fit for HVAC topology, because connection points and connectables resemble EnergyPlus nodes. Unstable until published. Its focus is control and analytics, not envelope or loads. |
| **Project Haystack** | v4 with Xeto/defs (from memory, not verified here) | AFL-style, open | Mostly JVM/SkySpark ecosystem; Python support is thin | Tag-based and point-centric. Weak fit for simulation models. |
| **IFC / BOT / SAREF** | Mature (IFC 4.3 ISO) | Open | ifcopenshell (heavy) | BOT (Site/Building/Storey/Space/Zone) is trivially derivable from idfkit zones and surfaces. IFC itself goes the other way (BIM→BEM). |
| **BuildingSync** | DOE XML schema for audits (from memory) | BSD | XML | Fits "energy audit" metadata better than RDF does, but out of scope. |

Tooling around these:

- **BuildingMOTIF** (NREL) creates, validates and translates Brick, 223P and Haystack models ([DOE semantic modeling page](https://www.energy.gov/cmei/buildings/semantic-modeling-and-interoperability)). The PyPI release is 0.4.0 (2025-09), classified as "Other/Proprietary License". It pulls in Flask, SQLAlchemy<2, pygit2, pandas, matplotlib and setuptools<74. That is far too heavy for an idfkit extra.
- **ontoenv** 0.6.4 (BSD-3): rdflib plus oxrdflib, for managing ontology imports.
- **BrickLLM** (Eurac) generates Brick from text with LLMs, using a langchain stack. Prior art for "LLM authors semantic graph", but not reusable here.
- **No EnergyPlus→Brick or →223P translator was found.** Searches turned up BIM→BEM work (e.g. [arXiv 2601.16813](https://arxiv.org/html/2601.16813v1)) but nothing going from IDF to RDF. That is either an opening or a sign of low demand. **[speculation: mostly the latter. Brick users have BAS data, not IDFs. The main overlap is the "digital twin / calibration" crowd who want to bind measured points to simulated variables.]**
- rdflib itself is light (BSD-3, pure Python, deps: pyparsing, plus isodate on Python <3.11) ([PyPI](https://pypi.org/project/rdflib/)). A **Turtle/JSON-LD writer needs no rdflib at all**, because it is just string serialisation, so even core could emit it. Validation (SHACL) is where the heavy dependencies come in.

### 2.2 Standards data

| Source | What | Licence / reuse | Maturity | Fit |
|---|---|---|---|---|
| **PNNL building-energy-standards-data (BESD)** ([GitHub](https://github.com/pnnl/building-energy-standards-data), [PyPI](https://pypi.org/project/building-energy-standards-data)) | 139 JSON tables: `envelope_requirements_{90_1,90_1_prm,IECC,189_1}` (6,315 rows for 90.1 alone, with climate zone set × surface type × construction class × building category, max U / C / F, SHGC, VT, WWR limits, HDD65-based formulas); `level_3_lighting_90_1_{2004..2025}[_prm]` (LPD by space type, BA and SS methods, control requirements); `level_3_ventilation_62_1_{1999..2022}` (Rp, Ra, occupant density, air class); `hvac_minimum_requirements_*` (chillers, boilers, unitary, heat pumps, VRF, motors, water heaters, ...); `system_requirements_*` (economizer, ERV, fan power allowance, ...); and space-type mapping tables `level_1_space_types` / `level_2_*`. Every row has an `annotation` such as "From 90.1-2019 Table 5.5-5". | **BSD-2-Clause, © Battelle** (checked in the 0.3.3 wheel's `LICENSE.md`). The package has no runtime dependencies; the `mcp` extra adds fastmcp, pandas and sqlglot. Wheel is 1.3 MB; unpacked JSON is ~60 MB. | Actively maintained (0.3.3 on 2026-10-22). Feeds openstudio-standards. The README warns that "not all prescriptive requirements are included... many exceptions". | **Best fit.** Reusable as a dependency of an optional extra. Includes `besd-mcp`, a text-to-SQL style MCP with tools such as `get_candidate_tables`, `get_table_metadata`, `run_sql` and `get_unique_values`. |
| **ASHRAE 90.1 / 62.1 text** | The standards themselves | © ASHRAE. Reproduction and distribution are prohibited without permission ([e.g. addendum PDF notice](https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20addenda/90_1_2022_as_20250430.pdf)) | — | **Do not bundle text, exceptions or footnotes.** Numeric table values are facts, and the compilation has thin copyright in the US. PNNL and NREL have redistributed these numbers under BSD for about 10 years. **[Not legal advice. The safest posture is to depend on BESD (a third-party, government-lab redistribution) rather than copying values into idfkit, and to cite the table number rather than quote it.]** |
| **openstudio-standards** ([GitHub](https://github.com/NREL/openstudio-standards)) | Ruby gem with prototype and typical building logic plus data, now sourced from BESD | OpenStudio BSD-style licence with a naming clause (checked `LICENSE.md`) | DOE/PNNL prototypes are marked deprecated in favour of "typical" buildings | Ruby. Only the data is relevant, and that data is BESD. The NREL [BuildingStandardsData](https://github.com/NREL/BuildingStandardsData) copy is superseded. |
| **ASHRAE 229P RPD schema + PNNL RCT** | RPD JSON schema ([open229](https://github.com/open229/ruleset-model-description-schema)); `ruleset-checking-tool` 0.5.0 (MIT, 2026-02) implements 90.1-2019 Appendix G, with a 2022 extra ([GitHub](https://github.com/pnnl/ruleset-checking-tool)); `energyplus-ruleset-model` 0.61 (2025-02, Modified BSD) builds an RPD from epJSON plus simulation output ([PyPI](https://pypi.org/project/energyplus-ruleset-model/)) | Open | The schema "should be considered unstable", and the RCT's "final release... dependent upon acceptance and publication of 229P". RCT dependencies are heavy and pinned: numpy<2, pandas, Pint<0.24, **black<23**, regex<2023, among others. | The right long-term compliance engine, but only for Appendix G **performance-path** rule checking (baseline vs proposed). The heavy dependency pins would conflict in a user's environment, so it needs a subprocess or an isolated environment. The RPD "compliance parameters" (`--create_empty_cp`: space types, building segments, and so on) are the most useful near-term idea: **a ready-made vocabulary for semantic tags on EnergyPlus objects.** |
| **DOE prototype / reference buildings** | IDFs per building type, vintage and climate zone at energycodes.gov | US government work, effectively public domain (not re-verified here) | Mature, but deprecated in openstudio-standards in favour of "typical" | Useful as **benchmark distributions** (typical LPD, EPD, OA, infiltration per building type). Could be distilled into a small table. **[speculation]** |
| **COMNET** | Modeling-assumption manual | Copyrighted (from memory) | Stale | Skip. |
| **NECB** | Canadian code; tables live in openstudio-standards / BTAP | Code text © NRC; BTAP data is openly licensed (from memory, unverified) | — | Possible later via BTAP JSON. Out of scope for v1. |
| **CBECS / ComStock benchmarks** | EUI distributions | Public | — | "Is this EUI atypical?" checks. Later. |

---

## 3. Options, ranked

Scoring is value to an LLM agent, against effort, dependency weight and risk.

### Rank 1: Standards lookup and prescriptive screening via BESD (optional extra)

**What it does.** Add `idfkit.standards` to core, holding only pure logic: unit conversion, surface classification and the join engine. Data access lives behind `idfkit[standards]`, which depends on `building-energy-standards-data` (itself zero-dependency). Functions:

- `get_climate_zone(doc | station)` reads it from the station index. The EPW header also lets the zone be inferred from HDD/CDD.
- `lookup_envelope_requirements(standard="90.1-2019", climate_zone="5A", building_category="Nonresidential")` returns SI-converted maximum U, F, C and SHGC per (surface type, construction class), with the `annotation` citation.
- `lookup_lpd(standard, space_type)` and `lookup_ventilation(standard_62_1, space_type)`.
- `check_envelope(doc, standard, cz)` computes, per construction actually used by exterior surfaces: area-weighted U (with orientation-correct films, which means extending `thermal/properties.py` to take a surface type), the inferred construction class, the requirement, the margin, and a pass/fail/unknown verdict. Fenestration gets U/SHGC against WWR-banded limits, plus whole-building WWR against the cap.
- `check_lighting(doc, standard, method="space")` computes LPD per zone (Lights in W/m², W/person × occupancy, or Level; ZoneList and SpaceList aware) against the allowance for the assigned space type.
- `check_ventilation(doc, standard)` compares DesignSpecification:OutdoorAir Rp/Ra against 62.1 Table 6-1. It needs a space type and occupancy density.

**Value to the LLM: very high.** It removes the most hallucination-prone step (table recall and units) and turns a multi-step manual chain into one call with cited answers. It directly serves `envelope-analyst`, `energy-audit` and `energy-modeler`.

**Effort: moderate.** Roughly 2–3 weeks for envelope, LPD and OA. Climate-zone plumbing is about a day. The hard parts:

- Surface → 90.1 class inference. Mass, steel or wood framing is not in the IDF and has to be guessed from layers (concrete or masonry with high heat capacity means mass; otherwise unknown, with the LLM asked or a parameter supplied).
- Space type mapping. Zone names, People/Lights object names and DOE prototype naming conventions such as `Office WholeBuilding - Md Office` give hints. Otherwise the answer is "unassigned".
- Climate zone set expansion: BESD rows use `ClimateZone 5`, `ClimateZone 4-8` and similar.
- HDD65-formula rows for 90.1-2022+ and IECC.

**Dependencies.** Core stays at zero. The extra adds one package with no transitive dependencies. Data is about 60 MB unpacked, so lazy-load it per table and never at import time.

**Risks.**

- **False authority.** A "PASS" can be read as code compliance. Mitigate this in naming ("prescriptive screening"), by always returning `basis` (table annotation), `assumptions` (inferred class, films) and `not_checked` (exceptions, mandatory provisions, tradeoffs), and with a disclaimer.
- Coverage gaps that BESD documents itself.
- BESD's schema is not a stable API. Pin a minor range and add a CI test against a fixture.
- Licensing: low risk when depending on BESD rather than vendoring.

### Rank 2: Lightweight internal semantic roles (core, zero dependencies)

**What it does.** Add a `SemanticIndex` derived on demand from the document: no persistence, no RDF. For each object it gives a small, closed vocabulary role:

- surfaces: `exterior_wall`, `roof`, `slab_on_grade`, `interior_floor`, `exterior_window`, `skylight`, ...
- constructions: `assembly_class` ∈ {mass, steel_framed, wood_framed, metal_building, IEAD, attic, unknown}
- zones: `conditioning` ∈ {conditioned, semiheated, unconditioned, plenum}, plus `space_type` with confidence and source
- HVAC objects: `system_type` (90.1 G3.1.1 system numbers 1–10 where recognisable, otherwise "VAV w/ reheat", "PTAC", ...), `serves` (zone list derived from node and connection topology), `heating_source` and `cooling_source`

Roles are **inferred**, carry a `confidence` and `evidence` such as "inferred from name 'Office_Open'", and can be **overridden** by user or LLM assertions. Overrides are stored in a side dict keyed by (type, name) and rename-safe through ReferenceGraph rename hooks. Assertions could optionally persist into the IDF as structured `!-` comments or a sidecar `.idfkit.json`. **[design speculation]** The vocabulary should reuse the existing terms: BESD space-type names (`office_enclosed_lighting` etc.), 229 RPD enumerations, and Brick class local names (`AHU`, `VAV`, `Zone`). That way it becomes the bridge to Ranks 1 and 3 later.

**Value to the LLM: high.** It answers "what is this?" in one cheap call, and it is the prerequisite for Rank 1: you cannot check LPD without a space type. It also gives the LLM a clean slot to contribute judgement ("set space type of zone X to `office_open_plan`") instead of keeping that judgement in conversation memory.

**Effort: moderate.** Surface roles are trivial (surface type plus boundary condition plus tilt; existing integrity code already walks these). Conditioning status comes from thermostat and HVAC presence. HVAC topology is the expensive part, since nodes, branches and AirLoop/ZoneHVAC connections must be walked. A partial first version (surfaces, zones, assembly class) is about 1 week.

**Dependencies:** none. **Risks:** wrong inference silently propagates. Always surface confidence and evidence, and default to `unknown` rather than guessing.

### Rank 3: Semantic export (IDF → Brick, later 223P) as an optional extra

**What it does.** `idfkit.semantic.to_brick(doc) -> str` (Turtle) and `to_bot(doc)`. Emit Turtle/JSON-LD by hand-serialising from the Rank 2 roles: no rdflib needed for writing. `idfkit[semantic]` would add `brickschema` for SHACL validation and SPARQL querying.

**Value to the LLM: low to moderate.** LLMs are mediocre at SPARQL over large graphs, and the Rank 2 JSON roles answer the same questions with fewer tokens. The real value is **interop**: handing a Brick model to a digital-twin, FDD or calibration platform, or binding measured BAS points to simulated Output:Variables for calibration. **[speculation: a niche today, which could grow once 223P is published.]**

**Effort:** 1–2 weeks for Brick equipment and spatial classes on top of Rank 2. 223P is larger (connection points per node), and it should wait for publication.

**Dependencies:** none for writing. The validation extra needs Python ≥3.11 for brickschema, while idfkit supports 3.10. BuildingMOTIF is too heavy and its licence is unclear.

**Risks:** ontology churn (223P), and low adoption.

### Rank 4: ASHRAE 229 RPD / RCT integration

**What it does.** Produce an RPD with the `createRulesetProjectDescription` CLI (needs epJSON plus simulation output) and run the RCT out of process. Expose the result as "Appendix G rule evaluation". The compliance-parameter JSON maps onto Rank 2's roles.

**Value:** high for the narrow group of professionals doing PRM. For general LLM-assisted modelling, low.

**Effort:** moderate glue, high maintenance while the schema churns. **Dependencies:** the RCT's pinned stack (numpy<2, black<23, ...) **must not** be an install extra. Run it in an isolated environment (`uv tool run` / `uvx`) through a subprocess, as idfkit already does for EnergyPlus.

**Risks:** the standard is unpublished and both tools are self-described as "highly unstable" ([PNNL BEM-for-PRM](https://pnnl.github.io/BEM-for-PRM/get_start/usecase_workflows/compliance_check)). **Revisit after 229 is published.**

### Rank 5: Typical-value benchmarks (DOE prototypes / ComStock)

A small, curated, public-domain table of typical inputs per building type and vintage (LPD, EPD, people/m², OA, infiltration, EUI) supports "this is atypical" flags. It would also put citations and building-type awareness behind the hard-coded thresholds in `peak_loads.py:352-449`. It is cheap once Rank 2's space and building types exist. The value is medium. Distilling the values is real work and needs provenance. **[speculation]**

**Not recommended:** bundling hand-copied ASHRAE tables into idfkit core (licence risk, and a maintenance burden duplicating PNNL), or making BuildingMOTIF or the RCT a dependency.

---

## 4. Proposed MCP surface (idfkit-mcp)

Principles:

- Return **verdict tables, not raw rows**.
- Always include `basis` (standard, edition, table citation from BESD `annotation`), `assumptions`, `confidence` and `not_checked`.
- Use SI by default and show the IP original next to it, since that is exactly what the LLM gets wrong.
- Default to the worst N offenders plus summary counts, and paginate the rest.

### Tools

1. **`get_standard_context()`** returns the climate zone, its source (`weather_station` / `epw` / `user`), HDD/CDD, building category and the selected standard edition. Missing values come back as explicit nulls with a one-line hint. Cheap; this is the LLM's first call.
2. **`set_standard_context(standard="90.1-2019", climate_zone=None, building_category=None)`** stores session state, as `migrate_model` does.
3. **`get_semantic_roles(object_type=None, role=None, unknown_only=False, limit=50)`** returns a compact list: `{"type":"Zone","name":"Core_ZN","roles":{"conditioning":"conditioned","space_type":{"value":"office_open_plan","confidence":0.6,"evidence":"name"}}}`.
4. **`assign_semantic_role(object_type, name, role, value)`** lets the LLM or user assert a role. Logged in `get_change_log`.
5. **`lookup_standard(topic, ...)`** where `topic` ∈ {`envelope`, `lighting`, `ventilation`, `hvac_efficiency`, `economizer`}. Filters are required, so it never returns 6,000 rows. Example: `lookup_standard("envelope", climate_zone="5A", surface="roof")` returns 4–6 rows in SI and IP with citations. This is the safe, curated version of besd-mcp's `run_sql`, without asking the LLM to write SQL.
6. **`check_prescriptive(scope=["envelope","lighting","ventilation"], limit=20)`** returns:
   ```json
   {"basis":"ASHRAE 90.1-2019 prescriptive (via PNNL BESD 0.3.3)","climate_zone":"5A",
    "summary":{"envelope":{"pass":7,"fail":2,"unknown":1},"lighting":{"pass":4,"fail":1,"unassigned":3}},
    "failures":[{"object":"Construction/Roof_IEAD","check":"roof U-factor","value_si":0.29,"limit_si":0.18,
                 "limit_ip":0.032,"area_m2":1200,"basis":"Table 5.5-5","assumptions":["assembly_class=IEAD (inferred)"]}],
    "unknown":[{"object":"Construction/ExtWall","reason":"assembly class ambiguous (mass vs steel-framed)",
                "fix":"assign_semantic_role(...,'assembly_class','mass')"}],
    "not_checked":["mandatory provisions §5.4","exceptions","envelope tradeoff (§5.6)"]}
   ```
7. **Extend existing tools rather than duplicate them.** Add `u_value_w_m2k` and `shgc` to construction summaries in `get_zone_properties`. Add `ashrae_climate_zone` to `WeatherStationModel` and a `climate_zone` filter to `search_weather_stations`. These are about one day of work and immediately useful.

### Resources

- `idfkit://standards/context`
- `idfkit://standards/check` (last check result)
- `idfkit://model/semantic/{type}/{name}`
- Later: `idfkit://model/semantic.ttl` (Brick export, Rank 3)

### LLM use cases and example queries

- "Does this model's envelope meet 90.1-2019 in Chicago?" → `get_standard_context` → (`set_standard_context`) → `check_prescriptive(["envelope"])` → explain the two failures with cited tables.
- "Upgrade the roof to just meet code." → `lookup_standard("envelope", surface="roof")` → compute the required insulation R from the gap. That is `thermal.calculate_r_value` arithmetic, which a future helper could do. → `update_object`.
- "Set up internal loads for a 5-storey medium office per 90.1-2019." → `lookup_standard("lighting", space_type=...)` and `("ventilation", ...)` → `batch_add_objects` with cited values.
- "Why is lighting energy so high?" → `check_prescriptive(["lighting"])` shows a zone at 16 W/m² against an allowance of 6.9.
- "Which zones haven't been classified?" → `get_semantic_roles(unknown_only=True)` → the LLM proposes space types from names and geometry, and the user confirms with `assign_semantic_role`.
- Later: "Export a Brick model of the HVAC so our FDD platform can ingest it."

### Coexisting with `besd-mcp`

Users can already add PNNL's `besd-mcp` next to idfkit-mcp for open-ended table questions. idfkit-mcp should not try to replicate generic SQL. Its value is the **model ↔ table join**, the units, and classification. The plugin docs should mention both servers. **[speculation: an LLM given only besd-mcp would still have to do the unit conversion, class inference and U-calculation itself.]**

---

## 5. Recommendation and phased plan

**Yes, it is worth doing,** but framed as *"standards-aware screening with cited sources"*, not as a knowledge graph or ontology project. The ontology half (Brick/223P) is premature for this audience. Build the internal role layer so that an export becomes cheap later.

**Phase 0: plumbing and corrections, no new dependencies, about 2–3 days.**

- Fix the IP/SI error in `envelope-analyst.md:27` in idfkit-plugin, and replace the hard-coded numbers with "use `lookup_standard`".
- Expose `ashrae_climate_zone` in MCP `WeatherStationModel` and add a `climate_zone` filter to `search_weather_stations`.
- Add U-value and SHGC per construction to `get_zone_properties`, or add a small `get_construction_properties` tool, using the existing `idfkit.thermal`.
- Add `get_standard_context` / `set_standard_context`, getting the climate zone from the loaded weather file's station match.

**Phase 1: the smallest valuable step, about 2 weeks.**

- Make surface-type-aware films in `thermal/properties.py` (roof, wall, floor interior films per ASHRAE Handbook / 90.1 App. A), keeping the default backwards-compatible.
- Add semantic roles v0 (surfaces, conditioning status, assembly class with confidence) to core.
- Add `idfkit[standards]` → `building-energy-standards-data>=0.3,<0.4`.
- Add `idfkit.standards.lookup_envelope_requirements` and `check_envelope`, for 90.1-2016/2019/2022 opaque plus fenestration, with SI/IP and citations.
- Add MCP `lookup_standard(topic="envelope")` and `check_prescriptive(["envelope"])`.
- Update the agent references (template and snippet), CHANGELOG, and the env-var docs if any are added.

**Phase 2, about 2–3 weeks.** Zone space-type roles (name heuristics plus `assign_semantic_role`), LPD and 62.1 OA checks, `hvac_efficiency` lookup for objects with a rated COP/efficiency (Coil:Cooling:DX:SingleSpeed, Chiller:Electric:EIR, Boiler:HotWater) against BESD `hvac_minimum_requirements_*`, and IECC as a second `standard` value.

**Phase 3, opportunistic.** Benchmark-backed "atypical value" flags that replace the bare thresholds in `peak_loads.py`. HVAC topology roles (`serves`, system type). A Brick Turtle export from roles once a user asks. Re-evaluate 223P and 229/RCT after both are published (expected late 2026 to 2027), with the RCT run out of process.

**Guardrails throughout.** Never vendor ASHRAE values or text; depend on BESD. Label output "prescriptive screening, not a compliance determination". Always return basis, assumptions and not_checked. Keep idfkit core free of dependencies, with all data behind the extra and lazy-loaded.

---

## Sources

- PNNL BESD: https://github.com/pnnl/building-energy-standards-data · https://pypi.org/project/building-energy-standards-data (0.3.3 wheel inspected: BSD-2 `LICENSE.md`, 139 JSON tables, `besd-mcp` entry point)
- openstudio-standards licence: https://github.com/NREL/openstudio-standards (raw `LICENSE.md` read) · NREL BuildingStandardsData: https://github.com/NREL/BuildingStandardsData
- ASHRAE 223P: https://www.energy.gov/cmei/buildings/ashrae-standard-223p · https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20actions/sajun_27_2025.pdf · https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20actions/sa-apr_24_2026.pdf · https://www.aceee.org/sites/default/files/proceedings/ssb26/pdfs/072_0959_1434_000095.pdf
- Brick: https://github.com/BrickSchema/Brick · https://groups.google.com/g/brickschema/c/Ree1Jxwd5-c · py-brickschema https://github.com/BrickSchema/py-brickschema · PyPI metadata for brickschema 0.8.0, buildingmotif 0.4.0, ontoenv 0.6.4, rdflib 7.6.0
- DOE semantic modeling / BuildingMOTIF: https://www.energy.gov/cmei/buildings/semantic-modeling-and-interoperability
- ASHRAE 229P: https://github.com/open229/ruleset-model-description-schema · https://github.com/pnnl/ruleset-checking-tool · https://pypi.org/project/ruleset-checking-tool/ · https://pypi.org/project/energyplus-ruleset-model/ · https://pnnl.github.io/BEM-for-PRM/get_start/usecase_workflows/compliance_check · https://www.energy.gov/cmei/buildings/ashrae-standard-229p-development
- ASHRAE copyright notice example: https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20addenda/90_1_2022_as_20250430.pdf
- BIM→BEM ontology pipeline (no IDF→Brick tool found): https://arxiv.org/html/2601.16813v1
- Could not reach from this sandbox (network allowlist): nist.gov, open223.info. The 223P status relies on the ASHRAE and ACEEE sources above.
