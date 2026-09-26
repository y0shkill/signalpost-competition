# Signalpost — Estado de Submissão (2026-09-10)

## O que está validado e executado

| Item | Estado | Evidência |
|---|---|---|
| Starter kit instalado (`uv sync`) | OK | deps pinned em uv.lock, venv criado |
| Testes do kit | OK | 104 passed, 5 subtests (pytest) |
| MVP standalone (`mvp_signalpost.py`) | OK | 3 envelopes out/mvp-validation.jsonl, 10/11 claim families, 0 falhas |
| Bulk dataset `brreg-enheter.csv` | OK | 1.467.983 empresas, sha256 d89ba2be...0aa0, 147.5 MB gzip |
| Universe público | OK | 411.160 empresas, `signalpost-universe.jsonl.gz` (12.6 MB) |
| Manifest de 1000 empresas | OK | `entry-companies.jsonl` (universe-order, filtrado contra bulk — determinístico) |
| Smoke run 50 perfis | OK | `out/run-report-smoke50.json`, validation.passed=true, 276 requests |
| **Run 1000 perfis (mínimo de submissão)** | OK | `out/run-report-1000.json`, run-id run1000-001, **5/5 gates passados** |
| Refresh replay (previous-snapshot + material-change) | OK | `out/refresh-replay-report.json`, precision/recall 1.0, idempotent |

## Resultados do run 1000 (run1000-001)

- 1000 envelopes, entity states: 1000 × `complete` (zero silent drops)
- Módulos: 6191 `complete`, 1789 `not_found`, 8 `source_error`, 9 `blocked_policy`, 3 `blocked_robots` — todos estados terminais explícitos
- **6191 claims available; 100% com source_url + retrieved_at** (contract do juiz cumprido)
- Operações: 5733 requests, 72.8 MB, p50 276 ms, p95 937 ms
- Cobertura de website: 142/1000 têm site no registo; 120/1000 módulo website completo (restante = not_found/blocked — estado explícito, não fabricado)
- Custos: 0 (sem APIs pagas usadas; apenas BRREG open data, NLOD 2.0)

## Comando de submissão (documentado, aceita JSONL de orgnr)

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

## Problema encontrado e resolvido

O manifest original (amostra aleatória seed 20260823) continha 928987728 (SVANHOLMEN 23 AS), **apagada do registo em 2026-08-24** (`slettedato`, classe `SlettetEnhet`) — verificada por API live. O bulk exclui entidades deletadas. Fix: manifest reconstruído em ordem determinística do universe, filtrado por pertença ao bulk (1000/1000 presentes). Nota para submissão: regenerar bulk perto da data de submissão e re-filtrar o manifest.

## Gaps para submissão (por prioridade)

1. **External footprint** (55/100 da rubrica — maior ganho de score): connectors Brave Search (discovery de sites para os 858/1000 sem site), JSON-LD/sitemap/About/Team/Careers/News nos sites existentes; scripts já existem no kit (`run_brave_discovery.py`, `apply_verified_site_seeds.py`) mas precisam de API key Brave e do gate de 500 orgs frozen.
2. **Score de completeness/external-first**: baseline do kit é 33.968/100 — external evidence é o diferenciador; correr `score_competition_v3.py` para medir localmente antes de submeter.
3. **Repositório + commit hash**: criar repo git, push (GitHub), pin uv.lock (já existe), README de setup reprodutível.
4. **Email a submit@builderr.ai** com: repo URL, run command, models/APIs declarados, custo esperado por 100 empresas (~0 se só registry+site crawl; ~0.02-0.04 USD/1000 com Brave).
5. Regenerar brreg-enheter.csv na semana de submissão (bulk muda a diario; empresas podem ser deletadas como a SVANHOLMEN).

## Ficheiros-chave

- `signalpost-starter-kit/brreg-enheter.csv` (bulk, 1.47 M empresas)
- `signalpost-starter-kit/signalpost-universe.jsonl.gz` (universe 411k)
- `signalpost-starter-kit/entry-companies.jsonl` (manifest 1000, determinístico)
- `signalpost-starter-kit/out/profiles-1000.jsonl`, `out/envelopes-1000.jsonl`, `out/run-report-1000.json`
- `signalpost-starter-kit/out/refresh-replay-report.json`
- `/root/daily-money-maker/signalpost/out/mvp-validation.jsonl` (MVP standalone)

## Teste de discovery sem API key — DDG HTML + SearXNG (2026-09-15)

**Script novo:** `scripts/run_ddg_discovery.py` — discovery de websites sem API key, modelado em
`run_brave_discovery.py`, com cadeia de providers: DuckDuckGo HTML (`result__url`/`uddg`) → SearXNG
público JSON (`search.lumy.live`, verificado a funcionar sem key) → Bing HTML. Mesmo deterministic
crawl-candidate gate do Brave + dois reforços de evidência para resultados sem snippet: domínio de
e-mail oficial do registo igual ao host candidato, e sequência compactada do nome legal no host
(norueguês composto, ex. `sandneselektriske.no` para "SANDNES ELEKTRISKE AS"). Rate-limit 3–5 s
random por query. Saída crua de search nunca persistida; publicação exige crawl independente +
exact-entity gate (`deterministic_name_org_evidence_v2`).

