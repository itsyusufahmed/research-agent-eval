#!/usr/bin/env python3
"""Exa Agent arm of the research-agents eval.

One Agent API run per (company, effort): the shared task text and flat output
schema from brief_task.py go in, a brief_schema.json record comes out with
cost_usd and latency_seconds, plus the untouched vendor response.

Configs:
  exa-agent-medium-A-v1   effort "medium", fixed $0.10 per run (what customers usually run)
  exa-agent-high-B-v1     effort "high",   fixed $0.50 per run (Exa's own pick for a 17-field brief)
  exa-agent-xhigh-v1      effort "xhigh",  fixed $1.00 per run
  exa-agent-auto-A-v1     effort "auto" under budget.maxCostDollars (--auto-cap); a sidebar, never a
                          scored config
  exa-agent-minimal-smoke-v1  effort "minimal", smoke test only, never a scored config
Fixed efforts send no budget field. Only auto and ultra carry budget.maxCostDollars.

API (exa.ai/docs/reference/agent, read 2026-10-20): POST https://api.exa.ai/agent/runs
returns {id, status:"queued"}; poll GET /agent/runs/{id} until completed, failed
or cancelled. Result in output.structured (schema-validated by Exa),
output.grounding (citations) and costDollars. No systemPrompt is sent: the task
text goes in `query`, so Exa runs on its own defaults; dataSources off; no input.data
rows (one company per run, vendor-confirmed Nov 5).
Exa's limit is 50 active Agent runs per team, so runs are submitted in batches of
--max-active (default 45) and the rest wait for a slot.

Key: EXA_API_KEY from the environment or the repo-root .env (eval_common.env_key).

Spend gate: without --yes it prints the plan and the worst-case list price and stops.
Resumable: submitted run ids are kept in <run>/state.json, so a rerun polls
instead of paying twice; finished records are skipped. Launch it, rerun the same
command later to collect whatever was still running.

Usage:
  python3 run_exa_agent.py --smoke                     # plan for 1 company at minimal
  python3 run_exa_agent.py --smoke --yes               # ~1 cent: checks the API shape
  python3 run_exa_agent.py --run 2026-11-10-v1-exa --csv scored_120.csv --run-date 2026-11-09   # plan: 120 x medium,high,xhigh ($192)
  python3 run_exa_agent.py --run 2026-11-10-v1-exa --csv scored_120.csv --run-date 2026-11-09 --yes
  python3 run_exa_agent.py --run <name> --summary      # tables only, no API calls
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

import brief_task
import eval_common as ec

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.exa.ai/agent/runs"
FIXED_PRICE = {"minimal": 0.012, "low": 0.025, "medium": 0.10, "high": 0.50, "xhigh": 1.00}
CONFIG_ID = {"medium": "exa-agent-medium-A-v1", "high": "exa-agent-high-B-v1", "xhigh": "exa-agent-xhigh-v1",
             "auto": "exa-agent-auto-A-v1", "minimal": "exa-agent-minimal-smoke-v1"}
SCORED = ("medium", "high", "xhigh")
MAX_ACTIVE_DEFAULT = 45  # Exa: 50 active Agent runs per team
TERMINAL = {"completed", "failed", "cancelled"}
BAND_ORDER = {"rich": 0, "medium": 1, "thin": 2}
SMOKE_COMPANY = "colabsoftware.com"   # the first rich company in scored_120.csv


def config_id(effort: str) -> str:
    """exa-agent-high-B-v1; an effort outside CONFIG_ID (ultra) gets exa-agent-<effort>-v1."""
    return CONFIG_ID.get(effort, "exa-agent-" + effort + brief_task.config_suffix())


def load_key() -> str:
    return ec.env_key("EXA_API_KEY")


def call(method: str, url: str, key: str, body: dict | None = None, retries: int = 2) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:600]
            if e.code in (429, 502, 503) and attempt < retries:
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} on {method} {url}: {msg}")
    raise RuntimeError("unreachable")


def cost_of(resp: dict) -> float | None:
    c = resp.get("costDollars")
    if isinstance(c, (int, float)):
        return float(c)
    if isinstance(c, dict):
        for k in ("total", "totalDollars", "amount"):
            if isinstance(c.get(k), (int, float)):
                return float(c[k])
    return None


def structured_of(resp: dict) -> dict | None:
    out = resp.get("output") or {}
    s = out.get("structured")
    if isinstance(s, dict):
        return s
    t = out.get("text")
    if isinstance(t, str):
        try:
            j = json.loads(t)
            return j if isinstance(j, dict) else None
        except ValueError:
            return None
    return None


def load_companies(csv_name: str, arg: str) -> list[dict]:
    rows = list(csv.DictReader(open(os.path.join(HERE, csv_name))))
    if arg == "all":
        return rows
    want = set(arg.split(","))
    return [r for r in rows if r["domain"] in want]


def body_for(c: dict, effort: str, run_date: str, auto_cap: float, prompt_version: str = brief_task.PROMPT_VERSION) -> dict:
    b = {"query": brief_task.task_prompt(c["name"], c["domain"], run_date, prompt_version),
         "outputSchema": brief_task.vendor_schema(prompt_version),
         "effort": effort}
    if effort in ("auto", "ultra"):
        b["budget"] = {"maxCostDollars": auto_cap}
    return b


def _med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return f"{statistics.median(xs):.2f}" if xs else "?"


def _mean(xs, nd=1):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return f"{statistics.mean(xs):.{nd}f}" if xs else "?"


def summarize(run_dir: str) -> None:
    rec_dir = os.path.join(run_dir, "records")
    if not os.path.isdir(rec_dir) or not os.listdir(rec_dir):
        print("no records yet")
        return
    manifest = json.load(open(os.path.join(run_dir, "manifest.json")))
    meta = {r["domain"]: r for r in csv.DictReader(open(os.path.join(HERE, manifest.get("csv", "scored_120.csv"))))}
    rows = []
    for fn in sorted(os.listdir(rec_dir)):
        rec = json.load(open(os.path.join(rec_dir, fn)))
        t = brief_task.tally(rec)
        errs = brief_task.validate(rec)
        m = meta.get(rec["domain"], {})
        rows.append({"domain": rec["domain"], "band": m.get("band", "?"), "third": m.get("source_third", "?"),
                     "config": rec["config_id"], "cost_usd": rec.get("cost_usd"),
                     "latency_s": rec.get("latency_seconds"), **t, "schema_errors": len(errs),
                     "failed": 1 if rec.get("answers", {}).get("product_one_liner", {}).get("notes", "").startswith("normalizer") and t["asserted"] == 0 else 0})
    rows.sort(key=lambda r: (r["config"], BAND_ORDER.get(r["band"], 9), r["domain"]))
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{'domain':22} {'band':6} {'config':20} {'cost':>6} {'secs':>6} {'assert':>6} {'unk':>4} {'nocite':>6} {'schErr':>6}")
    for r in rows:
        cost = f"{r['cost_usd']:.2f}" if isinstance(r["cost_usd"], (int, float)) else "?"
        secs = f"{r['latency_s']:.0f}" if isinstance(r["latency_s"], (int, float)) else "?"
        print(f"{r['domain']:22} {r['band']:6} {r['config']:20} {cost:>6} {secs:>6} "
              f"{r['asserted']:>6} {r['unknown']:>4} {r['asserted_no_cite']:>6} {r['schema_errors']:>6}")

    # the rollup that produces the call observations: per config x band
    print("\nPer config x band (n, cost min/median/max, median secs, mean unknowns of 17, asserted w/o citation, schema errors, empty outputs)")
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["config"], r["band"]), []).append(r)
    for (cfg, band), g in sorted(groups.items(), key=lambda kv: (kv[0][0], BAND_ORDER.get(kv[0][1], 9))):
        costs = [x["cost_usd"] for x in g if isinstance(x["cost_usd"], (int, float))]
        lo = f"{min(costs):.2f}" if costs else "?"
        hi = f"{max(costs):.2f}" if costs else "?"
        print(f"  {cfg:20} {band:6} n={len(g):<3} cost {lo}/{_med(costs)}/{hi}  secs {_med([x['latency_s'] for x in g])}  "
              f"unk {_mean([x['unknown'] for x in g])}  nocite {sum(x['asserted_no_cite'] for x in g)}  "
              f"schErr {sum(x['schema_errors'] for x in g)}  empty {sum(x['failed'] for x in g)}")
    for cfg in sorted({r["config"] for r in rows}):
        g = [r for r in rows if r["config"] == cfg]
        costs = [x["cost_usd"] for x in g if isinstance(x["cost_usd"], (int, float))]
        if costs:
            print(f"  {cfg}: {len(costs)} priced runs, total ${sum(costs):.2f}, "
                  f"mean ${statistics.mean(costs):.3f}/account -> ${1000*statistics.mean(costs):,.0f} per 1,000 accounts")
    print(f"\nsummary.csv written to {run_dir}/. Records are in records/, raw vendor responses in raw/.")
    print("Per-record errors: python3 -c \"import json,brief_task;print(brief_task.validate(json.load(open('<record>'))))\"")


def collect(run_dir: str, state: dict, key: str, a, cid, once: bool = False) -> int:
    """Poll every in-flight run once; write raw + record for each that finished. Returns how many finished."""
    finished = 0
    for t, s in list(state.items()):
        if os.path.exists(os.path.join(run_dir, "records", t + ".json")):
            continue
        resp = call("GET", f"{BASE}/{s['id']}", key)
        st = resp.get("status")
        if st not in TERMINAL:
            continue
        done_at = time.time()
        json.dump(resp, open(os.path.join(run_dir, "raw", t + ".json"), "w"), indent=1)
        rec = brief_task.normalize(
            structured_of(resp) or {}, company=s["name"], domain=s["domain"],
            config_id=cid(s["effort"]), run_date=a.run_date,
            cost_usd=cost_of(resp), latency_seconds=done_at - s["submitted"], prompt_version=a.prompt_version)
        json.dump(rec, open(os.path.join(run_dir, "records", t + ".json"), "w"), indent=1)
        left = sum(1 for x in state if not os.path.exists(os.path.join(run_dir, "records", x + ".json")))
        print(f"{st:9} {t}  cost={cost_of(resp)}  stop={resp.get('stopReason')}  {round(done_at - s['submitted'])}s  ({left} left)")
        finished += 1
    return finished


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="run folder name under runs/")
    ap.add_argument("--csv", default="scored_120.csv", help="company list with name and domain columns")
    ap.add_argument("--efforts", default="medium,high,xhigh",
                    help="comma list of medium, high, xhigh (the scored configs); auto, minimal and ultra run as a sidebar or a smoke test")
    ap.add_argument("--companies", default="all", help="all, or comma-separated domains from the csv")
    ap.add_argument("--auto-cap", type=float, default=1.0,
                    help="budget.maxCostDollars, sent only for auto or ultra (API floor $1); fixed efforts carry no budget")
    ap.add_argument("--max-active", type=int, default=MAX_ACTIVE_DEFAULT, help="runs in flight at once (Exa team limit 50)")
    ap.add_argument("--run-date", default=dt.date.today().isoformat())
    ap.add_argument("--prompt-version", default=brief_task.PROMPT_VERSION, choices=brief_task.PROMPT_VERSIONS,
                    help="task text version, recorded in the manifest and in every record (brief_task.PROMPT_VERSION)")
    ap.add_argument("--smoke", action="store_true", help=f"1 company ({SMOKE_COMPANY}) at effort minimal")
    ap.add_argument("--yes", action="store_true", help="actually call the API and spend")
    ap.add_argument("--summary", action="store_true", help="print the tables for an existing run, no API calls")
    ap.add_argument("--poll-every", type=int, default=20)
    ap.add_argument("--timeout-min", type=int, default=60)
    a = ap.parse_args()

    if a.smoke:
        a.run = a.run or f"{a.run_date}-smoke-exa"
        a.efforts, a.companies, a.csv = "minimal", SMOKE_COMPANY, "scored_120.csv"
    if not a.run:
        sys.exit("--run is required (or --smoke)")
    run_dir = os.path.join(HERE, "runs", a.run)
    if a.summary:
        summarize(run_dir)
        return
    if not os.path.exists(os.path.join(HERE, a.csv)):
        sys.exit(f"{a.csv} not found; pass --csv with a company list (scored_120.csv)")

    efforts = [e.strip() for e in a.efforts.split(",") if e.strip()]
    bad = [e for e in efforts if e not in CONFIG_ID and e != "ultra"]
    if bad:
        sys.exit(f"unknown effort(s) {bad}; known: {', '.join(CONFIG_ID)}, ultra")
    targets = [(c, e) for c in load_companies(a.csv, a.companies) for e in efforts]
    if not targets:
        sys.exit("no companies matched")

    def price(e):
        return a.auto_cap if e in ("auto", "ultra") else FIXED_PRICE.get(e, 0)

    worst = sum(price(e) for _, e in targets)
    doms = sorted({c["domain"] for c, _ in targets})
    print(f"Plan: {len(targets)} Exa Agent runs ({', '.join(efforts)}) on {len(doms)} companies from {a.csv}; run date {a.run_date}")
    per = "; ".join(f"{e} -> {config_id(e)} ${price(e):.2f}/run"
                    + (" (fixed, no budget field)" if e not in ("auto", "ultra") else f" (metered, capped at ${a.auto_cap:.2f})")
                    for e in efforts)
    print(f"Configs: {per}")
    print(f"Worst case at list price: ${worst:.2f}")
    if any(e not in SCORED for e in efforts) and not a.smoke:
        print("NOTE: auto, minimal and ultra are not scored configs; run them only for a sidebar or a smoke test.")
    print(f"Output: {run_dir}/")
    if not a.yes:
        print("Dry run: nothing sent. Add --yes to spend.")
        return

    key = load_key()
    os.makedirs(os.path.join(run_dir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "records"), exist_ok=True)
    state_path = os.path.join(run_dir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    man_path = os.path.join(run_dir, "manifest.json")
    if not os.path.exists(man_path):
        json.dump({"vendor": "exa", "endpoint": BASE, "prompt_version": a.prompt_version, "efforts": efforts,
                   "config_ids": {e: config_id(e) for e in efforts}, "csv": a.csv,
                   "auto_cap": a.auto_cap, "fixed_price_usd": {e: FIXED_PRICE[e] for e in efforts if e in FIXED_PRICE},
                   "cost_basis": "costDollars.total from the response; fixed efforts are flat list price",
                   "system_prompt": None, "data_sources": None, "input_data": None,
                   "run_date": a.run_date, "started": dt.datetime.now().isoformat(),
                   "vendor_schema": brief_task.vendor_schema(a.prompt_version)}, open(man_path, "w"), indent=1)

    cid = config_id

    def tag(c, e):
        return f"{c['domain']}__{cid(e)}"

    def done_already(c, e):
        return os.path.exists(os.path.join(run_dir, "records", tag(c, e) + ".json"))

    def in_flight():
        return sum(1 for t in state if not os.path.exists(os.path.join(run_dir, "records", t + ".json")))

    # submit (skip anything finished or already in flight; respect Exa's active-run limit)
    n_sub = 0
    todo = [(c, e) for c, e in targets if not done_already(c, e) and tag(c, e) not in state]
    while todo:
        while in_flight() >= a.max_active:
            print(f"{in_flight()} runs in flight (limit {a.max_active}); collecting before submitting more...")
            collect(run_dir, state, key, a, cid, once=True)
            time.sleep(a.poll_every)
        c, e = todo.pop(0)
        t = tag(c, e)
        resp = call("POST", BASE, key, body_for(c, e, a.run_date, a.auto_cap, a.prompt_version))
        state[t] = {"id": resp.get("id"), "submitted": time.time(), "domain": c["domain"],
                    "name": c["name"], "effort": e}
        json.dump(state, open(state_path, "w"), indent=1)
        n_sub += 1
        print(f"submitted {t}: {resp.get('id')} ({resp.get('status')})")
    print(f"{n_sub} submitted, {len(state) - n_sub} already in flight or done. Polling every {a.poll_every}s "
          f"for up to {a.timeout_min} min; Ctrl-C is safe, rerun to resume.")

    deadline = time.time() + a.timeout_min * 60
    while in_flight() and time.time() < deadline:
        collect(run_dir, state, key, a, cid, once=True)
        if in_flight():
            time.sleep(a.poll_every)
    if in_flight():
        print(f"\n{in_flight()} still running after {a.timeout_min} min; rerun the same command to keep collecting.")
    print()
    summarize(run_dir)


if __name__ == "__main__":
    main()
