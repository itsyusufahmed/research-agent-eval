#!/usr/bin/env python3
"""Parallel Task, flat-schema arm of the research-agents eval.

The nested arm (run_parallel_task.py, configs parallel-core-A-v1 / pro-B-v1 / ultra-C-v1) sends
the shared nested schema: status, value, citations and notes under each of the 17 facts, which
Parallel's validator counts as 90 properties; it answers that shape with "This task may be too
complex for <processor> processor" plus a warning per field that `citations` duplicates the
per-field basis. This client runs the same task on the shape Parallel's best practices describe:
one top-level property per answer, 20 in all, and the run's `basis` (per-field citations,
reasoning, confidence) as the receipt. The flat rows are published beside the nested rows.

What is the same as run_parallel_task.py (imported, not copied: submit, poll, key loading,
prices, size check, vendor clock):
  - POST /v1/tasks/runs, one company per run, processors core, pro, ultra.
  - `input` is brief_task.task_prompt(name, domain, "2026-11-09"), byte-identical to the nested
    run. The run date in the text is fixed at 2026-11-09 whatever the launch time, so the time
    windows and the adjudicated truth still apply; the real launch time is in the manifest.
  - No source_policy, no webhook, no MCP servers, no beta header, enable_events left unset.
  - metadata: domain, config_id, run_date, prompt_version.

What differs:
  - Config ids parallel-core-flat-v1, parallel-pro-flat-v1, parallel-ultra-flat-v1.
  - task_spec.output_schema: flat_schema(), 20 top-level properties, no nesting. The 17 facts in
    brief_task.FIELDS order, hq_location split into hq_city and hq_country, last_funding split
    into funding_stage, funding_date (YYYY-MM) and funding_amount_usd. Every property required,
    additionalProperties false, every type a union with null, no validation keywords. No status,
    citations, notes, reasoning or confidence fields. Each description is the question text from
    brief_task.FIELDS plus "Null means unknown." (the split parts also say which part they are).
  - normalize_flat() maps the flat output and the basis into a brief_schema.json record, so the
    existing grader reads it unchanged. Rules (also written to the manifest):
      null value                         -> status unknown
      anything else                      -> status asserted
      hq_location                        -> asserted only when hq_city and hq_country are both non-null
      last_funding                       -> asserted when funding_stage is non-null (a null date or
                                            amount is allowed; the grader scores it as a partial
                                            answer); brief_task's rule maps "bootstrapped" and its
                                            kin to "none"
      citations                          -> the URLs in the basis entry for that property, plus the
                                            per-element entries of a list (field.0, field.1, ...),
                                            and for the two split facts the union across their parts
      notes                              -> the basis reasoning
    The raw response, basis included, is stored untouched under raw/.

Spend: list price per processor (core $0.025, pro $0.10, ultra $0.30 a run; failed runs are not
billed). CAP_USD is a hard cap across every runs/*flat-parallel* folder, the published one
included: a batch that would cross it is refused (--cap-usd raises it). The account is prepaid:
an HTTP 402 stops submission at once, the runs already accepted are collected, and the script
exits 2. No retry, no top-up.

Key: PARALLEL_API_KEY from the environment or the repo-root .env (eval_common.env_key).

Usage:
  python3 run_parallel_flat.py --print-schema                                   # schema + property count
  python3 run_parallel_flat.py --smoke                                          # plan: 3 companies x 3 processors
  python3 run_parallel_flat.py --smoke --yes                                    # $1.28 at list
  python3 run_parallel_flat.py --run 2026-11-10-v1-flat-parallel --csv scored_120.csv         # plan ($51 at list)
  python3 run_parallel_flat.py --run 2026-11-10-v1-flat-parallel --csv scored_120.csv --yes   # spend
  python3 run_parallel_flat.py --run 2026-11-10-v1-flat-parallel --summary      # tables only, no API calls
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import glob
import json
import os
import re
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.parse

import brief_task
import run_parallel_task as rpt

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = rpt.BASE
RUN_DATE = "2026-11-09"          # the date in the task text; fixed so the windows and the truth still apply
PROMPT_VERSION = brief_task.PROMPT_VERSION   # set from --prompt-version in main
PRICE = {p: rpt.PRICE[p] for p in ("core", "pro", "ultra")}
CONFIG_ID = {"core": "parallel-core-flat-v1", "pro": "parallel-pro-flat-v1", "ultra": "parallel-ultra-flat-v1"}
CAP_USD = 55.0
SMOKE_COMPANIES = "colabsoftware.com,amplifai.com,advocate.app"   # scored_120.csv: the first rich, medium and thin company
BAND_ORDER = rpt.BAND_ORDER
NULL_CLAUSE = "Null means unknown."

# record fact -> the flat properties that carry it
SPLIT = {"hq_location": ["hq_city", "hq_country"],
         "last_funding": ["funding_stage", "funding_date", "funding_amount_usd"]}
PART = {"hq_city": ("string", "the city"), "hq_country": ("string", "the country"),
        "funding_stage": ("string", "the stage"), "funding_date": ("string", "the date as YYYY-MM"),
        "funding_amount_usd": ("number", "the amount in USD")}
KIND = {fid: kind for fid, kind, _ in brief_task.FIELDS}

MAPPING_RULES = [
    "A null value is status unknown; anything else is status asserted.",
    "hq_location is asserted only when hq_city and hq_country are both non-null; value is {city, country}.",
    "last_funding is asserted when funding_stage is non-null; a null funding_date or funding_amount_usd is "
    "allowed and graded as a partial answer; brief_task._norm_value maps none / bootstrapped / self-funded stages to \"none\" "
    "and trims a YYYY-MM-DD date to YYYY-MM.",
    "citations are the URLs in the run's basis entry for the property, plus the per-element entries of a list "
    "property (field.0, field.1, ...); for hq_location and last_funding, the union across their parts. "
    "An unknown carries no citations (brief_schema.json).",
    "notes carry the basis reasoning for the property (each part labelled when there is more than one entry).",
    "The raw response, basis included, is stored untouched under raw/.",
]


def config_id(proc: str) -> str:
    return CONFIG_ID[proc]   # parallel-core-flat-v1


# ---- the flat schema ----------------------------------------------------------------

def _prop(kind: str, desc: str) -> dict:
    if kind == "string":
        s = {"type": ["string", "null"]}
    elif kind == "bool":
        s = {"type": ["boolean", "null"]}
    elif kind == "list":
        s = {"type": ["array", "null"], "items": {"type": "string"}}
    elif kind == "band":
        s = {"type": ["string", "null"], "enum": list(brief_task.BANDS) + [None]}
    elif kind == "year":
        s = {"type": ["integer", "null"]}
    elif kind == "number":
        s = {"type": ["number", "null"]}
    else:
        raise ValueError(kind)
    s["description"] = desc
    return s


def flat_schema() -> dict:
    props = {}
    for fid, kind, q in brief_task.FIELDS:
        question = brief_task.question_text(fid, "the run date", PROMPT_VERSION)    # same wording as the nested schema's descriptions
        if fid in SPLIT:
            for p in SPLIT[fid]:
                pkind, what = PART[p]
                props[p] = _prop(pkind, f"{question} This property is {what}. {NULL_CLAUSE}")
        else:
            props[fid] = _prop(kind, f"{question} {NULL_CLAUSE}")
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def count_properties(s) -> int:
    """Properties at every level, the way the validator's 90 for the nested schema is reached."""
    if isinstance(s, dict):
        n = len(s["properties"]) if isinstance(s.get("properties"), dict) else 0
        return n + sum(count_properties(v) for v in s.values())
    if isinstance(s, list):
        return sum(count_properties(v) for v in s)
    return 0


