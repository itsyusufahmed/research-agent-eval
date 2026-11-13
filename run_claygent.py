#!/usr/bin/env python3
"""Claygent arm of the research-agents eval.

One Clay Routines API call per (company, model column): the company's Name and
Domain go in as the two row inputs of a saved Function, the Function runs the
Use AI web-research column built in Configure from claygent_kit/prompt.txt and
claygent_kit/output_schema.json, and a brief_schema.json record comes out through
brief_task.normalize, plus the untouched result item.

Configs:
  claygent-auto-A-v1   the column with Auto on (default since Oct 27; each row routed, billed at the routed model's rate)
  claygent-argon-B-v1  the same column pinned to Argon (3 credits a row, fixed)
  claygent-luna-v1     the same column pinned to GPT 6 Luna (picker: "OpenAI model optimized for cost-sensitive,
                       high-volume workloads", ~0.2 credit a row estimate), Clay's cheapest listed model
Each config is one saved Function (one column) with API access enabled, so the
client takes a function id per config: --functions auto=t_...,argon=t_...,luna=t_...
or claygent_kit/functions.json ({"auto": "t_...", ...}). The API key comes from
CLAY_API_KEY (environment or the repo-root .env); CLAY_API_KEY_AUTO / _ARGON / _LUNA
override it per config. Keys are never printed or written to disk.

API (developers.clay.com/routines/api, read Nov 6 and Nov 8, 2026):
  POST https://api.clay.com/public/v0/routines/function:<id>/run
       header clay-api-key; body {"items": [{"id": "<domain>", "inputs": {"Name": ..., "Domain": ...}}]}
       -> {"routine_run_id": "run_..."}   (1 to 100 items a call; this client sends ONE so wall clock is per company)
  GET  https://api.clay.com/public/v0/routines/run/<routine_run_id>/results
       202 while running: {status: "in_progress", total, finished}
       200 when done:     {status: "complete", total, finished, data: [{id, status: complete|failed, result | error}], cursor?}
The result item names no model and no price, so:
  cost     is merged after the run (--credits CSV of Domain,credits; claygent_raw_meta.py --write
           builds one from the per-row totalCreditsCharged in raw/; one action plus the data
           credits charged to the row, priced at --credit-price and --action-price list rates)
  latency  is wall clock from the POST to the completed GET, one item per call
  model    under Auto is whatever the table shows per row, if anything

Spend gate: without --yes it prints the plan and the worst case and stops. Argon is
3 credits a row; Auto and Luna are variable and unmeasured until the smoke, so the plan
prints Argon in dollars and the others as "variable". --credit-cap stops new submissions
once the projected credits pass it. Resumable: routine_run_ids are kept in
<run>/state.json, finished records are skipped, Ctrl-C is safe.

If the workspace cannot expose Functions, the arm can run by hand in a Clay table built
from the same kit; `--import-export <clay export csv> --model argon` then normalizes the
exported column into records in the same run folder.

Usage:
  python3 run_claygent.py --smoke                                   # plan: one company on argon (3 credits)
  python3 run_claygent.py --smoke --yes --functions argon=t_abc123
  python3 run_claygent.py --run 2026-11-10-v1-claygent --run-date 2026-11-09          # plan: scored_120 x auto+argon+luna
  python3 run_claygent.py --run 2026-11-10-v1-claygent --run-date 2026-11-09 --yes --functions auto=t_...,argon=t_...,luna=t_...
  python3 run_claygent.py --run <name> --credits runs/<name>/credits/argon_credits_fixed.csv --model argon
  python3 run_claygent.py --run <name> --import-export export.csv --model auto --column "Claygent Auto"
  python3 run_claygent.py --run 2026-11-10-v1-claygent --summary
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import brief_task
import eval_common as ec

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.clay.com/public/v0"
CONFIG_ID = {"auto": "claygent-auto-A-v1", "argon": "claygent-argon-B-v1",
             "luna": "claygent-luna-v1"}    # luna: GPT 6 Luna, Clay's cheapest listed model
FIXED_CREDITS = {"argon": 3, "helium": 1}        # university.clay.com/docs/ai-pricing (Nov 6): Argon 3, Helium 1; Auto variable
SMOKE_COMPANY = "colabsoftware.com"              # the first rich company in scored_120.csv
CREDIT_PRICE_DEFAULT = 0.05                     # clay.com/pricing Launch entry rate, about 5 cents a credit (Nov 6 read); override with --credit-price
ACTION_PRICE_DEFAULT = 0.005                    # "under a cent an action"; override with --action-price
FUNCTIONS_FILE = os.path.join(HERE, "claygent_kit", "functions.json")
INPUT_NAMES_DEFAULT = "Name,Domain"             # the two row inputs; must match the Function's input names


def load_key(model: str) -> str:
    k = ec.env_key(f"CLAY_API_KEY_{model.upper()}", required=False)
    return k or ec.env_key("CLAY_API_KEY")


def call(method: str, url: str, key: str, body=None, retries: int = 3, timeout: int = 60):
    """Returns (http_status, json_or_text). 202 is a normal answer here, not an error."""
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "clay-api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:800]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} on {method} {url}: {msg}")
    raise RuntimeError("unreachable")


def parse_functions(arg, file_path=FUNCTIONS_FILE) -> dict:
    out = {}
    if os.path.exists(file_path):
        out.update({k: v for k, v in json.load(open(file_path)).items() if isinstance(v, str)})
    if arg:
        for part in arg.split(","):
            if "=" not in part:
                sys.exit(f"--functions wants model=t_id pairs, got {part!r}")
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    norm = {}
    for k, v in out.items():
        v = v.strip()
        if v.startswith("function:"):
            v = v[len("function:"):]
        norm[k] = v
    return norm


def extract_structured(result, result_key=None):
    """Find the 17-field JSON inside a Function result item; the output's name is the Function's."""
    if not isinstance(result, dict):
        if isinstance(result, str):
            return _parse_json_text(result)
        return None
    if result_key:
        return _coerce(result.get(result_key))
    if sum(1 for f in brief_task.FIELD_IDS if f in result) >= 12:
        return result
    for v in result.values():
        c = _coerce(v)
        if isinstance(c, dict) and sum(1 for f in brief_task.FIELD_IDS if f in c) >= 12:
            return c
    return None


def _coerce(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        return _parse_json_text(v)
    return None


def _parse_json_text(t: str):
    t = t.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t).rstrip("`").strip()
    try:
        j = json.loads(t)
        return j if isinstance(j, dict) else None
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                j = json.loads(m.group(0))
                return j if isinstance(j, dict) else None
            except ValueError:
                return None
    return None


def results_all_pages(run_id: str, key: str):
    """GET results, following cursor until the response carries none."""
    status, body = call("GET", f"{BASE}/routines/run/{run_id}/results", key)
    if status == 202 or (isinstance(body, dict) and body.get("status") != "complete"):
        return status, body, []
    data = list((body or {}).get("data") or [])
    cursor = (body or {}).get("cursor")
    while cursor:
        q = urllib.parse.urlencode({"cursor": cursor, "limit": 100})
        _, more = call("GET", f"{BASE}/routines/run/{run_id}/results?{q}", key)
        data.extend((more or {}).get("data") or [])
        cursor = (more or {}).get("cursor")
    return status, body, data


def item_extras(item) -> dict:
    """Clay's per-row extras inside item.result["<column>"]: credits, cost-cap flag, steps, seconds."""
    res = (item or {}).get("result")
    out = {}
    if isinstance(res, dict):
        for v in [res] + [x for x in res.values() if isinstance(x, dict)]:
            for k in ("totalCreditsCharged", "forcedToFinishEarlyBecauseOfCost", "stepsTaken", "timeTakenInSeconds"):
                if k in v and k not in out:
                    out[k] = v[k]
    c = out.get("totalCreditsCharged")
    try:
        out["credits"] = float(c) if c is not None else None
    except (TypeError, ValueError):
        out["credits"] = None
    out["steps"] = len(out["stepsTaken"]) if isinstance(out.get("stepsTaken"), list) else None
    return out


