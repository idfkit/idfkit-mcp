# Feature Specification: Model Knowledge Graph for Agents

**Feature Branch**: `001-model-knowledge-graph`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "Model knowledge graph for LLM agents: extend the idfkit model graph (exposed through idfkit-mcp) with three layers — (1) a typed HVAC topology graph (nodes, ports, air/water flow, loop/side membership, static node-connection checks), (2) simulation results attached to model objects (results index keyed by object type+name and by node, linked error messages, symptom-to-cause diagnosis), and (3) links to standards knowledge (ASHRAE climate zone, construction U/SHGC, prescriptive screening against PNNL's BSD-licensed building-energy-standards-data), plus a shared fault-injection evaluation that measures whether these tools improve LLM diagnosis. Include the full research findings from three research reports and the literature scan."

## About This Specification

**What a feature spec is.** This document is the first artifact of Spec-Driven Development (spec-kit) in this
repository. It states *what* the people and agents who use idfkit-mcp need from this feature and *why*. It also
states how anyone can tell, by testing, that the need is met. It deliberately says nothing about *how* to build it:
no module layout, class names, tool names or file formats. Those decisions belong to the next steps.
`/speckit-clarify` resolves open questions, `/speckit-plan` produces the technical design, `/speckit-tasks` breaks
it into ordered work, and `/speckit-implement` builds it. Every later artifact must trace back to a requirement or
success criterion here. A design that satisfies none of them is out of scope, and a requirement no design satisfies
is unfinished work.

**What this feature is.** idfkit already keeps a *reference graph* of an EnergyPlus model: which object names which
other object. idfkit-mcp exposes it to AI agents. That graph is blind in three places where agents most often go
wrong:

1. **Physical connections.** Air and water flow through *node names*, which are not object references. The graph
   cannot say what feeds what. A node-name typo passes every check today and surfaces only as an EnergyPlus error
   after a full simulation.
2. **Simulation results.** Results are reported as free text and table rows that are not tied to model objects.
   An agent sees "300 unmet hours in zone X" and has to rebuild by hand the path to the equipment, schedules and
   constructions that might cause it.
3. **Domain expectations.** Nothing tells the agent what a value *should* be. Agents recite standards tables from
   memory, and the guidance shipped to them today contains a unit error that makes roof targets about 5.7 times too
   strict.

This feature adds those three layers to the model graph and exposes them through idfkit-mcp as targeted questions
an agent can ask. It also adds a fourth element that makes the rest accountable: **an evaluation that measures
whether these capabilities actually improve an agent's ability to find and fix faults.** No published study has
measured this (see [background/00-literature-scan.md](background/00-literature-scan.md)).

**Where the research lives.** The evidence behind every claim in this spec is in [`background/`](background/README.md):

- a literature scan
- three research reports with measurements on real EnergyPlus models
- a working prototype
- a table of findings checked independently

The design sketches in those reports are inputs to `/speckit-plan`, not decisions taken here.

**Where the work lands.** Under this repository's constitution (Principle I, *The Server Exposes, idfkit Knows*),
the domain knowledge (topology rules, result linking, standards lookups and screening) is built in **idfkit**.
idfkit-mcp exposes it. This spec is written here because this is where agents meet the feature. Its requirements
therefore bind both repositories. The work in idfkit is a dependency that must land first (see Dependencies).

## Clarifications

### Session 2026-11-11

- Q: Should the three layers and the evaluation stay in one spec, or be split into separate specs? → A: Keep one
  umbrella spec. One plan covers all layers, and stories are delivered in priority order.
- Q: When a modeller or agent asserts an object's role, where should that assertion be saved? → A: In the session
  only. It survives server restarts but not the end of the session, and nothing is written to model files.
- Q: Which ASHRAE 90.1 editions should the first envelope screening support? → A: Every 90.1 edition the standards
  data source covers (currently 2004 through 2025). *Correction during planning:* the original wording also
  required limits given as heating-degree-day formulas. In the data source those rows belong only to 90-1975, not
  to any 90.1 edition from 2004 to 2025, so that requirement was replaced by the climate-zone subtype rule
  (FR-033, SC-006). See research.md, R-08.
- Q: Which EnergyPlus versions' example models should make up the reference corpus that decides when a connection
  check can report errors? → A: The latest supported version only (26.2).
