# Signalpost — Norway company research agent (competition build)

Standalone research agent that produces evidence-grounded "envelopes" for
Norwegian companies (BRREG open data + public website evidence).

## Setup

```bash
uv sync
```

## Run (submission command, accepts a JSONL of organisation numbers)

```bash
uv sync && \
uv run python scripts/run_competition_batch.py \
  --organisations entry-companies.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id run1000-001 \
  --expected-count 1000 --workers 8
```

`brreg-enheter.csv` is the bulk BRREG export (regenerate it near the
submission date — deleted entities are excluded from the bulk). It is not
included in this repo (147 MB).

## Reference results

- `out/run-report-1000.json` — run1000-001: 1000 envelopes, 5/5 gates passed
- `out/run-report-smoke50.json` — 50-profile smoke run
- `out/refresh-replay-report.json` — refresh replay (precision/recall 1.0)
- `entry-companies.jsonl` — deterministic manifest of 1000 orgnrs (universe order)

## Local scoring

```bash
uv run python scripts/score_competition_v3.py
```

## Tests

```bash
uv sync --extra test && uv run pytest
```
## External-footprint integration (run1000-002-external)

The 858-org keyless discovery run (`external-footprint-full858/`) was audited
and its exact-entity subset (139 claims, 78 orgs) integrated:

- `external-footprint-full858/AUDIT.md` — audit method, verdicts, root causes.
- `out/profiles-1000-external.jsonl` / `out/envelopes-1000-external.jsonl` —
  1000 envelopes regenerated with external evidence attached (website seed for
  47 verified own sites; `external` evidence block with the audited claims).
- `out/research-agent-report-1000.json` — research suite 12/12 on the 1000-profile
  corpus (`tests/fixtures/research-agent-suite-submission-1000-v2.json`).
- `out/ux-report-1000.json`, `out/scorecard-preview-1000.html`.

Scoring inputs:

```bash
uv run python scripts/evaluate_external_footprint.py \
  --profiles out/profiles-1000.jsonl \
  --observations external-footprint-full858/published-observations.jsonl \
  --labels external-footprint-full858/audit-labels.jsonl \
  --output external-footprint-full858/external-audit-report.json

uv run python scripts/score_competition_v3.py \
  --profiles out/profiles-1000.jsonl \
  --external-report external-footprint-full858/external-report-competition.json \
  --batch-report out/run-report-1000.json \
  --refresh-report out/refresh-replay-report.json \
  --research-report out/research-agent-report-1000.json \
  --ux-report out/ux-report-1000.json \
  --output out/score-proxy-1000-v2.json
```

Latest local score: **55.329/100 raw, 7/7 qualification gates passed**
(baseline before external integration: 23.0/100 raw).

## Setup note

`pytest` is available via the `test` extra (`uv sync --extra test`).