def make_record(item, s, a, model):
    structured = extract_structured((item or {}).get("result"), a.result_key) if (item or {}).get("status") == "complete" else None
    rec = brief_task.normalize(structured or {}, company=s["name"], domain=s["domain"],
                               config_id=CONFIG_ID[model], run_date=a.run_date,
                               latency_seconds=time.time() - s["submitted"], prompt_version=a.prompt_version)
    return rec


def summarize(run_dir: str) -> None:
    man = ec.load_json(os.path.join(run_dir, "manifest.json"), {})
    meta_dir = os.path.join(run_dir, "meta")

    def extra(tag, rec):
        m = ec.load_json(os.path.join(meta_dir, tag + ".json"), {})
        return {"credits": m.get("credits"), "routed_model": m.get("routed_model"), "item_status": m.get("item_status")}

    rows = ec.summary_rows(run_dir, man.get("csv", "scored_120.csv"), extra)
    ec.write_summary_csv(run_dir, rows)
    ec.print_summary(rows, run_dir, cost_label="usd")
    by = {}
    for r in rows:
        if isinstance(r.get("credits"), (int, float)):
            by.setdefault((r["config"], r["band"]), []).append(r["credits"])
    if by:
        print("\nCredits per row by config x band (the Auto routing distribution): n, min/median/max")
        for (cfg, band), xs in sorted(by.items(), key=lambda kv: (kv[0][0], ec.BAND_ORDER.get(kv[0][1], 9))):
            print(f"  {cfg:18} {band:6} n={len(xs):<3} {min(xs)}/{ec.fmt(ec.median(xs), 1)}/{max(xs)}")
    else:
        print("\nNo credits merged yet: write a Domain,credits CSV (claygent_raw_meta.py --write) and pass --credits <csv> --model <auto|argon|luna>.")


