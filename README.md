# Agent Assurance Lab Demo

Smallest working demo for: secure -> unsafe MCP -> detected bypass -> fix.

Run:

```bash
python3 lab/executor.py
```

Tests (stdlib only, no install needed):

```bash
python3 -m unittest discover -s tests -v
```

Frontend:

```bash
python3 -m http.server 8765
```

Then open `http://localhost:8765/frontend/`.

Artifacts:

- `cases/mcp_bypass.yaml`: one YAML case
- `schemas/case.schema.json`: JSON Schema for the case
- `lab/executor.py`: reusable Python executor
- `lab/sandbox.py`: disposable local HTTP destination the attack actually has to reach
- `evidence/mcp_bypass_result.json`: objective PASS/FAIL evidence written by the run
- `frontend/index.html`: local dashboard for the proof chain
- `tests/test_executor.py`: unit tests for the parser, schema validator, and evaluator

## Monster Voice

The guide loads text from `frontend/dialogue.json`. When matching generated clips
exist, it plays them at their original pitch and speed and animates the mouth
during playback. Otherwise it labels the narration as "Browser voice".

For Intel Macs, install the voice tools in a Python 3.11 environment:

```bash
uv venv --python 3.11 .venv-coqui
uv pip install --python .venv-coqui/bin/python -r lab/requirements-voice.txt
```

After reviewing and accepting the [XTTS non-commercial license](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt):

```bash
.venv-coqui/bin/python lab/generate_voice.py /path/to/voice1.m4a --accept-noncommercial-license
```

Generation uses local CPU inference and requires an initial model download.
The reference is converted and normalized in a temporary directory, then removed.
Only generated dialogue clips and their manifest are written to `frontend/audio/`.
Refresh the frontend and click **Hear again** after generation finishes.
Keep the original reference recording outside the directory served by your web server.
