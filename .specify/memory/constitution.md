<!--
SYNC IMPACT REPORT
Version change: (unfilled template) -> 1.0.0
Rationale: initial ratification. The previous file was the unmodified scaffold with every
placeholder intact, so this is the first constitution this repository has had rather than an
amendment to one.

Modified principles:
  (none; no prior principles existed)

Added sections:
  - Scope statement (preamble)
  - Core Principles I through VII:
      I. The Server Exposes, idfkit Knows
      II. Every Tool Is a Typed Contract
      III. An Absent Answer Is Stated, Never Fabricated
      IV. Validation Gates Are Named for What They Prove
      V. Sessions Are Isolated, Persisted, and Bounded
      VI. Levels Are Pinned, Declared, and Reported
      VII. Behaviour Is Tested at the Protocol Boundary
  - Family Position and Delivery Constraints
  - Development Workflow and Quality Gates
  - Governance

Removed sections:
  (none)

Template note: the resolved scaffold provides five principle slots. Seven were ratified, so two
slots were added. Heading hierarchy is unchanged.

Deferred items and observations:
  - Observation (GOVERNANCE_TAG_SKEW): main.yml, bump-idfkit.yml and rehearse-candidate.yml pin
    governance-2026.18, while adopt-energyplus.yml pins governance-2026.27. Principle VI requires
    one pinned governance tag per repository; reconciling the pins is outside this amendment.
  - Observation (ERROR_SHAPE_DOC): docs/concepts/error-semantics.md describes failures as
    dictionaries with an `error` key, while src/idfkit_mcp/errors.py raises FastMCP `ToolError`.
    Principle III requires the documented shape to match the emitted shape; the page is to be
    verified against the code.
-->

# idfkit-mcp Constitution

This repository exposes the `idfkit` library to AI agents through the Model Context Protocol. It
owns the tool surface, the session, and the agent-facing contract; it does not own knowledge of
EnergyPlus. Schema, parsing, validation rules, geometry, simulation, and results parsing belong to
`idfkit`, and EnergyPlus itself is the authority on what a model does. This repository is one
consumer in the idfkit family, recorded as `idfkit-mcp` in the consumer register of
idfkit-conformance, and is in turn consumed by idfkit-plugin (through `uvx`) and by
idfkit-mcp-deployment (through a container image). Where a principle below conflicts with this
scope statement, the scope statement prevails.

## Core Principles

### I. The Server Exposes, idfkit Knows

This repository MUST NOT reimplement a capability that `idfkit` owns: no local schema tables, no
local IDF or epJSON parsing, no local reference resolution, no local results parsing, and no
literal lists of object types or field names beyond what a tool requires to name its own inputs.
Every domain answer a tool returns MUST be computed by `idfkit`, by EnergyPlus, or by a documented
external service (docs.idfkit.com, the weather station index). When a tool needs a capability that
`idfkit` lacks, the capability MUST be proposed upstream first; a local implementation is permitted
only as a recorded interim measure that names the upstream issue that will replace it.

Rationale: an agent cannot distinguish a local approximation from an answer read from the schema.
A local copy of domain knowledge is correct on the day it is written and silently wrong after the
next `idfkit` or EnergyPlus release, and the automated bump workflow cannot detect that drift.

### II. Every Tool Is a Typed Contract

- Every tool MUST return a Pydantic model (or a FastMCP result wrapping one) and MUST NOT return an
  untyped dictionary. Internal data passed between modules MUST use dataclasses or Pydantic models.
