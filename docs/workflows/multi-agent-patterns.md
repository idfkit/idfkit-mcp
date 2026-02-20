# Multi-Agent Patterns

This page describes team-style workflows where multiple agents collaborate on one model lifecycle.

## Pattern 1: Planner + Executor

- Planner agent:
  - decides object types and sequence
  - produces a batched action list
- Executor agent:
  - runs `idfkit-mcp` tools
  - captures outputs and failures

Best practice:

- Planner must emit schema checks before every write action.

## Pattern 2: Author + Verifier

- Author agent:
  - performs `add_object`, `batch_add_objects`, `update_object`
- Verifier agent:
  - runs `validate_model`, `check_references`
  - blocks merge if invalid

Gate criteria:

- `is_valid == true`
- `dangling_count == 0`

## Pattern 3: Modeling + Simulation Split

- Modeling lane edits IDF/epJSON structures.
- Simulation lane handles weather selection and execution.

Handoff contract:

1. Modeling lane saves artifact path.
2. Simulation lane loads same path with `load_model`.
3. Simulation lane returns summary plus severe/fatal messages.

## Minimal Orchestration Checklist

1. Single source of truth path for model files.
2. Explicit version pin (`new_model(version=...)` when creating).
3. Validation checkpoint after every mutation batch.
4. Simulation checkpoint before reporting results.
