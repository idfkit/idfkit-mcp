# Claude Workflow

This guide focuses on reliable tool-driven sessions in Claude clients.

## Session Contract

Use this instruction style in Claude projects:

```text
When editing EnergyPlus models, use idfkit-mcp tools instead of raw file edits.
Before writing: describe_object_type.
After writing: validate_model and check_references.
For simulation: ensure weather source first, then run_simulation.
```

## Suggested Conversation Pattern

1. **Intent framing**
   - "Target: reduce heating loads in perimeter zones"
2. **Model context pull**
   - `get_model_summary`
   - `list_objects(object_type="Zone")`
3. **Schema-first changes**
   - `describe_object_type` for edited types
4. **Implementation**
   - `batch_add_objects` and `update_object`
5. **Safety checks**
   - `validate_model`
   - `check_references`
6. **Simulation + analysis**
   - `download_weather_file`
   - `run_simulation`
   - `get_results_summary`

## Failure Recovery Pattern

When a call returns `{"error": ...}`:

1. Keep prior successful steps unchanged.
2. Read error details and adjust arguments.
3. Re-run only failed step.
4. Re-run validation after any fix.

## Example Claude Prompt

```text
Use idfkit-mcp to inspect and improve this model.
Workflow: summarize current model, add missing zone objects, validate,
resolve dangling references, save as ./out/fixed.idf,
run annual simulation with weather for Boston, and report key errors.
```