- Q: Should result linking and diagnosis also work on simulation outputs the agent did not produce, such as an
  existing run directory? → A: No. Only runs started through the server in the current session.

## User Scenarios & Testing *(mandatory)*

The primary actor throughout is an **agent**: an LLM working on an EnergyPlus model through idfkit-mcp on behalf of
a **modeller**. The secondary actor is a **maintainer** of idfkit and idfkit-mcp who decides what to build next.

### User Story 1 - Catch HVAC connection faults before simulating (Priority: P1)

An agent has edited the HVAC system of a model: added a coil, rewired a branch, renamed equipment. Before spending
minutes on a simulation, it asks whether the air and water systems are connected consistently. It gets back each
broken connection, the objects and fields involved, and what the other end expected. Then it fixes the fault in one
edit.

**Why this priority**: This is the most common class of HVAC authoring fault, and today it is invisible until
EnergyPlus fails. The research showed that a deliberate node-name typo left schema validation unchanged (10 errors
before, 10 after). Of the four capabilities this has the strongest evidence: a prototype found no false Branch
mismatches across 575 real example models and caught the injected typo.

**Independent Test**: Load an EnergyPlus example model, change one component's outlet node name to a typo, and ask
for the connection check. The fault is reported with the component, the field, the branch that expected a
different node, and the node left with nothing on one side. Running the same check on the unmodified model reports
no errors.

**Acceptance Scenarios**:

1. **Given** a model in which a component's outlet node differs from the node its branch lists for it, **When** the
   agent requests the connection check, **Then** the response reports an error naming the branch, the component,
   the field, the expected node and the actual node.
2. **Given** a model in which a setpoint manager controls a node that no flow component uses, **When** the agent
   requests the connection check, **Then** the response reports the setpoint manager and the unused node.
3. **Given** a model in which a supply air terminal's outlet is not any zone's inlet, **When** the agent requests the
   check, **Then** the response names the terminal and the unconnected node.
4. **Given** an unmodified EnergyPlus example model, **When** the agent requests the check, **Then** no error-severity
   finding is reported, and any warnings each give the rule that raised them.
5. **Given** a model that still contains unexpanded HVAC template objects, **When** the agent requests the check,
   **Then** the response says the check could not cover those systems and why, and does not report the missing
   nodes as faults.

---

### User Story 2 - Measure whether the graph helps agents (Priority: P1)

A maintainer wants evidence, not intuition, before investing in later phases. They run a repeatable evaluation.
Known faults are injected into a set of real models, and an agent is asked to find and fix each one. This is done
twice, once with the new capabilities and once without. The run produces success rate, effort and wrong-fix rate
for each fault type.

**Why this priority**: All three research reports reached the same unknown. The capabilities are plausible, and no
study shows they improve an agent's diagnosis. This evaluation decides whether User Stories 3 to 6 are worth their
cost. It also produces the paired model and output fixtures the automated tests need anyway, which do not exist
today.

**Independent Test**: Run the evaluation on the fault catalogue with the capabilities from User Story 1 enabled and
then disabled. The output is a per-fault-type table comparing the two conditions, and repeating the run with the
same agent configuration gives comparable figures.

**Acceptance Scenarios**:

1. **Given** the fault catalogue and the reference model set, **When** a maintainer runs the evaluation, **Then** each
   task records whether the fault was fixed, whether the model then passes the relevant check or simulates, how
   many tool calls and how much response text the agent consumed, and whether the agent changed anything that was
   not faulty.
2. **Given** two evaluation runs, one with and one without the new capabilities, **When** the results are compared,
   **Then** the comparison is reported per fault type and overall.
3. **Given** a fault type whose detection needs simulation output, **When** the evaluation runs without EnergyPlus
   available, **Then** those tasks are reported as skipped with the reason, not as failures.

---

### User Story 3 - Act on simulation results through the objects they concern (Priority: P2)

After a simulation, an agent reads the quality summary and sees that two zones have high unmet heating hours and
that a warning recurs hundreds of times. Each flag and warning names the model objects it concerns, in a form the
agent can pass straight to its next request. The agent can also ask for one object (a zone, a coil, a terminal
unit) and get every result that concerns it: sizing values, peak loads, unmet hours, linked warnings with
occurrence counts, and the output variables available for it.