def task_spec() -> dict:
    return {"output_schema": {"type": "json", "json_schema": flat_schema()}}


def body_for(c: dict, proc: str) -> dict:
    return {"input": brief_task.task_prompt(c["name"], c["domain"], RUN_DATE, PROMPT_VERSION),
            "processor": proc,
            "task_spec": task_spec(),
            "metadata": {"domain": c["domain"], "config_id": config_id(proc),
                         "run_date": RUN_DATE, "prompt_version": PROMPT_VERSION}}


# ---- normalizer: flat output + basis -> brief_schema.json record -----------------------

def basis_index(result: dict) -> dict:
    """Basis entries grouped by top-level property: 'named_customers' and 'named_customers.0' both
    sit under 'named_customers', the whole-field entry first, then the elements in order."""
    idx: dict = {}
    for b in ((result or {}).get("output") or {}).get("basis") or []:
        if isinstance(b, dict) and isinstance(b.get("field"), str):
            m = re.match(r"^([A-Za-z0-9_]+)(.*)$", b["field"])
            if m:
                idx.setdefault(m.group(1), []).append((m.group(2), b))

    def order(item):
        rest = item[0]
        n = re.search(r"(\d+)", rest)
        return (0 if not rest else 1, int(n.group(1)) if n else 0)

    return {k: [b for _, b in sorted(v, key=order)] for k, v in idx.items()}


