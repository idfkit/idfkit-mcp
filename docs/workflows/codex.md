# Codex Workflow

This pattern optimizes `idfkit-mcp` usage for Codex-style autonomous coding sessions.

## Recommended System Prompt Fragment

```text
Use idfkit-mcp to edit and simulate EnergyPlus models.
Always:
1) call get_model_summary first,
2) call describe_object_type before create/update,
3) validate after each edit batch,
4) prefer batch_add_objects over repeated add_object calls,
5) summarize errors with actionable fixes.
```

## High-Throughput Authoring Loop

1. Load or create model (`load_model` / `new_model`)
2. Fetch type contract (`describe_object_type`)
3. Create objects in bulk (`batch_add_objects`)
4. Wire references (`get_available_references`, `update_object`)
5. Run guards (`validate_model`, `check_references`)
6. Persist (`save_model`)

## Simulation Loop

1. Ensure weather (`download_weather_file` or explicit `weather_file`)
2. Run (`run_simulation`)
3. Inspect (`get_results_summary`)
4. Query variables (`list_output_variables`)
5. Iterate from schema + validation findings

## Prompting Tips for Better Tool Use

- Ask for **diff-oriented updates**: "Change only these fields."
- Ask for **batched object creation**: "Create all schedules in one call."
- Ask for **structured exit criteria**:
  - model validates
  - no dangling references
  - simulation completes without severe/fatal errors

## Example Task Brief

```text
Load ./models/baseline.idf, add 4 perimeter zones, update references,
run validation and dangling reference checks, save to ./models/revised.idf,
then run design-day simulation and summarize severe/fatal messages.
```