**Why this priority**: The research showed that the join from results to objects is reliable for the outputs that
matter. Every sizing row resolved, 97–99% of timeseries keys resolved, and 89% of object rows in tables resolved.
idfkit-mcp joins results to the model in only one place today, and only by string. This turns several hops of
string searching into one request. It stands on its own without User Story 1, but node-level results need it.

**Independent Test**: Simulate a model with a known sizing shortfall in one terminal unit. Ask for the results of
that terminal unit and of its zone. The responses return the sizing values, the zone's unmet hours and any linked
warnings, each traceable to the report row or message it came from.

**Acceptance Scenarios**:

1. **Given** a completed simulation, **When** the agent reads the quality summary, **Then** every quality flag and
   every warning class lists the affected objects by type and name.
2. **Given** a completed simulation, **When** the agent asks for one object's results, **Then** the response gathers
   every linked result with its source (table and row, or message) and states how complete the linking was.
3. **Given** two objects of different types that share a name (for example a zone and its people object), **When**
   the agent asks for either one's results, **Then** only results belonging to that type are returned.
4. **Given** results from a model whose zones use multipliers, **When** zone results are returned, **Then** each
   carries its multiplier and no total silently ignores it.
5. **Given** the agent edited the model after the simulation, **When** it asks for results, **Then** the response says
   the results predate the edits.
6. **Given** an output key or message that cannot be tied to any object, **When** results are returned, **Then** it is
   listed as unresolved, not dropped or guessed.

---

### User Story 4 - Understand an HVAC system and rename its nodes safely (Priority: P2)

An agent is asked "which plant serves this zone's reheat coil?" or "add a second chiller in parallel". It asks what
a node connects or where a component sits. The answer gives the loop, the supply or demand side, the branch and
position, what is upstream and downstream, and which controls act on it. It can also ask for a compact summary of
a whole loop. When the modeller wants to rename nodes, the agent renames each one once and every use is updated.

**Why this priority**: Answering these questions today means reading every object. A full connection dump of a
large model (2,607 nodes in one example) would cost about 100,000 tokens and is useless. Bounded, targeted answers
make system-level edits possible. Node renaming has no safe path today: the shipped guidance tells agents to "update
both ends" by hand.

**Independent Test**: On a standard five-zone VAV example, ask for the loop that serves one zone's terminal, for a
summary of the chilled-water loop, and for a node to be renamed. The answers identify the air loop and the hot-water
loop for the reheat coil. The summary fits a small, fixed budget. After the rename every former use refers to the
new name and the connection check still passes.

**Acceptance Scenarios**:

1. **Given** a node name, **When** the agent asks what it connects, **Then** the response gives the components on each
   side, the loop, side and branch it belongs to, and any controls that sense or set it.
2. **Given** a component, **When** the agent asks where it sits, **Then** the response lists its connections per
   fluid stream and its membership in each loop it touches. A water coil, for example, is on an air loop and on the
   demand side of a water loop.
3. **Given** a loop, **When** the agent asks for a summary, **Then** the response describes the supply and demand
   sides in order and collapses repeated parallel components into counts.
4. **Given** a node renamed through the feature, **When** the rename completes, **Then** every field and node-list entry
   that used the old name uses the new one, and the change appears in the session's change log.

---

### User Story 5 - Screen the envelope against a chosen energy standard (Priority: P2)

A modeller asks "does this envelope meet ASHRAE 90.1-2019 in Chicago?". The agent establishes the climate zone and
where it came from, and confirms the standard edition. It then requests a screening. Each opaque construction and
window type gets a verdict (meets, does not meet, or cannot tell), with the computed value and the requirement in
both SI and inch-pound units. Each verdict cites the standard's table, lists the assumptions it rests on, and lists
what was not checked. The screening is labelled as a screening, not a compliance determination.

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

---

### User Story 6 - Go from a symptom to its likely causes (Priority: P3)

After a simulation, an agent asks "why does zone X have unmet heating hours?" or "what causes this recurring coil
warning?". It gets a short ranked list of candidate causes. Each comes with the evidence (a value from the results
or the model), the reason it is a candidate, and the next request that would confirm or rule it out. When many
objects share a warning, the answer points to what they have in common upstream: one schedule, rather than 25
coils.

