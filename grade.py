#!/usr/bin/env python3
"""Grader for the research-agents eval: adjudicated truth, per-cell grades, tallies, CIs.

Inputs: every records/*.json under the --runs folders (default: the published Exa, nested Parallel and
Claygent run folders), the blind gold sheets in --gold when that folder exists (one CSV per domain, graded
as the config "human-blind"), bands from --csv. One cell per (domain, field); the candidates of a cell are
every config's answer plus the human's.

Truth per cell (union of evidence). Default mode:
  1. Group the asserted candidates by value under the field's match rule. Cells where at least two
     searchers asserted, all agree, nobody asserted a different value, and the mechanical citation check
     passes for the agreed value are AUTO-ACCEPTED: truth = that value, provenance consensus, every
     asserting candidate correct, unknowns honest-unknown. A seeded --audit-sample fraction of them is
     adjudicated anyway and the agreement rate is reported beside the auto-accept rate. Cells where every
     searcher said unknown are unfindable by consensus (nothing to inspect). product_one_liner is always
     adjudicated (semantic match is the LLM's job). --adjudicate-all skips the auto-accept.
  2. Every other cell goes to the LLM adjudicator: Anthropic Messages API over stdlib HTTPS
     (POST https://api.anthropic.com/v1/messages, x-api-key, anthropic-version 2023-06-01; model
     --adjudicator-model, default claude-opus-5-5; thinking adaptive; output_config json_schema + effort
     high; the rules as one cached system block). It sees the rules in grading_rules.md (read at runtime;
     the sha256 of that text is stored with every verdict), the candidates with config ids MASKED to
     letters in a per-cell shuffled order (the letters are the only mask: values, notes and page text
     reach the judge as written), and the text of every cited page from its saved copy, whole when it is
     short and as passages with search lines when it is long. It returns truth (status, value, URL, provenance, reason,
     confidence, needs_human) and a grade, support and failure tag per candidate. Verdicts are cached in
     <out>/adjudications.jsonl keyed by (domain, field, candidates), so reruns never re-spend.
  --no-llm --truth <csv>: truth and grades come from the file (a recorded adjudication as data); no network.
     The mechanical matcher runs on the same cells and every cell where it differs from the recorded grade
     is listed with the reason.

Citation check (mechanical): each cited URL is fetched once and cached (<out>/pages/<sha1>.json,
reusing runs/<name>/snapshots/ from snapshot.py when present): urllib with a browser UA, then Firecrawl v2
(1 credit), then the Wayback copy closest to the run date. Pass = status < 400 and, for string, list,
year and location values, the page text carries the value's key tokens (any customer name, the year, the
city, a provider token); bools, bands, funding and the one-liner pass on status alone.
grading/judge_pages/ holds the pages the published judge read from its own store, read before snapshots/ as it did.
Withheld pages (withheld_sources.txt) keep their metadata but not their text: on the judge path a candidate
citing one keeps its published grade from grading/cells.csv when its answer is unchanged (support "withheld").

Grades (truth known): unknown -> unknown (honest unknown, never wrong); asserted, value matches
and page supports it -> correct; matches but the page does not support it -> wrong:miscitation; does not
match -> wrong with the adjudicator's tag. Truth unfindable: unknown -> correct (abstention success),
asserted -> wrong (the wrong-confident failure; tag overclaim unless another fits). `gap` exists only in
--no-llm mode (a truth file can leave a cell as a rule gap).

Field match rules (mechanical; the adjudicator's cross-check): product_one_liner asserted = correct; bools
exact; named_customers at least 2 asserted names in the truth set (case-insensitive, containment either
way); employee_band within one band; hq_location country equal after normalizing (US / USA / United
States, UK, FR; US states -> United States) and city equal or in the truth's alternates; founded_year equal
to any truth year; model_provider any truth token in the value; compliance_certs every
asserted cert in the truth set after normalizing (SOC 2 Type II -> SOC 2), an extra = wrong, an
asserted empty list = the claim "none", graded like any claim; last_funding "none" vs object,
then stage, date and amount as sub-cells: stage equal (skipped when the truth stage is null),
date equal at YYYY-MM (a missing candidate date is an unmatched sub-cell, never an unknown),
amount within 10% (skipped when either is null); crm_stack_signal every asserted system in
the 12-list and in the truth set; raised_18mo, hiring_sdr_ae, launched_6mo,
leadership_change_12mo exact bools.

Outputs in --out (default grading/rerun, so a rerun never overwrites the published grading/truth.csv and
grading/cells.csv): truth.csv, cells.csv, tallies.csv (per config x band | pooled | equal_weighted: n_cells,
answerable, correct, wrong, unknown, gap, accuracy, Wilson 95%, yield, trust, hallucination_rate,
wrong_confident_rate, abstention_rate, all17_companies, cost_mean, usd_per_1k, latency_median),
knob_delta.csv (B minus A in pp on paired companies, McNemar exact on discordant cells), disputes.csv,
metrics.json, report.md (headline first, metric definitions at the top); --no-llm adds matcher_diffs.csv.

Spend gate: the plan prints the cells to adjudicate x --est-cell-input/--est-cell-output at $4 / $20 per
MTok (cache read $0.20) and the all-cells upper bound, plus the URLs to fetch and the Firecrawl worst case;
nothing is called without --yes. --no-llm never touches the network. Keys: ANTHROPIC_API_KEY and, for the
Firecrawl fallback, FIRECRAWL_API_KEY, from the environment or the repo-root .env.

Usage:
  python3 grade.py                                   # plan for the published run folders: cells, URLs, worst case
  python3 grade.py --yes                             # fetch, auto-accept, adjudicate, write grading/rerun/
  python3 grade.py --no-llm --truth grading/truth.csv --out grading/rerun-mechanical
                                                     # mechanical grades against the published truth, no network
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import brief_task
import eval_common as ec
import score_views
import snapshot as snap

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(HERE, "grading_rules.md")
DEFAULT_RUNS = ["runs/2026-11-10-v1-exa", "runs/2026-11-10-v1-nested-parallel", "runs/2026-11-10-v1-claygent"]
DEFAULT_OUT = "grading/rerun"
JUDGE_PAGES = os.path.join(HERE, "grading", "judge_pages")
PUBLISHED_CELLS = os.path.join(HERE, "grading", "cells.csv")
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
ADJ_MODEL_DEFAULT = "claude-opus-5-5"
# USD per MTok: input, output, cache read, cache write (platform.claude.com pricing, Nov 8, 2026)
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.20, 5.00), "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.50),
          "claude-fable-5-1": (10.0, 50.0, 1.00, 12.50)}
HUMAN = "human-blind"
BANDS = list(brief_task.BANDS)
KINDS = {fid: kind for fid, kind, _ in brief_task.FIELDS}
QUESTIONS = {fid: q for fid, _, q in brief_task.FIELDS}
FIELDS = list(brief_task.FIELD_IDS)
CRM_SYSTEMS = ["Salesforce", "HubSpot", "Pipedrive", "Outreach", "Salesloft", "Apollo", "Gong", "Marketo", "Pardot",
               "Intercom", "Zendesk", "Segment"]
CERTS = ["SOC 2", "ISO 27001", "HIPAA", "GDPR", "PCI DSS"]
# titles searched for on pages cited for ai_ml_roles_open (the passages build)
AI_TITLES_YES = ["AI", "ML", "Machine Learning", "Data Scientist", "Data Science", "Applied Scientist", "Research Scientist",
                 "NLP", "LLM", "Computer Vision"]
# (label, A, B): two settings of one product, compared on the cells both ran (knob_delta.csv)
KNOB_PAIRS = [("exa-v1", "exa-agent-medium-A-v1", "exa-agent-high-B-v1"),
              ("parallel-flat-v1", "parallel-core-flat-v1", "parallel-pro-flat-v1"),
              ("clay-v1", "claygent-auto-A-v1", "claygent-argon-B-v1")]
FAILURE_TAGS = ["fabrication", "miscitation", "entity_confusion", "stale", "overclaim"]
GOLD_ALIASES = {"raised_18_mo": "raised_18mo", "launched_6_mo": "launched_6mo", "leadership_change_12_month": "leadership_change_12mo",
                "leadership_change_12_mo": "leadership_change_12mo", "ai_ml_roles": "ai_ml_roles_open"}
US_STATES = {"alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida", "georgia",
             "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts",
             "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
             "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
             "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
             "wisconsin", "wyoming", "district of columbia", "dc", "ca", "ny", "tx", "wa", "ma", "co", "il", "fl", "ga", "pa", "nj", "va",
             "or", "az", "ut", "nc", "mn", "mi", "oh", "md", "tn", "in", "wi", "mo", "ct"}
COUNTRY_NORM = {"us": "united states", "usa": "united states", "u.s.": "united states", "u.s.a.": "united states",
                "united states of america": "united states", "america": "united states", "uk": "united kingdom", "u.k.": "united kingdom",
                "great britain": "united kingdom", "england": "united kingdom", "fr": "france", "de": "germany", "deutschland": "germany",
                "nl": "netherlands", "the netherlands": "netherlands", "ca": "canada", "au": "australia", "es": "spain",
                "it": "italy", "ch": "switzerland", "se": "sweden", "il": "israel", "in": "india", "sg": "singapore", "ie": "ireland",
                "be": "belgium", "dk": "denmark", "no": "norway", "fi": "finland", "pt": "portugal", "pl": "poland", "at": "austria",
                "nz": "new zealand", "br": "brazil", "mx": "mexico", "jp": "japan", "kr": "south korea", "ae": "united arab emirates",
                "uae": "united arab emirates"}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "truth_status": {"type": "string", "enum": ["known", "unfindable"]},
        "truth_value_json": {"type": "string", "description": "The truth value as a JSON literal in a string (true, \"201-500\", [\"HubSpot\"], {\"city\":..}, 2019; null when unfindable)."},
        "truth_url": {"type": "string", "description": "The URL whose page supports the truth; empty when unfindable."},
        "provenance": {"type": "string", "enum": ["human-blind", "vendor-surfaced", "adjudicator", "consensus"]},
        "reason": {"type": "string", "description": "One line."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "needs_human": {"type": "boolean"},
        "candidates": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "grade": {"type": "string", "enum": ["correct", "wrong", "unknown"]},
                "support": {"type": "string", "enum": ["supported", "unsupported", "unreachable", "n_a"]},
                "failure_tag": {"type": "string", "enum": FAILURE_TAGS + ["none"]},
                "note": {"type": "string"}},
            "required": ["label", "grade", "support", "failure_tag", "note"], "additionalProperties": False}},
    },
    "required": ["truth_status", "truth_value_json", "truth_url", "provenance", "reason", "confidence", "needs_human", "candidates"],
    "additionalProperties": False,
}


# ---- small helpers -----------------------------------------------------------------------------

def norm_text(s: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s or "").lower())).strip()


def norm_country(s: Any) -> str:
    t = norm_text(s)
    t = COUNTRY_NORM.get(t, t)
    if t in US_STATES:
        return "united states"
    return t


def norm_cert(s: Any) -> Optional[str]:
    t = norm_text(s)
    if re.search(r"\bsoc\s*2\b|\bsoc\s*ii\b", t):
        return "SOC 2"
    if "27001" in t:
        return "ISO 27001"
    if "hipaa" in t:
        return "HIPAA"
    if "gdpr" in t:
        return "GDPR"
    if "pci" in t:
        return "PCI DSS"
    return None


def norm_crm(s: Any) -> Optional[str]:
    t = norm_text(s)
    for sysn in CRM_SYSTEMS:
        if sysn.lower() in t:
            return sysn
    return None


def as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;]", v) if x.strip()]
    return [v]


def truth_years(v: Any) -> List[int]:
    out = []
    for x in as_list(v):
        try:
            out.append(int(str(x)[:4]))
        except ValueError:
            continue
    return out


def band_idx(v: Any) -> Optional[int]:
    return BANDS.index(v) if isinstance(v, str) and v in BANDS else None


def ym(v: Any) -> Optional[str]:
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}", v):
        return v[:7]
    return None


def num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", ""))
        except ValueError:
            return None
    return None


def provider_tokens(s: Any) -> List[str]:
    toks = [t for t in re.split(r"[,/&]|\band\b|\s+", str(s or "").lower()) if t]
    return [t for t in toks if len(t) >= 3 and t not in ("the", "via", "models", "model", "api", "azure")] + \
           (["azure"] if "azure" in str(s or "").lower() else [])


def resolve_run(arg: str) -> str:
    p = arg if os.path.isabs(arg) else os.path.join(HERE, arg)
    if os.path.isdir(os.path.join(p, "records")):
        return p
    alt = ec.run_dir_for(arg)
    if os.path.isdir(os.path.join(alt, "records")):
        return alt
    sys.exit(f"no records/ under {arg}")


# ---- match rules -------------------------------------------------------------------------------

def names_overlap(a: List[Any], b: List[Any]) -> int:
    n = 0
    bn = [norm_text(x) for x in b if norm_text(x)]
    for x in a:
        xn = norm_text(x)
        if xn and any(xn == y or xn in y or y in xn for y in bn):
            n += 1
    return n


def match(field: str, cand: Any, truth: Any) -> Tuple[bool, str]:
    """Does the asserted candidate value match the truth value under the field rule? (bool, detail)."""
    kind = KINDS[field]
    if field == "product_one_liner":
        return True, "asserted one-liner counts as correct mechanically (semantic match is the LLM's job)"
    if kind == "bool":
        return (isinstance(cand, bool) and isinstance(truth, bool) and cand == truth), f"{cand} vs {truth}"
    if field == "named_customers":
        k = names_overlap(as_list(cand), as_list(truth))
        return k >= 2, f"{k} of {len(as_list(cand))} asserted names in the truth set (need 2)"
    if field == "employee_band":
        ci, ti = band_idx(cand), band_idx(truth)
        if ci is None or ti is None:
            return False, f"{cand} vs {truth}"
        return abs(ci - ti) <= 1, f"{cand} vs {truth} (within one band)"
    if field == "hq_location":
        c = cand if isinstance(cand, dict) else {}
        t = truth if isinstance(truth, dict) else {}
        ok_country = norm_country(c.get("country")) == norm_country(t.get("country")) and bool(norm_country(t.get("country")))
        cities = [norm_text(t.get("city"))] + [norm_text(x) for x in (t.get("alt_cities") or [])]
        ok_city = norm_text(c.get("city")) in cities and bool(norm_text(c.get("city")))
        return ok_country and ok_city, f"country {c.get('country')} vs {t.get('country')}; city {c.get('city')} vs {cities}"
    if field == "founded_year":
        ys = truth_years(truth)
        cy = truth_years(cand)
        return bool(cy) and cy[0] in ys, f"{cand} vs {ys}"
    if field == "model_provider":
        toks = provider_tokens(truth)
        cl = str(cand or "").lower()
        hit = [t for t in toks if t in cl]
        return bool(hit), f"truth tokens {toks} in {cand!r}: {hit}"
    if field == "compliance_certs":
        cs = [norm_cert(x) for x in as_list(cand)]
        ts = {norm_cert(x) for x in as_list(truth)} - {None}
        if None in cs:
            return False, f"unrecognized cert in {cand}"
        cs_set = set(cs)
        if not cs_set and ts:
            return False, "asserted no certs, truth has some"
        extra = cs_set - ts
        return not extra, f"asserted {sorted(cs_set)} vs truth {sorted(ts)}" + (f"; extra {sorted(extra)}" if extra else "")
    if field == "last_funding":
        cn = isinstance(cand, str) and cand.lower() in ("none", "no known funding")
        tn = isinstance(truth, str) and truth.lower() == "none"
        if cn or tn:
            return cn == tn, f"{cand} vs {truth}"
        c = cand if isinstance(cand, dict) else {}
        t = truth if isinstance(truth, dict) else {}
        # Stage, date and amount are sub-cells. A sub-cell the candidate left empty is an unmatched
        # sub-cell (the fact is wrong, never a whole-fact unknown); a sub-cell the truth lacks is
        # skipped for stage and amount; a round's date is always required.
        details = []
        ok = True
        if t.get("stage") is not None:
            if norm_text(c.get("stage")):
                s_ok = norm_text(c.get("stage")) == norm_text(t.get("stage"))
                details.append(f"stage {c.get('stage')} vs {t.get('stage')} {'ok' if s_ok else 'MISMATCH'}")
            else:
                s_ok = False
                details.append(f"stage missing vs {t.get('stage')} (unmatched sub-cell)")
            ok &= s_ok
        if ym(c.get("date")) is None:
            d_ok = False
            details.append(f"date missing vs {t.get('date')} (unmatched sub-cell)")
        else:
            d_ok = ym(c.get("date")) == ym(t.get("date")) and ym(t.get("date")) is not None
            details.append(f"date {c.get('date')} vs {t.get('date')} {'ok' if d_ok else 'MISMATCH'}")
        ok &= d_ok
        ca, ta = num(c.get("amount_usd")), num(t.get("amount_usd"))
        if ca is not None and ta is not None and ta > 0:
            a_ok = abs(ca - ta) / ta <= 0.10
            ok &= a_ok
            details.append(f"amount {ca:,.0f} vs {ta:,.0f} ({100 * abs(ca - ta) / ta:.0f}% off) {'ok' if a_ok else 'MISMATCH'}")
        return bool(ok), "; ".join(details)
    if field == "crm_stack_signal":
        cs = [norm_crm(x) for x in as_list(cand)]
        ts = {norm_crm(x) for x in as_list(truth)} - {None}
        if None in cs:
            return False, f"a system outside the 12-list in {cand}"
        cs_set = set(cs)
        if not cs_set and ts:
            return False, "asserted no systems, truth has some"
        extra = cs_set - ts
        return not extra, f"asserted {sorted(cs_set)} vs truth {sorted(ts)}" + (f"; not in truth {sorted(extra)}" if extra else "")
    if kind == "string":
        return norm_text(cand) == norm_text(truth), f"{cand!r} vs {truth!r}"
    return cand == truth, f"{cand} vs {truth}"


def values_agree(field: str, a: Any, b: Any) -> bool:
    """Symmetric agreement for grouping consensus (stricter than match for sets)."""
    if field == "product_one_liner":
        return True
    if field in ("compliance_certs", "crm_stack_signal"):
        f = norm_cert if field == "compliance_certs" else norm_crm
        return {f(x) for x in as_list(a)} == {f(x) for x in as_list(b)}
    if field == "named_customers":
        return names_overlap(as_list(a), as_list(b)) >= 2
    if field == "founded_year":
        return truth_years(a) == truth_years(b)
    return match(field, a, b)[0]


def key_tokens(field: str, value: Any) -> List[str]:
    """Tokens the cited page must carry for the mechanical citation check; [] = status alone."""
    kind = KINDS[field]
    if field == "named_customers":
        return [norm_text(x) for x in as_list(value) if norm_text(x)]
    if field == "founded_year":
        return [str(y) for y in truth_years(value)]
    if field == "hq_location" and isinstance(value, dict):
        return [norm_text(value.get("city"))] if norm_text(value.get("city")) else []
    if field == "model_provider":
        return provider_tokens(value)
    if field in ("compliance_certs", "crm_stack_signal"):
        return [norm_text(x) for x in as_list(value) if norm_text(x)]
    if kind in ("bool", "band", "funding") or field == "product_one_liner":
        return []
    return []


# ---- gold sheets -> human-blind records ---------------------------------------------------------

def gold_field(label: str) -> Optional[str]:
    k = re.sub(r"\s+", "_", label.strip().lower())
    k = GOLD_ALIASES.get(k, k)
    return k if k in KINDS else None


def parse_gold_answer(field: str, ans: str) -> Tuple[str, Any, Optional[str]]:
    """-> (status, value, note)"""
    t = (ans or "").strip()
    if not t or t.lower() in ("unfindable", "unknown", "?"):
        return "unknown", None, None
    kind = KINDS[field]
    if kind == "bool":
        if t.lower() in ("true", "yes"):
            return "asserted", True, None
        if t.lower() in ("false", "no"):
            return "asserted", False, None
        return "asserted", t, "gold: unparsed bool"
    if kind == "list":
        if t.lower() in ("[]", "none", "empty"):
            return "asserted", [], None
        return "asserted", as_list(t), None
    if kind == "band":
        return "asserted", t.replace(" ", ""), None
    if kind == "year":
        m = re.search(r"\d{4}", t)
        return "asserted", (int(m.group(0)) if m else t), None
    if kind == "location":
        parts = [p.strip() for p in t.split(",") if p.strip()]
        city = parts[0] if parts else t
        region = parts[-1] if len(parts) > 1 else ""
        country = "United States" if norm_text(region) in US_STATES else region
        note = f"gold wrote {t!r}" if country != region else None
        return "asserted", {"city": city, "country": country}, note
    if kind == "funding":
        if t.lower() in ("none", "bootstrapped", "no funding"):
            return "asserted", "none", None
        m_amt = re.search(r"([\d][\d,]*\.?\d*)\s*([MKBmkb])?", t)
        amount = None
        if m_amt:
            amount = float(m_amt.group(1).replace(",", ""))
            mult = {"m": 1e6, "k": 1e3, "b": 1e9}.get((m_amt.group(2) or "").lower(), 1)
            amount *= mult
        m_date = re.search(r"(\d{4}-\d{2})(?:-\d{2})?", t)
        cur = "EUR" if "eur" in t.lower() or "€" in t else ("GBP" if "gbp" in t.lower() or "£" in t else "USD")
        val = {"stage": None, "date": m_date.group(1) if m_date else None}
        if amount is not None:
            val["amount_usd"] = amount
        return "asserted", val, (f"gold text {t!r}; currency {cur}" if cur != "USD" else f"gold text {t!r}")
    return "asserted", t, None


def load_gold(gold_dir: str, names: Dict[str, str], run_date_for: Dict[str, str], default_date: str) -> Dict[str, Dict[str, Any]]:
    out = {}
    gd = gold_dir if os.path.isabs(gold_dir) else os.path.join(HERE, gold_dir)
    if not os.path.isdir(gd):
        return out
    for fn in sorted(os.listdir(gd)):
        if not fn.endswith(".csv"):
            continue
        domain = fn[:-4]
        rows = list(csv.reader(open(os.path.join(gd, fn))))
        if not rows:
            continue
        rows = rows[1:]  # header: <Company>,Answer,URL (the company cell is not trusted)
        answers = {}
        for r in rows:
            if not r or not r[0].strip():
                continue
            fid = gold_field(r[0])
            if not fid:
                continue
            ans = r[1] if len(r) > 1 else ""
            url = (r[2] if len(r) > 2 else "").strip()
            status, value, note = parse_gold_answer(fid, ans)
            if url and not url.startswith("http"):
                url = "https://" + url
            a = {"status": status, "value": value if status == "asserted" else None,
                 "citations": [url] if (url and status == "asserted") else []}
            if note:
                a["notes"] = note
            if status == "asserted" and not url:
                a["notes"] = (a.get("notes", "") + "; gold gave no URL").strip("; ")
            answers[fid] = a
        for fid in FIELDS:
            answers.setdefault(fid, {"status": "unknown", "value": None, "citations": [], "notes": "gold: row missing"})
        out[domain] = {"schema_version": "v0", "company": names.get(domain, domain), "domain": domain, "config_id": HUMAN,
                       "track": "human", "run_date": run_date_for.get(domain, default_date), "answers": answers}
    return out


# ---- truth file (--no-llm) ----------------------------------------------------------------------

def load_truth_file(path: str) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[str]]:
    p = path if os.path.isabs(path) else os.path.join(HERE, path)
    rows = list(csv.DictReader(open(p)))
    grade_cols = [c for c in (rows[0].keys() if rows else []) if c.startswith("grade:")]
    truth = {}
    for r in rows:
        tv = r.get("truth_value", "")
        try:
            val = json.loads(tv) if tv not in ("", None) else None
        except ValueError:
            val = tv
        grades = {}
        for c in grade_cols:
            g = (r.get(c) or "").strip()
            if g:
                parts = g.split(":", 1)
                grades[c[len("grade:"):]] = (parts[0], parts[1] if len(parts) > 1 else None)
        truth[(r["domain"], r["field"])] = {"status": r["truth_status"], "value": val, "url": r.get("truth_url") or "",
                                            "provenance": r.get("provenance") or "file", "note": r.get("note") or "",
                                            "grades": grades, "source": "file"}
    return truth, [c[len("grade:"):] for c in grade_cols]


# ---- rules text for the adjudicator ----------------------------------------------------------

def _slice_section(text: str, heading_prefix: str) -> str:
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(heading_prefix)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip()


def rules_text() -> Tuple[str, Dict[str, str]]:
    """The adjudicator's system text, read from grading_rules.md as is, and the field table's row per field id."""
    with open(RULES_FILE, encoding="utf-8") as f:
        text = f.read()
    table = _slice_section(text, "## The full table")
    field_rows = {}
    for line in table.splitlines():
        if line.startswith("|") and not line.startswith("|---") and not line.startswith("| #"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[1] in KINDS:
                field_rows[cells[1]] = line.strip()
    return text, field_rows


# ---- pages -------------------------------------------------------------------------------------

class Pages:
    def __init__(self, out_dir: str, run_dirs: List[str], firecrawl_key: Optional[str], allow_fetch: bool, max_chars: int = 200000):
        self.dir = os.path.join(out_dir, "pages")
        os.makedirs(self.dir, exist_ok=True)
        self.run_dirs = run_dirs
        self.key = firecrawl_key
        self.allow_fetch = allow_fetch
        self.max_chars = max_chars
        self.fetched_via = collections.Counter()
        self.firecrawl_calls = 0

    def path(self, url: str) -> str:
        return os.path.join(self.dir, snap.url_key(url) + ".json")

    def cached(self, url: str) -> Optional[Dict[str, Any]]:
        for p in (self.path(url), os.path.join(JUDGE_PAGES, snap.url_key(url) + ".json")):
            if os.path.exists(p):
                return ec.load_json(p)
        s = snap.load_snapshot(self.run_dirs, url)
        if s and (s.get("status") is not None or s.get("markdown") or s.get("withheld")):
            return {"url": url, "fetched_via": "snapshot:" + str(s.get("fetched_via")), "status": s.get("status"),
                    "text": s.get("markdown") or "", "title": s.get("title") or "", "error": s.get("error"),
                    "fetched_at": s.get("fetched_at"), "withheld": s.get("withheld"),
                    "save_truncated": bool(s.get("truncated")), "saved_chars": s.get("chars")}
        return None

    def get(self, url: str, run_date: str) -> Dict[str, Any]:
        c = self.cached(url)
        if c:
            return c
        if not self.allow_fetch:
            return {"url": url, "fetched_via": None, "status": None, "text": "", "title": "", "error": "fetching disabled"}
        got = snap.fetch_urllib(url)
        via = "urllib"
        if (got["status"] is None or got["status"] >= 400 or (not got["text"] and not got["error"])) and self.key:
            fc = snap.fetch_firecrawl(url, self.key)
            self.firecrawl_calls += 1
            if fc["status"] is not None and fc["status"] < 400 and fc["text"]:
                got, via = fc, "firecrawl"
            else:
                got["error"] = "; ".join(x for x in [got.get("error"), fc.get("error")] if x) or got.get("error")
        if got["status"] is None or got["status"] >= 400 or not got["text"]:
            wb = snap.fetch_wayback(url, run_date)
            if wb["status"] is not None and wb["status"] < 400 and wb["text"]:
                got, via = wb, "wayback"
        text, _ = ec.scrub_credentials(got.get("text") or "")
        rec = {"url": url, "fetched_via": via, "status": got.get("status"), "text": text[:self.max_chars],
               "title": got.get("title") or "", "error": got.get("error"), "archived_url": got.get("archived_url"),
               "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        ec.dump_json(self.path(url), rec)
        self.fetched_via[via] += 1
        return rec


def support_check(field: str, value: Any, urls: List[str], pages: Dict[str, Dict[str, Any]]) -> Tuple[str, str]:
    """-> (supported|unsupported|unreachable, detail)"""
    if not urls:
        return "unsupported", "no citation"
    toks = key_tokens(field, value)
    reachable = withheld = False
    for u in urls:
        p = pages.get(u) or {}
        st = p.get("status")
        withheld = withheld or bool(p.get("withheld"))
        if st is None or st >= 400 or not (p.get("text") or "").strip():
            continue
        reachable = True
        if not toks:
            return "supported", f"{u} status {st} (status-only field)"
        text = norm_text(p.get("text"))
        hit = [t for t in toks if t and t in text]
        if hit:
            return "supported", f"{u} carries {hit[:3]}"
    if not reachable:
        return ("withheld", "page withheld") if withheld else ("unreachable", "no cited page could be fetched")
    return "unsupported", f"reachable page(s) do not carry {toks[:4]}"


# ---- verdict cache, prior truth, negatives ------------------------------------------------------

def load_verdict_cache(path: str) -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(path):
        for line in open(path):
            try:
                e = json.loads(line)
                cache[e["key"]] = e
            except (ValueError, KeyError):
                continue
    return cache


def load_prior(path: str) -> Dict[str, Any]:
    """truth.csv from an earlier grading folder, plus that folder's cells.csv grades when it sits beside it."""
    p = path if os.path.isabs(path) else os.path.join(HERE, path)
    csv.field_size_limit(10**9)
    truth = {}
    for r in csv.DictReader(open(p)):
        tv = r.get("truth_value", "")
        try:
            val = json.loads(tv) if tv not in ("", None) else None
        except ValueError:
            val = tv
        truth[(r["domain"], r["field"])] = {
            "status": r["truth_status"], "value": val, "url": r.get("truth_url") or "", "provenance": r.get("provenance") or "prior",
            "source": "prior:" + (r.get("source") or ""), "note": r.get("reason") or r.get("note") or "",
            "confidence": r.get("confidence") or "", "needs_human": (r.get("needs_human") or "").strip().lower() == "true", "grades": {}}
    grades = {}
    cp = os.path.join(os.path.dirname(p), "cells.csv")
    if os.path.exists(cp):
        for r in csv.DictReader(open(cp)):
            if r.get("grade") in (None, "", "ungraded"):
                continue
            grades[(r["domain"], r["field"], r["config_id"])] = {
                "status": r.get("status"), "value": r.get("value"), "citations": r.get("citations") or "",
                "grade": {"grade": r["grade"], "tag": r.get("failure_tag") or None, "support": r.get("support") or "n_a",
                          "detail": r.get("detail") or "", "source": "prior:" + (r.get("grade_source") or "")}}
    return {"truth": truth, "grades": grades, "path": path}