- Every tool MUST declare MCP tool annotations (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`) that are accurate for its behaviour. A tool that mutates the
  session model MUST be listed among the mutation tools that the change log records.
- Tool names, parameter names, and descriptions are public API. Renaming or removing a tool or a
  parameter, or changing the meaning of a returned field, is a breaking change and MUST be released
  as such.
- Tool and parameter vocabulary MUST follow the family verb vocabulary (`parse`, `load`, `write`,
  `save`, `add`, `remove`, `rename`, `validate`) as recorded in the idfkit naming map, so that a
  verb means the same thing in the library and in the tool that wraps it.
- Tool descriptions and responses consume the agent's context window. A change that materially
  increases the token cost of the tool listing or of a common response MUST state the increase and
  its justification; `scripts/token_audit.py` is the instrument for measuring it.

Rationale: an agent plans against the declared schema and annotations, not against the source.
An inaccurate annotation causes a client to skip a confirmation it owed the user, and an untyped
response gives the agent nothing to branch on.

### III. An Absent Answer Is Stated, Never Fabricated

- When a tool cannot produce a correct answer, it MUST fail with an actionable error that names
  the cause and, where one exists, the remedy (for example, a missing EnergyPlus installation and
  the discovery paths that were searched). It MUST NOT return a plausible default, a partial result
  presented as complete, or a value inferred from a name pattern.
- Errors from `idfkit` MUST be mapped to the documented error categories, and the shape that the
  documentation describes MUST be the shape the server emits.
- A capability that this server cannot offer because the underlying library does not implement it
  MUST carry an `idfkit:unavailable` statement marker resting on a parity ledger entry, so that the
  idfkit bump workflow can detect when an adopted level makes the statement false.
- Exceptions MUST NOT be swallowed. A caught exception is either re-raised as a typed tool error or
  logged with its cause.

Rationale: the agent is the reader most likely to act on a guess without questioning it. An
explicit failure stops a dependent chain of tool calls; a fabricated result propagates into the
model and into the user's conclusions.

### IV. Validation Gates Are Named for What They Prove

- Schema validation (`validate_model`) and domain integrity checks (`check_model_integrity`) MUST
  NOT be described, in tool descriptions, responses, or documentation, as evidence that a model
  will simulate. Only a completed EnergyPlus run establishes runtime validity.
- Simulation QA results MUST be derived from EnergyPlus outputs, and MUST respect EnergyPlus
  semantics that change totals: zone multipliers, aggregate rows in tabular reports, and the
  plural `Multipliers` column. Where EnergyPlus reports a facility or building aggregate, a value
  this server computes from component rows MUST be cross-checked against that aggregate.
- A QA flag MUST identify the object, zone, or report row it concerns, so that an agent can act on
  it without a second lookup.

Rationale: practitioners use these results in engineering work. An overstated validation claim or
a total that ignores a zone multiplier is an error that reaches a design decision.

### V. Sessions Are Isolated, Persisted, and Bounded

- Server state MUST be scoped to a session identity. No model, simulation result, upload, or
  weather file belonging to one session MAY be observable from another, including under the
  concurrent Streamable HTTP transport used by the hosted deployment.
- Session state MUST be persisted to disk and restored on restart, so that clients that restart
  the server between turns resume without loss. Restoration failure MUST be reported, not silently
  replaced by an empty session.
- Every filesystem write initiated by a tool MUST pass output path validation and resolve within
  the directories named by `IDFKIT_MCP_OUTPUT_DIRS` (or the working directory when unset).
- Metadata that downstream consumers depend on, in particular the `_meta.billing` block read by
  idfkit-mcp-deployment, MUST be versioned through its `schema_version` field. A change to its
  shape MUST increment that version and MUST be coordinated with the deployment repository.

Rationale: the same server runs as a local stdio process for one user and as a shared hosted
service for many. The local case tolerates loose state handling; the hosted case does not, and the
code is the same in both.

### VI. Levels Are Pinned, Declared, and Reported

- `idfkit` MUST be pinned to an exact version in `project.dependencies` of `pyproject.toml`, and
  that pin is the only place the level is declared. Moving the declaration elsewhere, or adding a
  dependency on either idfkit library, is a change to the consumer register in idfkit-conformance
  and MUST land with a paired register change reviewed by both languages.
- The repository MUST pin one governance tag of idfkit-conformance, and every workflow that reads
  the register, the parity ledger, or the conformance workflows MUST read it at that tag.
- `idfkit-mcp --version` MUST report both this server's version and the `idfkit` version it runs
  against, read from the installed distributions.
- A candidate `idfkit` release SHOULD be rehearsed through `rehearse-candidate.yml` before it is
  published. An automated bump that fails MUST be repaired with the smallest compatible change and
  MUST NOT carry unrelated refactoring.
- The set of supported EnergyPlus versions is defined by `idfkit` and adopted through the
  procedure in idfkit-conformance; this repository MUST NOT declare a version range of its own.

Rationale: two downstream consumers deliver this server to people, and each must be able to state
which level it runs. A level that is declared in one place and reported on request answers that
question without investigation.

### VII. Behaviour Is Tested at the Protocol Boundary

- Every tool and resource MUST be covered by tests that invoke it through the FastMCP server, with
  no AI client in the loop, and assert on the structured response.
- Tests that require EnergyPlus or network access MUST be marked so that the default suite runs
  without either, and the default suite MUST run in CI on every change.
- A bug fix MUST include a test that fails before the fix and passes after it.
- A behaviour demonstrated only by a conversation with an AI client is untested, and MUST NOT be
  accepted in review as evidence that a change works.

Rationale: agent conversations are non-deterministic and cannot run in CI. The protocol boundary
is the contract that every client shares, so it is the boundary at which the contract is proven.

## Family Position and Delivery Constraints

- **Upstream**: `idfkit` (core library, zero third-party dependencies) is the foundation. Defects
  found here that originate in `idfkit` MUST be reported and fixed there; a local workaround MUST
  reference the upstream issue.
- **Downstream**: idfkit-plugin resolves this server by name through `uvx` and declares its level
  in `.mcp.json`; idfkit-mcp-deployment resolves it as a container image and declares its level in
  `cdk.json`. A release of this repository propagates to both through `notify-dependents.yml`.
- **Runtime stack**: Python 3.10 or later, FastMCP 3.x, the `mcp` SDK, Pydantic 2, and `openstudio`
  for OSM conversion. A new runtime dependency MUST be justified in the change that adds it and
  MUST pass `deptry`.
- **Transports**: stdio is the default transport and MUST remain fully functional. Streamable HTTP
  is supported for hosted use and MUST satisfy Principle V.
- **External services**: documentation search reads docs.idfkit.com and weather search reads the
  station index. Schema exploration, model editing, and validation MUST work with no network
  access and no EnergyPlus installation.
- **Documentation**: user documentation lives in `docs/` and is published at mcp.idfkit.com. It is
  organised by Diataxis, and a change to a tool's name, parameters, or response shape MUST update
  the corresponding page in the same change.
- **Conventions**: `from __future__ import annotations` in every module; Ruff at line length 120;
  Pyright in strict mode over `src`; hatchling builds; uv manages dependencies and the lock file.

## Development Workflow and Quality Gates

- Before any change is proposed, `make check && make test` MUST pass. This runs lock file
  validation, pre-commit (Ruff format and lint), Pyright, deptry, and pytest.
- The `consumer-register` job in `main.yml` MUST pass. A failure there means the repository no
  longer matches its register entry, and is resolved by correcting the repository or by amending
  the register in idfkit-conformance, never by disabling the job.
- After a version bump in `pyproject.toml`, `uv sync` MUST be run so that `uv.lock` matches.
- Review MUST verify each principle that a change touches. In particular, a reviewer MUST reject a
  change that adds local domain knowledge (I), returns an untyped or unannotated result (II),
  returns a guessed value (III), overstates what a validation gate proves (IV), shares or leaks
  state across sessions or writes outside the allowed roots (V), moves the declared level without
  a register change (VI), or adds a tool without a protocol-level test (VII).
- Complexity MUST be justified in the change that introduces it. Absent a justification, the
  simpler form is the required one.

## Governance

This constitution supersedes other practices in this repository, including conventions recorded in
`CLAUDE.md`, wherever the two disagree. On matters that span repositories (shared vocabulary,
parity statements, the consumer register, governance tags, and EnergyPlus version adoption), the
governance documents of idfkit-conformance and the idfkit unification constitution take precedence
over this file, and this file MUST be amended when it conflicts with them.

**Amendment procedure**: an amendment is a pull request that changes this file, states the version
bump and its rationale, and updates in the same change any guidance, template, or documentation
that the amendment makes incorrect. An amendment that removes or redefines a principle MUST state
what now governs the behaviour that principle covered.

**Versioning policy**: this constitution is versioned as MAJOR.MINOR.PATCH. MAJOR denotes a
backward incompatible governance change, meaning a principle removed or redefined so that it
permits what it previously forbade. MINOR denotes a principle or section added, or guidance
materially expanded. PATCH denotes clarifications, wording, and non-semantic refinements.

**Compliance review**: every pull request is reviewed against the principles above. The quality
gate, the protocol-level test suite, and the consumer register check are the mechanical part of
that review. Runtime development guidance lives in `CLAUDE.md`, which is subordinate to this file
and MUST be corrected when it conflicts with it.

**Version**: 1.0.0 | **Ratified**: 2026-10-14 | **Last Amended**: 2026-10-14