**Why this priority**: This is the highest-value capability, and it depends on User Stories 1 and 3. It is also the
most heuristic, so the evaluation from User Story 2 should show the earlier layers help before it is built.

**Independent Test**: Inject an undersized reheat coil into a model, simulate, and ask for the causes of the
affected zone's unmet heating hours. The undersized coil appears among the top three candidates, with its sizing
value as evidence.

**Acceptance Scenarios**:

1. **Given** a symptom and a target, **When** the agent asks for causes, **Then** the response returns a bounded ranked
   list. Each candidate has evidence, a reason and a verification step, and none has an unexplained score.
2. **Given** a recurring warning shared by many objects, **When** the agent asks for causes, **Then** the response
   reports any upstream object they all share.
3. **Given** a candidate found only through a weak, free-text match, **When** candidates are ranked, **Then** it is
   never ranked first and is labelled as weak.

---

### Edge Cases

- **Template systems**: Models with unexpanded HVAC template objects have no nodes for those systems. Connection
  checks, summaries and result links must say what they could not cover, and must not report missing nodes as
  faults.
- **Shared names**: The same name used for different object types occurs in 44% of example models. All lookups and
  links are by type and name together.
- **Case**: EnergyPlus upper-cases names in its outputs. Matching ignores case, and responses use the model's
  spelling.
- **Node lists**: Fields that accept "node or node list" resolve to the node list first, as EnergyPlus does.
- **Boundary nodes**: Outdoor-air inlets, relief outlets, exhaust fans and air-cooled condensers legitimately have
  nothing on one side. They are not reported as faults.
- **Object types not yet covered**: An object whose connection roles are not known produces an informational
  "unclassified" finding, never an error.
- **Generated names in results**: Loads applied through zone lists, mirrored shading surfaces, template-generated
  equipment and spaces mapped to zones follow EnergyPlus naming conventions. A link made through a convention is
  labelled with that convention.
- **Aggregate rows** such as "Total" and "Total Facility" are classified as aggregates, not left unresolved.
- **Large models**: Responses for models with thousands of nodes or hundreds of warnings stay within a fixed budget
  by summarising, counting and paging.
- **Stale results**: Edits after a simulation make the results stale, and every response that uses them says so.
- **No weather location**: Without a weather location the climate zone is unknown, and the screening says so rather
  than guessing.
- **Standards gaps**: A requirement the data source does not cover is reported as not evaluated, not as a pass.
- **Version spread**: Models from every EnergyPlus version idfkit supports (currently 8.9 to 26.2) are handled.
  Only version 26.2's schema marks node fields explicitly, so earlier versions must reach the same result by
  other means.

## Requirements *(mandatory)*

### Functional Requirements

**Cross-cutting**

- **FR-001**: Every capability in this feature MUST compute its domain answers in idfkit. idfkit-mcp exposes them and
  holds no topology rules, result-linking rules or standards data of its own (Constitution, Principle I).
- **FR-002**: Every finding, flag, link and verdict MUST name the model object, node or report row it concerns, by
  type and name, in a form the agent can pass directly to existing model requests.
- **FR-003**: Every response MUST stay within a bounded size by summarising, deduplicating, counting and paging. It
  MUST report the totals that the bounded view leaves out.
- **FR-004**: Every response that depends on matching, linking or inference MUST report how complete the result is:
  coverage or unresolved counts, and what could not be evaluated.
- **FR-005**: The system MUST NOT present an inferred or pattern-matched value as a fact. Each inferred value MUST
  carry how it was obtained. Links made through EnergyPlus naming conventions MUST carry the convention used.
  Matches based only on free text MUST be labelled weak.
- **FR-006**: Capabilities that read only the model (topology, standards lookup, envelope screening) MUST work with no
  EnergyPlus installation and no network access.
- **FR-007**: The capabilities MUST support every EnergyPlus version that idfkit supports.
- **FR-008**: No response may describe a connection check or a screening as proof that a model will simulate or
  complies with a code (Constitution, Principle IV).

**Layer 1: HVAC topology**

- **FR-010**: The system MUST identify every use of a node name in the model. For each use it records the object, the
  field, the connection role (inlet, outlet, sensed, set, outdoor-air boundary, zone inlet, zone return, zone
  exhaust and similar) and the fluid stream it belongs to.
