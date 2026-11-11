# Contract: evaluation harness (idfkit-mcp `eval/`, not packaged)

The harness is a maintainer tool for User Story 2 and FR-040 to FR-046. It uses the standard library plus the
FastMCP client idfkit-mcp already depends on, and is excluded from the wheel. Decisions: research R-13, R-14 and
R-31 to R-33, R-37.

## Command line

```bash
# --faults takes "all", a layer ("topology", "results") or a comma-separated list of fault ids
uv run python -m eval run \
    --models eval/reference_models.toml \
    --faults all \
    --baseline-config eval/baseline.toml \
    --treatment "uv run idfkit-mcp" \
    --runner eval/runners/claude_code.toml \
    --repeat 3 \
    --out eval/runs/<run_id>/

uv run python -m eval compare eval/runs/<a>/ [eval/runs/<b>/]   # tables and gate verdict; with two runs, slice delta
uv run python -m eval list-faults [--check-held-out]           # ids, layer, kind, held_out, needs_energyplus
```

Exit codes: 0 when the run completed (whatever the scores), 2 for bad configuration, 3 when no tasks were
runnable. `list-faults --check-held-out` exits 2 when any held-out fault is invalid.

## Baseline (FR-042c)

`eval/baseline.toml` pins the revision just before the feature's first change:

```toml
kind = "pre_feature"
idfkit_mcp_sha = "81d3cd6"     # idfkit-mcp revision before the feature
idfkit = "idfkit==<level>"     # the level that revision pins
```

The harness builds the baseline server from a `git worktree` of that SHA, run with the pinned idfkit, so the two
conditions differ only by this feature. `--baseline "<command>"` is accepted instead, for example a released
version; the run is then recorded with `baseline_kind = "other"`, and its SC-009 verdict is marked not valid.

## Runner configuration (`eval/runners/*.toml`)

```toml
name = "claude-code-headless"
command = ["claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}", "--output-format", "stream-json"]
model = "<model identifier recorded with the run>"
max_turns = 40
parse = "claude_stream_json"        # parser that extracts tool calls and token counts
disallowed_tools = []               # ablation only: tools the agent may not call
disallowed_flag = "--disallowedTools"
```

The harness writes `{mcp_config}` per condition, pointing at the baseline or treatment server. Any agent CLI with a
parser can be added. No LLM SDK is imported.

**Ablations.** A non-empty `disallowed_tools` passes the list to the agent CLI, so the server is unchanged and only
the agent's tool list differs. Ablation runs are labelled `ablation = true` in `run.json` and never produce an
SC-009 verdict. The slice 4 ablation disallows `trace_hvac` and `get_object_results` (research R-31).

## Inputs

- `reference_models.toml`: at least 20 entries `{id, file, version = "26.2", tags}`, with files resolved under
  `$ENERGYPLUS_DIR/ExampleFiles`.
- Task registry (data-model.md, Evaluation):
  - `eval/faults/*.py`, each exposing `FAULT: FaultType`: designed fault types (10, research R-14)
  - `eval/faults/held_out/*.py`, each exposing `FAULT: FaultType`: held-out fault types (at least 5, research R-33)
  - `eval/tasks/controls.toml`, one `TaskSpec` per entry: control tasks, at least one per five fault tasks
  - `eval/tasks/authoring/*.py`, each exposing `TASK: TaskSpec`: authoring tasks (4), each with a goal and a
    verifier
  - `eval/tasks/questions/*.py`, each exposing `TASK: TaskSpec`: open questions (6), each with an answer key
    computed by idfkit from the unmodified model
- Each task declares `kind` (`fault`, `control`, `authoring`, `question`), `layer`, the model tags it applies to
  (capped at 8 models per fault type), `prompt` (a template), `intended_tools` and `needs_energyplus`.

## Rules

- **Prompt lint (FR-042b).** Before any run, every rendered prompt is checked. A prompt that contains the injected
  object's name, the field name, the fault id, or the words "fault", "injected" or "bug" fails the run with exit 2.
- **Held-out check (FR-040a).** For each held-out fault file, the commit that first added it must predate the first
  commit that added `idfkit.hvac.checks` at the idfkit level the treatment pins. A fault that fails is recorded as
  `held_out_invalid` and counted with the designed faults. The check runs at the start of every run.
- **Skips (FR-043).** Tasks with `needs_energyplus = true` are recorded as `verified_by="skipped"` with the reason
  when EnergyPlus is not found. They are never counted as failures.
- **Unwanted changes.** Computed by diffing the final model against the starting model, outside the task's declared
  object scope.
- **Order.** The same task list and order is used for both conditions, and every task runs `--repeat` times
  (default 3) per condition (FR-042a).

## Recorded per task, condition and repeat (`outcomes.jsonl`)

- fixed or answered correctly, and `verified_by`: check, simulation, answer key or skipped
- tool calls and response tokens consumed
- unwanted changes
- for control tasks, `false_fix`: any model change or any fault reported
- for authoring tasks, whether the result passed the connection check with no error and simulated
- for treatment runs, `tools_used` and whether an `intended_tools` entry was among them (SC-010a)
- for runs that call `diagnose_symptom`, the top-ranked candidate, whether the agent's first model change targeted
  it, and whether it was the injected object (SC-009a, research R-37)

## Outputs (`--out` directory)

- `run.json`: `EvaluationRun`: runner, model identifier, `baseline_kind`, baseline and treatment revisions,
  `ablation`, repeats, bootstrap seed, timestamps.
- `outcomes.jsonl`: one `TaskOutcome` per task, condition and repeat.
- `transcripts/`: raw runner output per task and repeat.
- `summary.md`:
  - the paired difference (treatment minus baseline) of fix rate, median tool calls and median response tokens,
    with a 95% percentile-bootstrap interval over tasks (10,000 resamples), overall, per layer and per fault type
  - per-type rows whose interval includes zero, marked descriptive
  - a separate table for held-out fault types
  - control-task false-fix rates, authoring success and question accuracy, per condition
  - the SC-008 spread: the range of the overall fix rate across the repeat passes
  - SC-009a: wrong top-candidate edits against the baseline's wrong first edits
  - SC-010a: the share of tasks whose intended tool was used, per new tool
  - the SC-009 verdict, decided per layer on pooled tasks, listing each clause: effect size against 20 points or
    30% fewer calls, interval excludes zero, direction on held-out types, no increase in unwanted changes, no
    increase in false fixes on controls

## Per-slice runs (FR-046)

The pull request that completes a user story includes a run over that story's fault types and the controls, and
`eval compare` against the previous slice's run. When the run shows no benefit on any SC-009 measure, the pull
request also adds `eval/decisions/<slice>.md`, naming the maintainer, the decision (continue, change or stop) and
the reason.
