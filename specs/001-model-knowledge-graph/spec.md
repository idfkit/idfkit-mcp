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
A third gap, **domain expectations** (nothing tells the agent what a value *should* be under an energy standard),
was part of this feature until 2026-11-11 and is now deferred to a future spec. Its requirements are kept in
[deferred-standards.md](deferred-standards.md).

This feature adds the first two layers to the model graph and exposes them through idfkit-mcp as targeted questions
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
the domain knowledge (topology rules, result linking and diagnosis) is built in **idfkit**.
idfkit-mcp exposes it. This spec is written here because this is where agents meet the feature. Its requirements
therefore bind both repositories. The work in idfkit is a dependency that must land first (see Dependencies).

## Clarifications

### Session 2026-11-11

- Q: Should the three layers and the evaluation stay in one spec, or be split into separate specs? → A: Keep one
  umbrella spec. One plan covers all layers, and stories are delivered in priority order.
- Q: Is the scope too large, and should the standards layer stay in this feature? → A: Defer it. The standards
  layer (User Story 5, FR-030 to FR-038a, SC-006, SC-007) moves to a future spec, and this feature covers the
  topology and results layers, the combined graph view and the evaluation. The deferred text is kept verbatim in
  [deferred-standards.md](deferred-standards.md), with the standards clarifications from this session. This also
  removes the open question about the standards data on Python 3.14 and later.
- Q: Which EnergyPlus versions' example models should make up the reference corpus that decides when a connection
  check can report errors? → A: The latest supported version only (26.2).
- Q: Should result linking and diagnosis also work on simulation outputs the agent did not produce, such as an
  existing run directory? → A: No. Only runs started through the server in the current session.
- Q: Should developers who use idfkit directly in Python be a first-class audience of this feature, with their own
  user story and requirements? → A: Yes. The graph is a documented, tested, stable public API of idfkit in its own
  right. The MCP server is one consumer of it.
- Q: Should developers reach the three layers through one combined graph object, or through three separate APIs?
  → A: Three layered APIs, plus a thin combined graph view on top with one vocabulary of node and edge kinds for
  walking across layers.
- Q: Should developers be able to export the graph to standard formats for use in other tools? → A: Yes, one format
  in this feature: node-link JSON, written with the standard library and loadable directly by networkx and common
  JavaScript graph tools.
- Q: Should the feature cover every node-bearing object type from the start, with connection rules generated from
  EnergyPlus's own output plus a few hand-written ones, so that no extension API for developers is needed? → A: Yes.
  All node-bearing types in the latest supported schema are covered at first release. There is no developer
  extension API. *Refined the same day:* field naming is not trusted as a source of roles. EnergyPlus's own
  connection report is the only source of truth: 247 of the 257 types in 26.2 come from the example models, and
  the 10 others from minimal test models run through EnergyPlus. Naming is only a cross-check, and any rule
  EnergyPlus cannot verify is labelled and capped at warning severity (FR-010a).
- Q: Should agents also get MCP tools to walk the combined graph and export it, or should the combined view and
  export be available only to Python developers? → A: One bounded MCP tool returns the cross-layer neighbourhood of
  an object. Export stays Python-only.

### Review revisions, 2026-11-11

A review of the spec against the research and the knowledge-graph literature changed the following. None of
them reverses a clarification above.

- **The evaluation can now answer its question.** Each task runs several times and the comparison is paired, with
  confidence intervals (FR-042a, SC-008, SC-009). Faults the checks were not designed against are held out
  (FR-040a). Prompts do not reveal that a fault exists, and fault-free control tasks are included (FR-042b). The
  baseline differs from the treatment only by this feature (FR-042c). Authoring tasks and open questions are
  measured as well as fault fixing (FR-040b).
- **The evaluation's role is stated as the plan applies it.** It hard-gates User Story 6 only. Every later slice
  reports its own effect (User Story 2, FR-046).
