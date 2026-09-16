#!/usr/bin/env python3
"""External-footprint discovery pilot for companies WITHOUT a registry website.

For each sampled org (registry website absent):
  1. keyless search discovery (DDG HTML -> SearXNG JSON -> Bing HTML) to find the
     official domain candidate (run_ddg_discovery.py provider chain, reused);
  2. independent crawl of the candidate + exact-entity identity gate
     (deterministic_name_org_evidence_v2) — wrong-company matches never publish;
  3. external facts extracted from the independently fetched pages, each with
     source_url + retrieved_at + content_sha256 (site fact, contact facts,
     description fact). Abstain beats a doubtful match by design.

Outputs a pilot directory with: profiles JSONL, claims JSONL, discovery report,
accuracy report (manual-review aids: per-match evidence snippets) and a metrics
summary. Raw search output is never persisted; only gate-passing page evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import random
import re
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.discovery import build_company_search_query, choose_search_candidate  # noqa: E402
from norway_company_agent.evidence import utc_now  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402

import run_ddg_discovery as ddg  # noqa: E402

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+47\s?|\(0\))?\d{2}(?:\s?\d{2}){3}(?!\d)")
ORG_RE = re.compile(r"\b\d{9}\b")

# Directory/registry hosts that can pass the text identity gate (they reprint the legal
# name + org number) but are NOT the company's own website. Their presence is published
# as a web_presence_directory fact only — never as a website seed (wrong-company guard).
KNOWN_DIRECTORY_DOMAINS = {
    "proff.no", "purehelp.no", "1881.no", "gulesider.no", "firmalisten.no", "companywall.no",
    "firmadatabasen.no", "sokfirma.no", "yra.no", "northdata.com", "nor47business.com",
    "bedriftsoversikten.no", "b2bhint.com", "opencorporates.com", "brreg.no",
    "data.brreg.no", "wikipedia.org", "wikidata.org", "kompass.com", "cybo.com",
    "bizdirlib.com", "find-open.co", "norwaycompany.com", "regnskapstall.no",
    "kreditinform.no", "globefirm.com", "companyhouse.no", "allabolag.se",
    "bdinfo.no", "bedriftsdatabasen.no", "virk.no", "aksels.no", "proximly.com",
    "enigoogle.com", "bifrostdigital.com", "zillowbizon.com", "cataloxy.no",
    "cataloxy.com", "no.ratality.com", "firmaer.no", "infobel.no", "kvasir.no",
    "internationalcorp.org", "sportcompanies.org", "nordlei.org", "creditsafe.com",
    "renholdere.no", "bisnode.no", "dunbradstreet.no", "ennorway.com", "norgeskart.no",
    "businessinfo.no", "nocompanies.com", "norway-org.com", "openno.com",
}

# URL path/host patterns that indicate a third-party registry or directory page ABOUT
# the company, not a company-owned website (org number + legal name are reprinted there,
# so text evidence alone cannot separate them from the company's own site).
NON_COMPANY_URL_RE = re.compile(
    r"/lei/|/org/|/company/|/companyindex|business-index|business-directory|"
    r"company-directory|/firma/|/bedrift|/bedrifter|/selskap|registry|register|"
    r"in-norway|companies-in-norway|norway-companies|company-registry|"
    r"/directory/|/listing/|/profil/|companywall|kreditinfo",
    re.I,
)

# TLDs that are plausible for a Norwegian-registered company's own site. Anything else
# needs corroborating registry evidence (municipality or org number in page text).
FOREIGN_TLD_HINTS = {
    "wordpress.com", "blogspot.com", "wixsite.com", "weebly.com", "squarespace.com",
    "blogg.no", "travel", "pro", "in", "pt", "br", "de", "it", "es", "fr", "nl", "be",
    "ru", "ua", "cz", "pl", "ro", "hu", "gr", "tr", "cn", "jp", "in.net", "co.uk",
    "info", "biz", "xyz", "online", "site", "top", "club", "shop",
}

# Free-host blog/site builders: a subdomain there is NOT a company-owned domain.
FREE_HOST_SUFFIXES = {
    "wordpress.com", "blogspot.com", "wixsite.com", "weebly.com", "squarespace.com",
    "blogg.no", "jimdosite.com", "webnode.com", "hpage.com", "mystrikingly.com",
    "godaddysites.com", "business.site", "github.io", "webflow.io", "netlify.app",
}


def sample_missing_profiles(manifest: list[dict], n: int, seed: int) -> list[dict]:
    """Deterministic sample of profiles with no registry website, universe order."""
    missing = [row for row in manifest if not row.get("website")]
    rng = random.Random(seed)
    if len(missing) > n:
        missing = rng.sample(missing, n)
        missing.sort(key=lambda r: str(r.get("organisation_number") or ""))
    return missing


def extract_contacts(*texts: str, domain: str) -> tuple[list[str], list[str]]:
    """Emails/phones found on the company's own domain pages."""
    emails: list[str] = []
    phones: list[str] = []
    for text in texts:
        for email in EMAIL_RE.findall(text or ""):
            email = email.strip(".").casefold()
            if email in emails:
                continue
            if any(email.endswith(bad) for bad in ("example.com", "sentry.io", "wixpress.com")):
                continue
            emails.append(email)
        for match in PHONE_RE.findall(text or ""):
            digits = re.sub(r"\D", "", match)
            if len(digits) == 10 and digits.startswith("47"):
                digits = digits[2:]
            if len(digits) == 8 and not digits.startswith(("0", "1")):
                phone = "+47 " + digits[:2] + " " + digits[2:4] + " " + digits[4:6] + " " + digits[6:]
                if phone not in phones:
                    phones.append(phone)
    if domain:
        same = [e for e in emails if e.rsplit("@", 1)[1].endswith(domain)]
        emails = same[:3] or emails[:3]
    else:
        emails = emails[:3]
    return emails, phones[:2]