def merge_credits(run_dir: str, a) -> None:
    rows = list(csv.DictReader(open(a.credits)))
    if not rows:
        sys.exit("empty credits csv")
    cols = list(rows[0].keys())
    dom_col = a.credits_domain_col or next((c for c in cols if c.strip().lower() == "domain"), None)
    if not dom_col:
        sys.exit(f"no Domain column in {a.credits}; columns: {cols}. Pass --credits-domain-col.")
    cred_col = a.credits_col or next((c for c in cols if "credit" in c.lower()), None)
    if not cred_col:
        sys.exit(f"no credits column found; pass --credits-col. Columns: {cols}")
    model_col = a.credits_model_col or next((c for c in cols if "model" in c.lower()), None)
    meta_dir = os.path.join(run_dir, "meta")
    os.makedirs(meta_dir, exist_ok=True)
    n = 0
    for r in rows:
        dom = (r.get(dom_col) or "").strip().lower()
        tag = f"{dom}__{CONFIG_ID[a.model]}"
        rp = ec.record_path(run_dir, tag)
        if not os.path.exists(rp):
            continue
        try:
            credits = float(str(r.get(cred_col, "")).strip() or "nan")
        except ValueError:
            credits = float("nan")
        if credits != credits:  # NaN
            continue
        rec = ec.load_json(rp)
        rec["cost_usd"] = round(credits * a.credit_price + a.action_price, 4)
        ec.dump_json(rp, rec)
        meta = ec.load_json(os.path.join(meta_dir, tag + ".json"), {})
        meta.update({"credits": credits, "routed_model": (r.get(model_col) or None) if model_col else None,
                     "credit_price_usd": a.credit_price, "action_price_usd": a.action_price,
                     "credits_source": os.path.basename(a.credits)})
        ec.dump_json(os.path.join(meta_dir, tag + ".json"), meta)
        n += 1
    print(f"merged credits into {n} {CONFIG_ID[a.model]} records from {a.credits} "
          f"(column {cred_col!r}; ${a.credit_price}/credit + ${a.action_price}/action list)")


def import_export(run_dir: str, a) -> None:
    """By-hand path: a Clay table export with the Claygent column's JSON per row -> records."""
    rows = list(csv.DictReader(open(a.import_export)))
    if not rows:
        sys.exit("empty export")
    cols = list(rows[0].keys())
    dom_col = a.credits_domain_col or next((c for c in cols if c.strip().lower() == "domain"), None)
    name_col = next((c for c in cols if c.strip().lower() == "name"), None)
    if not dom_col:
        sys.exit(f"no Domain column; columns: {cols}")
    col = a.column
    if not col:
        for c in cols:
            if any(extract_structured(r.get(c)) for r in rows[:5]):
                col = c
                break
    if not col:
        sys.exit(f"no column parses as the 17-field JSON; pass --column. Columns: {cols}")
    ec.ensure_run_dirs(run_dir)
    ec.write_manifest_once(run_dir, manifest_for(a, [a.model], {}, by_hand=True))
    n = 0
    for r in rows:
        dom = (r.get(dom_col) or "").strip().lower()
        if not dom:
            continue
        structured = extract_structured(r.get(col))
        tag = f"{dom}__{CONFIG_ID[a.model]}"
        ec.dump_json(os.path.join(run_dir, "raw", tag + ".json"), {"export_row": r, "column": col})
        rec = brief_task.normalize(structured or {}, company=(r.get(name_col) or dom) if name_col else dom,
                                   domain=dom, config_id=CONFIG_ID[a.model], run_date=a.run_date,
                                   prompt_version=a.prompt_version)
        ec.dump_json(ec.record_path(run_dir, tag), rec)
        n += 1
    print(f"imported {n} rows from {a.import_export} column {col!r} as {CONFIG_ID[a.model]} (latency: not measured on a table run)")
    summarize(run_dir)