- **FR-011**: The system MUST determine each component's membership in air loops, plant loops, condenser loops and
  zone equipment, including the supply or demand side and the branch and position where they apply. Components on
  several loops (water coils, chillers, heat exchangers) report every membership.
- **FR-012**: The system MUST check connections without simulating, for at least these fault classes:
  - a branch whose listed nodes disagree with the component's own nodes
  - a branch whose consecutive components are not connected
  - a flow inlet with no matching outlet or boundary
  - a zone inlet that nothing supplies, and a zone exhaust that nothing draws from
  - a setpoint or controller acting on a node that no flow component uses
  - a node used on only one side that no boundary rule explains
- **FR-013**: A connection check MUST be reported at error severity only once it has produced no false findings on the
  reference corpus: the unmodified example models shipped with the latest supported EnergyPlus version (currently
  26.2). All other checks MUST be reported as warnings until then. When the latest supported version changes, the
  corpus moves with it and every error-severity check is re-qualified against it.
- **FR-014**: Connection findings MUST appear in the existing model integrity check, under their own category.
- **FR-015**: An agent MUST be able to ask, for a single node, what it connects and where it sits (FR-010, FR-011), and
  for a single component, its connections per stream and its loop memberships, with a bounded number of hops
  upstream and downstream.
- **FR-016**: An agent MUST be able to ask for a compact summary of one loop or all loops. It describes supply and
  demand sides in flow order and collapses repeated parallel components.
- **FR-017**: An agent MUST be able to rename a node in one request. The rename updates every field and node-list entry
  that uses it, atomically, and is recorded in the session change log.
- **FR-018**: After a simulation, an agent SHOULD be able to compare the statically derived connections with the
  branch and node report EnergyPlus writes, and see any disagreement.

**Layer 2: Results attached to the model**

- **FR-019**: Result linking and diagnosis (FR-020–FR-027) MUST apply only to simulations started through the server
  in the current session. A request for results with no such simulation MUST fail with an actionable message.
  Outputs produced elsewhere are out of scope.
- **FR-020**: After a simulation, the system MUST link to model objects, or to nodes:
  - component sizing results
  - timeseries output keys
  - object rows in tabular reports
  - error and warning messages

  Each link is keyed by object type and name.
- **FR-021**: Rows that are aggregates MUST be classified as aggregates. Items that cannot be linked MUST be listed as
  unresolved and never silently dropped.
- **FR-022**: Each error or warning message MUST carry a message kind, the objects it names, its occurrence count and,
  where EnergyPlus reports it, when it first occurred.
- **FR-023**: Every existing post-simulation quality flag and warning class MUST list its affected objects. Adding
  these fields MUST NOT remove or rename any existing field.
- **FR-024**: An agent MUST be able to request, for one object, all of its linked results with their sources, its
  linked messages deduplicated by kind with counts, and the output variables available for it.
- **FR-025**: Zone-level results MUST carry the zone multiplier. No total MUST be computed from zone rows without
  applying it.
- **FR-026**: Results MUST be marked stale when the model has changed since the simulation that produced them.
- **FR-027**: Given a symptom (such as unmet heating or cooling hours, an outlier peak load, or a message kind) and an
  optional target, an agent MUST be able to request a bounded, ranked list of candidate causes. Each candidate has
  evidence, a reason and a verification step. Candidates that rest only on free-text matches MUST NOT be ranked
  first.

**Layer 3: Standards knowledge**

- **FR-030**: An agent MUST be able to obtain the model's climate zone together with its source (weather station
  record, weather file, or user assertion). Weather station search MUST report the climate zone and allow filtering
  by it.
- **FR-031**: An agent MUST be able to obtain, for each construction used on the building's exterior, its thermal
  transmittance. Fenestration also gets solar heat gain coefficient. Surface films MUST be the ones appropriate to
  the surface's orientation (wall, roof, floor).
- **FR-032**: An agent or modeller MUST be able to set the standard, edition, climate zone and building category for
  a session. A screening MUST fail with an actionable message when any required item is missing, rather than
  assuming a default.
- **FR-033**: An agent MUST be able to look up requirement values for envelope assemblies by standard, edition,
  climate zone and assembly class. Results come back in SI and inch-pound units with the standard's table cited.
  A lookup without the filters needed to keep it bounded MUST be refused with guidance. Lookups and screenings MUST
  support every ASHRAE 90.1 edition the data source covers (currently 2004 through 2025). Where a limit is given
  for a whole climate zone and also for its moist, dry or marine subtype (for example "3" and "3A"), the subtype
  row MUST be used. A requested edition the data source does not cover MUST be refused, with the covered editions
  named.