- **The tool surface is a requirement, not only a budget.** No two new tools may answer the same question, and the
  listing cost counts input and output schemas against a stated base (FR-059, SC-010). The evaluation checks that
  agents pick the right tool (FR-042).
- **Older EnergyPlus versions are measured, not assumed.** False findings are measured on earlier example sets,
  and a check is capped at warning for any version where it is not clean (FR-013a, SC-001a).
- **Diagnosis must not anchor the agent.** It says when no candidate has strong evidence and what the catalogue
  does not cover. The evaluation counts fixes applied to a wrong top-ranked candidate (FR-027, SC-009a).
- **Blind spots are declared.** EnergyPlus Energy Management System (EMS) programs and other references held in
  free text are listed as not covered (edge cases, FR-004a).
- **Components carry a category** (heating coil, fan, pump and so on), so agents can ask questions across object
  types (FR-016a).
- **The standards layer was deferred** after these revisions, which also closes the open question on standards
  availability on Python 3.14 and later (see Clarifications).

## User Scenarios & Testing *(mandatory)*

There are three actors:

- **Agent.** An LLM working on an EnergyPlus model through idfkit-mcp on behalf of a **modeller**. It is the
  primary actor of User Stories 1 and 3 to 6.
- **Developer.** Someone who uses idfkit directly in Python to build their own application on the graph: a QA
  script, a dashboard, a design tool, another server. The developer is a first-class audience (User Story 7), and
  idfkit-mcp is one consumer of the same public API.
- **Maintainer.** Someone who maintains idfkit and idfkit-mcp and decides what to build next (User Story 2).

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
Known faults are injected into a set of real models. An agent is given the task a modeller would give it, such as
"this model fails to simulate" or "zone 3 is too cold", without being told where the fault is. Some tasks contain
no fault at all, and some ask the agent to build or change an HVAC system. Each task is run several times with the
new capabilities and several times without, and the run produces success rate, effort and wrong-fix rate, with
their uncertainty.

**Why this priority**: All three research reports reached the same unknown. The capabilities are plausible, and no
study shows they improve an agent's diagnosis. This evaluation hard-gates User Story 6, the most heuristic layer.
User Stories 3 to 5 are built on their own evidence, and each one's slice re-runs the evaluation and reports its
effect, so a layer that does not help is seen before the next is built. The evaluation also produces the paired
model and output fixtures the automated tests need anyway, which do not exist today.

The evaluation must measure the agent, not the checks. If every fault were one a new check was written to catch,
the treatment would win simply by calling that check. So part of the catalogue is held out: faults defined
independently of the checks, preferably taken from failures seen in real agent sessions.

**Independent Test**: Run the evaluation on the fault catalogue with the capabilities from User Story 1 and then
without them. The output is a paired comparison per fault type and overall, with confidence intervals, held-out
faults reported separately. Repeating the run with the same agent configuration gives figures within the stated
spread.

**Acceptance Scenarios**:

1. **Given** the fault catalogue and the reference model set, **When** a maintainer runs the evaluation, **Then** each
   task records whether the fault was fixed, whether the model then passes the relevant check or simulates, how
   many tool calls and how much response text the agent consumed, and whether the agent changed anything that was
   not faulty.
2. **Given** two evaluation runs, one with and one without the new capabilities, **When** the results are compared,
   **Then** the comparison is reported per fault type and overall.
3. **Given** a fault type whose detection needs simulation output, **When** the evaluation runs without EnergyPlus
   available, **Then** those tasks are reported as skipped with the reason, not as failures.
4. **Given** a fault-free control task, **When** the agent reports a fault or changes the model, **Then** that is
   recorded as a false fix, in both conditions.
5. **Given** a task prompt, **When** it is shown to the agent, **Then** it describes a symptom or a goal and never
   names the injected object, field or fault type.

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

### User Story 5 - Screen the model against a chosen energy standard (deferred)