def manifest_for(a, models, functions, by_hand=False) -> dict:
    return {"vendor": "clay", "product": "Claygent, Use AI column (Web research), built in Configure",
            "endpoint": None if by_hand else f"{BASE}/routines/function:<id>/run",
            "by_hand": by_hand, "prompt_version": a.prompt_version,
            "models": models, "config_ids": {m: CONFIG_ID[m] for m in models},
            "function_ids": {m: functions.get(m) for m in models} if not by_hand else None,
            "input_names": a.input_names, "csv": a.csv, "run_date": a.run_date,
            "items_per_call": 1, "started": dt.datetime.now().isoformat(),
            "cost_basis": "1 action + data credits per row, merged after the run (--credits); "
                          f"priced at ${a.credit_price}/credit and ${a.action_price}/action list; Argon 3 credits fixed, Auto and Luna variable",
            "attached": {"business_context": False, "skills": False, "documents": False, "find_contacts_jobs_tool": False,
                         "own_api_key": {m: False for m in models}, "auto_run": False, "run_condition": None,
                         "reuse_saved_data": False},
            "version": "Auto, launched Oct 27, 2026; Clay publishes no version string",
            "prompt_file": "claygent_kit/prompt.txt", "schema_file": "claygent_kit/output_schema.json",
            "vendor_schema": brief_task.vendor_schema()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", default=None, help="run folder name under runs/")
    ap.add_argument("--csv", default="scored_120.csv", help="company list with name and domain columns")
    ap.add_argument("--models", default="auto,argon,luna", help="comma list of auto, argon, luna")
    ap.add_argument("--companies", default="all")
    ap.add_argument("--functions", default=None, help="model=t_id pairs, e.g. auto=t_abc,argon=t_def (or claygent_kit/functions.json)")
    ap.add_argument("--input-names", default=INPUT_NAMES_DEFAULT, help="the Function's two input names, name then domain")
    ap.add_argument("--result-key", default=None, help="the Function output name that holds the JSON (auto-detected if omitted)")
    ap.add_argument("--run-date", default=dt.date.today().isoformat())
    ap.add_argument("--prompt-version", default=brief_task.PROMPT_VERSION, choices=brief_task.PROMPT_VERSIONS,
                    help="task text version the Clay column was built from (claygent_kit.py), recorded in the manifest and every record")
    ap.add_argument("--parallel", type=int, default=5, help="routine runs in flight at once (one item each)")
    ap.add_argument("--poll-every", type=int, default=10)
    ap.add_argument("--timeout-min", type=int, default=60)
    ap.add_argument("--credit-price", type=float, default=CREDIT_PRICE_DEFAULT, help="USD per credit at list (plan entry rate)")
    ap.add_argument("--action-price", type=float, default=ACTION_PRICE_DEFAULT, help="USD per action at list")
    ap.add_argument("--smoke", action="store_true", help=f"1 company ({SMOKE_COMPANY}) on argon")
    ap.add_argument("--yes", action="store_true", help="actually call the API and spend credits")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--credits", default=None, help="Clay table export csv with per-row credits to merge into one model's records")
    ap.add_argument("--credits-col", default=None)
    ap.add_argument("--credits-domain-col", default=None)
    ap.add_argument("--credits-model-col", default=None, help="column naming the routed model per row, if the export has one")
    ap.add_argument("--import-export", default=None, help="by-hand path: Clay export csv whose column holds the JSON per row")
    ap.add_argument("--column", default=None, help="with --import-export: the column holding the JSON")
    ap.add_argument("--model", default=None, help="with --credits or --import-export: auto, argon or luna")
    ap.add_argument("--credit-cap", type=float, default=None,
                    help="stop submitting when credits charged so far plus the projection for every row still in flight "
                         "or to do (per-band mean once a band has 3 rows, else the run mean) pass this; in-flight rows finish")
    ap.add_argument("--cap-min-rows", type=int, default=5, help="rows completed before the projection is trusted")
    a = ap.parse_args()

    if a.smoke:
        a.run = a.run or f"{a.run_date}-smoke-claygent"
        a.models, a.companies, a.csv = "argon", SMOKE_COMPANY, "scored_120.csv"
    if not a.run:
        sys.exit("--run is required (or --smoke)")
    run_dir = ec.run_dir_for(a.run)
    if a.summary:
        summarize(run_dir)
        return
    if a.credits or a.import_export:
        if a.model not in CONFIG_ID:
            sys.exit("--model auto|argon|luna is required with --credits or --import-export")
        if a.credits:
            merge_credits(run_dir, a)
            summarize(run_dir)
        else:
            import_export(run_dir, a)
        return

    models = [m.strip() for m in a.models.split(",") if m.strip()]
    bad = [m for m in models if m not in CONFIG_ID]
    if bad:
        sys.exit(f"unknown model(s) {bad}; known: {', '.join(CONFIG_ID)}")
    companies = ec.load_companies(a.csv, a.companies)
    targets = [(c, m) for c in companies for m in models]
    functions = parse_functions(a.functions)
    names = [x.strip() for x in a.input_names.split(",")]
    if len(names) != 2:
        sys.exit("--input-names wants two names: name column, domain column")

    print(f"Plan: {len(targets)} Claygent runs ({', '.join(models)}) on {len(companies)} companies from {a.csv}; "
          f"run date {a.run_date}; one item per API call, {a.parallel} in flight")
    for m in models:
        fid = functions.get(m)
        fixed = FIXED_CREDITS.get(m)
        if fixed:
            usd = len(companies) * (fixed * a.credit_price + a.action_price)
            print(f"  {m:5} -> {CONFIG_ID[m]:18} function {fid or 'MISSING'}  {fixed} credits + 1 action a row = "
                  f"{len(companies) * fixed} credits, ${usd:.2f} at ${a.credit_price}/credit + ${a.action_price}/action list")
        else:
            print(f"  {m:5} -> {CONFIG_ID[m]:18} function {fid or 'MISSING'}  variable credits (routed per row; unmeasured until the smoke) + 1 action a row")
    missing = [m for m in models if not functions.get(m)]
    print(f"Inputs per item: {{{names[0]!r}: name, {names[1]!r}: domain}}; cost read from the table afterwards (--credits)")
    print(f"Output: {run_dir}/")
    if missing:
        print(f"BLOCKED: no function id for {missing}. Save each column as a Function with API access in the Clay UI "
              f"(Functions > Details > enable API), then pass --functions {','.join(m + '=t_...' for m in missing)} "
              f"or write claygent_kit/functions.json. Needs CLAY_API_KEY in the env or .env.")
    if not a.yes:
        print("Dry run: nothing sent. Add --yes to spend credits.")
        return
    if missing:
        sys.exit("cannot run without the function ids above")
    keys = {m: load_key(m) for m in models}

    ec.ensure_run_dirs(run_dir)
    os.makedirs(os.path.join(run_dir, "meta"), exist_ok=True)
    ec.write_manifest_once(run_dir, manifest_for(a, models, functions))
    state_path = os.path.join(run_dir, "state.json")
    state = ec.load_json(state_path, {})

    def tag(c, m):
        return f"{c['domain']}__{CONFIG_ID[m]}"

    def pending():
        return {t: s for t, s in state.items() if not os.path.exists(ec.record_path(run_dir, t))}

    def collect_once():
        for t, s in list(pending().items()):
            status, body, data = results_all_pages(s["id"], keys[s["model"]])
            if status == 202 or (isinstance(body, dict) and body.get("status") != "complete"):
                continue
            item = next((d for d in data if str(d.get("id")) == s["domain"]), data[0] if data else {})
            done_at = time.time()
            ec.dump_json(os.path.join(run_dir, "raw", t + ".json"), {"run": body, "item": item})
            rec = brief_task.normalize(
                extract_structured(item.get("result"), a.result_key) if item.get("status") == "complete" else {},
                company=s["name"], domain=s["domain"], config_id=CONFIG_ID[s["model"]], run_date=a.run_date,
                latency_seconds=done_at - s["submitted"], prompt_version=a.prompt_version)
            ec.dump_json(ec.record_path(run_dir, t), rec)
            ex = item_extras(item)
            ec.dump_json(os.path.join(run_dir, "meta", t + ".json"),
                         {"routine_run_id": s["id"], "item_status": item.get("status"), "error": item.get("error"),
                          "submitted": s["submitted"], "completed": done_at, "credits": None, "routed_model": None,
                          "credits_live": ex["credits"], "forced_early_cost": ex.get("forcedToFinishEarlyBecauseOfCost"),
                          "steps": ex["steps"], "band": s.get("band")})
            err = f"  error={json.dumps(item.get('error'))[:200]}" if item.get("error") else ""
            live = (f"  {ex['credits']} cr" if ex["credits"] is not None else "") + \
                   (f"  {ex['steps']} steps" if ex["steps"] is not None else "") + \
                   ("  FORCED-EARLY-COST" if ex.get("forcedToFinishEarlyBecauseOfCost") else "")
            print(f"{str(item.get('status')):9} {t}  {round(done_at - s['submitted'])}s wall{live}  ({len(pending()) - 1} left){err}")

    todo = [(c, m) for c, m in targets if tag(c, m) not in state and not os.path.exists(ec.record_path(run_dir, tag(c, m)))]
    n_sub = 0
    capped = False

    def projection():
        """(spent, projected_total, rows_done): credits charged on finished rows of this run's targets, plus
        a per-band mean (run mean until a band has 3 rows) for every row in flight or still to do."""
        wanted = {tag(c, m): c.get("band") for c, m in targets}
        done = []
        for t, band in wanted.items():
            mp = os.path.join(run_dir, "meta", t + ".json")
            if os.path.exists(mp):
                cr = ec.load_json(mp, {}).get("credits_live")
                if isinstance(cr, (int, float)):
                    done.append((band, cr))
        spent = sum(cr for _, cr in done)
        if not done:
            return 0.0, None, 0
        mean = spent / len(done)
        by = {}
        for b, cr in done:
            by.setdefault(b, []).append(cr)
        rate = {b: sum(v) / len(v) for b, v in by.items() if len(v) >= 3}
        rest = [wanted[t] for t in pending()] + [c.get("band") for c, m in todo]
        return spent, spent + sum(rate.get(b, mean) for b in rest), len(done)
    deadline = time.time() + a.timeout_min * 60
    while (todo or pending()) and time.time() < deadline:
        while todo and len(pending()) < a.parallel and not capped:
            if a.credit_cap is not None:
                spent, proj, n_done = projection()
                if proj is not None and n_done >= a.cap_min_rows and proj > a.credit_cap:
                    capped = True
                    print(f"\nCREDIT CAP: {spent:.1f} credits charged on {n_done} rows; projected total {proj:.1f} > cap "
                          f"{a.credit_cap:g}. No new submissions; {len(pending())} in flight will finish; {len(todo)} not run.")
                    break
            c, m = todo.pop(0)
            t = tag(c, m)
            body = {"items": [{"id": c["domain"], "inputs": {names[0]: c["name"], names[1]: c["domain"]}}]}
            # no automatic retry on the create call: Clay can answer 5xx after it has already created (and billed) the run,
            # and a retry then runs the company twice (seen twice in a 9-item smoke). On an error the client
            # exits; rerunning the same command resumes from state.json.
            status, resp = call("POST", f"{BASE}/routines/function:{functions[m]}/run", keys[m], body, retries=0)
            rid = (resp or {}).get("routine_run_id") if isinstance(resp, dict) else None
            if not rid:
                sys.exit(f"no routine_run_id in create response for {t}: HTTP {status} {str(resp)[:600]}")
            state[t] = {"id": rid, "submitted": time.time(), "domain": c["domain"], "name": c["name"], "model": m,
                        "band": c.get("band")}
            ec.dump_json(state_path, state)
            n_sub += 1
            print(f"submitted {t}: {rid}")
        collect_once()
        if capped and not pending():
            break
        if todo or pending():
            time.sleep(a.poll_every)
    if pending():
        print(f"\n{len(pending())} still running after {a.timeout_min} min; rerun the same command to keep collecting.")
    print(f"\n{n_sub} submitted this call. Next: export the table and run --credits <csv> --model <m> to price the rows.")
    if a.credit_cap is not None:
        spent, proj, n_done = projection()
        print(f"Credits charged (live, this run's targets): {spent:.1f} on {n_done} rows; projected for all "
              f"{len(targets)}: {proj if proj is None else round(proj, 1)}; cap {a.credit_cap:g}")
    summarize(run_dir)
    if capped:
        sys.exit(3)


if __name__ == "__main__":
    main()