- **FR-034**: An agent MUST be able to request an envelope screening. Each opaque construction and fenestration type
  receives one of three verdicts: meets, does not meet, or cannot tell. Each verdict comes with:
  - the computed value
  - the requirement in both unit systems
  - the margin
  - the area concerned
  - the cited table
  - the assumptions used
- **FR-035**: Every screening response MUST state the data source and its version. It MUST list the provisions it does
  not evaluate (mandatory provisions, exceptions, trade-off paths), and MUST call itself a screening, not a
  compliance determination.
- **FR-036**: Object roles that a screening depends on MUST be derived only from model physics and structure, or
  asserted by the agent or modeller. These roles are surface class, conditioned status and assembly class. A role
  that cannot be determined MUST be reported as unknown. Any suggestion based on names MUST be labelled unconfirmed
  and MUST NOT be used in a verdict until it is confirmed.
- **FR-037**: An asserted role MUST be recorded in the session change log and kept in the session's persisted state.
  It MUST survive object renames and server restarts within the same session. It MUST NOT be written into the model
  file or any file beside it. When the session ends, or the model is loaded in a new session, asserted roles are
  gone, and screenings report the affected objects as "cannot tell" until roles are asserted again.
- **FR-038**: Requirement data MUST come from an openly licensed, maintained third-party source. Neither idfkit nor
  idfkit-mcp may copy standards text, exceptions or footnotes, or reproduce requirement tables of their own.

**Evaluation**

- **FR-040**: The project MUST provide a fault catalogue of at least 10 fault types covering all three layers. Each
  fault type has a known correct fix and a way to inject it into a model automatically.
- **FR-041**: The project MUST provide a reference set of at least 20 EnergyPlus example models drawn from the
  EnergyPlus distribution, covering variable air volume, plant loops, packaged equipment, zone lists and template
  systems.
- **FR-042**: A maintainer MUST be able to run the evaluation with and without the new capabilities, using the same
  agent configuration. For each task it records:
  - fixed or not
  - verified by a check or a simulation
  - tool calls made
  - response text consumed
  - unwanted changes to correct parts of the model
- **FR-043**: Evaluation tasks that need simulation output MUST be skipped with a stated reason when EnergyPlus is
  unavailable.
- **FR-044**: The project MUST keep paired model, simulation output and error report fixtures from the reference set,
  so that result linking can be tested without running EnergyPlus.
- **FR-045**: Every new or changed capability MUST be covered by tests that exercise it through the server's protocol
  boundary, with no AI client involved (Constitution, Principle VII). Agent conversations, including the
  evaluation, are evidence of benefit, not tests of correctness.

### Key Entities

- **Node**: A named connection point through which air or water flows. It is not an object. It is used by two or
  more object fields.
- **Node use**: One field of one object naming a node, with a connection role and a fluid stream.
- **Loop membership**: A component's place in a loop: loop, loop kind (air, plant, condenser, zone equipment), side,
  branch and position.
- **Connection finding**: The result of a connection check. It has a rule, a severity, and the objects and nodes
  involved.
- **Result link**: A tie between an output item and an object or node. It records the method used (exact, typed,
  naming convention, weak) and the output item's source.
- **Result fact**: One value attached to an object, such as a design capacity, peak load or unmet hours. It records
  units, source and severity where relevant.
- **Linked message**: An error or warning with its kind, linked objects, occurrence count and first occurrence.
- **Candidate cause**: An object proposed as the cause of a symptom, with evidence, a reason and a verification step.
- **Standards context**: The standard, edition, climate zone and building category in force for a session, each
  with its source.
- **Requirement**: One requirement value with its units, its applicability (climate zone, assembly class, building
  category) and its citation.
- **Object role**: A classification of an object (surface class, conditioned status, assembly class, later space
  type) with its origin: computed, asserted or unconfirmed suggestion. Asserted roles belong to the session, not to
  the model.
- **Screening verdict**: Meets, does not meet or cannot tell, for one construction against one requirement, with
  value, margin, area, citation and assumptions.