def _receipts(idx: dict, props: list) -> tuple:
    urls, reasons = [], []
    for p in props:
        for b in idx.get(p, []):
            for c in b.get("citations") or []:
                u = c.get("url") if isinstance(c, dict) else None
                if isinstance(u, str) and u.startswith("http") and u not in urls:
                    urls.append(u)
            r = b.get("reasoning")
            if isinstance(r, str) and r.strip():
                reasons.append((b["field"], r.strip()))
    if len(reasons) == 1 and len(props) == 1:
        notes = reasons[0][1]
    else:
        notes = " | ".join(f"{f}: {r}" for f, r in reasons)
    return urls, notes


def normalize_flat(content: dict, result: dict, *, company: str, domain: str, config: str,
                   cost_usd=None, latency_seconds=None) -> dict:
    content = content if isinstance(content, dict) else {}
    idx = basis_index(result)
    answers = {}
    for fid in brief_task.FIELD_IDS:
        props = SPLIT.get(fid, [fid])
        if not any(p in content for p in props):
            answers[fid] = {"status": "unknown", "value": None, "citations": [],
                            "notes": "normalizer: field missing from vendor output"}
            continue
        urls, notes = _receipts(idx, props)
        extra = ""
        if fid == "hq_location":
            city, country = content.get("hq_city"), content.get("hq_country")
            asserted = city is not None and country is not None
            value = brief_task._norm_value("location", {"city": city, "country": country}) if asserted else None
            if not asserted and (city is not None or country is not None):
                extra = (f"normalizer: partial location recorded as unknown (hq_city={json.dumps(city)}, "
                         f"hq_country={json.dumps(country)})")
        elif fid == "last_funding":
            stage, date, amount = (content.get(p) for p in SPLIT[fid])
            asserted = stage is not None
            value = (brief_task._norm_value("funding", {"stage": stage, "date": date, "amount_usd": amount})
                     if asserted else None)
            if not asserted and (date is not None or amount is not None):
                extra = (f"normalizer: no stage, so recorded as unknown (funding_date={json.dumps(date)}, "
                         f"funding_amount_usd={json.dumps(amount)})")
        else:
            value = content.get(fid)
            asserted = value is not None
        if asserted:
            ans = {"status": "asserted", "value": value, "citations": urls}
        else:
            ans = {"status": "unknown", "value": None, "citations": []}
        notes = " | ".join(x for x in (extra, notes) if x)
        if notes:
            ans["notes"] = notes
        answers[fid] = ans
    rec = {"schema_version": "v0", "company": company, "domain": domain, "config_id": config,
           "track": "managed", "run_date": RUN_DATE, "prompt_version": PROMPT_VERSION, "answers": answers}
    if cost_usd is not None:
        rec["cost_usd"] = cost_usd
    if latency_seconds is not None:
        rec["latency_seconds"] = round(latency_seconds, 1)
    return rec


# ---- checks the flat shape needs --------------------------------------------------------

_UNKNOWNISH = re.compile(
    r"^\s*(unknown|unk|n/?a|not (found|available|known|disclosed|specified|public|publicly (disclosed|available|stated))"
    r"|null|undisclosed|unspecified|no (data|information)|tbd|\?+|-+)\s*\.?\s*$", re.I)