Deferred to a future spec on 2026-11-11 (Clarifications). Its full text is kept in
[deferred-standards.md](deferred-standards.md). The number is kept so that references to User Stories 6 and 7 stay
valid.

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

### User Story 7 - Build other applications on the model graph (Priority: P2)

A developer writing their own tool in Python, for example a pre-submission QA script for their firm's models, loads
a model with idfkit and uses the same graph the agent uses. They walk air and water connections, list connection
findings, and read the results attached to an object after a simulation.
The API is documented with runnable examples, fully typed, and stable across minor releases. Nothing in it assumes
an MCP server or an AI agent.

**Why this priority**: idfkit is a library first. Every capability in this feature is built in idfkit (FR-001), so a
well-shaped public API costs little extra and lets other applications reuse the work. Designing it only around one
consumer would produce an API that has to be broken later. It is P2 because User Stories 1 and 2 deliver the
first, measurable value; this story makes sure each later layer lands in a form developers can use.

**Independent Test**: In a plain Python script with no MCP server, load a reference model, list the connection
findings, trace one node, and walk the neighbourhood of one component across layers. Do it using only the public
API and the documented examples. The script passes strict type checking, and repeating it against the next minor
release needs no change.

**Acceptance Scenarios**:

1. **Given** a loaded model, **When** a developer asks idfkit for its connection view, **Then** they can trace any
   node or component and list findings using public, typed functions, with no MCP server involved.
2. **Given** a completed simulation run through idfkit, **When** a developer asks for the results of one object,
   **Then** they get the same linked facts and messages that the agent receives through the server.
3. **Given** the documentation for each layer, **When** a developer runs its examples, **Then** each example runs
   unchanged and passes the project's strict type checking.
4. **Given** a minor release after this feature ships, **When** a developer upgrades, **Then** code written against the
   documented API keeps working, and any deprecation is announced at least one minor release before removal.

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
- **Object types without connection rules**: Every node-bearing type in the latest supported schema has rules
  (FR-010a). A type can still lack them in a model from a newer EnergyPlus release than idfkit knows, or in an older
  version with a type since removed. Such an object produces an informational "unclassified" finding, never an
  error.
- **Generated names in results**: Loads applied through zone lists, mirrored shading surfaces, template-generated
  equipment and spaces mapped to zones follow EnergyPlus naming conventions. A link made through a convention is
  labelled with that convention.
- **Aggregate rows** such as "Total" and "Total Facility" are classified as aggregates, not left unresolved.
- **Large models**: Responses for models with thousands of nodes or hundreds of warnings stay within a fixed budget
  by summarising, counting and paging.
- **Stale results**: Edits after a simulation make the results stale, and every response that uses them says so.
- **Version spread**: Models from every EnergyPlus version idfkit supports (currently 8.9 to 26.2) are handled.
  Only version 26.2's schema marks node fields explicitly, so earlier versions must reach the same result by
  other means. Most models agents receive are older than the latest release, so false findings on older versions
  are measured, not assumed away (FR-013a).
- **References held in free text**: EMS sensors, actuators and programs, and some other objects, name model
  objects in text that is not a schema reference. EMS sensors and actuators whose key fields name an object are
  linked with a convention label. Program text is not parsed. A model that uses EMS is reported as partially
  covered, so an agent knows the graph cannot see what EMS controls.
- **Causes outside the catalogue**: A symptom can have a cause no diagnosis rule knows. Diagnosis then says that
  no candidate has strong evidence, instead of promoting the best weak one.

## Requirements *(mandatory)*

### Functional Requirements

**Cross-cutting**

- **FR-001**: Every capability in this feature MUST compute its domain answers in idfkit. idfkit-mcp exposes them and
  holds no topology rules or result-linking rules of its own (Constitution, Principle I).
- **FR-002**: Every finding, flag and link MUST name the model object, node or report row it concerns, by
  type and name, in a form the agent can pass directly to existing model requests.