- **Fault type and evaluation task**: A known, injectable defect with its correct fix. A task applies one fault to one
  model and records how an agent performed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On every unmodified example model shipped with the latest supported EnergyPlus version (the reference
  corpus, FR-013), connection checks report zero error-severity findings.
- **SC-002**: Connection checks detect at least 95% of injected connection faults across the connection fault types
  in the catalogue, each with the responsible object and field.
- **SC-003**: For a standard five-zone VAV model, an agent identifies the loops serving any zone, and what is upstream
  of any component, in a single request. A whole-loop summary costs no more than about 200 tokens per loop.
- **SC-004**: On the paired reference runs, at least 95% of these results are either linked to a model object or node,
  or classified as an aggregate:
  - sizing rows
  - timeseries keys
  - object rows in tabular reports

  The rest are listed as unresolved, and a hand-checked sample of 100 links contains no wrong link labelled exact.
- **SC-005**: After any simulation, every quality flag and warning class names its affected objects. An agent can get
  all results for one object in one request, compared with three to ten requests today.
- **SC-006**: For every screening verdict in a hand-checked sample of at least 30, the requirement and its units match
  the cited table, and the computed value matches a hand calculation within 2%. The sample includes at least three
  verdicts from every supported 90.1 edition, and at least one climate zone whose limits differ by subtype
  (3A, 3B or 3C).
- **SC-007**: No screening verdict rests on a role inferred from a name. Every verdict cites its source and lists its
  assumptions.
- **SC-008**: The evaluation runs repeatably on the full catalogue and reference set. Repeated runs under the same
  configuration agree on overall success rate within 5 percentage points.
- **SC-009**: The decision gate for User Story 6 and later phases passes when, with the new capabilities, agents show
  either:
  - at least 20 percentage points higher fix rate on the relevant fault types, or
  - at least 30% fewer tool calls at no lower fix rate,

  with no increase in unwanted changes to correct parts of the model.
- **SC-010**: The tools added by this feature together increase the cost of the server's tool listing by no more than
  15%. The increase is stated in the change that adds them (Constitution, Principle II).

## Assumptions

- **One umbrella feature, delivered in slices.** The three layers and the evaluation are specified together because
  they share entities, identity rules (type and name) and the evaluation. Each user story is independently
  deliverable. User Stories 1 and 2 form the first slice. User Story 6 waits for the decision gate in SC-009.
  Keeping one spec was confirmed in Clarifications (2026-11-11), so one plan covers all layers.
- **Envelope only for standards in this feature.** Lighting power, ventilation, HVAC efficiency, other codes (IECC,
  NECB) and typical-value benchmarks are later work. They reuse the standards context, roles and verdict shape
  defined here.
- **The standards source is PNNL's building-energy-standards-data.** It is BSD-2 licensed, has no dependencies,
  covers ASHRAE 90.1 2004–2025, 62.1, IECC and 189.1, and cites the source table on every row. It is added as an
  optional dependency, so the core of idfkit keeps zero third-party dependencies. Version 0.3.3 was checked.
- **Climate zone comes from the existing weather station index.** It is already curated in idfkit and currently
  dropped by idfkit-mcp.
- **The reference corpus is the example file set of the latest supported EnergyPlus version**, currently 26.2
  (confirmed in Clarifications, 2026-11-11). The research measured the 24.1 set (735 files, 575 with branches);
  the 26.2 set is expected to be of similar size. The reference model set for the evaluation (FR-041), fault
  injection and fixtures are drawn from it.
- **Accepted risk: older versions are not part of qualification.** Models from 8.9 to 26.1 get the same checks.
  Their schemas do not mark node fields, so those fields are found by other means, and false findings there are
  not measured before a check is promoted to error severity. Reports of false findings on older models are fixed
  as bugs, with a regression test built from the reported model.
- **Topology is derived on request** from the current model, not stored. The model's change tracking decides when a
  cached derivation is out of date.
- **Results linking needs EnergyPlus's SQL output.** idfkit-mcp already requests it on every simulation it runs,
  which is why linking is limited to those runs (FR-019).
- **The evaluation's agent configuration is a maintainer's choice** (model, prompts, budget). It is recorded with
  each run so results are comparable. The evaluation is a development instrument, not a shipped feature.

## Dependencies