def flat_checks(content: dict) -> dict:
    """Guesses dressed as answers, and split facts that came back half-filled."""
    content = content if isinstance(content, dict) else {}
    stringy = []
    for p, v in content.items():
        if p == "funding_stage":
            continue                                   # "none" is a real answer there
        vals = v if isinstance(v, list) else [v]
        if any(isinstance(x, str) and (_UNKNOWNISH.match(x) or not x.strip()) for x in vals):
            stringy.append(p)
    stage = content.get("funding_stage")
    if isinstance(stage, str) and (not stage.strip() or re.match(r"^\s*(unknown|n/?a|undisclosed|null)\s*$", stage, re.I)):
        stringy.append("funding_stage")
    city, country = content.get("hq_city"), content.get("hq_country")
    return {"string_unknowns": stringy,
            "partial_hq": int((city is None) != (country is None)),
            "funding_no_stage": int(stage is None and (content.get("funding_date") is not None
                                                       or content.get("funding_amount_usd") is not None)),
            "raised_18mo": content.get("raised_18mo", "missing")}


def warning_kind(w: dict) -> str:
    msg = (w or {}).get("message") or ""
    if "may be too complex" in msg:
        return "too_complex"
    if "already provided in the FieldBasis" in msg:
        return "duplicates_basis"
    if "enable_events" in msg:
        return "enable_events_default"
    return "other: " + msg[:120]


# ---- spend ------------------------------------------------------------------------------

def spent_at_list() -> float:
    """List-price spend across every flat run folder: finished runs at their recorded cost
    (0 for a failed run), runs still in flight at their processor's price."""
    total = 0.0
    for d in glob.glob(os.path.join(HERE, "runs", "*flat-parallel*")):
        sp = os.path.join(d, "state.json")
        if not os.path.exists(sp):
            continue
        for t, s in json.load(open(sp)).items():
            rp = os.path.join(d, "records", t + ".json")
            if os.path.exists(rp):
                total += json.load(open(rp)).get("cost_usd") or 0.0
            else:
                total += PRICE.get(s.get("processor"), 0.0)
    return total


# ---- summary ----------------------------------------------------------------------------

def _med(xs, nd=2):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return f"{statistics.median(xs):.{nd}f}" if xs else "?"


def _mean(xs, nd=1):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return f"{statistics.mean(xs):.{nd}f}" if xs else "?"