- **FR-003**: Every response MUST stay within a bounded size by summarising, deduplicating, counting and paging. It
  MUST report the totals that the bounded view leaves out.
- **FR-004**: Every response that depends on matching, linking or inference MUST report how complete the result is:
  coverage or unresolved counts, and what could not be evaluated.
- **FR-004a**: Every response that answers from the graph MUST state the parts of the model the graph does not
  cover: unexpanded templates, EMS program text, object types without rules, and results not linked. An agent
  must be able to tell "nothing found" from "not looked at".
- **FR-005**: The system MUST NOT present an inferred or pattern-matched value as a fact. Each inferred value MUST
  carry how it was obtained. Links made through EnergyPlus naming conventions MUST carry the convention used.
  Matches based only on free text MUST be labelled weak.
- **FR-006**: Capabilities that read only the model (topology and connection checks) MUST work with no
  EnergyPlus installation and no network access.
- **FR-007**: The capabilities MUST support every EnergyPlus version that idfkit supports.
- **FR-008**: No response may describe a connection check, a result link or a diagnosis as proof that a model will
  simulate or is correct (Constitution, Principle IV).
- **FR-009**: Performance is a requirement, not a goal. Every capability in this feature MUST meet the time and size
  budgets in SC-011 to SC-013 on the largest reference model. Each budget MUST be checked by an automated benchmark
  that fails the build on a regression. Analysis MUST cost a small fraction of loading the model. It MUST NOT
  require reloading the model or re-reading simulation output on every question.

**Layer 1: HVAC topology**

- **FR-010**: The system MUST identify every use of a node name in the model. For each use it records the object, the
  field, the connection role (inlet, outlet, sensed, set, outdoor-air boundary, zone inlet, zone return, zone
  exhaust and similar) and the fluid stream it belongs to.
- **FR-010a**: Connection roles MUST cover every node-bearing object type in the latest supported EnergyPlus schema
  at first release, with no extension API for developers.
  - **The only source of truth for a role is the set of connections EnergyPlus itself reports when it runs a
    model.** That covers connection type, fluid stream and whether the object is a parent of other components.
    Field naming MUST NOT decide any role on its own. Naming does not reveal parent objects, outdoor boundaries,
    fluid streams or value-dependent roles, and the research found a field named as an outdoor inlet that is fed by
    another component.
  - Field naming MUST be used only as a cross-check. Any disagreement between naming and EnergyPlus's report stops
    rule generation until a person has reviewed it.
  - Types that appear in no EnergyPlus example model (10 in 26.2) MUST each get a minimal test model. The test model
    is run through EnergyPlus in the same generation step, so that its roles are verified like every other type.
  - A type whose test model cannot be made to run gets a hand-written rule labelled "not verified by EnergyPlus".
    Its findings MUST never be reported above warning severity.
  - Every rule MUST record its provenance: "EnergyPlus-verified from example models", "EnergyPlus-verified from a
    test model", or "hand-written, not verified". Every connection finding and connection use MUST carry the
    provenance of the rule that produced it.
  - Where examples disagree because a role depends on a field's value, the disagreement MUST become an explicit,
    reviewed rule.
  - An automated test MUST fail if any node-bearing type in the latest schema lacks rules.
  - The rules MUST be regenerated when a new EnergyPlus version is adopted.
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
- **FR-013a**: False findings MUST also be measured on the unmodified example models of at least two earlier
  EnergyPlus versions, one of them from the 9.x series. This does not change which checks qualify for error
  severity (FR-013). A check that produces a false error on an earlier version's corpus MUST be reported at warning
  severity for models of that version, until the cause is fixed and the measurement is clean. The measured rate per
  version and check MUST be published with the release.
- **FR-014**: Connection findings MUST appear in the existing model integrity check, under their own category.
- **FR-015**: An agent MUST be able to ask, for a single node, what it connects and where it sits (FR-010, FR-011), and
  for a single component, its connections per stream and its loop memberships, with a bounded number of hops
  upstream and downstream.