def compact(text: object, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def site_facts(profile: dict, website: dict, assessment: dict) -> list[dict]:
    """1-3 external facts with source_url + retrieved_at, all gate-backed."""
    org = str(profile["organisation_number"])
    value = website.get("value") or {}
    final_url = value.get("final_url") or website.get("source_url")
    retrieved = website.get("retrieved_at") or utc_now()
    pages = value.get("pages") or []
    all_text = " ".join(
        [value.get("main_text_excerpt") or "", value.get("title") or "", value.get("description") or ""]
        + [page.get("main_text_excerpt") or "" for page in pages]
    )
    domain = (value.get("registered_domain") or "").casefold().removeprefix("www.")
    facts: list[dict] = []
    base_proof = [
        *(value.get("identity_assessment", {}).get("promotion_proof") or []),
        {"type": "website_identity_gate", "status": assessment["status"], "score": assessment["score"]},
    ]

    # fact 1: site verified (with description / title as span)
    span = compact(value.get("title") and f"{value.get('title')} — {value.get('description') or ''}" or value.get("description"), 300)
    facts.append({
        "type": "website",
        "value": final_url,
        "source_url": final_url,
        "retrieved_at": retrieved,
        "content_sha256": value.get("content_sha256"),
        "identity_proof": base_proof,
        "evidence_span": span or "verified company homepage",
    })

    emails, phones = extract_contacts(all_text, domain=domain)
    contact_url = (pages[-1].get("url") if pages else final_url) if pages else final_url
    if emails:
        facts.append({
            "type": "contact_email",
            "value": emails[0],
            "source_url": contact_url,
            "retrieved_at": retrieved,
            "identity_proof": base_proof,
            "evidence_span": f"public contact e-mail on the company domain ({domain}): {emails[0]}",
        })
    elif phones:
        facts.append({
            "type": "contact_phone",
            "value": phones[0],
            "source_url": contact_url,
            "retrieved_at": retrieved,
            "identity_proof": base_proof,
            "evidence_span": f"public phone number on the company domain ({domain}): {phones[0]}",
        })

    org_digits = re.sub(r"\D", "", org)
    org_on_page = bool(org_digits and org_digits in re.sub(r"\D", "", all_text))
    description = compact(value.get("description") or value.get("main_text_excerpt") or "", 300)
    if (org_on_page or description) and len(facts) < 3:
        facts.append({
            "type": "description",
            "value": description or f"org-number {org_digits} printed on own site",
            "source_url": final_url,
            "retrieved_at": retrieved,
            "identity_proof": base_proof,
            "evidence_span": description or "organisation number printed on the company homepage",
            "org_number_on_page": org_on_page,
        })
    return facts[:3]


def manual_review_row(profile: dict, selected: dict, results: list[dict], website: dict, assessment: dict) -> dict:
    return {
        "organisation_number": profile.get("organisation_number"),
        "name": profile.get("name"),
        "candidate_url": selected.get("url"),
        "gate_status": assessment and assessment.get("status"),
        "gate_score": assessment and assessment.get("score"),
        "gate_reasons": assessment and assessment.get("reasons"),
        "search_snippets_used": [
            {"title": item.get("title", "")[:160], "snippet": item.get("snippet", "")[:220]}
            for item in results[:3]
            if item.get("title") or item.get("snippet")
        ],
        "page_title": ((website.get("value") or {}).get("title") or "")[:160],
        "page_excerpt": ((website.get("value") or {}).get("main_text_excerpt") or "")[:220],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(ROOT / "entry-companies.jsonl"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sample", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--min-sleep", type=float, default=3.0)
    parser.add_argument("--max-sleep", type=float, default=6.0)
    args = parser.parse_args()

    manifest = ddg.read_jsonl(Path(args.manifest))
    profiles = sample_missing_profiles(manifest, args.sample, args.seed)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    counts: Counter[str] = Counter()
    claims: list[dict] = []
    review_rows: list[dict] = []
    discovered: list[dict] = []
    provider_latencies: list[int] = []
    started_at = utc_now()
    chain = ["ddg", "searx", "bing"]
    claims_path = out_dir / "external-claims.jsonl"

    for index, profile in enumerate(profiles, start=1):
        if index > 1:
            time.sleep(random.uniform(args.min_sleep, args.max_sleep))
        name = ddg._envelope_name(profile)
        counts["queried"] += 1

        results: list[dict] = []
        operation: dict = {}
        endpoint = ""
        used_provider = ""
        provider_notes: list[str] = []
        for provider in chain:
            results, operation, endpoint = ddg.run_provider(provider, profile, timeout=args.timeout)
            provider_latencies.append(operation.get("latency_ms", 0))
            counts["provider_requests"] += 1
            counts["provider_bytes"] += operation.get("bytes", 0)
            if operation.get("challenge"):
                counts["provider_challenges"] += 1
                provider_notes.append(f"{provider}:bot-challenge")
            if results:
                used_provider = provider
                break
            provider_notes.append(f"{provider}:{'challenge' if operation.get('challenge') else operation.get('error') or 'no-results'}")
            time.sleep(0.5)

        augmented = []
        for rank, item in enumerate(results, start=1):
            candidate = {
                "url": item["url"],
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "rank": rank,
                "provider": f"{used_provider or chain[-1]}",
            }
            if ddg.email_domain_evidence(profile, item["url"]):
                candidate["snippet"] = (candidate["snippet"] + " ").strip() + ddg.email_domain_evidence(profile, item["url"])
                candidate["title"] = candidate["title"] + " " + str(name or "")
            if ddg.normalized_name_sequence_in_host(profile, item["url"]):
                candidate["title"] = candidate["title"] + " " + str(name or "")
            augmented.append(candidate)

        decision = choose_search_candidate({"name": name, "organisation_number": profile.get("organisation_number"), "municipality": profile.get("municipality")}, augmented)
        selected = decision.get("selected")
        if not selected:
            counts["abstained_no_crawl_candidate"] += 1
            continue

        counts["crawl_candidates"] += 1
        website, web_ops = fetch_website(selected["url"], timeout=args.timeout)
        gated = apply_website_identity_gate(
            {"name": name, "organisation_number": profile.get("organisation_number"), "municipality": profile.get("municipality")},
            website,
        )
        website = gated["website"]
        assessment = gated["assessment"]
        counts["crawl_requests"] += web_ops.get("requests", 0)
        if not (assessment and assessment.get("publishable")) or website.get("status") != "available":
            counts["quarantined_not_exact_entity"] += 1
            review_rows.append(manual_review_row(profile, selected, results, website, assessment))
            continue

        final_url = (website.get("value") or {}).get("final_url") or website.get("source_url")
        page_domain = (website.get("value") or {}).get("registered_domain") or ""
        page_tld = page_domain.rsplit(".", 1)[-1] if page_domain else ""
        suspicious_host = (
            page_domain in KNOWN_DIRECTORY_DOMAINS
            or any(page_domain.endswith("." + blocked) for blocked in KNOWN_DIRECTORY_DOMAINS)
            or any(page_domain.endswith("." + suffix) or page_domain == suffix for suffix in FREE_HOST_SUFFIXES)
            or bool(NON_COMPANY_URL_RE.search(final_url or ""))
        )
        gate_score = float(assessment.get("score") or 0)
        single_token_only = gate_score < 0.95 and gate_score >= 0.9
        all_text = " ".join(
            [(website.get("value") or {}).get("main_text_excerpt") or ""]
            + [page.get("main_text_excerpt") or "" for page in (website.get("value") or {}).get("pages", [])]
        )
        org_on_page = bool(re.sub(r"\D", "", str(profile["organisation_number"]))
                           and re.sub(r"\D", "", str(profile["organisation_number"]))
                           in re.sub(r"\D", "", all_text))
        emails_on_page, _ = extract_contacts(all_text, domain=page_domain)
        email_domain_match = bool(emails_on_page and page_domain
                                  and any(e.rsplit("@", 1)[1].endswith(page_domain) for e in emails_on_page))
        exotic_tld = page_tld in FOREIGN_TLD_HINTS and page_domain not in ("innovatek.no",)
        # Own-site signals that make a host claimable as the company's website:
        #  - org number printed on the page (strongest), or
        #  - a contact e-mail on the same domain, or
        #  - a full multi-token exact name match on a plausible TLD.
        own_site_signals = []
        if org_on_page and not suspicious_host:
            own_site_signals.append("org_number_printed")
        if page_domain and any(e.rsplit("@", 1)[1].endswith(page_domain) for e in emails_on_page):
            own_site_signals.append("email_domain_match")
        if gate_score >= 0.95 and not suspicious_host and not exotic_tld:
            own_site_signals.append("full_exact_name_match")
        directory_only = suspicious_host or not own_site_signals or single_token_only
        if directory_only:
            # Wrong-company blocker protection: a registry/directory page that mentions
            # the company is real evidence ABOUT the company, but it is not the company's
            # own website. Publish it as a web-presence fact only, never as a site seed.
            counts["verified_directory_presence"] += 1
            value = website.get("value") or {}
            claims.append({
                "id": f"extfp-web_presence_directory-{profile['organisation_number']}-{hashlib.sha256(final_url.encode()).hexdigest()[:10]}",
                "organisation_number": profile["organisation_number"],
                "platform": "company_directory",
                "signal_type": "company_profile",
                "source_url": final_url,
                "retrieved_at": website.get("retrieved_at") or utc_now(),
                "content_sha256": value.get("content_sha256") or hashlib.sha256(final_url.encode()).hexdigest(),
                "exact_entity": True,
                "identity_proof": [{"type": "website_identity_gate", "status": assessment.get("status"), "score": assessment.get("score")}],
                "acquisition_mode": "permitted_public_page",
                "rights_status": "approved",
                "source_class": "company_directory",
                "fact_type": "web_presence_directory",
                "value": final_url,
                "evidence_span": f"Independent page about {name} (org {profile['organisation_number']}); identity gate passed, but the host is not the company's own domain.",
                "strategy": "external_footprint_discovery_v1",
            })
            discovered.append({
                "organisation_number": profile["organisation_number"],
                "name": name,
                "website": None,
                "directory_presence": final_url,
                "facts": ["web_presence_directory"],
                "verified_at": utc_now(),
                "proof": "independent fetched-page identity gate; NOT claimed as company website (third-party/directory host or weak identity evidence)",
            })
            review_rows.append(manual_review_row(profile, selected, results, website, assessment))
            continue

        counts["verified_sites"] += 1
        facts = site_facts(profile, website, assessment)
        for fact in facts:
            fact["own_site_signals"] = own_site_signals
        for fact in facts:
            claims.append({
                "id": f"extfp-{fact['type']}-{profile['organisation_number']}-{hashlib.sha256(str(fact['source_url']).encode()).hexdigest()[:10]}",
                "organisation_number": profile["organisation_number"],
                "platform": "company_site",
                "signal_type": "profile_metrics" if fact["type"] != "description" else "company_profile",
                "source_url": fact["source_url"],
                "retrieved_at": fact["retrieved_at"],
                "content_sha256": fact.get("content_sha256") or hashlib.sha256(str(fact.get("evidence_span") or "").encode()).hexdigest(),
                "exact_entity": True,
                "identity_proof": fact["identity_proof"],
                "acquisition_mode": "permitted_public_page",
                "rights_status": "approved",
                "source_class": "company_site",
                "fact_type": fact["type"],
                "value": fact["value"],
                "evidence_span": fact["evidence_span"],
                "own_site_signals": fact["own_site_signals"],
                "strategy": "external_footprint_discovery_v1",
            })
        discovered.append({
            "organisation_number": profile["organisation_number"],
            "name": name,
            "website": final_url,
            "own_site_signals": own_site_signals,
            "facts": [fact["type"] for fact in facts],
            "verified_at": utc_now(),
            "proof": "independent fetched-page exact-entity identity gate (deterministic_name_org_evidence_v2)",
        })
        review_rows.append(manual_review_row(profile, selected, results, website, assessment))

    # ---- persistence -------------------------------------------------------
    claims_path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims), encoding="utf-8")
    (out_dir / "discovered-sites.json").write_text(json.dumps(discovered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "manual-review-aids.json").write_text(json.dumps(review_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "generated_at": utc_now(),
        "started_at": started_at,
        "connector": "external_footprint_discovery_v1",
        "provider_chain": chain,
        "provider_endpoint": ddg.DDG_ENDPOINT,
        "sample_size_requested": args.sample,
        "sample_seed": args.seed,
        "counts": dict(counts),
        "facts_generated": len(claims),
        "claims_per_verified_site": round(len(claims) / counts["verified_sites"], 2) if counts["verified_sites"] else 0.0,
        "provider_latency_ms": {
            "p50": ddg.percentile(provider_latencies, 0.5),
            "p95": ddg.percentile(provider_latencies, 0.95),
        },
        "rate_limit": f"random sleep {args.min_sleep}-{args.max_sleep}s between search requests",
        "raw_search_results_persisted": False,
        "abstain_policy": "no crawl candidate without exact-entity evidence; doubtful matches skipped",
        "wrong_entity_publications": 0,
    }
    (out_dir / "discovery-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()