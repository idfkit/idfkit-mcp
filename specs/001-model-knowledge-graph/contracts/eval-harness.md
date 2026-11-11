# Contract: evaluation harness (idfkit-mcp `eval/`, not packaged)

The harness is a maintainer tool for User Story 2 and FR-040 to FR-043. It uses the standard library plus the
FastMCP client idfkit-mcp already depends on, and is excluded from the wheel.

## Command line

```bash
# --faults takes "all" or a comma-separated list of fault ids
uv run python -m eval run \
    --models eval/reference_models.toml \
    --faults all \
    --baseline "uvx idfkit-mcp==0.11.1" \
    --treatment "uv run idfkit-mcp" \
    --runner eval/runners/claude_code.toml \
    --repeat 1 \
    --out eval/runs/<run_id>/

uv run python -m eval compare eval/runs/<a>/ eval/runs/<b>/   # per-fault-type and overall table
uv run python -m eval list-faults                              # ids, layer, needs_energyplus
```

Exit codes: 0 when the run completed (whatever the scores), 2 for bad configuration, 3 when no tasks were
runnable.

## Runner configuration (`eval/runners/*.toml`)

```toml
name = "claude-code-headless"
command = ["claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}", "--output-format", "stream-json"]
model = "<model identifier recorded with the run>"
max_turns = 40
parse = "claude_stream_json"        # parser that extracts tool calls and token counts
```

The harness writes `{mcp_config}` per condition, pointing at the baseline or treatment server command. Any agent
CLI with a parser can be added. No LLM SDK is imported.

## Inputs

- `reference_models.toml`: at least 20 entries `{id, file, version = "26.2", tags}`, with files resolved under
  `$ENERGYPLUS_DIR/ExampleFiles`.
- Fault registry: `eval/faults/*.py`, each exposing `FAULT: FaultType` (data-model.md, Evaluation).

## Outputs (`--out` directory)

- `run.json`: `EvaluationRun` (runner, model identifier, baseline version, treatment git revision, timestamps).
- `outcomes.jsonl`: one `TaskOutcome` per task and condition.
- `transcripts/`: raw runner output per task.
- `summary.md`: a table per fault type and overall, with fix rate, median tool calls, median response tokens and
  unwanted changes, for baseline against treatment, plus the SC-009 gate verdict.

## Rules

- Tasks with `needs_energyplus = true` are recorded as `verified_by="skipped"` with the reason when EnergyPlus is
  not found. They are never counted as failures (FR-043).
- `unwanted_changes` is computed by diffing the final model against the injected model, outside the fault's
  declared object scope.
- The same task list and order is used for both conditions, and `--repeat N` re-runs it N times so the SC-008
  repeatability spread can be computed.