- **FR-016**: An agent MUST be able to ask for a compact summary of one loop or all loops. It describes supply and
  demand sides in flow order and collapses repeated parallel components.
- **FR-016a**: Every component SHOULD carry a category drawn from a small, documented vocabulary (for example
  heating coil, cooling coil, fan, pump, terminal unit, chiller, boiler, heat rejection, humidifier). The category
  is derived from the object type alone, never from names, and any object type without one is reported as
  uncategorised. Topology questions and neighbourhood requests SHOULD accept a category as a filter, so that an
  agent can ask, for example, for every heating coil upstream of a zone in one request.
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
  first. When no candidate has evidence stronger than a weak match, the response MUST say so first, before the
  list. Every response MUST name the cause families the diagnosis rules cover for that symptom, so that a cause
  outside them is visibly unexamined, not implicitly ruled out.

**Layer 3: Standards knowledge (deferred)**

FR-030 to FR-038a are deferred to a future spec (Clarifications, 2026-11-11). Their text is kept in
[deferred-standards.md](deferred-standards.md). The numbers are retired, not reused.

**Evaluation**

- **FR-040**: The project MUST provide a fault catalogue of at least 10 fault types covering both layers. Each
  fault type has a known correct fix and a way to inject it into a model automatically.
- **FR-040a**: At least a third of the fault types MUST be held out: defined and committed before the checks that
  might detect them are written, by someone not writing those checks, and preferably taken from failures recorded
  in real agent sessions or published LLM model-generation studies. Results for held-out fault types MUST be
  reported separately from the others.
