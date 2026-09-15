#!/usr/bin/env python3
"""Transient keyless web-search discovery followed by independent exact-entity site crawling.

Modelled on run_brave_discovery.py, but needs no API key. Provider chain:

  1. ddg    — DuckDuckGo HTML (html.duckduckgo.com/html), result__url anchors and
              uddg redirect targets. The endpoint rate-limits datacenter IPs with
              a bot-challenge page; a challenge is counted explicitly and the
              run falls through to the next provider.
  2. searx  — public SearXNG instances with the JSON API enabled
              (search.lumy.live verified working; others in SEARX_FALLBACKS).
              No key, public instances, generous random pacing.
  3. bing   — Bing HTML organic results (b_algo blocks, ck/a base64 redirect).

All providers get the same deterministic crawl-candidate gate (choose_search_candidate)
used for Brave, with an explicit blocked-directory filter, and only independently
fetched page evidence that passes the exact-entity identity gate is retained.
Raw search output (titles, snippets, URLs, queries) is never persisted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html as html_mod
import http.client
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.discovery import build_company_search_query, choose_search_candidate  # noqa: E402
from norway_company_agent.evidence import evidence, utc_now  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402
from norway_company_agent.identity import _tokens as identity_tokens  # noqa: E402


def email_domain_evidence(row: dict, url: str) -> str | None:
    """Official registry e-mail domain matching the candidate host is exact-entity evidence.

    Used only as crawl-candidate evidence for keyless providers whose results carry
    no snippets; publication still requires the fetched-page identity gate.
    """
    claims = row.get("claims")
    if not isinstance(claims, dict):
        return None
    contact = claims.get("official_contact")
    if not isinstance(contact, dict):
        return None
    value = contact.get("value")
    if not isinstance(value, dict):
        return None
    email = str(value.get("epostadresse") or "")
    if "@" not in email:
        return None
    email_domain = email.rsplit("@", 1)[1].strip().casefold().removeprefix("www.")
    parsed = urllib.parse.urlparse(str(url or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if not email_domain or not host:
        return None
    return email_domain if email_domain == host else None


def normalized_name_sequence_in_host(row: dict, url: str) -> bool:
    """True when the compacted legal-name token sequence appears in the compacted host.

    Handles Norwegian compound hostname spellings (sandneselektriske.no for
    "SANDNES ELEKTRISKE AS") that the per-token name_in_host rule misses.
    """
    name = _envelope_name(row)
    tokens = [t for t in identity_tokens(name) if len(t) > 1]
    if len(tokens) < 2:
        return False
    parsed = urllib.parse.urlparse(str(url or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    host_compact = "".join(identity_tokens(host))
    name_compact = "".join(tokens)
    return bool(name_compact) and name_compact in host_compact


DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
BING_ENDPOINT = "https://www.bing.com/search"
SEARX_ENDPOINTS = [
    "https://search.lumy.live/",
    "https://sx.xo.st/",
]
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]
DDG_CHALLENGE_MARKERS = ("challenge", "unfortunately, bots use duckduckgo too")


def _envelope_name(row: dict) -> str:
    """Legal name from either a batch profile row or a terminal envelope row."""
    name = str(row.get("name") or "").strip()
    if name:
        return name
    claims = row.get("claims")
    if not isinstance(claims, dict):
        return ""
    identity = claims.get("legal_identity")
    if not isinstance(identity, dict):
        return ""
    value = identity.get("value")
    if not isinstance(value, dict):
        return ""
    return str(value.get("name") or "").strip()


def discovery_profile(row: dict) -> dict:
    return {
        "name": _envelope_name(row),
        "organisation_number": row.get("organisation_number"),
        "municipality": row.get("municipality"),
    }


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def _http_get(url: str, *, timeout: float, accept: str = "text/html,application/xhtml+xml") -> tuple[str, int, int]:
    request = urllib.request.Request(url, headers={
        "Accept": accept,
        "Accept-Encoding": "identity",
        "User-Agent": random.choice(USER_AGENTS),
    })
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace"), response.status, int((time.monotonic() - started) * 1000)


# ---------------------------------------------------------------- DDG HTML ----

def parse_ddg_html(page: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for raw in re.findall(r'class="result__url"[^>]*>\s*([^\s<]+)', page):
        url = html_mod.unescape(raw.strip())
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            results.append({"url": url})
    for raw in re.findall(r"uddg=([^&\"']+)", page):
        url = urllib.parse.unquote(raw)
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            results.append({"url": url})
    return results


def ddg_search(profile: dict, *, timeout: float) -> tuple[list[dict], dict]:
    query = build_company_search_query(discovery_profile(profile)) + " norge"
    url = DDG_ENDPOINT + "?" + urllib.parse.urlencode({"q": query})
    started = time.monotonic()
    try:
        page, status, elapsed_ms = _http_get(url, timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, http.client.RemoteDisconnected) as exc:
        return [], {
            "status": getattr(exc, "code", 0),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": type(exc).__name__,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "challenge": False,
        }
    lowered = page.lower()
    challenged = any(marker in lowered for marker in DDG_CHALLENGE_MARKERS)
    results = [] if challenged else parse_ddg_html(page)
    return results, {
        "status": status,
        "latency_ms": elapsed_ms,
        "bytes": len(page),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "challenge": challenged,
    }


# ------------------------------------------------------------- SearXNG JSON ----

def parse_searx_json(payload: bytes) -> list[dict]:
    data = json.loads(payload)
    results = []
    for item in data.get("results", []):
        url = str(item.get("url") or "")
        if url.startswith(("http://", "https://")):
            results.append({"url": url, "title": str(item.get("title") or ""), "snippet": str(item.get("content") or "")})
    return results


def searx_search(profile: dict, *, timeout: float) -> tuple[list[dict], dict, str]:
    query = build_company_search_query(discovery_profile(profile)) + " norge"
    errors: list[str] = []
    endpoints = SEARX_ENDPOINTS[:]
    started = time.monotonic()
    last_elapsed = 0
    for endpoint in endpoints:
        url = endpoint + "search?" + urllib.parse.urlencode({"q": query, "format": "json", "language": "nb"})
        started = time.monotonic()
        try:
            request = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": random.choice(USER_AGENTS),
            })
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            return parse_searx_json(raw), {
                "status": response.status,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "bytes": len(raw),
                "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "instance": endpoint,
            }, endpoint
        except Exception as exc:  # instance down/rate-limited: try the next one
            errors.append(f"{endpoint}: {type(exc).__name__}: {str(exc)[:80]}")
            last_elapsed = int((time.monotonic() - started) * 1000)
            time.sleep(1.0)
    return [], {
        "status": 0,
        "latency_ms": last_elapsed if endpoints else 0,
        "bytes": 0,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "error": "all_searx_instances_failed",
        "instance_errors": errors,
    }, "searx_json"


# ---------------------------------------------------------------- Bing HTML ----

def _decode_bing_redirect(href: str) -> str:
    match = re.search(r"[?&]u=a1([^&]+)", href)
    if match:
        padded = match.group(1)
        padded += "=" * (-len(padded) % 4)
        try:
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return html_mod.unescape(href)


def parse_bing_html(page: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        match = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"', block)
        if not match:
            continue
        url = _decode_bing_redirect(html_mod.unescape(match.group(1)))
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            results.append({"url": url})
    return results


def bing_search(profile: dict, *, timeout: float) -> tuple[list[dict], dict]:
    query = build_company_search_query(discovery_profile(profile)) + " norge"
    url = BING_ENDPOINT + "?" + urllib.parse.urlencode({"q": query, "cc": "no", "setlang": "en"})
    started = time.monotonic()
    try:
        page, status, elapsed_ms = _http_get(url, timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, http.client.RemoteDisconnected) as exc:
        return [], {
            "status": getattr(exc, "code", 0),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": type(exc).__name__,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        }
    return parse_bing_html(page), {
        "status": status,
        "latency_ms": elapsed_ms,
        "bytes": len(page),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
    }


# ------------------------------------------------------------------ driver ----

PROVIDERS = {
    "ddg": ("DuckDuckGo HTML", DDG_ENDPOINT),
    "searx": ("SearXNG public JSON", "https://search.lumy.live/"),
    "bing": ("Bing HTML", BING_ENDPOINT),
}


def run_provider(provider: str, profile: dict, *, timeout: float) -> tuple[list[dict], dict, str]:
    if provider == "ddg":
        results, operation = ddg_search(profile, timeout=timeout)
        return results, operation, DDG_ENDPOINT
    if provider == "searx":
        return searx_search(profile, timeout=timeout)
    results, operation = bing_search(profile, timeout=timeout)
    return results, operation, BING_ENDPOINT


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transient keyless search-engine discovery followed by independent exact-entity site crawling."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--provider", choices=list(PROVIDERS), default="ddg",
                        help="Search provider. ddg: DuckDuckGo HTML; searx: public SearXNG JSON; bing: Bing HTML.")
    parser.add_argument("--fallbacks", default="",
                        help="Comma-separated providers tried when the primary returns no candidates or fails (e.g. 'searx,bing')")
    parser.add_argument("--limit", type=int, default=25, help="Maximum missing-website profiles to query")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--min-sleep", type=float, default=2.0, help="Minimum seconds between search requests")
    parser.add_argument("--max-sleep", type=float, default=5.0, help="Maximum seconds between search requests")
    parser.add_argument("--promote-verified", action="store_true", help="Copy exact-entity discovered sites into canonical website evidence")
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_sleep < args.min_sleep:
        parser.error("--max-sleep must be >= --min-sleep")
    chain = [args.provider] + [p.strip() for p in args.fallbacks.split(",") if p.strip() in PROVIDERS]
    chain = list(dict.fromkeys(chain))

    rows = read_jsonl(Path(args.input))
    counts: Counter[str] = Counter()
    provider_latencies: list[int] = []
    started_at = utc_now()
    queried = 0
    for row in rows:
        if queried >= args.limit:
            break
        if row.get("website"):
            counts["registry_website_present_skipped"] += 1
            continue
        queried += 1
        if queried > 1:
            time.sleep(random.uniform(args.min_sleep, args.max_sleep))

        results: list[dict] = []
        operation: dict = {}
        endpoint = ""
        used_provider = ""
        provider_notes: list[str] = []
        for provider in chain:
            results, operation, endpoint = run_provider(provider, row, timeout=args.timeout)
            provider_latencies.append(operation.get("latency_ms", 0))
            counts["provider_requests"] += 1
            counts["provider_bytes"] += operation.get("bytes", 0)
            if operation.get("error"):
                counts["provider_errors"] += 1
            if operation.get("challenge"):
                counts["provider_challenges"] += 1
                provider_notes.append(f"{provider}:bot-challenge")
            if results:
                used_provider = provider
                break
            provider_notes.append(f"{provider}:{'challenge' if operation.get('challenge') else operation.get('error') or 'no-results'}")
            if isinstance(row.get("evidence"), dict):
                row.setdefault("evidence", {})

        # Keyless providers may return the exact company site without snippet
        # evidence (compound hostnames, org-number directories outranking it).
        # Registry e-mail domain and normalized name-sequence host matches are
        # promoted to crawl-candidate evidence; publication still requires the
        # independent fetched-page exact-entity identity gate.
        augmented = []
        for rank, item in enumerate(results, start=1):
            candidate = {
                "url": item["url"],
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "rank": rank,
                "provider": f"{used_provider or chain[-1]}_html",
            }
            if email_domain_evidence(row, item["url"]):
                candidate["snippet"] = (candidate["snippet"] + " ").strip() + email_domain_evidence(row, item["url"])
                candidate["title"] = candidate["title"] + " " + str(_envelope_name(row) or "")
            if normalized_name_sequence_in_host(row, item["url"]):
                candidate["title"] = candidate["title"] + " " + str(_envelope_name(row) or "")
            augmented.append(candidate)
        decision = choose_search_candidate(discovery_profile(row), augmented)
        selected = decision.get("selected")
        discovery_summary = {
            "provider": (used_provider or chain[-1]) + "_html",
            "provider_chain": chain,
            "provider_notes": provider_notes,
            "query_sha256": operation.get("query_sha256"),
            "candidate_count": len(results),
            "selected_for_independent_crawl": bool(selected),
            "provider_status": operation.get("status"),
            "provider_challenge": bool(operation.get("challenge")),
            "retention_policy": "Search titles, snippets, ranks, query text, and raw response are not persisted.",
        }
        if not selected:
            counts["abstained_before_crawl"] += 1
            if isinstance(row.get("evidence"), dict):
                row["evidence"]["website_discovery"] = evidence(
                    "website_discovery",
                    "not_found",
                    "transient_keyless_search",
                    endpoint or DDG_ENDPOINT,
                    value=discovery_summary,
                    note="No result passed the deterministic crawl-candidate gate; raw search output was discarded.",
                )
            continue

        website, web_ops = fetch_website(selected["url"], timeout=args.timeout)
        gated = apply_website_identity_gate(discovery_profile(row), website)
        website = gated["website"]
        assessment = gated["assessment"]
        website["source_type"] = "search_discovered_company_website"
        website["value"] = website.get("value") or {}
        if isinstance(row.get("evidence"), dict):
            row["evidence"]["website_discovery"] = evidence(
                "website_discovery",
                "available" if assessment["publishable"] else "not_found",
                "transient_keyless_search_then_independent_crawl",
                endpoint,
                value={**discovery_summary, "independent_page_url": website.get("source_url") if assessment["publishable"] else None},
                note="Search output was transient. Publication depends only on independently fetched exact-entity page evidence.",
            )
            row["evidence"]["website_discovered"] = website
        counts["independent_crawls"] += 1
        counts["crawl_requests"] += web_ops.get("requests", 0)
        if assessment["publishable"] and website.get("status") == "available":
            counts["verified_sites"] += 1
            if args.promote_verified:
                row["website"] = website.get("source_url")
                row["website_seed_source"] = "independently_verified_exact_entity"
                row["website_seed_proof"] = {
                    "proof_url": website.get("source_url"),
                    "proof": "independent fetched-page exact-entity identity gate (deterministic_name_org_evidence_v2)",
                }
                if isinstance(row.get("evidence"), dict):
                    row["evidence"]["website"] = website
                counts["promoted_sites"] += 1
        else:
            counts["quarantined_sites"] += 1

    write_jsonl(Path(args.output), rows)
    report = {
        "generated_at": utc_now(),
        "started_at": started_at,
        "provider": args.provider,
        "provider_chain": chain,
        "provider_endpoint": PROVIDERS[args.provider][1],
        "input_profiles": len(rows),
        "queried_missing_website_profiles": queried,
        "counts": dict(counts),
        "provider_latency_ms": {"p50": percentile(provider_latencies, 0.5), "p95": percentile(provider_latencies, 0.95)},
        "rate_limit": f"random sleep {args.min_sleep}-{args.max_sleep}s between search requests",
        "raw_search_results_persisted": False,
        "promote_verified_enabled": args.promote_verified,
        "qualification": "not_evaluated_on_500_org_external_final_corpus",
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()