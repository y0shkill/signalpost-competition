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
uv run pytest
```