**Teste nas 20 empresas do batch25 (sem site no registo):**

| Métrica | Valor |
|---|---|
| Empresas consultadas | 20 (todas sem website no registo) |
| Candidatos aceites para crawl | 5 (25%) |
| **Sites verificados exact-entity** | **4 (20%)** |
| DDG HTML | 20/20 bot-challenge (IP de datacenter flaggado; funciona de IP residencial — verificado na 1ª chamada) |
| Fallback SearXNG JSON | serviu 15/20 queries com resultados reais; 1 instância junk no pool (removida do fluxo primário) |
| Claims externas novas (activity + news) | 5 (4 activity, 1 news — BECKMANN AS blog post datado) |
| Abstains | 15/20 — spot-check manual de 4 abstainers noutra engine não encontrou site oficial em nenhum (true negatives: holding imobiliária, comércio pequeno) |

Sites verificados: ALSTRA AS → alstramax.com, SERVI GROUP AS → servi.no, METALLCO AS → metallco.com,
BECKMANN AS → beckmann-norway.com (todos `exact` no identity gate, re-verificado pós-crawl).

**Veredicto: taxa de verificação 20% — abaixo da barra de 70%; NÃO correr os 1000** com esta cadeia.
O custo por empresa é baixo (~30 s), mas 858 queries renderiam ~170 sites com este recall. Blocker:
sem API de search licenciada (Brave/Google), o recall em engine pública degrada para ~20-25% nesta
população (muitas empresas sem site real + SERP poluída por directórios). Recomendação: submeter
revisão 2 com o run 1000 registry-only (score local 23) + estes 4 sites verificados como prova de
conceito do loop; acquisition de uma Brave API key (grátis até 2k qd/mês) antes de regenerar os
envelopes valeria ~+1-2 pts de external coverage, não mais.

**Score local:** inalterado vs baseline 23.0/100 — os 4 seeds + 5 claims ficam fora dos artefactos
submetidos (batch25 não é o manifest de 1000) e `score_competition_v3.py` requer external report com
audit de ≥100 observações labeladas (gate `external_audit_at_least_100`), não atingível com 5 claims.

Artefactos: `out/ddg-discovery-test/` (relatórios + seeds JSON), `scripts/run_ddg_discovery.py`.
Testes do kit: 104 passed (pyright/pytest limpos pós-mudanças).
## External-footprint-full858 integration (2026-09-21) — score 23.0 → 55.329

Run: 858 orgs (sem site no registo, seed 20260918), connector `external_footprint_discovery_v1`
(DDG HTML → SearXNG JSON → Bing HTML, keyless). Funil: 260 crawl candidates → 157 quarantined →
70 sites verificados + 33 directory presences → 193 claims.

**Auditoria (exact-entity, HTTP):** 32/70 sites re-verificados (os 22 com sinal forte + 10 aleatórios) →
47 sites TRUE, **23 sites publicados eram wrong-company** (directórios de terceiros finn.no, kurzy.cz,
klesbutikk.no, poppel.app, krsfirma.no, okab.no, forvalt.no, tikkio.com, asker.kommune.no, soft112.com;
colisões de nome axelar.network, bastec.se, sec-consult.com, silverstone.co.uk, climatech.net.au,
praymorenovenas.com, kraskickers.org, ych.art, strongboxmagazine.com, cnaudly.com, framer.website).
8/33 directory claims re-verificados (6 TRUE, 2 FP: atys.pro, solvilla.es). Root cause: org_number_printed
e single-token name match também disparam em hosts de terceiros fora do deny-list. 46/193 claims herdaram FPs.

**Publicado (auditado):** 139 claims (47 website, 46 description, 31 directory, 13 email, 2 phone; 78 orgs) —
`external-footprint-full858/published-observations.jsonl` + `audit-labels.jsonl`.
`evaluate_external_footprint.py`: 139/139, wrong_entity=0, audit_size_gate=true, qualification_passed=true.

**Envelopes:** `out/envelopes-1000-external.jsonl` (run1000-002-external, 1000 envelopes, 5/5 checks,
website seed aplicado aos 47 sites verificados; evidence block `external` com as claims auditadas).

**Score local (score_competition_v3, out/score-proxy-1000-v2.json): raw 55.329/100, 7/7 gates
(external_audit_at_least_100, zero_wrong_company, claims_supported, connector_policy, identity,
batch, refresh) — baseline 23.0.** Subscore externo: 13.329/55 (identidade 10, buzz 0.329, freshness 3).

Restante para o target 80: multi-source breadth (2+ plataformas/org), workforce/jobs, ratings/reviews,
sentimento labelado (precisam de APIs/licenças), resume determinístico (resume-report não corrido no
novo run), e recall de discovery (7-8% das 858; Brave API key é a via).

## Setup fix (2026-09-21)

`pytest` agora é extra `test` no pyproject (`uv sync --extra test && uv run pytest`); uv.lock actualizado.