def summarize(run_dir: str, per_run: bool = True) -> None:
    rec_dir = os.path.join(run_dir, "records")
    if not os.path.isdir(rec_dir) or not os.listdir(rec_dir):
        print("no records yet")
        return
    manifest = json.load(open(os.path.join(run_dir, "manifest.json")))
    state = json.load(open(os.path.join(run_dir, "state.json")))
    meta = {r["domain"]: r for r in csv.DictReader(open(os.path.join(HERE, manifest["csv"])))}
    rows, extra = [], {}
    for fn in sorted(os.listdir(rec_dir)):
        rec = json.load(open(os.path.join(rec_dir, fn)))
        t = brief_task.tally(rec)
        errs = brief_task.validate(rec)
        m = meta.get(rec["domain"], {})
        raw_path = os.path.join(run_dir, "raw", fn)
        raw = json.load(open(raw_path)) if os.path.exists(raw_path) else {}
        run = raw.get("run") or {}
        vsecs = rpt.vendor_seconds(run)
        failed = 1 if run.get("status") != "completed" else 0
        rows.append({"domain": rec["domain"], "band": m.get("band", "?"), "third": m.get("source_third", "?"),
                     "config": rec["config_id"], "cost_usd": rec.get("cost_usd"),
                     "latency_s": rec.get("latency_seconds"), "vendor_s": round(vsecs, 1) if vsecs else None,
                     **t, "schema_errors": len(errs), "failed": failed})
        x = extra.setdefault(rec["config_id"], {
            "high": 0, "medium": 0, "low": 0, "none": 0, "unknown_low": 0, "unknown_other": 0,
            "string_unknowns": collections.Counter(), "partial_hq": 0, "funding_no_stage": 0,
            "raised": collections.Counter(), "errs_citation_only": 0, "errs_other": 0, "err_examples": [],
            "failed": []})
        if failed:
            x["failed"].append(f"{rec['domain']}: {run.get('status')} {json.dumps(run.get('error'))[:200]}")
            continue
        content = rpt.content_of(raw.get("result") or {}) or {}
        fc = flat_checks(content)
        for p in fc["string_unknowns"]:
            x["string_unknowns"][p] += 1
        x["partial_hq"] += fc["partial_hq"]
        x["funding_no_stage"] += fc["funding_no_stage"]
        x["raised"][{True: "true", False: "false", None: "null"}.get(fc["raised_18mo"], "other")] += 1
        idx = basis_index(raw.get("result") or {})
        for fid, ans in rec["answers"].items():
            levels = [b.get("confidence") for p in SPLIT.get(fid, [fid]) for b in idx.get(p, [])[:1]]
            levels = [l for l in levels if l in ("high", "medium", "low")]
            level = min(levels, key=["low", "medium", "high"].index) if levels else "none"   # weakest part
            if ans.get("status") == "asserted":
                x[level] += 1
            else:
                x["unknown_low" if level == "low" else "unknown_other"] += 1
        # a schema error on an asserted answer with no basis citation is the missing receipt, nothing else
        nocite = {fid for fid, a in rec["answers"].items() if a.get("status") == "asserted" and not a.get("citations")}
        for e in errs:
            fid = e.split(":", 1)[0].split("/")[-1]
            if fid in nocite:
                x["errs_citation_only"] += 1
            else:
                x["errs_other"] += 1
                if len(x["err_examples"]) < 6:
                    x["err_examples"].append(f"{rec['domain']} {e[:140]}")
    rows.sort(key=lambda r: (r["config"], BAND_ORDER.get(r["band"], 9), r["domain"]))
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    if per_run:
        print(f"{'domain':24} {'band':6} {'config':20} {'cost':>6} {'secs':>6} {'vend_s':>6} {'assert':>6} {'unk':>4} {'nocite':>6} {'schErr':>6}")
        for r in rows:
            cost = f"{r['cost_usd']:.3f}" if isinstance(r["cost_usd"], (int, float)) else "?"
            secs = f"{r['latency_s']:.0f}" if isinstance(r["latency_s"], (int, float)) else "?"
            vs = f"{r['vendor_s']:.0f}" if isinstance(r["vendor_s"], (int, float)) else "?"
            print(f"{r['domain']:24} {r['band']:6} {r['config']:20} {cost:>6} {secs:>6} {vs:>6} "
                  f"{r['asserted']:>6} {r['unknown']:>4} {r['asserted_no_cite']:>6} {r['schema_errors']:>6}")

    print("\nPer config x band (n, median secs wall clock / vendor clock, mean asserted and unknown of 17, "
          "asserted with no basis citation, schema errors, failed runs)")
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["config"], r["band"]), []).append(r)
        groups.setdefault((r["config"], "all"), []).append(r)
    order = dict(BAND_ORDER, all=3)
    for (cfg, band), g in sorted(groups.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 9))):
        ok = [x for x in g if not x["failed"]]
        print(f"  {cfg:20} {band:6} n={len(g):<3} secs {_med([x['latency_s'] for x in ok], 0)} / {_med([x['vendor_s'] for x in ok], 0)}  "
              f"asserted {_mean([x['asserted'] for x in ok], 2)}  unk {_mean([x['unknown'] for x in ok], 2)}  "
              f"nocite {sum(x['asserted_no_cite'] for x in ok)}  schErr {sum(x['schema_errors'] for x in g)}  "
              f"failed {sum(x['failed'] for x in g)}")
    total = 0.0
    for cfg in sorted({r["config"] for r in rows}):
        costs = [r["cost_usd"] for r in rows if r["config"] == cfg and isinstance(r["cost_usd"], (int, float))]
        total += sum(costs)
        if costs:
            print(f"  {cfg}: {len(costs)} priced runs, ${sum(costs):.2f} at list")
    print(f"  folder total ${total:.2f} at list; every flat folder ${spent_at_list():.2f} of the ${CAP_USD:.0f} cap")

    print("\nFlat-shape checks per config")
    for cfg, x in sorted(extra.items()):
        su = ", ".join(f"{p} {n}" for p, n in x["string_unknowns"].most_common()) or "none"
        print(f"  {cfg:20} raised_18mo true {x['raised']['true']} / false {x['raised']['false']} / null {x['raised']['null']}"
              f"{' / other ' + str(x['raised']['other']) if x['raised']['other'] else ''}   "
              f"string-unknowns: {su}   half-filled hq {x['partial_hq']}   funding with no stage {x['funding_no_stage']}")
        print(f"  {'':20} basis confidence, asserted: high {x['high']} medium {x['medium']} low {x['low']} no-basis {x['none']}; "
              f"unknown: low {x['unknown_low']} other {x['unknown_other']}   "
              f"schema errors: missing receipt {x['errs_citation_only']}, other {x['errs_other']}")
        for e in x["err_examples"]:
            print(f"  {'':20}   schema error: {e}")
        for e in x["failed"]:
            print(f"  {'':20}   FAILED {e}")

    print("\nValidator warnings at submission, per processor (runs carrying the warning / runs)")
    by_proc: dict = {}
    for t, s in state.items():
        kinds = {warning_kind(w) for w in (s.get("warnings") or [])}
        c = by_proc.setdefault(s["processor"], collections.Counter())
        c["runs"] += 1
        for k in kinds:
            c[k] += 1
        if not kinds:
            c["no_warning"] += 1
    for p in ("core", "pro", "ultra"):
        if p in by_proc:
            c = by_proc[p]
            print(f"  {p:6} " + "  ".join(f"{k} {v}/{c['runs']}" for k, v in sorted(c.items()) if k != "runs"))
    print(f"\nsummary.csv written to {run_dir}/. Records in records/, raw vendor results (run + output.content + output.basis) in raw/.")


