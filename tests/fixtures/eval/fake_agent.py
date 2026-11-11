"""A stand-in for an agent CLI, for the evaluation harness's end-to-end test (T063). No model, no network.

Invoked as ``fake_agent.py <prompt> <mcp_config> [flags...]`` in the task's working directory. It reads which
condition it serves from the MCP configuration (the server command's last argument, ``baseline`` or
``treatment``), acts on ``model.idf`` with idfkit as the canned transcript says, prints that transcript (Claude
Code stream-JSON) to standard output, and appends what it was given to the JSON-lines file ``$FAKE_AGENT_LOG``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from idfkit import load_idf, save_idf

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    prompt, mcp_config = argv[1], Path(argv[2])
    config = json.loads(mcp_config.read_text(encoding="utf-8"))
    server = config["mcpServers"]["idfkit"]
    condition = server["args"][-1]
    log = os.environ.get("FAKE_AGENT_LOG")
    if log:
        entry = {"argv": argv, "cwd": os.getcwd(), "condition": condition, "prompt": prompt, "server": server}
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")

    if "loads look far too high" in prompt:
        doc = load_idf("model.idf")
        if condition == "treatment":
            doc["Zone"]["Office"].multiplier = 1
            transcript = "treatment_fix.jsonl"
        else:
            doc["Zone"]["Store"].multiplier = 3
            transcript = "baseline_wrong.jsonl"
        save_idf(doc, "model.idf")
    elif "set up correctly" in prompt:
        transcript = "control_clean.jsonl" if condition == "treatment" else "control_claims.jsonl"
    elif "Which zone" in prompt:
        transcript = "question_right.jsonl" if condition == "treatment" else "question_wrong.jsonl"
    else:
        print(f"fake agent: unexpected prompt {prompt!r}", file=sys.stderr)
        return 1
    sys.stdout.write((HERE / transcript).read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