def prior_grade(prior: Dict[str, Any], k: Tuple[str, str], cfg: str, x: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The prior pass's grade for this candidate when it is the same answer (status, value and citations)."""
    g = prior["grades"].get((k[0], k[1], cfg))
    if not g:
        return None
    if g["status"] == x.get("status") and g["value"] == ec.canonical_json(x.get("value")) and g["citations"] == "|".join(x.get("citations") or []):
        return dict(g["grade"])
    return None


def classify_prior(cells, with_assert, prior, pages_for) -> Dict[str, Any]:
    """Prior-truth mode. Per asserted cell: keep the prior truth when every NEW candidate (one the prior pass did not grade)
    either abstains, agrees with a known truth under values_agree and passes the citation check, or carries no citation
    (graded wrong under the record-schema rule: an assertion needs a receipt); otherwise the whole cell goes to the judge."""
    kept, to_judge = {}, []
    why = collections.Counter()
    new_agree = uncited = 0
    for k in with_assert:
        c = cells[k]
        pt = prior["truth"].get(k)
        if not pt:
            to_judge.append(k)
            why["no prior truth"] += 1
            continue
        g_out, trigger = {}, None
        for cfg, x in c["candidates"].items():
            pg = prior_grade(prior, k, cfg, x)
            if pg:
                g_out[cfg] = pg
                continue
            if x.get("status") != "asserted":
                mg, md = mechanical_grade(k[1], x, pt)
                g_out[cfg] = {"grade": mg, "tag": None, "support": "n_a", "detail": "new candidate; " + md, "source": "prior-truth"}
                continue
            if not (x.get("citations") or []):
                uncited += 1
                mg, md = mechanical_grade(k[1], x, pt)
                tag = "miscitation" if mg == "correct" else ("overclaim" if pt["status"] == "unfindable" else None)
                g_out[cfg] = {"grade": "wrong", "tag": tag, "support": "unsupported",
                              "detail": f"uncited assertion (record-schema rule: an assertion needs a citation); value {md}", "source": "prior-truth"}
                continue
            if k[1] == "product_one_liner":
                trigger = "one-liner (always adjudicated)"
                break
            if pt["status"] != "known":
                trigger = "assertion on an unfindable prior truth"
                break
            if not values_agree(k[1], x.get("value"), pt.get("value")):
                trigger = "disagrees with the prior truth"
                break
            sup = support_check(k[1], x.get("value"), x.get("citations") or [], pages_for(k))
            if sup[0] != "supported":
                trigger = f"agrees, citation check {sup[0]}"
                break
            new_agree += 1
            g_out[cfg] = {"grade": "correct", "tag": None, "support": "supported", "detail": "agrees with the prior truth; " + sup[1], "source": "prior-truth"}
        if trigger:
            to_judge.append(k)
            why[trigger] += 1
        else:
            kept[k] = (dict(pt), g_out)
    return {"kept": kept, "to_judge": to_judge, "why": ", ".join(f"{n} {w}" for w, n in why.most_common()) or "none",
            "why_counts": dict(why), "new_agree": new_agree, "uncited": uncited}


REJUDGE_SALT = "rejudge-list"


def load_rejudge(path: str) -> set:
    """A CSV with domain,field columns naming cells that go to the judge again in prior-truth mode."""
    p = path if os.path.isabs(path) else os.path.join(HERE, path)
    return {(r["domain"], r["field"]) for r in csv.DictReader(open(p))}


def force_rejudge(pc: Dict[str, Any], rejudge: set) -> int:
    """Move listed cells the prior truth would keep to the judge (cells already going there stay)."""
    moved = [k for k in pc["kept"] if k in rejudge]
    for k in moved:
        del pc["kept"][k]
        pc["to_judge"].append(k)
    if moved:
        tag = "on the --rejudge list"
        pc["why_counts"][tag] = len(moved)
        pc["why"] = (pc["why"] + ", " if pc["why"] != "none" else "") + f"{len(moved)} {tag}"
    return len(moved)


def is_negative(field: str, value: Any) -> bool:
    """A negative truth: false, 'none', or an empty list (the twelve questions whose answer can be negative)."""
    if value is False:
        return True
    if isinstance(value, list) and not value:
        return True
    if isinstance(value, str) and norm_text(value) in ("none", "no funding", "bootstrapped"):
        return True
    return False


def miss_rates(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Unknowns on findable facts: a cell whose truth is known and where some config was graded correct with a
    supported citation; split by positive and negative truth."""
    findable = {}
    for r in rows:
        if r["truth_status"] == "known" and r["grade"] == "correct" and r.get("support") == "supported":
            try:
                v = json.loads(r["truth_value"]) if r["truth_value"] not in ("", None) else None
            except ValueError:
                v = r["truth_value"]
            findable[(r["domain"], r["field"])] = "negative" if is_negative(r["field"], v) else "positive"
    out = {}
    for r in rows:
        kind = findable.get((r["domain"], r["field"]))
        if not kind:
            continue
        m = out.setdefault(r["config_id"], {"positive": [0, 0], "negative": [0, 0], "all": [0, 0]})
        for part in (kind, "all"):
            m[part][1] += 1
            if r["grade"] == "unknown":
                m[part][0] += 1
    return {cfg: {part: {"missed": v[0], "findable": v[1], "miss_rate": (v[0] / v[1]) if v[1] else None} for part, v in m.items()}
            for cfg, m in out.items()}


# ---- the adjudicator call ----------------------------------------------------------------------

def adjudicator_price(model: str) -> Tuple[float, float, float, float]:
    return PRICES.get(model, PRICES[ADJ_MODEL_DEFAULT])


def usage_cost(model: str, usage: Dict[str, Any]) -> float:
    pin, pout, pread, pwrite = adjudicator_price(model)
    return (float(usage.get("input_tokens") or 0) * pin + float(usage.get("output_tokens") or 0) * pout
            + float(usage.get("cache_read_input_tokens") or 0) * pread
            + float(usage.get("cache_creation_input_tokens") or 0) * pwrite) / 1e6


def call_messages(body: Dict[str, Any], key: str, retries: int = 3, timeout: int = 300) -> Dict[str, Any]:
    data = json.dumps(body).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(API_URL, data=data, method="POST", headers={
            "x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:800]
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries:
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"network: {e}")
    raise RuntimeError("unreachable")


def windows_text(run_date: str) -> str:
    try:
        d = dt.date.fromisoformat(run_date[:10])
    except ValueError:
        return f"run date {run_date}"

    def back(months):
        y, m = d.year, d.month - months
        while m <= 0:
            m += 12
            y -= 1
        return dt.date(y, m, min(d.day, 28)).isoformat()
    return (f"run date {d.isoformat()}: raised_18mo counts rounds on or after {back(18)}; leadership_change_12mo on or after {back(12)}; "
            f"launched_6mo on or after {back(6)}; 'right now' = live on {d.isoformat()}")


# ---- passages from the full saved page -----------------------------------------------------------
# The judge reads each cited page from its saved copy (up to 200,000 characters a page): a page that fits its share
# of the cell's budget whole; a longer page as its start, its end and a window around each place where a value a
# candidate asserted or a term of the field occurs, every gap marked with the characters skipped. Under each page,
# search lines run over the whole saved text state what a gap can and cannot hold. The rule the judge is given for
# reading them is the last section of grading_rules.md.
PASS_HEAD, PASS_TAIL = 1500, 1000          # always shown from a long page: its start and its end (footers carry addresses and badges)
PASS_HALF, PASS_HALF_MIN = 600, 120        # characters shown either side of a hit; shrunk toward the minimum when a page is over budget
PASS_PAGE_BUDGET, PASS_CELL_BUDGET = 12000, 150000
PASS_SAVE_CAP = 200000                     # snapshot.py and Pages save at most this much of a page
PASS_TOKEN_HITS, PASS_TERM_HITS = 3, 2     # occurrences windowed per asserted value, per field term
PASS_NEAR = 300                            # an occurrence with other searched words this close is windowed first
PASS_SNAP = 25
PASS_STOP = {"the", "and", "for", "with", "via", "its", "own", "not", "models", "model", "api", "uses", "using", "based", "other",
             "such", "including", "multiple", "various", "unknown", "none", "inc", "llc", "ltd", "company", "provider", "providers",
             "public", "publicly", "disclosed", "named", "specific", "large", "language", "open", "source", "proprietary", "house",
             "from", "that", "this", "are", "has", "have", "any", "all", "per", "also"}
_MONTHS = [("January", "Jan"), ("February", "Feb"), ("March", "Mar"), ("April", "Apr"), ("May", "May"), ("June", "Jun"),
           ("July", "Jul"), ("August", "Aug"), ("September", "Sept?"), ("October", "Oct"), ("November", "Nov"), ("December", "Dec")]
_CERT_SRC = {"SOC 2": r"(?<!\w)soc[\W_]*(?:2|ii)(?!\w)", "ISO 27001": r"(?<!\d)27001(?!\d)", "HIPAA": r"(?<!\w)hipaa(?!\w)",
             "GDPR": r"(?<!\w)gdpr(?!\w)", "PCI DSS": r"(?<!\w)pci(?!\w)"}
_MONEY = ("an amount in dollars", r"\$\s?\d[\d,.]*\s?(?:k|m|mm|mn|b|bn|thousand|million|billion)?(?!\w)", re.I)
_FUND_TERMS = ["raised", "raises", "funding", "Series", "seed", "led by", "investor", "financing", "venture", "valuation", _MONEY]
_JOB_TERMS = ["open positions", "open roles", "job openings", "careers", "apply"]
PASS_FIELD_TERMS: Dict[str, List[Any]] = {
    "product_one_liner": [],
    "pricing_page": ["pricing", ("a per-month price", r"/\s?mo(?:nth)?(?!\w)|per\s+month", re.I), "per user", "per seat", "free trial",
                     "contact sales", "plans", "billed", _MONEY],
    "named_customers": ["customers", "case stud", "customer stor", "success stor", "trusted by", "testimonial", "clients"],
    "employee_band": ["employees", "team of", "company size", "headcount"],
    "hq_location": ["headquarter", "HQ", "based in", "located in", "head office", "address", "offices"],
    "founded_year": ["founded", "established", ("since <year>", r"(?<!\w)since\s+(?:19|20)\d\d(?!\d)", re.I), "started in", "inception",
                     "incorporated", ("est. <year>", r"(?<!\w)est\.?\s*(?:19|20)\d\d(?!\d)", re.I),
                     ("a copyright line", r"©|\(c\)\s*(?:19|20)\d\d|(?<!\w)copyright", re.I)],
    "eng_blog": ["engineering blog", "tech blog", "technical blog", "developer blog", "engineering", "blog"],
    "public_docs": ["documentation", "docs", "developer", "API reference", "API", "SDK", "help center", "knowledge base", "guides"],
    "ai_ml_roles_open": AI_TITLES_YES + _JOB_TERMS,
    "model_provider": ["OpenAI", "GPT", "Anthropic", "Claude", "Gemini", "Azure OpenAI", "Bedrock", "Llama", "Mistral", "Cohere", "LLM",
                       "large language model", "foundation model", "powered by", "subprocessor", "sub-processor"],
    "compliance_certs": [(n, src, re.I) for n, src in _CERT_SRC.items()] + ["certif", "complian", "trust center", "security"],
    "last_funding": list(_FUND_TERMS),
    "raised_18mo": list(_FUND_TERMS),
    "hiring_sdr_ae": ["SDR", "BDR", "Sales Development", "Business Development Representative", "Account Executive"] + _JOB_TERMS,
    "launched_6mo": ["launch", "introducing", "announc", "now available", "generally available", "general availability", "new feature",
                     "release", "changelog", "what's new", "beta"],
    "leadership_change_12mo": ["appoint", "joins", "joined", "named", "hires", "hired", "promoted", "steps down", "stepped down", "depart",
                               "welcome", "Chief", "CEO", "CTO", "CFO", "COO", "CRO", "CMO", "CPO", "CISO", "Vice President", "VP", "SVP",
                               "General Manager", "Head of"],
    "crm_stack_signal": CRM_SYSTEMS + ["CRM", "integrations", "subprocessor", "sub-processor", "experience with"],
}
PASS_WINDOW_MONTHS = {"raised_18mo": 18, "leadership_change_12mo": 12, "launched_6mo": 6}


def _lit_src(tok: Any, prefix: bool = False) -> Optional[str]:
    """Regex source for a word or phrase: case and spacing free, punctuation between its parts optional, whole words
    (prefix=True leaves the end open, so 'launch' also finds 'launched'). Offsets are those of the raw text."""
    parts = [x for x in re.split(r"[\W_]+", str(tok)) if x]
    if not parts:
        return None
    out = re.escape(parts[0])
    for a, b in zip(parts, parts[1:]):
        out += (r"[\W_]+" if a[-1].isdigit() and b[0].isdigit() else r"[\W_]*") + re.escape(b)
    return r"(?<!\w)" + out + ("" if prefix else r"(?!\w)")


def _month_src(y: int, m: int) -> str:
    full, ab = _MONTHS[m - 1]
    return (rf"(?<!\w)(?:{full}|{ab})\.?,?\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?{y}(?!\d)|(?<!\d){y}-{m:02d}(?!\d)"
            rf"|(?<!\d)0?{m}/\d{{1,2}}/(?:{y}|{y % 100:02d})(?!\d)")


def _amount_pat(n: float) -> Tuple[str, str, int]:
    if n >= 1e9:
        v, units, suf = n / 1e9, r"(?:b|bn|billion)", "B"
    elif n >= 1e6:
        v, units, suf = n / 1e6, r"(?:m|mm|mn|million)", "M"
    elif n >= 1e3:
        v, units, suf = n / 1e3, r"(?:k|thousand)", "K"
    else:
        v, units, suf = n, "", ""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    whole, _, frac = s.partition(".")
    numsrc = re.escape(whole) + (rf"\.{frac}\d*" if frac else r"(?:\.0+)?")
    plain = re.escape(f"{int(round(n)):,}")
    return f"${s}{suf}", rf"(?<![\d.,]){numsrc}\s*{units}(?!\w)|(?<![\d.,]){plain}(?![\d,])", re.I


def passage_value_patterns(field: str, value: Any) -> List[Tuple[str, str, int]]:
    """(label, regex source, flags): the words by which an asserted value would show on a page. key_tokens' tokens for
    the fields that have them, plus the parts of a funding round and an employee band, which key_tokens leaves to status."""
    out: List[Tuple[str, str, int]] = []

    def lit(x: Any) -> None:
        label = norm_text(x)
        src = _lit_src(label)
        if src and len(label) >= 2 and label not in PASS_STOP:
            out.append((label, src, re.I))

    if field == "compliance_certs":
        for x in as_list(value):
            n = norm_cert(x)
            if n:
                out.append((n, _CERT_SRC[n], re.I))
            else:
                lit(x)
    elif field == "crm_stack_signal":
        for x in as_list(value):
            lit(norm_crm(x) or x)
    elif field == "last_funding":
        if isinstance(value, dict):
            st = norm_text(value.get("stage"))
            if st and st != "none":
                lit(st)
            n = num(value.get("amount_usd"))
            if n and n > 0:
                out.append(_amount_pat(n))
            d = ym(value.get("date"))
            if d:
                y, m = int(d[:4]), int(d[5:7])
                if 1 <= m <= 12:
                    out.append((f"{_MONTHS[m - 1][0]} {y}", _month_src(y, m), re.I))
    elif field == "employee_band":
        if isinstance(value, str) and value in BANDS:
            lo, hi = value.split("-")
            out.append((f"{value} (a head count)", rf"(?<!\d){lo}\s*(?:-|–|—|to)\s*{hi}(?!\d)", re.I))
    else:
        for t in key_tokens(field, value):
            if field == "model_provider" and not re.search(r"[^\W\d_]", str(t)):
                continue                    # a bare version number names no provider
            lit(t)
    return out


def passage_field_patterns(field: str, run_date: Any) -> List[Tuple[str, str, int]]:
    out: List[Tuple[str, str, int]] = []
    for term in PASS_FIELD_TERMS.get(field, []):
        if isinstance(term, tuple):
            out.append(term)
        elif term.isalpha() and term.isupper() and len(term) <= 5:
            out.append((term, r"(?<!\w)" + re.escape(term) + r"s?(?!\w)", 0))     # an acronym: capitals only, plural allowed
        else:
            src = _lit_src(term, prefix=True)
            if src:
                out.append((term, src, re.I))
    months = PASS_WINDOW_MONTHS.get(field)
    if months:
        try:
            d = dt.date.fromisoformat(str(run_date)[:10])
        except ValueError:
            d = None
        if d:
            yms, y, m = [], d.year, d.month
            for _ in range(months + 1):
                yms.append((y, m))
                m -= 1
                if m == 0:
                    y, m = y - 1, 12
            label = f"a date from {_MONTHS[yms[-1][1] - 1][0]} {yms[-1][0]} to {_MONTHS[yms[0][1] - 1][0]} {yms[0][0]}"
            out.append((label, "|".join(_month_src(yy, mm) for yy, mm in yms), re.I))
    return out


def _merge_iv(iv: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for s, e in sorted(iv):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _iv_size(iv: List[Tuple[int, int]]) -> int:
    return sum(e - s for s, e in iv)


def _window(text: str, s: int, e: int, half: int) -> Tuple[int, int]:
    a, b, n = max(0, s - half), min(len(text), e + half), len(text)
    for _ in range(PASS_SNAP):           # widen each edge to the nearest space, so an excerpt does not start mid-word
        if a == 0 or text[a - 1].isspace():
            break
        a -= 1
    for _ in range(PASS_SNAP):
        if b >= n or text[b].isspace():
            break
        b += 1
    return a, b


def page_hits(text: str, pats: List[Tuple[str, str, int]]) -> Dict[str, List[Tuple[int, int]]]:
    """label -> every occurrence (start, end) in the raw text, in page order."""
    out: Dict[str, List[Tuple[int, int]]] = {}
    for label, src, flags in pats:
        out[label] = [(m.start(), m.end()) for m in re.finditer(src, text, flags) if m.end() > m.start()]
    return out


def _by_company(hits: Dict[str, List[Tuple[int, int]]], everything: List[Tuple[int, str]]) -> Dict[str, List[Tuple[int, int]]]:
    """Each label's occurrences, the ones with the most other searched words within PASS_NEAR characters first
    (a year beside 'founded', an amount beside 'raised'), then in page order."""
    starts = [p for p, _ in everything]
    out = {}
    for label, hs in hits.items():
        def near(h, label=label):
            i, j = bisect.bisect_left(starts, h[0] - PASS_NEAR), bisect.bisect_right(starts, h[0] + PASS_NEAR)
            return len({l for _, l in everything[i:j] if l != label})
        out[label] = sorted(hs, key=lambda h: (-near(h), h[0]))
    return out


def select_passages(text: str, alloc: int, tok: Dict[str, List[Tuple[int, int]]], term: Dict[str, List[Tuple[int, int]]],
                    tiers: int = 2) -> List[Tuple[int, int]]:
    """The stretches of a page to show within alloc characters. Order of claim on the budget: the start and the end;
    one window per asserted value found (windows narrow, down to PASS_HALF_MIN a side, until they all fit); further
    occurrences of those values; then (tiers=2) windows on the field's terms; then whatever is left extends the start."""
    L = len(text)
    if L <= alloc:
        return [(0, L)]
    if alloc <= PASS_HEAD + PASS_TAIL:
        h = max(1, int(alloc * PASS_HEAD / (PASS_HEAD + PASS_TAIL)))
        return _merge_iv([(0, min(L, h)), (max(0, L - max(0, alloc - h)), L)])
    base = _merge_iv([(0, PASS_HEAD), (L - PASS_TAIL, L)])
    must = [hs[0] for hs in tok.values() if hs]
    half = PASS_HALF
    while True:
        iv = _merge_iv(base + [_window(text, s, e, half) for s, e in must])
        if _iv_size(iv) <= alloc or half <= PASS_HALF_MIN:
            break
        half = max(PASS_HALF_MIN, int(half * 0.8))
    if _iv_size(iv) > alloc:                 # more values than fit even at the narrowest window: as many as fit, in order
        iv = base
        for s, e in must:
            cand = _merge_iv(iv + [_window(text, s, e, half)])
            if _iv_size(cand) <= alloc:
                iv = cand

    def add(hits: Dict[str, List[Tuple[int, int]]], first: int, upto: int) -> None:
        nonlocal iv
        for r in range(first, upto):
            for hs in hits.values():
                if r < len(hs):
                    cand = _merge_iv(iv + [_window(text, hs[r][0], hs[r][1], half)])
                    if _iv_size(cand) <= alloc:
                        iv = cand

    add(tok, 1, PASS_TOKEN_HITS)
    if tiers >= 2:
        add(term, 0, PASS_TERM_HITS)
        while True:
            left = alloc - _iv_size(iv)
            if left <= 0 or iv == [(0, L)]:
                break
            iv = _merge_iv([(0, min(L, iv[0][1] + left))] + iv[1:])
    return iv


def _waterfill(wants: List[int], budget: int) -> List[int]:
    """Shares of a budget: every want at or under the common level is met in full, the rest get the level."""
    if sum(wants) <= budget:
        return list(wants)
    out, left, n = [0] * len(wants), budget, len(wants)
    for i in sorted(range(len(wants)), key=lambda i: wants[i]):
        share = left // n
        out[i] = min(wants[i], share)
        left -= out[i]
        n -= 1
    return out


def cell_passages(cell: Dict[str, Any], pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per cited URL (sorted, as the default build orders them): the page record and, for a reachable page,
    its text, the stretches shown, and every searched word's occurrences. Budget: PASS_PAGE_BUDGET a page and
    PASS_CELL_BUDGET a cell. Every page first gets its start, its end and its asserted-value windows; what the cell has
    left is then shared evenly for field-term windows and more of each page's start. When even the first round is over
    the cell budget the pages share it evenly and their windows narrow; a reachable page is never shown at zero."""
    field = cell["field"]
    vals: Dict[str, Tuple[str, str, int]] = {}
    for cfg in sorted(cell["candidates"]):
        a = cell["candidates"][cfg]
        if a.get("status") == "asserted":
            for pat in passage_value_patterns(field, a.get("value")):
                vals.setdefault(pat[0], pat)
    tok_pats = [vals[k] for k in sorted(vals)]
    seen = {k.lower() for k in vals}
    term_pats = [p for p in passage_field_patterns(field, cell.get("run_date")) if p[0].lower() not in seen]
    out: List[Dict[str, Any]] = []
    for u in sorted({u for a in cell["candidates"].values() for u in (a.get("citations") or [])}):
        p = pages.get(u) or {}
        st = p.get("status")
        text = (p.get("text") or "").strip()
        e: Dict[str, Any] = {"url": u, "page": p, "reachable": bool(text) and st is not None and st < 400}
        if e["reachable"]:
            tok, term = page_hits(text, tok_pats), page_hits(text, term_pats)
            everything = sorted([(s, l) for l, hs in tok.items() for s, _ in hs] + [(s, l) for l, hs in term.items() for s, _ in hs])
            e.update({"text": text, "tok_all": tok, "term_all": term, "tok": _by_company(tok, everything), "term": _by_company(term, everything),
                      "cap_hit": bool(p.get("save_truncated")) or len(p.get("text") or "") >= PASS_SAVE_CAP})
            e["first"] = _iv_size(select_passages(text, min(len(text), PASS_PAGE_BUDGET), e["tok"], e["term"], tiers=1))
        out.append(e)
    live = [e for e in out if e["reachable"]]
    firsts = [e["first"] for e in live]
    if sum(firsts) > PASS_CELL_BUDGET:
        allocs = _waterfill(firsts, PASS_CELL_BUDGET)
    else:
        extra = _waterfill([min(len(e["text"]), PASS_PAGE_BUDGET) - e["first"] for e in live], PASS_CELL_BUDGET - sum(firsts))
        allocs = [f + x for f, x in zip(firsts, extra)]
    for e, alloc in zip(live, allocs):
        e["alloc"] = alloc
        e["shown"] = select_passages(e["text"], alloc, e["tok"], e["term"], tiers=2)
        e["shown_chars"] = _iv_size(e["shown"])
    return out


def _search_line(what: str, hits: Dict[str, List[Tuple[int, int]]], shown: List[Tuple[int, int]], whole: bool) -> Optional[str]:
    """One line a page: the searched words that occur in its saved text, with counts; the words it leaves out do not occur."""
    if not hits:
        return None
    found = []
    for label, hs in hits.items():
        if not hs:
            continue
        n = len(hs)
        k = sum(1 for s, e in hs if any(a <= s and e <= b for a, b in shown))
        found.append(f'"{label}" {n} hit{"s" if n != 1 else ""}' + ("" if whole else " (all shown)" if k == n else f" ({k} shown)"))
    if not found:
        return f"search, {what}: none occurs in the saved text"
    rest = len(hits) - len(found)
    return f"search, {what}: " + "; ".join(found) + (f"; the other {rest} do not occur" if rest else "")


def cell_user_text(cell: Dict[str, Any], letters: Dict[str, str], pages: Dict[str, Dict[str, Any]], field_row: str,
                   mech: Dict[str, str]) -> str:
    """The judge's user message for one cell: the question, the field's rule, the candidates by letter, and the cited pages."""
    field = cell["field"]
    lines = [f"Company: {cell['company']} ({cell['domain']}). Field: {field}. Question: {QUESTIONS[field].format(run_date=cell['run_date'])}",
             windows_text(cell["run_date"]), "", "Field rule (row from the gold definitions table):", field_row or "(see the table in the rules)", "",
             "Candidates (letters only):"]
    for cfg, letter in sorted(letters.items(), key=lambda kv: kv[1]):
        a = cell["candidates"][cfg]
        v = a.get("value")
        note = a.get("notes") or ""
        lines.append(f"- {letter}: status={a.get('status')}" + (f", value={json.dumps(v, ensure_ascii=False)}" if a.get("status") == "asserted" else "")
                     + (f", citations={json.dumps(a.get('citations') or [])}" if a.get("citations") else "")
                     + (f", note={json.dumps(note, ensure_ascii=False)}" if note else "")
                     + (f"  [mechanical cross-check: {mech.get(cfg)}]" if mech.get(cfg) else ""))
    lines += ["", "Fetched page text for every cited URL, from the full saved copy ('unreachable' when no fetch worked). A page that fits its share of "
                  "the cell's budget is shown whole. A longer page is shown as excerpts: its start, its end, and the text around places where a value a "
                  "candidate asserted or a term of this field occurs; every gap is marked `[... N chars not shown ...]`. The search lines under each "
                  "page were run over the whole saved text, shown or not; a searched word a page's search line leaves out does not occur in that "
                  "page's saved text (see the last section of the rules)."]
    entries = cell_passages(cell, pages)
    first = next((e for e in entries if e["reachable"]), None)
    if first:
        lines.append("Searched in the whole saved text of every page below. Values the candidates asserted: "
                     + (", ".join(f'"{k}"' for k in first["tok_all"]) or "none (this field's values are not words on a page)")
                     + ". Terms of this field: " + (", ".join(f'"{k}"' for k in first["term_all"]) or "none") + ".")
    for e in entries:
        p = e["page"]
        head = f"### {e['url']}\nstatus={p.get('status')} via={p.get('fetched_via')} title={json.dumps(p.get('title') or '')}"
        if p.get("error"):
            head += f" error={json.dumps(str(p.get('error'))[:200])}"
        if p.get("withheld"):
            lines += [head, "(page withheld: text not redistributed)", ""]
            continue
        if not e["reachable"]:
            lines += [head, "(unreachable or empty)", ""]
            continue
        text, shown = e["text"], e["shown"]
        whole = shown == [(0, len(text))]
        lines.append(head)
        lines.append(f"saved text: {len(text):,} chars; " + ("shown whole" if whole else f"shown: {e['shown_chars']:,} chars in {len(shown)} excerpts")
                     + ("; the saved copy stops at the save limit, the live page ran longer and the rest was not saved" if e["cap_hit"] else ""))
        for line in (_search_line("asserted values", e["tok_all"], shown, whole),
                     _search_line("field terms", e["term_all"], shown, whole)):
            if line:
                lines.append(line)
        body, at = [], 0
        for s, t in shown:
            if s > at:
                body.append(f"[... {s - at:,} chars not shown ...]")
            body.append(text[s:t])
            at = t
        if at < len(text):
            body.append(f"[... {len(text) - at:,} chars not shown ...]")
        lines += ["\n".join(body), ""]
    lines.append("Decide the truth for this cell and grade every candidate. Return the verdict JSON.")
    return "\n".join(lines)


def cell_cache_key(cell: Dict[str, Any], model: str) -> str:
    cands = sorted((cfg, a.get("status"), ec.canonical_json(a.get("value")), sorted(a.get("citations") or []))
                   for cfg, a in cell["candidates"].items())
    return ec.sha256_hex(ec.canonical_json([cell["domain"], cell["field"], cands, model]))


def adjudicate_cell(cell, letters, pages, rules, field_row, mech, model, key) -> Dict[str, Any]:
    body = {"model": model, "max_tokens": 16000, "thinking": {"type": "adaptive"},
            "output_config": {"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}, "effort": "high"},
            "system": [{"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": cell_user_text(cell, letters, pages, field_row, mech)}]}
    resp = call_messages(body, key)
    usage = resp.get("usage") or {}
    out = {"usage": usage, "cost_usd": round(usage_cost(model, usage), 6), "stop_reason": resp.get("stop_reason"),
           "model": resp.get("model") or model, "verdict": None, "refusal": False, "parse_error": None}
    if resp.get("stop_reason") == "refusal":
        out["refusal"] = True
        out["stop_details"] = resp.get("stop_details")
        return out
    text = next((b.get("text") for b in resp.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"), None)
    try:
        v = json.loads(text) if text else None
    except ValueError:
        v = None
    if not isinstance(v, dict):
        out["parse_error"] = (text or "")[:300]
        return out
    try:
        v["truth_value"] = json.loads(v.get("truth_value_json") or "null")
    except ValueError:
        v["truth_value"] = v.get("truth_value_json")
    out["verdict"] = v
    return out


# ---- metrics -----------------------------------------------------------------------------------

def tally(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    answerable = [r for r in rows if r["truth_status"] == "known" and r["grade"] != "gap"]
    unfind = [r for r in rows if r["truth_status"] == "unfindable"]
    correct = sum(1 for r in rows if r["grade"] == "correct")
    correct_known = sum(1 for r in answerable if r["grade"] == "correct")
    wrong = sum(1 for r in rows if r["grade"] == "wrong")
    unknown = sum(1 for r in rows if r["grade"] == "unknown")
    gap = sum(1 for r in rows if r["grade"] == "gap")
    asserted = sum(1 for r in rows if r["status"] == "asserted")
    lo, hi = ec.wilson(correct_known, len(answerable))
    return {"n_cells": n, "answerable": len(answerable), "correct": correct, "correct_on_answerable": correct_known, "wrong": wrong,
            "unknown": unknown, "gap": gap, "asserted": asserted,
            "accuracy": correct_known / len(answerable) if answerable else None, "wilson_lo": lo, "wilson_hi": hi,
            "yield": asserted / n if n else None, "trust": correct_known / asserted if asserted else None,
            "hallucination_rate": wrong / asserted if asserted else None,
            "unfindable_cells": len(unfind),
            "wrong_confident_rate": (sum(1 for r in unfind if r["status"] == "asserted") / len(unfind)) if unfind else None,
            "abstention_rate": (sum(1 for r in unfind if r["status"] == "unknown") / len(unfind)) if unfind else None}


def band_accuracy(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    out = {}
    for b in ec.BANDS:
        t = tally([r for r in rows if r["band"] == b])
        out[b] = t["accuracy"]
    return out


def equal_weighted(rows: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    accs = [a for a in band_accuracy(rows).values() if a is not None]
    if not accs:
        return None, None, None
    mean = sum(accs) / len(accs)
    by_company = collections.defaultdict(list)
    for r in rows:
        by_company[r["domain"]].append(r)
    companies = sorted(by_company)

    def stat(sample):
        rs = [r for d in sample for r in by_company[d]]
        a = [x for x in band_accuracy(rs).values() if x is not None]
        return sum(a) / len(a) if a else None
    lo, hi = ec.bootstrap_ci(companies, stat)
    return mean, lo, hi


def knob_deltas(cell_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    by = collections.defaultdict(dict)
    for r in cell_rows:
        by[(r["domain"], r["field"])][r["config_id"]] = r
    for vendor, A, B in KNOB_PAIRS:
        pairs = [(c[A], c[B]) for c in by.values() if A in c and B in c and c[A]["truth_status"] == "known"
                 and c[A]["grade"] != "gap" and c[B]["grade"] != "gap"]
        if not pairs:
            continue
        comps = {a["domain"] for a, _ in pairs}
        accA = sum(1 for a, _ in pairs if a["grade"] == "correct") / len(pairs)
        accB = sum(1 for _, b in pairs if b["grade"] == "correct") / len(pairs)
        b_ = sum(1 for a, b in pairs if a["grade"] == "correct" and b["grade"] != "correct")
        c_ = sum(1 for a, b in pairs if a["grade"] != "correct" and b["grade"] == "correct")
        out.append({"vendor": vendor, "A": A, "B": B, "accuracy_A": accA, "accuracy_B": accB,
                    "delta_pp": 100 * (accB - accA), "b_A_right_B_wrong": b_, "c_A_wrong_B_right": c_,
                    "mcnemar_p": ec.mcnemar_exact(b_, c_), "paired_cells": len(pairs), "paired_companies": len(comps)})
    return out


# ---- main -------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", nargs="+", default=DEFAULT_RUNS,
                    help="run folders (runs/<name> or a name under runs/); default: " + " ".join(DEFAULT_RUNS))
    ap.add_argument("--gold", default="gold")
    ap.add_argument("--csv", default="scored_120.csv", help="company list for bands")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"output folder, relative to this folder unless absolute (default {DEFAULT_OUT}; the published grading/ files stay untouched)")
    ap.add_argument("--only", default=None, help="comma list of domains")
    ap.add_argument("--no-llm", action="store_true", help="truth and grades from --truth; no network")
    ap.add_argument("--truth", default=None, help="truth CSV for --no-llm (for example grading/truth.csv)")
    ap.add_argument("--adjudicator-model", default=ADJ_MODEL_DEFAULT)
    ap.add_argument("--audit-sample", type=float, default=0.10)
    ap.add_argument("--adjudicate-all", action="store_true", help="send every cell to the adjudicator (no auto-accept)")
    ap.add_argument("--no-fetch", action="store_true", help="skip citation fetching (every cell with an assertion is adjudicated)")
    ap.add_argument("--no-firecrawl", action="store_true")
    ap.add_argument("--seed", type=int, default=20261108)
    ap.add_argument("--est-cell-input", type=int, default=15000)
    ap.add_argument("--est-cell-output", type=int, default=600)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--run-date", default=None, help="run date for the gold records when no run supplies one")
    ap.add_argument("--prior-truth", default=None,
                    help="grade against this truth.csv as a prior (its cells.csv, when beside it, supplies prior grades); "
                         "agreeing cited candidates are correct with no call, a disagreement or an assertion on an unfindable truth sends "
                         "the whole cell to the judge")
    ap.add_argument("--rejudge", default=None,
                    help="CSV of domain,field cells sent to the judge again in --prior-truth mode, with a fresh verdict "
                         "(their cache key is salted, so a verdict already cached for the same candidates is not reused)")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    if a.prior_truth and (a.no_llm or a.adjudicate_all):
        sys.exit("--prior-truth runs the judge path; it does not combine with --no-llm or --adjudicate-all")
    if a.rejudge and not a.prior_truth:
        sys.exit("--rejudge needs --prior-truth")
    rejudge_set = load_rejudge(a.rejudge) if a.rejudge else set()

    run_dirs = [resolve_run(r) for r in a.runs]
    out_dir = a.out if os.path.isabs(a.out) else os.path.join(HERE, a.out)
    os.makedirs(out_dir, exist_ok=True)
    only = set(x.strip() for x in a.only.split(",")) if a.only else None

    # records
    meta = ec.company_meta(a.csv)
    for fallback in ("scored_120.csv",):
        for d, m in ec.company_meta(fallback).items():
            meta.setdefault(d, m)
    records = []
    for rd in run_dirs:
        for tag, rec in ec.iter_records(rd):
            if only and rec.get("domain") not in only:
                continue
            rec["_run"] = os.path.basename(rd)
            records.append(rec)
    if not records:
        sys.exit("no records matched")
    run_date_for: Dict[str, str] = {}
    for rec in records:
        run_date_for.setdefault(rec["domain"], rec.get("run_date"))
    default_date = a.run_date or (sorted(run_date_for.values())[0] if run_date_for else dt.date.today().isoformat())
    names = {d: (meta.get(d) or {}).get("name", d) for d in run_date_for}
    gold = load_gold(a.gold, names, run_date_for, default_date)
    gold = {d: g for d, g in gold.items() if (not only or d in only) and d in run_date_for}
    records += list(gold.values())
    configs = sorted({r["config_id"] for r in records})
    domains = sorted({r["domain"] for r in records})

    # cells
    cells: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in records:
        for fid in FIELDS:
            ans = (rec.get("answers") or {}).get(fid) or {"status": "unknown", "value": None, "citations": []}
            c = cells.setdefault((rec["domain"], fid), {
                "domain": rec["domain"], "field": fid, "company": rec.get("company") or rec["domain"],
                "band": (meta.get(rec["domain"]) or {}).get("band", "?"), "run_date": run_date_for.get(rec["domain"], default_date),
                "candidates": {}})
            c["candidates"][rec["config_id"]] = ans
    rec_by = {(r["domain"], r["config_id"]): r for r in records}

    def ck_of(k):
        ck = cell_cache_key(cells[k], a.adjudicator_model)
        return ec.sha256_hex(ck + ":" + REJUDGE_SALT) if k in rejudge_set else ck

    print(f"Loaded {len(records) - len(gold)} records from {len(run_dirs)} folder(s) + {len(gold)} gold sheet(s) as {HUMAN}: "
          f"{len(domains)} companies, {len(configs)} configs ({', '.join(configs)}), {len(cells)} cells")

    # ---- truth -----------------------------------------------------------------------------------
    truth: Dict[Tuple[str, str], Dict[str, Any]] = {}
    grades: Dict[Tuple[str, str, str], Dict[str, Any]] = {}   # (domain, field, config) -> {grade, tag, support, detail, source}
    adjudicated: Dict[Tuple[str, str], Dict[str, Any]] = {}
    auto_accepted = set()
    all_unknown = set()
    audited = {}
    grading_cost = 0.0
    pages_by_cell: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    file_grade_cols: List[str] = []
    prior_kept = set()
    prior_stats: Dict[str, Any] = {}
    prompt_version_of = {}
    for rec in records:
        if rec.get("config_id") != HUMAN:
            prompt_version_of.setdefault(rec["config_id"], rec.get("prompt_version") or "")

    if a.no_llm:
        if not a.truth:
            sys.exit("--no-llm needs --truth <csv>")
        truth_file, file_grade_cols = load_truth_file(a.truth)
        for key_, t in truth_file.items():
            if key_ in cells:
                truth[key_] = t
        ungraded = sorted(d for d in domains if not any((d, f) in truth for f in FIELDS))
        print(f"Truth from {a.truth}: {len(truth)} cells on {len({d for d, _ in truth})} companies; "
              f"{len(ungraded)} companies ungraded (no truth): {', '.join(ungraded) if ungraded else 'none'}")
    else:
        # plan
        urls = sorted({u for c in cells.values() for ans in c["candidates"].values() for u in (ans.get("citations") or []) if isinstance(u, str) and u.startswith("http")})
        fkey = None if a.no_firecrawl else ec.env_key("FIRECRAWL_API_KEY", required=False)
        pages = Pages(out_dir, run_dirs, fkey, allow_fetch=not a.no_fetch)
        cached = sum(1 for u in urls if pages.cached(u))
        with_assert = [k for k, c in cells.items() if any(x.get("status") == "asserted" for x in c["candidates"].values())]
        agree_cells, disagree_cells, single_cells, abstainer_cells = [], [], [], []
        for k in with_assert:
            c = cells[k]
            asserted = [(cfg, x) for cfg, x in c["candidates"].items() if x.get("status") == "asserted"]
            if k[1] == "product_one_liner":
                disagree_cells.append(k)
                continue
            if len(asserted) < 2:
                single_cells.append(k)
                continue
            base = asserted[0][1].get("value")
            if all(values_agree(k[1], base, x.get("value")) for _, x in asserted[1:]):
                # auto-accept needs every config that ran the cell to have asserted and agreed;
                # an abstention is not agreement, so a cell with any abstainer goes to the judge
                if len(asserted) < len(c["candidates"]):
                    abstainer_cells.append(k)
                else:
                    agree_cells.append(k)
            else:
                disagree_cells.append(k)
        n_unknown_cells = len(cells) - len(with_assert)
        pin, pout, _, _ = adjudicator_price(a.adjudicator_model)
        est = (a.est_cell_input * pin + a.est_cell_output * pout) / 1e6
        prior = load_prior(a.prior_truth) if a.prior_truth else None
        if prior:
            plan_lookup = {u: pages.cached(u) for u in urls}
            pc = classify_prior(cells, with_assert, prior, lambda k: {u: plan_lookup.get(u) or {} for x in cells[k]["candidates"].values()
                                                                      for u in (x.get("citations") or [])})
            if rejudge_set:
                n_forced = force_rejudge(pc, rejudge_set)
                print(f"Rejudge list: {a.rejudge}, {len(rejudge_set)} cells; {n_forced} moved from kept to the judge, "
                      f"{sum(1 for k in rejudge_set if k in cells and k not in set(with_assert))} all-unknown (not judged)")
            n_adj, n_audit = len(pc["to_judge"]), 0
            print(f"Prior-truth mode: {a.prior_truth} ({len(prior['truth'])} truth cells, {len(prior['grades'])} prior grades)")
            print(f"Cells: {len(cells)} = {n_unknown_cells} all-unknown (unfindable by consensus, free) + {len(pc['kept'])} kept on the prior truth "
                  f"(new candidates graded against it, no judge) + {len(pc['to_judge'])} to the judge ({pc['why']}); "
                  f"{pc['new_agree']} new candidates agree with a known truth and pass the citation check, {pc['uncited']} uncited new assertions "
                  f"graded wrong without a call; support checked on cached pages only in this plan, so the judge count is an upper bound")
        else:
            n_adj = len(disagree_cells) + len(single_cells) + len(abstainer_cells) + (len(agree_cells) if (a.adjudicate_all or a.no_fetch) else 0)
            n_audit = 0 if (a.adjudicate_all or a.no_fetch) else int(round(a.audit_sample * len(agree_cells)))
            print(f"Cells: {len(cells)} = {n_unknown_cells} all-unknown (unfindable by consensus, free) + {len(agree_cells)} value-agreement, every config asserted "
                  f"(auto-accept if the citation check passes) + {len(abstainer_cells)} agreement with an abstainer (judge) + "
                  f"{len(single_cells)} single-asserter + {len(disagree_cells)} disagreement or one-liner")
        cached_verdicts = load_verdict_cache(os.path.join(out_dir, "adjudications.jsonl"))
        if prior:
            plan_cells = list(pc["to_judge"])
        else:
            plan_cells = list(disagree_cells) + list(single_cells) + list(abstainer_cells) + (list(agree_cells) if (a.adjudicate_all or a.no_fetch) else [])
        n_cached = sum(1 for k in plan_cells if ck_of(k) in cached_verdicts)
        print(f"Verdict cache: {n_cached} of {len(plan_cells)} judge cells already have a cached verdict for the same candidates; "
              f"~{len(plan_cells) - n_cached} new calls x ~${est:.3f} = ~${(len(plan_cells) - n_cached) * est:.2f} (+ ~{n_audit} audit cells, mostly new)")
        print(f"Citation check: {len(urls)} distinct cited URLs, {cached} cached (pages/ or snapshots/), {len(urls) - cached} to fetch "
              f"(urllib first; Firecrawl worst case {0 if (fkey is None or a.no_fetch) else len(urls) - cached} credits; then Wayback)"
              + ("; fetching DISABLED (--no-fetch): every asserted cell is adjudicated" if a.no_fetch else ""))
        print(f"Adjudicator {a.adjudicator_model}: ~{n_adj} cells + ~{n_audit} audit cells x ~${est:.3f} (est {a.est_cell_input:,} in / "
              f"{a.est_cell_output} out at ${pin}/${pout} per MTok, cache read $0.20) = worst case ~${(n_adj + n_audit) * est:.2f}; "
              f"all-cells upper bound {len(with_assert)} x ${est:.3f} = ${len(with_assert) * est:.2f}; agreement cells that fail the citation check add to it")
        print(f"Output: {out_dir}/")
        if not a.yes:
            print("Dry run: nothing fetched, nothing adjudicated. Add --yes to spend.")
            return
        api_key = ec.env_key("ANTHROPIC_API_KEY")
        rules, field_rows = rules_text()
        rules_hash = ec.sha256_hex(rules)
        print(f"Rules text: {len(rules):,} chars, sha256 {rules_hash[:16]} ({os.path.basename(RULES_FILE)})")

        # fetch pages
        url_dates = {}
        for k in with_assert:
            for x in cells[k]["candidates"].values():
                for u in x.get("citations") or []:
                    if isinstance(u, str) and u.startswith("http"):
                        url_dates.setdefault(u, cells[k]["run_date"])
        page_store: Dict[str, Dict[str, Any]] = {}
        if not a.no_fetch:
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = {pool.submit(pages.get, u, d): u for u, d in url_dates.items()}
                for i, fut in enumerate(as_completed(futs), 1):
                    u = futs[fut]
                    try:
                        page_store[u] = fut.result()
                    except Exception as e:  # noqa: BLE001
                        page_store[u] = {"url": u, "status": None, "text": "", "error": str(e)[:200], "fetched_via": None}
                    if i % 50 == 0:
                        print(f"  fetched {i}/{len(url_dates)} ({round(time.time() - t0)}s)")
            print(f"Pages: {len(page_store)} ({dict(pages.fetched_via)} newly fetched; {pages.firecrawl_calls} Firecrawl calls)")
        for k in with_assert:
            pages_by_cell[k] = {u: page_store.get(u) or pages.cached(u) or {"url": u, "status": None, "text": ""}
                                for x in cells[k]["candidates"].values() for u in (x.get("citations") or [])}

        # all-unknown cells: unfindable by consensus
        for k, c in cells.items():
            if k in with_assert:
                continue
            pt = prior["truth"].get(k) if prior else None
            if pt and pt["status"] == "known":
                # prior-truth mode: a prior pass found this fact; every candidate here abstained, so each is a blank against it
                truth[k] = dict(pt)
                prior_kept.add(k)
                for cfg, x in c["candidates"].items():
                    grades[(k[0], k[1], cfg)] = prior_grade(prior, k, cfg, x) or {"grade": "unknown", "tag": None, "support": "n_a",
                                                                                  "detail": "honest unknown on a prior known truth", "source": "prior-truth"}
                continue
            truth[k] = {"status": "unfindable", "value": None, "url": "", "provenance": "consensus", "note": "no searcher asserted",
                        "source": "consensus", "grades": {}}
            all_unknown.add(k)

        # prior-truth mode: the prior truth stands where every new candidate agrees with it and
        # passes the citation check; a candidate already graded in the prior pass (same status, value and citations)
        # keeps its prior grade, so the prior pass's numbers do not move; anything else sends the whole cell to the judge
        if prior:
            pc = classify_prior(cells, with_assert, prior, lambda k: pages_by_cell.get(k, {}))
            n_forced = force_rejudge(pc, rejudge_set) if rejudge_set else 0
            for k, (t, g) in pc["kept"].items():
                truth[k] = t
                for cfg, gr in g.items():
                    grades[(k[0], k[1], cfg)] = gr
                prior_kept.add(k)
            to_adjudicate = list(pc["to_judge"])
            prior_stats.update({"kept_cells": len(pc["kept"]), "judge_cells": len(pc["to_judge"]), "why": pc["why"],
                                "new_candidates_agree": pc["new_agree"], "uncited_new_assertions": pc["uncited"],
                                "prior_truth": a.prior_truth})
            if rejudge_set:
                prior_stats.update({"rejudge_file": a.rejudge, "rejudge_cells": len(rejudge_set), "rejudge_moved_from_kept": n_forced})
            print(f"Prior truth kept on {len(pc['kept'])} cells; {len(to_adjudicate)} cells to the adjudicator ({pc['why']})")
            agree_cells = []
        # auto-accept
        rng = random.Random(a.seed)
        if not prior:
            to_adjudicate = list(disagree_cells) + list(single_cells) + list(abstainer_cells)
        for k in agree_cells:
            c = cells[k]
            asserted = [(cfg, x) for cfg, x in c["candidates"].items() if x.get("status") == "asserted"]
            value = asserted[0][1].get("value")
            supports = {cfg: support_check(k[1], x.get("value"), x.get("citations") or [], pages_by_cell[k]) for cfg, x in asserted}
            ok = (not a.adjudicate_all and not a.no_fetch and all(s[0] == "supported" for s in supports.values()))
            if ok:
                url = next((u for cfg, x in asserted for u in (x.get("citations") or [])
                            if (pages_by_cell[k].get(u) or {}).get("status") and pages_by_cell[k][u]["status"] < 400), "")
                truth[k] = {"status": "known", "value": value, "url": url, "provenance": "consensus", "source": "consensus",
                            "note": f"{len(asserted)} searchers agree; citation check passed", "grades": {}}
                auto_accepted.add(k)
                for cfg, x in c["candidates"].items():
                    if x.get("status") == "asserted":
                        grades[(k[0], k[1], cfg)] = {"grade": "correct", "tag": None, "support": supports[cfg][0], "detail": supports[cfg][1], "source": "consensus"}
                    else:
                        grades[(k[0], k[1], cfg)] = {"grade": "unknown", "tag": None, "support": "n_a", "detail": "", "source": "consensus"}
                if rng.random() < a.audit_sample:
                    audited[k] = {"consensus_value": value}
                    to_adjudicate.append(k)
            else:
                to_adjudicate.append(k)
        if not prior:
            print(f"Auto-accepted {len(auto_accepted)} of {len(agree_cells)} agreement cells; {len(abstainer_cells)} agreement cells with an abstainer "
                  f"to the judge; {len(all_unknown)} all-unknown cells unfindable by consensus; "
                  f"{len(to_adjudicate)} cells to the adjudicator ({len(audited)} of them audit samples)")

        # adjudicate (cached)
        adj_path = os.path.join(out_dir, "adjudications.jsonl")
        cache: Dict[str, Dict[str, Any]] = load_verdict_cache(adj_path)
        lock = __import__("threading").Lock()

        def letters_for(k):
            cfgs = sorted(cells[k]["candidates"])
            r = random.Random(f"{a.seed}:{k[0]}:{k[1]}")
            r.shuffle(cfgs)
            return {cfg: chr(ord("A") + i) for i, cfg in enumerate(cfgs)}

        def mech_notes(k):
            c = cells[k]
            asserted = [(cfg, x) for cfg, x in c["candidates"].items() if x.get("status") == "asserted"]
            notes = {}
            for cfg, x in asserted:
                agree = [letters[cfg2] for cfg2, y in asserted if cfg2 != cfg and values_agree(k[1], x.get("value"), y.get("value"))]
                sup = support_check(k[1], x.get("value"), x.get("citations") or [], pages_by_cell.get(k, {}))
                notes[cfg] = f"agrees with {','.join(sorted(agree)) or 'nobody'}; citation {sup[0]}"
            return notes

        def do(k):
            ck = ck_of(k)
            if ck in cache:
                return k, cache[ck], True
            res = adjudicate_cell(cells[k], letters_by[k], pages_by_cell.get(k, {}), rules, field_rows.get(k[1], ""),
                                  mech_by[k], a.adjudicator_model, api_key)
            entry = {"key": ck, "domain": k[0], "field": k[1], "letters": letters_by[k], "model": a.adjudicator_model,
                     "rules_sha256": rules_hash, "at": dt.datetime.now(dt.timezone.utc).isoformat(), **res}
            with lock:
                with open(adj_path, "a") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return k, entry, False

        letters_by = {k: letters_for(k) for k in to_adjudicate}
        mech_by = {}
        for k in to_adjudicate:
            letters = letters_by[k]
            mech_by[k] = mech_notes(k)
        n_new = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=a.parallel) as pool:
            futs = [pool.submit(do, k) for k in to_adjudicate]
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    k, entry, from_cache = fut.result()
                except Exception as e:  # noqa: BLE001
                    print(f"  adjudication error: {e}")
                    continue
                adjudicated[k] = entry
                if not from_cache:
                    n_new += 1
                    grading_cost += entry.get("cost_usd") or 0
                if i % 25 == 0 or i == len(to_adjudicate):
                    print(f"  adjudicated {i}/{len(to_adjudicate)} ({n_new} new, ${grading_cost:.2f}, {round(time.time() - t0)}s)")

        # apply verdicts
        for k, entry in adjudicated.items():
            v = entry.get("verdict")
            letters = entry.get("letters") or letters_by.get(k, {})
            inv = {l: cfg for cfg, l in letters.items()}
            if not v:
                truth.setdefault(k, {"status": "known", "value": None, "url": "", "provenance": "adjudicator", "source": "adjudicator",
                                     "note": "REFUSAL" if entry.get("refusal") else f"unparseable verdict: {entry.get('parse_error')}",
                                     "grades": {}, "needs_human": True, "confidence": "low"})
                for cfg, x in cells[k]["candidates"].items():
                    grades.setdefault((k[0], k[1], cfg), {"grade": "unknown" if x.get("status") != "asserted" else "wrong", "tag": None,
                                                           "support": "n_a", "detail": "no verdict; left for the human", "source": "none"})
                continue
            if k in audited:
                audited[k]["verdict_truth"] = v.get("truth_value")
                audited[k]["agree"] = (v.get("truth_status") == "known" and values_agree(k[1], v.get("truth_value"), audited[k]["consensus_value"])
                                       and all(c.get("grade") == "correct" for c in v.get("candidates") or []
                                               if (cells[k]["candidates"].get(inv.get(c.get("label"), ""), {}).get("status") == "asserted")))
                continue  # the consensus truth and grades stand; the audit only measures agreement
            truth[k] = {"status": v.get("truth_status"), "value": v.get("truth_value"), "url": v.get("truth_url") or "",
                        "provenance": v.get("provenance") or "adjudicator", "source": "adjudicator", "note": v.get("reason") or "",
                        "confidence": v.get("confidence"), "needs_human": bool(v.get("needs_human")), "grades": {}}
            seen = set()
            for cand in v.get("candidates") or []:
                cfg = inv.get(cand.get("label"))
                if not cfg:
                    continue
                seen.add(cfg)
                tag = cand.get("failure_tag")
                grades[(k[0], k[1], cfg)] = {"grade": cand.get("grade"), "tag": None if tag in (None, "none") else tag,
                                             "support": cand.get("support"), "detail": cand.get("note") or "", "source": "adjudicator"}
            for cfg, x in cells[k]["candidates"].items():
                if cfg in seen:
                    continue
                g, d = mechanical_grade(k[1], x, truth[k])
                grades[(k[0], k[1], cfg)] = {"grade": g, "tag": None, "support": "n_a", "detail": "label missing from verdict; " + d, "source": "mechanical"}

    # ---- an assertion with no citation is graded wrong under the record-schema rule ------------------------
    # (wrong, whatever the judge made of a URL named only in the notes; the brief rules out taking the notes as the receipt)
    uncited_overrides = []
    if not a.no_llm:
        for k, c in cells.items():
            for cfg, x in c["candidates"].items():
                if cfg == HUMAN or x.get("status") != "asserted" or (x.get("citations") or []):
                    continue
                g = grades.get((k[0], k[1], cfg))
                if g and g.get("grade") == "correct":
                    uncited_overrides.append({"domain": k[0], "field": k[1], "config_id": cfg, "judge_detail": g.get("detail", "")})
                    grades[(k[0], k[1], cfg)] = {**g, "grade": "wrong", "tag": "miscitation", "support": "unsupported",
                                                 "detail": "uncited assertion (record-schema rule); the judge had graded it correct: " + (g.get("detail") or ""),
                                                 "source": (g.get("source") or "") + "+uncited-rule"}
                elif g and g.get("grade") == "wrong" and not g.get("tag"):
                    grades[(k[0], k[1], cfg)] = {**g, "tag": "miscitation" if (truth.get(k) or {}).get("status") == "known" else "overclaim"}
    if uncited_overrides:
        print(f"Uncited rule: {len(uncited_overrides)} uncited assertion(s) the judge graded correct set to wrong:miscitation: "
              + "; ".join(f"{o['domain']} {o['field']} {o['config_id']}" for o in uncited_overrides))

    # ---- grades in --no-llm mode (file) + mechanical matcher everywhere ---------------------------
    diffs = []
    for k, c in cells.items():
        t = truth.get(k)
        for cfg, x in c["candidates"].items():
            gk = (k[0], k[1], cfg)
            mg, md = (mechanical_grade(k[1], x, t) if t else ("ungraded", "no truth"))
            if a.no_llm:
                if not t:
                    grades[gk] = {"grade": "ungraded", "tag": None, "support": "n_a", "detail": "no truth in file", "source": "none"}
                    continue
                rec_grade = t["grades"].get(cfg)
                if rec_grade:
                    g, tag = rec_grade
                    grades[gk] = {"grade": g, "tag": tag, "support": "n_a", "detail": md, "source": "file"}
                else:
                    g, tag = mg, None
                    grades[gk] = {"grade": g, "tag": None, "support": "n_a", "detail": md, "source": "mechanical"}
                if g != mg:
                    diffs.append({"domain": k[0], "field": k[1], "config_id": cfg, "recorded": g + (f":{tag}" if tag else ""),
                                  "mechanical": mg, "reason": diff_reason(k[1], g, tag, mg, md)})
            else:
                grades.setdefault(gk, {"grade": "ungraded", "tag": None, "support": "n_a", "detail": "no verdict and no truth", "source": "none"})
                grades[gk]["mechanical"] = mg
                if t and grades[gk]["source"] == "adjudicator" and grades[gk]["grade"] != mg:
                    diffs.append({"domain": k[0], "field": k[1], "config_id": cfg, "recorded": grades[gk]["grade"] + (f":{grades[gk]['tag']}" if grades[gk].get("tag") else ""),
                                  "mechanical": mg, "reason": "adjudicator and mechanical matcher disagree: " + md})

    # ---- withheld pages: a candidate citing one keeps its published grade (same answer only) ------------
    if not a.no_llm and os.path.exists(PUBLISHED_CELLS):
        csv.field_size_limit(10**9)
        pub = {(r["domain"], r["field"], r["config_id"]): r for r in csv.DictReader(open(PUBLISHED_CELLS, newline=""))}
        kept_pub = 0
        for k, cell_pages in pages_by_cell.items():
            for cfg, x in cells[k]["candidates"].items():
                r = pub.get((k[0], k[1], cfg))
                if not r or not any((cell_pages.get(u) or {}).get("withheld") for u in (x.get("citations") or [])):
                    continue
                if (r["status"], r["value"], r["citations"]) != (x.get("status"), ec.canonical_json(x.get("value")), "|".join(x.get("citations") or [])):
                    continue
                grades[(k[0], k[1], cfg)] = {**grades.get((k[0], k[1], cfg), {}), "grade": r["grade"], "tag": r["failure_tag"] or None,
                                             "support": "withheld", "detail": "page withheld; published grade: " + r["detail"], "source": "published"}
                kept_pub += 1
        print(f"Withheld pages: {kept_pub} candidates citing one keep their published grade from {os.path.relpath(PUBLISHED_CELLS, HERE)}")

    # ---- rows ------------------------------------------------------------------------------------
    cell_rows = []
    for k, c in sorted(cells.items()):
        t = truth.get(k)
        for cfg, x in sorted(c["candidates"].items()):
            g = grades.get((k[0], k[1], cfg), {"grade": "ungraded", "tag": None, "support": "n_a", "detail": ""})
            sup = ""
            fetched_via = ""
            if k in pages_by_cell:
                vias = [str((pages_by_cell[k].get(u) or {}).get("fetched_via")) for u in (x.get("citations") or [])]
                fetched_via = ",".join(vias)
            cell_rows.append({"domain": k[0], "band": c["band"], "field": k[1], "config_id": cfg, "status": x.get("status"),
                              "value": ec.canonical_json(x.get("value")), "citations": "|".join(x.get("citations") or []),
                              "grade": g["grade"], "failure_tag": g.get("tag") or "", "support": g.get("support") or sup,
                              "fetched_via": fetched_via, "auto_accepted": 1 if k in auto_accepted else 0,
                              "adjudicated": 1 if k in adjudicated and k not in audited else 0,
                              "truth_status": (t or {}).get("status", "none"), "truth_value": ec.canonical_json((t or {}).get("value")),
                              "grade_source": g.get("source", ""), "detail": g.get("detail", ""), "mechanical": g.get("mechanical", "")})
    graded_rows = [r for r in cell_rows if r["grade"] not in ("ungraded",)]

    # tallies
    tallies = []
    metrics_cfg = {}
    for cfg in configs:
        rows = [r for r in graded_rows if r["config_id"] == cfg]
        if not rows:
            continue
        recs = [rec_by[(d, cfg)] for d in {r["domain"] for r in rows} if (d, cfg) in rec_by]
        costs = [r.get("cost_usd") for r in recs if isinstance(r.get("cost_usd"), (int, float))]
        lats = [r.get("latency_seconds") for r in recs if isinstance(r.get("latency_seconds"), (int, float))]
        all17 = sum(1 for d in {r["domain"] for r in rows}
                    if sum(1 for r in rows if r["domain"] == d and r["grade"] == "correct") == 17)
        base = {"all17_companies": all17, "companies": len({r["domain"] for r in rows}),
                "cost_mean": ec.mean(costs), "usd_per_1k": 1000 * ec.mean(costs) if costs else None, "latency_median": ec.median(lats),
                "prompt_version": prompt_version_of.get(cfg, "")}
        for band in ec.BANDS:
            br = [r for r in rows if r["band"] == band]
            if br:
                tallies.append({"config_id": cfg, "slice": band, **tally(br), **base})
        pooled = tally(rows)
        tallies.append({"config_id": cfg, "slice": "pooled", **pooled, **base})
        ew, lo, hi = equal_weighted(rows)
        tallies.append({"config_id": cfg, "slice": "equal_weighted", **{**pooled, "accuracy": ew, "wilson_lo": lo, "wilson_hi": hi}, **base,
                        "ci": "bootstrap over companies (2000, seed 20261108)"})
        metrics_cfg[cfg] = {"pooled": pooled, "equal_weighted": {"accuracy": ew, "ci_lo": lo, "ci_hi": hi},
                            "by_band": {b: tally([r for r in rows if r["band"] == b]) for b in ec.BANDS}, **base}
    knobs = knob_deltas(graded_rows)
    # right / wrong / blank per 100 graded facts, the net score swept over the cost of a wrong answer, the
    # paired bootstrap (score_views.py), and the miss rate on findable facts
    views = score_views.views(graded_rows)
    misses = miss_rates(graded_rows)

    # disputes
    disputes = []
    for k, c in sorted(cells.items()):
        t = truth.get(k)
        if not t:
            continue
        reasons = []
        if t.get("needs_human"):
            reasons.append("adjudicator asked for a human")
        if t.get("confidence") == "low":
            reasons.append("adjudicator confidence low")
        if any(grades.get((k[0], k[1], cfg), {}).get("grade") == "gap" for cfg in c["candidates"]):
            reasons.append("rule gap")
        if t.get("note", "").startswith("REFUSAL") or "unparseable" in t.get("note", ""):
            reasons.append("no verdict")
        if t.get("url") and k in pages_by_cell:
            p = pages_by_cell[k].get(t["url"]) or {}
            if p.get("status") is None or (p.get("status") or 0) >= 400:
                reasons.append("truth URL unreachable at grading")
        h = c["candidates"].get(HUMAN)
        if h and h.get("status") == "asserted" and t.get("status") == "known" and not match(k[1], h.get("value"), t.get("value"))[0]:
            reasons.append("gold flipped (human asserted a different value)")
        if h and h.get("status") == "asserted" and t.get("status") == "unfindable":
            reasons.append("human asserted on an unfindable truth")
        if reasons:
            disputes.append({"domain": k[0], "field": k[1], "truth": f"{t.get('status')}: {ec.canonical_json(t.get('value'))} @ {t.get('url')}",
                             "reason": "; ".join(reasons),
                             "candidates": " | ".join(f"{cfg}={x.get('status')}:{ec.canonical_json(x.get('value'))}->{grades.get((k[0], k[1], cfg), {}).get('grade')}"
                                                      for cfg, x in sorted(c["candidates"].items())),
                             "what_to_check": t.get("note", "")[:300]})

    # ---- write ------------------------------------------------------------------------------------
    def write_csv(name, rows):
        if not rows:
            return
        keys = []
        for r in rows:
            for kk in r:
                if kk not in keys:
                    keys.append(kk)
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)

    write_csv("truth.csv", [{"domain": k[0], "field": k[1], "truth_status": t.get("status"), "truth_value": ec.canonical_json(t.get("value")),
                             "truth_url": t.get("url"), "provenance": t.get("provenance"), "reason": t.get("note", ""), "source": t.get("source"),
                             "confidence": t.get("confidence", ""), "needs_human": t.get("needs_human", "")}
                            for k, t in sorted(truth.items())])
    write_csv("cells.csv", cell_rows)
    write_csv("tallies.csv", tallies)
    write_csv("knob_delta.csv", knobs)
    write_csv("disputes.csv", disputes)
    if diffs:
        write_csv("matcher_diffs.csv", diffs)
    ungraded_domains = sorted(d for d in domains if not any((d, f) in truth for f in FIELDS))
    metrics = {"mode": "no-llm (truth file)" if a.no_llm else "adjudicated", "truth_file": a.truth if a.no_llm else None,
               "adjudicator_model": None if a.no_llm else a.adjudicator_model, "runs": [os.path.basename(r) for r in run_dirs],
               "gold_companies": sorted(gold), "configs": configs, "companies": len(domains), "cells": len(cells),
               "ungraded_companies": ungraded_domains,
               "auto_accept": {"auto_accepted": len(auto_accepted), "all_unknown_unfindable": len(all_unknown), "adjudicated": len(adjudicated) - len(audited),
                               "audited": len(audited), "rate": (len(auto_accepted) + len(all_unknown)) / len(cells) if cells else None,
                               "audit_agreement": (sum(1 for v in audited.values() if v.get("agree")) / len(audited)) if audited else None},
               "pages_fetched_via": dict(getattr(locals().get("pages"), "fetched_via", {}) or {}) if not a.no_llm else {},
               "prompt_versions": {cfg: prompt_version_of.get(cfg, "") for cfg in configs},
               "score_views": {"rows": views["rows"], "ranks": {str(p): r for p, r in views["ranks"].items()},
                               "pairs": [{kk: vv for kk, vv in q.items() if not kk.startswith("_")} for q in views["pairs"]]},
               "miss_rate_findable": misses,
               "prior_truth": prior_stats or None, "prior_kept_cells": len(prior_kept), "uncited_rule_overrides": uncited_overrides,
               "abstainer_cells_to_judge": (len(locals().get("abstainer_cells") or []) if not a.no_llm and not prior_stats else None),
               "grading_cost_usd_this_pass": round(grading_cost, 4), "per_config": metrics_cfg, "knob_delta": knobs,
               "disputes": len(disputes), "matcher_diffs": len(diffs),
               "definitions": {"answerable": "truth known (and not a rule gap)", "accuracy": "correct / answerable; unknowns count against accuracy",
                               "wilson": "95% Wilson interval on correct / answerable, per band and pooled",
                               "equal_weighted": "mean of the three band accuracies; 95% CI by seeded percentile bootstrap over companies (2000 resamples, seed 20261108)",
                               "yield": "asserted / cells", "trust": "correct on answerable / asserted", "hallucination_rate": "wrong / asserted",
                               "wrong_confident_rate": "asserted on unfindable truth / unfindable cells", "abstention_rate": "unknown on unfindable / unfindable cells",
                               "usd_per_1k": "1000 x mean cost_usd over records with a cost", "latency_median": "median latency_seconds",
                               "all17": "companies with 17 correct cells", "knob_delta": "B minus A accuracy in pp on cells both ran, McNemar exact on discordant cells",
                               "right_wrong_blank": "per 100 graded facts: right = correct, incl. an honest unknown on an unfindable truth; wrong = wrong, incl. an assertion on an unfindable truth; blank = unknown on a known truth",
                               "net_p": "100 x (right - p x wrong) / graded, p = the cost of a wrong answer in blanks (0, 1, 2, 3); 95% interval by paired bootstrap over companies (score_views.py, 2000, seed 20261108)",
                               "miss_rate_findable": "unknowns / findable cells, where findable = truth known and some config graded correct with a supported citation; split by positive and negative truth (false, none, empty list)",
                               "prompt_version": "task text the config ran on (the record's prompt_version, brief_task.PROMPT_VERSION)"},
               "written": dt.datetime.now().isoformat()}
    ec.dump_json(os.path.join(out_dir, "metrics.json"), metrics)
    write_report(out_dir, metrics, tallies, knobs, disputes, diffs, a)

    # ---- print ------------------------------------------------------------------------------------
    print(f"\nPer company x config: correct / wrong / unknown / gap" + (" (from the truth file's recorded grades)" if a.no_llm else ""))
    for d in domains:
        if d in ungraded_domains:
            continue
        for cfg in configs:
            rows = [r for r in graded_rows if r["domain"] == d and r["config_id"] == cfg]
            if not rows:
                continue
            t = tally(rows)
            print(f"  {d:22} {cfg:26} {t['correct']:>2} / {t['wrong']:>2} / {t['unknown']:>2}" + (f" + {t['gap']} gap" if t["gap"] else ""))
    if ungraded_domains:
        print(f"  ungraded (no truth): {', '.join(ungraded_domains)}")
    print(f"\nTallies per config (pooled): accuracy on answerable [Wilson 95%], yield, trust, wrong-confident, abstention, $/1k, median s")
    for cfg in configs:
        m = metrics_cfg.get(cfg)
        if not m:
            continue
        p = m["pooled"]
        print(f"  {cfg:26} acc {ec.fmt(p['accuracy'], 1, True):>6} [{ec.fmt(p['wilson_lo'], 1, True)}, {ec.fmt(p['wilson_hi'], 1, True)}]  "
              f"eq-wt {ec.fmt(m['equal_weighted']['accuracy'], 1, True):>6}  yield {ec.fmt(p['yield'], 1, True)}  trust {ec.fmt(p['trust'], 1, True)}  "
              f"wrong-conf {ec.fmt(p['wrong_confident_rate'], 0, True)}  abstain {ec.fmt(p['abstention_rate'], 0, True)}  "
              f"$/1k {ec.fmt(m['usd_per_1k'], 0)}  {ec.fmt(m['latency_median'], 0)}s  all17 {m['all17_companies']}/{m['companies']}")
    if knobs:
        print("\nKnob deltas (B minus A, pp; McNemar exact on discordant cells):")
        for kd in knobs:
            print(f"  {kd['vendor']:11} {kd['B']} - {kd['A']}: {kd['delta_pp']:+.1f} pp on {kd['paired_cells']} cells / {kd['paired_companies']} companies; "
                  f"b={kd['b_A_right_B_wrong']} c={kd['c_A_wrong_B_right']} p={ec.fmt(kd['mcnemar_p'], 3)}")
    if diffs:
        print(f"\n{'Mechanical matcher vs recorded grade' if a.no_llm else 'Adjudicator vs mechanical matcher'}: {len(diffs)} cells differ")
        for d in diffs:
            print(f"  {d['domain']:20} {d['field']:24} {d['config_id']:20} recorded {d['recorded']:18} mechanical {d['mechanical']:8} {d['reason']}")
    elif a.no_llm:
        print("\nMechanical matcher agrees with every recorded grade.")
    if not a.no_llm:
        aa = metrics["auto_accept"]
        print(f"\nAuto-accept rate {ec.fmt(aa['rate'], 1, True)} ({aa['auto_accepted']} consensus + {aa['all_unknown_unfindable']} all-unknown of {len(cells)}); "
              f"audit agreement {ec.fmt(aa['audit_agreement'], 0, True)} on {aa['audited']}; adjudicated {aa['adjudicated']}; grading cost this pass ${grading_cost:.2f}")
    print(f"\n{len(disputes)} disputes -> disputes.csv. Written: {out_dir}/ (truth.csv, cells.csv, tallies.csv, knob_delta.csv, disputes.csv, metrics.json, report.md"
          + (", matcher_diffs.csv" if diffs else "") + ")")


def mechanical_grade(field: str, ans: Dict[str, Any], t: Dict[str, Any]) -> Tuple[str, str]:
    # an asserted empty list on a set-valued field is the claim "none", graded like any claim
    asserted_none = (field in ("compliance_certs", "crm_stack_signal") and ans.get("status") == "asserted"
                     and isinstance(ans.get("value"), list) and not ans.get("value"))
    if t.get("status") == "unfindable":
        if ans.get("status") == "asserted":
            if asserted_none:
                return "correct", "asserted none; no searcher found one"
            return "wrong", "asserted on an unfindable truth (wrong-confident)"
        return "correct", "abstained on an unfindable truth"
    if ans.get("status") != "asserted":
        return "unknown", "honest unknown"
    ok, detail = match(field, ans.get("value"), t.get("value"))
    return ("correct" if ok else "wrong"), detail


def diff_reason(field: str, recorded: str, tag: Optional[str], mech: str, detail: str) -> str:
    if recorded == "gap":
        return f"rule gap left ungraded in the truth file; mechanical says {mech}: {detail}"
    if field == "product_one_liner":
        return "semantic match is the LLM's job; the mechanical matcher counts any assertion correct"
    if recorded == "wrong" and mech == "correct":
        if tag in ("miscitation", "stale"):
            return f"value matched the truth but the cited page did not support it or was stale ({tag}); needs page inspection, not value matching"
        return f"value matched mechanically but was graded wrong:{tag}; {detail}"
    if recorded == "correct" and mech == "wrong":
        return f"graded correct on inspection but the mechanical rule does not match: {detail}"
    if recorded == "unknown" and mech != "unknown":
        return f"recorded unknown; mechanical {mech}: {detail}"
    return f"{detail}"


def write_report(out_dir, metrics, tallies, knobs, disputes, diffs, a) -> None:
    L = [f"# Grading report: {os.path.basename(out_dir.rstrip('/'))}", "",
         f"Mode: {metrics['mode']}" + (f"; adjudicator {metrics['adjudicator_model']}" if metrics.get("adjudicator_model") else "")
         + f"; runs {', '.join(metrics['runs'])}; {metrics['companies']} companies, {metrics['cells']} cells, configs {', '.join(metrics['configs'])}.", ""]
    pv = metrics.get("prompt_versions") or {}
    if pv:
        L += ["Prompt version per config: " + ", ".join(f"{c} {v}" for c, v in pv.items() if v) + ".", ""]
    sv = metrics.get("score_views") or {}
    if sv.get("rows"):
        L += ["## Headline: right, wrong and blank per 100 graded facts, and the net score", "",
              "Right = correct, incl. an honest unknown on an unfindable truth; wrong = wrong, incl. an assertion on an unfindable truth; "
              "blank = unknown on a known truth. Net = right minus the cost of a wrong answer, in blanks. 95% interval by paired bootstrap over companies.", "",
              "| config | prompt | graded | right | wrong | blank | net, wrong costs 0 | net, costs 1 | 95% interval | net, costs 2 | net, costs 3 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sv["rows"]:
            L.append(f"| {r['config']} | {pv.get(r['config'], '')} | {r['graded']} | {r['right_per_100']} | {r['wrong_per_100']} | {r['blank_per_100']} | "
                     f"{r['net_0']} | **{r['net_1']}** | {r['net_1_lo']} to {r['net_1_hi']} | {r['net_2']} | {r['net_3']} |")
        L += ["", "Rank at each cost of a wrong answer, best first:", ""]
        for p_, order in sv["ranks"].items():
            L.append(f"- costs {p_}: " + ", ".join(f"{c} ({n})" for c, n in order))
        if sv.get("pairs"):
            L += ["", "Paired net-score differences (wrong costs 1), second minus first:", "",
                  "| first | second | difference | 95% interval | clear of zero |", "|---|---|---|---|---|"]
            for q in sv["pairs"]:
                L.append(f"| {q['first']} | {q['second']} | {q['diff_net_1']:+.1f} | {q['lo']:+.1f} to {q['hi']:+.1f} | {'yes' if q['clear_of_zero'] else 'no'} |")
        L.append("")
    mr = metrics.get("miss_rate_findable") or {}
    if mr:
        L += ["## Miss rate on findable facts", "",
              "Findable = truth known and some config graded correct with a supported citation. Miss = this config answered unknown.", "",
              "| config | all | positive truth | negative truth (false, none, empty) |", "|---|---|---|---|"]
        for cfg in metrics["configs"]:
            m = mr.get(cfg)
            if not m:
                continue
            cell = lambda part: (f"{ec.fmt(m[part]['miss_rate'], 1, True)} ({m[part]['missed']}/{m[part]['findable']})" if part in m else "")
            L.append(f"| {cfg} | {cell('all')} | {cell('positive')} | {cell('negative')} |")
        L.append("")
    if metrics.get("prior_truth"):
        pt = metrics["prior_truth"]
        L += ["## Prior-truth mode", "",
              f"Prior truth `{pt.get('prior_truth')}`: {pt.get('kept_cells')} asserted cells kept on it (plus all-unknown cells on a known prior truth, "
              f"{metrics.get('prior_kept_cells', 0)} kept in all); {pt.get('judge_cells')} cells to the judge ({pt.get('why')}); "
              f"{pt.get('new_candidates_agree')} new candidates agreed with a known truth and passed the citation check; "
              f"{pt.get('uncited_new_assertions')} uncited new assertions graded wrong under the record-schema rule. "
              "A candidate the prior pass already graded (same status, value and citations) keeps its prior grade unless its cell went to the judge.", ""]
    if metrics.get("uncited_rule_overrides"):
        L += [f"Uncited rule: {len(metrics['uncited_rule_overrides'])} assertion(s) with no citation that the judge graded correct are graded wrong:miscitation: "
              + "; ".join(f"{o['domain']} {o['field']} {o['config_id']}" for o in metrics["uncited_rule_overrides"]) + ".", ""]
    L += ["## Accuracy: yield times trust (pooled, accuracy on answerable cells; equal-weighted band mean beside it)", "",
          "| config | accuracy | Wilson 95% | equal-weighted | bootstrap 95% | yield | trust | wrong-confident | abstention | $/1k | median s | all 17 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for cfg, m in metrics["per_config"].items():
        p = m["pooled"]
        e = m["equal_weighted"]
        L.append(f"| {cfg} | {ec.fmt(p['accuracy'], 1, True)} | [{ec.fmt(p['wilson_lo'], 1, True)}, {ec.fmt(p['wilson_hi'], 1, True)}] | "
                 f"{ec.fmt(e['accuracy'], 1, True)} | [{ec.fmt(e['ci_lo'], 1, True)}, {ec.fmt(e['ci_hi'], 1, True)}] | {ec.fmt(p['yield'], 1, True)} | "
                 f"{ec.fmt(p['trust'], 1, True)} | {ec.fmt(p['wrong_confident_rate'], 0, True)} | {ec.fmt(p['abstention_rate'], 0, True)} | "
                 f"{ec.fmt(m['usd_per_1k'], 0)} | {ec.fmt(m['latency_median'], 0)} | {m['all17_companies']}/{m['companies']} |")
    L += ["", "## Metric definitions", ""]
    L += [f"- **{k}**: {v}" for k, v in metrics["definitions"].items()]
    L += ["", "## By band", "", "| config | band | cells | answerable | correct | wrong | unknown | gap | accuracy | Wilson 95% |", "|---|---|---|---|---|---|---|---|---|---|"]
    for t in tallies:
        if t["slice"] in ("pooled", "equal_weighted"):
            continue
        L.append(f"| {t['config_id']} | {t['slice']} | {t['n_cells']} | {t['answerable']} | {t['correct']} | {t['wrong']} | {t['unknown']} | {t['gap']} | "
                 f"{ec.fmt(t['accuracy'], 1, True)} | [{ec.fmt(t['wilson_lo'], 1, True)}, {ec.fmt(t['wilson_hi'], 1, True)}] |")
    if knobs:
        L += ["", "## Knob delta (B minus A)", "", "| vendor | A | B | acc A | acc B | delta pp | b | c | McNemar p | paired cells | companies |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for kd in knobs:
            L.append(f"| {kd['vendor']} | {kd['A']} | {kd['B']} | {ec.fmt(kd['accuracy_A'], 1, True)} | {ec.fmt(kd['accuracy_B'], 1, True)} | {kd['delta_pp']:+.1f} | "
                     f"{kd['b_A_right_B_wrong']} | {kd['c_A_wrong_B_right']} | {ec.fmt(kd['mcnemar_p'], 3)} | {kd['paired_cells']} | {kd['paired_companies']} |")
    aa = metrics["auto_accept"]
    L += ["", "## Truth provenance", "",
          f"Auto-accept rate {ec.fmt(aa['rate'], 1, True)}: {aa['auto_accepted']} consensus cells + {aa['all_unknown_unfindable']} all-unknown (unfindable by consensus) "
          f"of {metrics['cells']}; {aa['adjudicated']} adjudicated; {aa['audited']} auto-accepted cells audited, agreement {ec.fmt(aa['audit_agreement'], 0, True)}. "
          f"Grading cost this pass ${metrics['grading_cost_usd_this_pass']:.2f}.", "",
          f"Disputes: {len(disputes)} (disputes.csv). " + (f"Matcher differences: {len(diffs)} (matcher_diffs.csv)." if diffs else "")]
    if metrics.get("ungraded_companies"):
        L += ["", f"Ungraded (no truth): {', '.join(metrics['ungraded_companies'])}"]
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