# ---- main -------------------------------------------------------------------------------

def main() -> None:
    global PROMPT_VERSION, CAP_USD
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="run folder name under runs/ (must contain 'flat-parallel')")
    ap.add_argument("--csv", default="scored_120.csv", help="company list with name and domain columns")
    ap.add_argument("--processors", default="core,pro,ultra")
    ap.add_argument("--prompt-version", default=brief_task.PROMPT_VERSION, choices=brief_task.PROMPT_VERSIONS,
                    help="task text version, recorded in metadata, the manifest and every record (brief_task.PROMPT_VERSION)")
    ap.add_argument("--cap-usd", type=float, default=CAP_USD,
                    help=f"hard cap at list across every runs/*flat-parallel* folder, the published one included (default {CAP_USD:.0f})")
    ap.add_argument("--companies", default="all", help="all, or comma-separated domains from the csv")
    ap.add_argument("--smoke", action="store_true", help=f"{SMOKE_COMPANIES} from scored_120.csv at core, pro, ultra")
    ap.add_argument("--yes", action="store_true", help="actually call the API and spend")
    ap.add_argument("--summary", action="store_true", help="print the tables for an existing run, no API calls")
    ap.add_argument("--no-per-run", action="store_true", help="summary without the per-run table")
    ap.add_argument("--print-schema", action="store_true", help="print the flat schema and its property count, then exit")
    ap.add_argument("--retry-failed", action="store_true",
                    help="move failed or cancelled runs to failed/ and submit them again (failed runs are not billed)")
    ap.add_argument("--poll-every", type=int, default=15)
    ap.add_argument("--timeout-min", type=int, default=45)
    a = ap.parse_args()
    PROMPT_VERSION = a.prompt_version
    CAP_USD = a.cap_usd

    if a.print_schema:
        s = flat_schema()
        print(json.dumps(s, indent=1))
        n = count_properties(s)
        print(f"\nproperties: {n} (top level {len(s['properties'])}); nested schema (run_parallel_task.py): "
              f"{count_properties(rpt.parallel_schema())}")
        if n != 20 or len(s["properties"]) != 20:
            sys.exit("property count is not 20")
        return
    if a.smoke:
        a.run = a.run or f"{dt.date.today().isoformat()}-smoke-flat-parallel"
        a.companies, a.csv = SMOKE_COMPANIES, "scored_120.csv"
    if not a.run:
        sys.exit("--run is required (or --smoke)")
    if "flat-parallel" not in a.run:
        sys.exit("run folder name must contain 'flat-parallel' (the spend cap counts those folders)")
    run_dir = os.path.join(HERE, "runs", a.run)
    if a.summary:
        summarize(run_dir, per_run=not a.no_per_run)
        return

    procs = a.processors.split(",")
    bad = [p for p in procs if p not in PRICE]
    if bad:
        sys.exit(f"unknown processor(s) {bad}; this arm runs {', '.join(PRICE)}")
    targets = [(c, p) for c in rpt.load_companies(a.csv, a.companies) for p in procs]
    if not targets:
        sys.exit("no companies matched")

    def tag(c, p):
        return f"{c['domain']}__{config_id(p)}"

    state_path = os.path.join(run_dir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}

    def rec_path(t):
        return os.path.join(run_dir, "records", t + ".json")

    if a.retry_failed and a.yes:
        for t in list(state):
            raw_p = os.path.join(run_dir, "raw", t + ".json")
            if os.path.exists(rec_path(t)) and os.path.exists(raw_p):
                if (json.load(open(raw_p)).get("run") or {}).get("status") != "completed":
                    fdir = os.path.join(run_dir, "failed")
                    os.makedirs(fdir, exist_ok=True)
                    stamp = dt.datetime.now().strftime("%H%M%S")
                    shutil.move(raw_p, os.path.join(fdir, f"{t}.raw.{stamp}.json"))
                    shutil.move(rec_path(t), os.path.join(fdir, f"{t}.record.{stamp}.json"))
                    json.dump(state.pop(t), open(os.path.join(fdir, f"{t}.state.{stamp}.json"), "w"), indent=1)
                    print(f"retrying {t} (the failed attempt is kept under failed/)")
        json.dump(state, open(state_path, "w"), indent=1)

    new = [(c, p) for c, p in targets if not os.path.exists(rec_path(tag(c, p))) and tag(c, p) not in state]
    new_cost = sum(PRICE[p] for _, p in new)
    spent = spent_at_list()
    spec = task_spec()
    n_props = count_properties(spec["output_schema"]["json_schema"])
    sizes = rpt.size_check(body_for(targets[0][0], targets[0][1]))
    doms = sorted({c["domain"] for c, _ in targets})
    print(f"Plan: {len(targets)} Parallel Task runs ({', '.join(procs)}) on {len(doms)} companies from {a.csv}; "
          f"{len(new)} to submit; task-text run date {RUN_DATE}")
    print(f"Schema: flat, {n_props} properties. Sizes: {sizes}")
    print(f"List price of the new submissions: ${new_cost:.3f}; flat-arm spend so far ${spent:.3f}; "
          f"after this batch ${spent + new_cost:.3f} of the ${CAP_USD:.2f} cap")
    print(f"Output: {run_dir}/")
    if n_props != 20:
        sys.exit("property count is not 20")
    if spent + new_cost > CAP_USD + 1e-9:
        sys.exit(f"refused: this batch would take the flat arm to ${spent + new_cost:.2f}, over the ${CAP_USD:.2f} cap")
    if not a.yes:
        print("Dry run: nothing sent. Add --yes to spend.")
        return

    key = rpt.load_key()
    os.makedirs(os.path.join(run_dir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "records"), exist_ok=True)
    man_path = os.path.join(run_dir, "manifest.json")
    if not os.path.exists(man_path):
        now = dt.datetime.now().astimezone()
        json.dump({"vendor": "parallel", "endpoint": BASE, "client": "run_parallel_flat.py",
                   "schema_variant": "flat, 20 top-level properties, basis as the receipt",
                   "nested_run": "runs/2026-11-10-v1-nested-parallel",
                   "prompt_version": PROMPT_VERSION,
                   "processors": procs, "config_ids": {p: config_id(p) for p in procs},
                   "csv": a.csv, "run_date": RUN_DATE,
                   "run_date_note": "the date in the task text and the records, fixed at 2026-11-09 so the time "
                                    "windows and the adjudicated truth of the nested run apply; 'started' is the real launch time",
                   "started": now.replace(tzinfo=None).isoformat(),
                   "started_local": now.isoformat(),
                   "started_utc": now.astimezone(dt.timezone.utc).isoformat(),
                   "price_per_run_usd": {p: PRICE[p] for p in procs},
                   "cost_basis": "list price per processor; the Task API returns no per-run cost; failed runs are not billed",
                   "source_policy": None, "webhook": None, "mcp_servers": None, "beta_headers": [],
                   "enable_events": "unset",
                   "property_count": n_props,
                   "mapping_rules": MAPPING_RULES,
                   "task_spec": spec}, open(man_path, "w"), indent=1)

    n_sub, stopped_402 = 0, None
    for c, p in new:
        t = tag(c, p)
        try:
            resp = rpt.call("POST", BASE, key, body_for(c, p))
        except RuntimeError as e:
            if "HTTP 402" in str(e):
                stopped_402 = f"{t}: {e}"
                print(f"HTTP 402 on submit ({t}). The account is out of credit; nothing further is submitted.")
                break
            raise
        if not resp.get("run_id"):
            sys.exit(f"no run_id in create response for {t}: {json.dumps(resp)[:600]}")
        state[t] = {"id": resp["run_id"], "submitted": time.time(), "domain": c["domain"],
                    "name": c["name"], "processor": p, "created_at": resp.get("created_at"),
                    "warnings": resp.get("warnings")}
        json.dump(state, open(state_path, "w"), indent=1)
        n_sub += 1
        kinds = sorted({warning_kind(w) for w in (resp.get("warnings") or [])})
        print(f"submitted {t}: {resp['run_id']} ({resp.get('status')})  warnings={kinds or 'none'}")
    print(f"{n_sub} submitted, {len(state) - n_sub} already in flight or done. Polling every {a.poll_every}s "
          f"for up to {a.timeout_min} min; Ctrl-C is safe, rerun to resume.")

    pending = {t: s for t, s in state.items() if not os.path.exists(rec_path(t))}
    deadline = time.time() + a.timeout_min * 60
    while pending and time.time() < deadline:
        for t, s in list(pending.items()):
            try:
                run = rpt.call("GET", f"{BASE}/{s['id']}", key)
                st = run.get("status")
                if st not in rpt.TERMINAL:
                    continue
                done_at = time.time()
                result = {}
                if st == "completed":
                    result = rpt.call("GET", f"{BASE}/{s['id']}/result?{urllib.parse.urlencode({'timeout': 30})}",
                                      key, timeout=90)
            except (RuntimeError, urllib.error.URLError, OSError) as e:
                if "HTTP 402" in str(e):
                    stopped_402 = stopped_402 or f"{t} (poll): {e}"
                print(f"poll error on {t}, will try again: {str(e)[:200]}")
                continue
            json.dump({"run": run, "result": result}, open(os.path.join(run_dir, "raw", t + ".json"), "w"), indent=1)
            rec = normalize_flat(rpt.content_of(result), result, company=s["name"], domain=s["domain"],
                                 config=config_id(s["processor"]),
                                 cost_usd=PRICE[s["processor"]] if st == "completed" else None,
                                 latency_seconds=done_at - s["submitted"])
            json.dump(rec, open(rec_path(t), "w"), indent=1)
            err = f"  error={json.dumps(run.get('error'))[:200]}" if run.get("error") else ""
            print(f"{st:9} {t}  cost={PRICE[s['processor']] if st == 'completed' else 0}  "
                  f"{round(done_at - s['submitted'])}s wall  ({len(pending) - 1} left){err}")
            del pending[t]
        if pending:
            time.sleep(a.poll_every)
    if pending:
        print(f"\n{len(pending)} still running after {a.timeout_min} min; rerun the same command to keep collecting.")
    print()
    summarize(run_dir, per_run=len(targets) <= 60)
    if stopped_402:
        print(f"\nSTOPPED ON HTTP 402: {stopped_402}\n{len(new) - n_sub} of {len(new)} planned submissions were not sent.")
        sys.exit(2)


if __name__ == "__main__":
    main()
