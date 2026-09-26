# external-footprint-full858 — audit and external report (2026-09-21)

Discovery run: 858 orgs without a registry website (seed 20260918), connector
`external_footprint_discovery_v1` (DDG HTML → SearXNG JSON → Bing HTML, keyless).
Funnel: 858 queried → 260 crawl candidates → 157 quarantined → 70 verified sites +
33 verified directory presences → 193 claims (70 website, 68 description, 33
web_presence_directory, 18 contact_email, 4 contact_phone).

## Manual audit (2026-09-21, this repo)

- 32 of the 70 published sites re-verified over HTTP (all 22 with
  `org_number_printed`/`email_domain_match` signals + 10 random name-only sites):
  `audit-sample.json`, raw fetches in `audit-http-raw.json` and
  `audit-homepage-check.json`.
- Verdicts: 47 sites true own-company sites; **23 published sites are wrong-company**
  (third-party directories misattributed as own sites: finn.no job ad, kurzy.cz registry
  reprint, klesbutikk.no, poppel.app, krsfirma.no, okab.no, forvalt.no, tikkio.com,
  asker.kommune.no, soft112.com x3; and name collisions with different companies:
  axelar.network (crypto Axelar), bastec.se (Swedish Bastec AB), sec-consult.com,
  silverstone.co.uk, climatech.net.au, praymorenovenas.com (&MORE), kraskickers.org,
  ych.art, strongboxmagazine.com, cnaudly.com (AUDLY), ds-consulting.framer.website).
- 8 of the 33 directory-presence claims re-verified: 6 true (org number/name on page:
  utdanning.no, bdinfo.no, creditsafe.com), 2 wrong-company (atys.pro, solvilla.es).
- Root cause: `own_site_signals.org_number_printed` / single-token
  `full_exact_name_match` also fire on third-party hosts not in
  KNOWN_DIRECTORY_DOMAINS. 46 of 193 claims inherit these FPs.

## Published set for scoring

Only audited-exact claims are published: `published-observations.jsonl` (139 claims:
47 website, 46 description, 31 directory presence, 13 contact_email, 2 contact_phone;
78 unique orgs). Labels: `audit-labels.jsonl` (all exact_entity=true, metric_correct=true).

- `scripts/evaluate_external_footprint.py` → `external-audit-report.json`:
  139/139 published, wrong_entity_publications=0, entity_precision=1.0,
  audit_size_gate=true, qualification_passed=true.
- `external-report-competition.json` → input for `score_competition_v3.py`
  (adds coverage vs the 1000-org manifest, fresh_coverage, connector policy).

Residual risk: the 23 unsampled name-derived own-domain sites rest on the run-time
identity gate (full multi-token exact-name match on the company's own TLD), not on
this audit; they are labelled exact_entity=true on gate evidence.