- **FR-040b**: Besides fault-fixing tasks, the evaluation MUST include:
  - fault-free control tasks, at least one per five fault tasks
  - authoring tasks, in which the agent builds or changes an HVAC system from a description and success is a
    model that passes the connection check and simulates
  - open questions about a model that no single new tool answers directly (for example "which zones served by
    this air loop have unmet hours?"), with a known answer
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
  - for treatment runs, whether the agent used the new tool intended for the task, another new tool, or none
- **FR-042a**: Every task MUST be run at least three times in each condition. Comparisons MUST be paired by task
  and report a 95% confidence interval for each difference, overall and per layer. Per-fault-type figures are
  reported as description, not as evidence, when a fault type has too few tasks for its interval to exclude zero.
- **FR-042b**: Task prompts MUST describe a symptom or goal as a modeller would, and MUST NOT name the injected
  object, field or fault type, or state that the model contains a fault.
- **FR-042c**: The baseline condition MUST differ from the treatment only by this feature: the same server at the
  revision just before the feature's first change, with the same agent, model, prompts and limits. A baseline that
  includes other changes MUST be labelled as such in the report.
- **FR-043**: Evaluation tasks that need simulation output MUST be skipped with a stated reason when EnergyPlus is
  unavailable.
- **FR-044**: The project MUST keep paired model, simulation output and error report fixtures from the reference set,
  so that result linking can be tested without running EnergyPlus.
- **FR-045**: Every new or changed capability MUST be covered by tests that exercise it through the server's protocol
  boundary, with no AI client involved (Constitution, Principle VII). Agent conversations, including the
  evaluation, are evidence of benefit, not tests of correctness.
- **FR-046**: The change that completes each user story MUST include an evaluation run covering that story's fault
  types and the comparison against the previous slice. A story whose run shows no benefit on any measure in
  SC-009 MUST be reviewed by a maintainer before the next story is started, and the decision recorded with the
  run.

**Developer API**

- **FR-050**: Every capability in this feature MUST be available to developers as a public, documented idfkit API
  that works without idfkit-mcp. idfkit-mcp MUST reach each capability only through that same public API, never
  through private functions, so the public API is exercised by a real consumer.
- **FR-051**: The public API MUST be fully typed, so that code using it passes the project's strict type checking
  without suppressions.
- **FR-052**: Each layer MUST ship a reference page and runnable examples in idfkit's documentation and in its bundled
  agent references. Every example MUST run unchanged in the test suite.
- **FR-053**: The public API MUST follow idfkit's versioning: no breaking change within a major release, and
  deprecations announced at least one minor release before removal. Its names MUST be recorded in the naming
  register and its subpackages in the parity ledger (as Python-only until idfkit-js implements them).
- **FR-054**: The public API MUST make no assumptions about agents, sessions or servers. Session concepts (such as
  the session's simulation results) are passed in by the caller, not read from global state.
- **FR-055**: Each layer MUST be usable on its own through its own API: references (existing), topology and
  results. On top of them, idfkit MUST offer a combined graph view of a model that:
  - presents objects, nodes, result facts and messages as typed graph nodes
  - presents references, flow connections, control connections, loop membership and result links as typed edges
  - uses one documented vocabulary of node and edge kinds
  - lets a developer walk across layers from any starting object with a hop limit and optional filters on node and
    edge kinds
- **FR-056**: The combined view MUST be derived from the layer APIs and never duplicate their data. It MUST cost
  nothing until it is first used. It MUST include only the layers that are available: results only after a
  simulation. It MUST say which layers it includes. Its vocabulary MUST be extensible under FR-053, so that a later
  feature can add kinds (for example standards verdicts) without breaking existing code or exports.
- **FR-057**: A developer MUST be able to export the combined view, or a bounded part of it (selected layers, node
  and edge kinds, or the neighbourhood of a starting object within a hop limit), as node-link JSON. Each node and
  edge carries its kind, its layer and its identity. The output MUST load unchanged into networkx's node-link reader
  and MUST record the idfkit version, the model's EnergyPlus version and the layers included. The format MUST be
  versioned, and a change to it follows FR-053. No other export format is part of this feature.
- **FR-058**: Agents MUST be able to request, through the server, the cross-layer neighbourhood of one object or
  node. The response is bounded by a hop limit (at most 3), a maximum number of graph nodes, optional filters on
  node and edge kinds, and the 8 KB response budget. It states what was cut off. It is built from the combined view
  (FR-055) and uses the same node and edge vocabulary. The graph export (FR-057) MUST NOT be exposed through the
  server.
- **FR-059**: The server MUST expose this feature through the fewest tools that cover its user stories. No two new
  tools may answer the same question: where a targeted question (such as what a node connects) is a special case
  of the neighbourhood request, either the targeted tool is justified by a measured saving in calls or tokens, or
  it is not added. Each new tool's description MUST say when to use it instead of its nearest neighbour.

### Key Entities

- **Node**: A named connection point through which air or water flows. It is not an object. It is used by two or
  more object fields.
- **Node use**: One field of one object naming a node. It has a connection role, a fluid stream, and the provenance of
  the rule that assigned them (FR-010a).
- **Loop membership**: A component's place in a loop: loop, loop kind (air, plant, condenser, zone equipment), side,
  branch and position.
- **Connection finding**: The result of a connection check. It has a check rule, a severity, the objects and nodes
  involved, and the provenance of the connection rules it relied on.
- **Result link**: A tie between an output item and an object or node. It records the method used (exact, typed,
  naming convention, weak) and the output item's source.
- **Result fact**: One value attached to an object, such as a design capacity, peak load or unmet hours. It records
  units, source and severity where relevant.
- **Linked message**: An error or warning with its kind, linked objects, occurrence count and first occurrence.
- **Candidate cause**: An object proposed as the cause of a symptom, with evidence, a reason and a verification step.
- **Model graph view**: The combined, read-only view across layers (FR-055). Its node kinds are object, node,
  result fact and message. Its edge kinds are reference, flow, control, membership and result link. Each node and edge carries its kind, its layer and the identity (object type and name, or node name) a
  developer can pass back to the layer APIs.
- **Component category**: A coarse class of HVAC component (heating coil, fan, pump and so on), derived from the
  object type, used to filter questions across object types (FR-016a).
- **Fault type and evaluation task**: A known, injectable defect with its correct fix, marked held out or not
  (FR-040a). A task applies one fault to one model, or is a control, authoring or open-question task (FR-040b). It
  is run several times per condition and records how an agent performed each time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On every unmodified example model shipped with the latest supported EnergyPlus version (the reference
  corpus, FR-013), connection checks report zero error-severity findings.
- **SC-001a**: On the earlier-version corpora of FR-013a, connection checks report zero error-severity findings
  once the per-version warning cap is applied, and the false-finding rate per version and check is published.
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
- **SC-008**: The evaluation runs repeatably on the full catalogue and reference set. Repeated runs under the same
  configuration agree on overall success rate within 5 percentage points, measured over the repeats required by
  FR-042a.
- **SC-009**: The decision gate for User Story 6 and later phases passes when, with the new capabilities, agents show
  either:
  - a fix rate at least 20 percentage points higher on the relevant fault types, or
  - at least 30% fewer tool calls at no lower fix rate,

  with the 95% confidence interval of that difference excluding zero (FR-042a). The gain MUST also hold, at
  least in direction, on the held-out fault types (FR-040a). It MUST come with no increase in unwanted changes to
  correct parts of the model and no increase in false fixes on control tasks.
- **SC-009a**: On diagnosis tasks, including those whose cause is outside the diagnosis rules, the rate at which
  agents apply a fix to a wrong top-ranked candidate is no higher with diagnosis than without it.
- **SC-010**: The tools added by this feature together increase the cost of the server's tool listing by no more than
  15%. Cost is the full listing as an agent receives it, input and output schemas included. The base is the
  listing at the revision before the feature's first change, measured at 39 tools and about 15,300 tokens during
  review. The increase is stated in the change that adds each tool (Constitution, Principle II).
- **SC-010a**: In treatment runs, agents use the intended new tool on at least 80% of the tasks it was built for
  (FR-042).
- **SC-011**: On the largest reference model, at about 7,000 objects and 2,900 nodes, the following stay within
  budget:
  - Deriving the full connection view and running every connection check, after loading or after an edit, adds
    no more than 25% to the time it takes to load that model.
  - Every subsequent topology question is answered in under 0.05 s of server time.
- **SC-012**: After a simulation, the first results question is answered in under 0.25 s of server time, and every
  later one in under 0.05 s, whatever the size of the timeseries output.
- **SC-013**: A default response from any capability in this feature is under 8 KB.

- **SC-014**: Every public name this feature adds to idfkit appears in the reference documentation with at least one
  runnable example. Every example runs in the test suite and passes strict type checking. A developer can complete
  User Story 7's independent test using only the documentation.

## Assumptions

- **One umbrella feature, delivered in slices.** The two layers and the evaluation are specified together because
  they share entities, identity rules (type and name) and the evaluation. Each user story is independently
  deliverable. User Stories 1 and 2 form the first slice. User Story 6 waits for the decision gate in SC-009.
  Keeping one spec was confirmed in Clarifications (2026-11-11), so one plan covers all layers.
- **The reference corpus is the example file set of the latest supported EnergyPlus version**, currently 26.2
  (confirmed in Clarifications, 2026-11-11). The research measured the 24.1 set (735 files, 575 with branches);
  the 26.2 set is expected to be of similar size. The reference model set for the evaluation (FR-041), fault
  injection and fixtures are drawn from it.
- **Older versions are measured but do not qualify checks.** Models from 8.9 to 26.1 get the same checks. Their
  schemas do not mark node fields, so those fields are found by other means. Promotion to error severity is decided
  on the 26.2 corpus alone (Clarifications). False findings on older versions are measured on at least two earlier
  example sets, and a check is capped at warning for any version where it is not clean (FR-013a). Reports of false
  findings on other older models are fixed as bugs, with a regression test built from the reported model.
- **The tool budget is tight.** At about 15,300 tokens for the current listing, the 15% cap allows about 2,300
  tokens for every new tool together, roughly half the cost of an average tool today. Meeting it is expected to
  require fewer, broader tools (FR-059), not shorter descriptions that leave agents unsure which tool to use.
- **The evaluation costs real money and time.** Three repeats of each task in two conditions, across the catalogue,
  control, authoring and open-question tasks, is several hundred agent runs per evaluation. That cost is accepted
  because an underpowered evaluation would gate later work on noise.
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

  idfkit-mcp then adopts the new idfkit level through its pinned dependency and the bump procedure
  (Constitution, Principle VI).
- **A machine with EnergyPlus installed** is needed for several jobs:
  - generating the connection rules from the example models (once per adopted EnergyPlus version, FR-010a)
  - building the paired output fixtures
  - running the evaluation's simulation tasks
  - cross-checking against EnergyPlus's branch and node report

  The generated rules and fixtures are committed, so the default test suite never needs EnergyPlus.
- **Agent reference documentation** in idfkit (the bundled `developing-with-idfkit` references) must be updated with
  each new capability, as idfkit's contribution rules require.
- **Corrections outside this feature** are listed in [background/README.md](background/README.md#corrections-that-do-not-wait-for-this-feature).
  They are idfkit's wrong node-validation guidance and idfkit-plugin's unit error, and they should not wait for it.

## Out of Scope

- Exporting models to semantic ontologies (Brick, ASHRAE 223P, BOT). 223P is still in public review, no IDF
  translator exists, and energy models lack the sensor points those ontologies centre on. The node and edge vocabulary
  defined here is designed so that an export can be added later.
- Performance-path compliance (ASHRAE 229 ruleset description and PNNL's ruleset checking tool). Both are
  unpublished and self-described as unstable.
- Building or rewiring HVAC systems automatically. This feature reads, checks and renames. It does not construct
  loops.
- A visual schematic of HVAC systems.
- Standards knowledge: climate zone, envelope, lighting and ventilation screening against ASHRAE 90.1 and 62.1,
  object roles and their assertion. Deferred to a future spec (Clarifications, 2026-11-11), with its requirements
  kept in [deferred-standards.md](deferred-standards.md).
- A developer API for registering custom connection rules, message patterns or role vocabularies (Clarifications,
  2026-11-11). Coverage gaps are closed by regenerating idfkit's rules.
- Graph export through the MCP server; export is a Python developer capability (FR-057, FR-058).
- Graph export formats other than node-link JSON (GraphML, RDF, database loaders). The node and edge vocabulary of
  FR-055 is designed so they can be added later.
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
| Brick and 223P exports are low value now. 229 and its ruleset checking tool are unstable | Report 02, §§2.1, 3 | Out of Scope |
| No published work joins agent, MCP and a live model graph. Graph retrieval helped LLMs by 20–40% on Brick data, and pasting the whole ontology did not help | Literature scan | FR-003, FR-015, FR-016, User Story 2 |
| No study measures the benefit to an agent | All reports | User Story 2, SC-008, SC-009 |
| A catalogue written by the authors of the checks measures whether agents call the checks, not whether they diagnose better | Review, 2026-11-11 | FR-040a, FR-042b, SC-009 |
| Around 20 tasks per fault type, run once, gives a ±11-point uncertainty on each fix rate, wider than the effects the gate looks for | Review, 2026-11-11 | FR-042a, SC-008, SC-009 |
| The current tool listing is 39 tools and about 15,300 tokens, so the 15% cap leaves about 175 tokens per planned new tool | Review, 2026-11-11, measured | FR-059, SC-010 |
| A planned node-graph build takes 5.2 ms against 228 ms to load the largest example model. The results index takes 1.8 ms on a 32.5 MB SQL file. An existing unbounded tool response is 110 KB | Performance measurements | FR-009, SC-011–SC-013 |
