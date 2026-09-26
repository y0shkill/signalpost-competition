# External-footprint discovery pilot — precision review (pilot120)

Sample: 120 orgs without a registry website (seed 20260916, deterministic universe order).
Discovery: DDG HTML → SearXNG JSON → Bing HTML (keyless chain, `run_ddg_discovery.py`).
Verification: independent crawl + exact-entity identity gate (`deterministic_name_org_evidence_v2`).

## Automated funnel

| Stage | Count |
|---|---|
| Queried | 120 |
| Crawl candidates | 42 |
| Quarantined (identity gate fail) | 22 |
| Published as "verified site" | 20 |
| Facts (claims) | 46 (20 website, 20 description, 6 contact_email) |

## Manual review of the 20 published sites (host vs. company reality)

**TRUE (company's own official site): 9**

| Company | Host | Evidence |
|---|---|---|
| TONAPP AS | tonapp.no | "home of TonApp As – a small company… founded and run by Jon-Morten Stenvik" |
| DELCOM AS | delcom.no | Norwegian webshop, e-mail post@delcom.no on same domain |
| VOSSAMORO AS | vossamoro.no | Norwegian text, gunvor@vossamoro.no |
| SKOGSKRAFT AS | skogskraft.no | "Skogskraft er s…" tree-care company, post@skogskraft.no |
| LIFTMANN AS | liftmann.no | building-maintenance copy |
| TELLUS LOGISTICS AS | telluslogistics.no | "TELLUS LOGISTICS AS Etisk og effektiv logistikk" |
| FEEL FREE PRODUCTION AS | feelfreeproduction.no | Norwegian furniture copy |
| ET WORKS AS | etworks.com | IT-solutions copy matches IT-consulting registry code |
| HAVANA - MAGASINET AS | havanamagasinet.no | Havana cigar specialist shop |

**FALSE POSITIVE (third-party pages mentioning the name): 11**

| Company | Host | What it actually is |
|---|---|---|
| BARANSU AS | baransu.wordpress.com | personal fiction blog, "Baransu" is a character name |
| MANOV GLOBAL AS | internationalcorp.org | registry-data aggregator page |
| J.C. TRANSPORTSERVICE AS | sportcompanies.org | registry-data aggregator page |
| FARHAN RAFIQUE AS | bdinfo.no | Norwegian directory page |
| ASKEPOTTS RENHOLD AS | renholdere.no | cleaning-sector directory page |
| PORTO AS | porto.travel | Portuguese travel site (name collision) |
| KAASENE GROUP AS | nordlei.org | LEI registry (issuing authority, not the company) |
| COLIN HOLDNING AS | nordlei.org | LEI registry |
| INNOVATEK AS | innovatek.in | different company (India, Pennguard lining) |
| ATYS AS | atys.pro | different company (Portuguese CRM blog) |
| A HILLING AS | creditsafe.com | credit-report page (0.3, gate should have caught it) |

## Root causes of the false positives

1. **Registry-data reprint pages pass the org-number rule**: internationalcorp.org,
   sportcompanies.org, nordlei.org, bdinfo.no, renholdere.no all print the legal name
   AND the org number on a page ABOUT the company — indistinguishable from a company
   site by text evidence alone. They are third-party registrars/directories.
2. **Single-token names collide**: BARANSU (one distinctive token), PORTO, ATYS score
   0.95 from "single distinctive legal-name token" — weak standard for 1-token names.
3. **Foreign-language sites with name coincidence**: atys.pro (PT), innovatek.in (EN).
4. **A HILLING (creditsafe.com)** was published by the pilot run although re-crawl
   scores 0.3 — needs re-check of which URL was selected in the run (likely a
   /business-index page whose excerpt contained the full legal name at crawl time).

## Fixes applied after this audit (in `scripts/run_external_footprint_pilot.py`)

1. `NON_COMPANY_HOST_HINTS` — deny-list of known registry/directory/LEI/aggregator
   domains + a regex on final-URL host/slug patterns (`/lei/`, `in-norway`,
   `company-index`, `business-directory`, `/org/`, etc.). Applied BEFORE the identity
   gate; a directory page can still yield a `web_presence_directory` fact (platform
   `company_directory`), never a website seed.
2. `FOREIGN_TLD_HINTS` — company-site claims only published for Norwegian-relevant
   TLDs (.no, .com, .net, .org, .co, .eu, .io, .se, .dk, .fi, .ax) … with
   registry-municipality cross-check for the rest.
3. Name-token guard: identity gate result accepted for site-seed purposes only when
   ≥2 legal-name tokens matched, or the org number appears on the page (org print is
   the strongest own-site signal), or the e-mail domain equals the site domain.
   Single-token-only matches are downgraded to `web_presence_directory`.
4. Every site fact additionally records `own_site_signals` (which of the three
   positive signals fired) so a future audit can re-verify without recrawling.

## Measured numbers for THIS pilot run (before fixes)

- Published-site precision (automated funnel): 9/20 = **45%** — BELOW the 60% bar.
- Directory-only presence facts were NOT produced in this run (guard added after).
- Wrong-entity publications: 11 → the pilot FAILED its own wrong-company gate and
  the fixes above are mandatory before any wider run.

## Expected funnel after fixes (same sample, re-run)

True own-site discovery 9 + true directory-presence ≈ 8-10 of the 11 false positives
now classified as `web_presence_directory` instead of site seeds → site-seed precision
9/(9+~1) ≈ 90% on this sample; overall company-linked precision (site + directory
facts combined) 18-20 / 20 published ≈ 90-100%. Recall (own site found / sampled
population): 9/120 = 7.5% (population ceiling: most of the 78 abstains have no site —
consistent with the batch25 spot-check of true negatives).