- **idfkit (upstream, must land first)** provides:
  - node-use identification and connection roles
  - loop membership
  - connection checks and node rename
  - readers for the sizing and error tables in EnergyPlus's SQL output
  - the results-to-model linking and message catalogue
  - surface-appropriate films in thermal calculations
  - object roles and the standards lookup and screening, behind an optional dependency

  idfkit-mcp then adopts the new idfkit level through its pinned dependency and the bump procedure
  (Constitution, Principle VI).
- **A machine with EnergyPlus installed** is needed to build the paired output fixtures, to run the evaluation's
  simulation tasks, and to cross-check against EnergyPlus's branch and node report. The default test suite must not
  need it.
- **Agent reference documentation** in idfkit (the bundled `developing-with-idfkit` references) must be updated with
  each new capability, as idfkit's contribution rules require.
- **Corrections outside this feature** are listed in [background/README.md](background/README.md#corrections-that-do-not-wait-for-this-feature).
  They are idfkit's wrong node-validation guidance and idfkit-plugin's unit error, and they should not wait for it.

## Out of Scope

- Exporting models to semantic ontologies (Brick, ASHRAE 223P, BOT). 223P is still in public review, no IDF
  translator exists, and energy models lack the sensor points those ontologies centre on. The object roles defined
  here are designed so that an export can be added later.
- Performance-path compliance (ASHRAE 229 ruleset description and PNNL's ruleset checking tool). Both are
  unpublished and self-described as unstable.
- Building or rewiring HVAC systems automatically. This feature reads, checks and renames. It does not construct
  loops.
- A visual schematic of HVAC systems.
- Linking or diagnosing simulation outputs that were not produced by the server in the current session, such as a
  run directory a modeller brings from OpenStudio or a colleague (Clarifications, 2026-11-11).
- Machine-learned ranking of causes. Ranking is rule-based and explained.

## Research Summary

Full reports: [background/](background/README.md). Highlights that shaped the requirements above:

| Finding | Source | Requirement it drives |
|---|---|---|
| Node fields carry no reference declaration, so a node typo leaves validation unchanged (10 errors before and after) | Report 01, §1 | FR-010–FR-014 |
| Only EnergyPlus 26.2 marks node fields (819 tags). A field-name rule plus those tags covers over 97% of node fields in every bundled version | Report 01, §2a; checked independently | FR-007, FR-010 |
| Connection roles are not in the schema. They need a curated rule set mirroring EnergyPlus's own node-connection model | Report 01, §2b | FR-010, FR-013 |
| Prototype over 575 example models (58,027 nodes): no false Branch mismatches, injected typo caught, 1.6% of nodes one-sided, mostly legitimate boundaries | Report 01, §2c | FR-012, FR-013, SC-001, SC-002 |
| A full connection dump of a large model costs about 100k tokens. A loop summary costs about 150 | Report 01, §4 | FR-003, FR-016, SC-003 |
| Results link to objects at: sizing 100%, timeseries keys 97–99%, object rows in tables 89%, messages 76–99% | Report 03, §2.2 | FR-020, SC-004 |
| 44% of example models reuse a name across object types | Report 03, §2.3 | FR-002, FR-020 |
| 38% of example models request node outputs, which cannot be linked without nodes in the graph | Report 03, §2.3 | FR-020, ordering of stories |
| idfkit-mcp joins results to the model in one place, by string. idfkit's SQL reader ignores the sizing and error tables | Report 03, §1; checked independently | FR-023, FR-024 |
| Agents recite standards from memory. Shipped guidance has a 5.7× unit error | Report 02, §1.3; checked independently | FR-033–FR-036 |
| An openly licensed, dependency-free, maintained source of requirement tables exists (PNNL, BSD-2) | Report 02, §2.2 | FR-038, Assumptions |
| idfkit's U-value calculation uses one interior film for all surfaces | Report 02, §1.1 | FR-031 |
| Brick and 223P exports are low value now. 229 and its ruleset checking tool are unstable | Report 02, §§2.1, 3 | Out of Scope |
| No published work joins agent, MCP and a live model graph. Graph retrieval helped LLMs by 20–40% on Brick data, and pasting the whole ontology did not help | Literature scan | FR-003, FR-015, FR-016, User Story 2 |
| No study measures the benefit to an agent | All reports | User Story 2, SC-008, SC-009 |
