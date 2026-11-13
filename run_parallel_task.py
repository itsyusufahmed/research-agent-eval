#!/usr/bin/env python3
"""Parallel Task arm of the research-agents eval, nested schema.

One Task API run per (company, processor): the shared task text from
brief_task.py goes in as `input`, the shared output schema goes in as
task_spec.output_schema (rewritten into Parallel's JSON Schema dialect, see
parallel_schema()), and a brief_schema.json record comes out with cost_usd and
latency_seconds, plus the untouched vendor result: output.content and
output.basis (Parallel's per-field citations, reasoning and confidence).

Configs:
  parallel-core-A-v1      processor "core"   $0.025 per run, fixed
  parallel-pro-B-v1       processor "pro"    $0.10 per run, fixed
  parallel-ultra-C-v1     processor "ultra"  $0.30 per run, fixed
  parallel-lite-smoke-v1  processor "lite"   $0.005; smoke test only
  any other processor     parallel-<name>-v1 so another processor (base, core2x) can be tried

API (docs.parallel.ai, Task API v1, read 2026-10-24):
  POST https://api.parallel.ai/v1/tasks/runs           {input, processor, task_spec, metadata}
       -> {run_id, status "queued", is_active, processor, created_at, modified_at, warnings}
  GET  https://api.parallel.ai/v1/tasks/runs/{run_id}  status: queued | running | completed | failed | cancelled
  GET  https://api.parallel.ai/v1/tasks/runs/{run_id}/result?timeout=N   (blocks up to N <= 600 s)
       -> {run, output: {type "json", content {...}, basis [{field, citations [{url, excerpts, title}],
                         reasoning, confidence high|medium|low}]}}
  Header x-api-key. The response carries no per-run cost: Task runs are priced flat per
  processor (per 1,000: lite $5, base $10, core $25, core2x $50, pro $100, ultra $300,
  ultra2x $600, ultra4x $1,200, ultra8x $2,400) and failed runs are not billed, so
  cost_usd is the processor's list price. Nothing else is sent: no source_policy (open
  web), no webhook, no beta header, and there is no system prompt to send, so Parallel
  runs on its own defaults with the same task text every vendor gets.

Schema dialect. Parallel requires additionalProperties:false and every property listed
in `required` at every level, caps 100 properties and 5 levels, and rejects the
validation keywords (pattern, minimum, minItems, format, ...). vendor_schema() uses
none of those, so the rewrite is: all-required plus additionalProperties:false, and
`value` and `notes` become null unions (the shared convention "value omitted when
unknown" becomes "value null when unknown"). Field ids, question text, status enum,
band enum and the citations array are identical to the Exa arm's schema.

Prompt version. brief_task.task_prompt and brief_task.vendor_schema get the version
(brief_task.PROMPT_VERSION) explicitly, every config id ends in its short name from
brief_task.config_suffix (parallel-core-A-v1), and the version rides in metadata, in
each record and in the manifest. Importers (run_parallel_flat.py, claygent_kit.py)
call parallel_schema() or task_spec() with no argument and get the same default.

Key: PARALLEL_API_KEY from the environment or the repo-root .env (eval_common.env_key).

Spend gate: without --yes it prints the plan and the worst-case cost and stops.
Resumable: submitted run ids are kept in <run>/state.json, so a rerun polls instead
of paying twice; finished records are skipped. Ctrl-C is safe. The account is prepaid:
an HTTP 402 on submit stops submission at once, the runs already accepted are
collected, and the script exits 2. No retry, no top-up.

Usage:
  python3 run_parallel_task.py --smoke                         # plan: 1 company at lite
  python3 run_parallel_task.py --smoke --yes                   # half a cent: checks the API and the schema dialect
  python3 run_parallel_task.py --run 2026-11-10-v1-nested-parallel --csv scored_120.csv \\
      --run-date 2026-11-09                                     # plan: 120 x core+pro+ultra ($51 at list)
  python3 run_parallel_task.py --run 2026-11-10-v1-nested-parallel --csv scored_120.csv \\
      --run-date 2026-11-09 --yes                               # spend
  python3 run_parallel_task.py --run 2026-11-10-v1-nested-parallel --summary   # tables only, no API calls
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import brief_task
import eval_common as ec

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.parallel.ai/v1/tasks/runs"
PRICE = {"lite": 0.005, "base": 0.01, "core": 0.025, "core2x": 0.05, "pro": 0.10,
         "ultra": 0.30, "ultra2x": 0.60, "ultra4x": 1.20, "ultra8x": 2.40}
CONFIG_ID = {"core": "parallel-core-A-v1", "pro": "parallel-pro-B-v1",
             "ultra": "parallel-ultra-C-v1", "lite": "parallel-lite-smoke-v1"}
TERMINAL = {"completed", "failed", "cancelled"}
TASK_SPEC_MAX, COMBINED_MAX = 15000, 25000   # docs.parallel.ai/task-api/guides/specify-a-task
BAND_ORDER = {"rich": 0, "medium": 1, "thin": 2}
PROMPT_VERSION = brief_task.PROMPT_VERSION   # set from --prompt-version in main; importers keep this default
SMOKE_COMPANY = "colabsoftware.com"          # the first rich company in scored_120.csv


def config_id(proc: str, version: str | None = None) -> str:
    """parallel-core-A-v1; a processor outside CONFIG_ID gets parallel-<processor>-v1."""
    suffix = brief_task.config_suffix(version or PROMPT_VERSION)
    return CONFIG_ID[proc] if proc in CONFIG_ID else f"parallel-{proc}{suffix}"


def load_key() -> str:
    return ec.env_key("PARALLEL_API_KEY")


def call(method: str, url: str, key: str, body: dict | None = None, retries: int = 2, timeout: int = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:800]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} on {method} {url}: {msg}")
    raise RuntimeError("unreachable")


# ---- schema dialect -------------------------------------------------------------

def _nullable(s: dict) -> dict:
    s = dict(s)
    t = s.get("type")
    if isinstance(t, str):
        s["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        s["type"] = list(t) + ["null"]
    if "enum" in s and None not in s["enum"]:
        s["enum"] = list(s["enum"]) + [None]
    return s


def _is_object(s: dict) -> bool:
    t = s.get("type")
    return "properties" in s and (t == "object" or (isinstance(t, list) and "object" in t))


def _strict(s):
    """additionalProperties:false and every property required, at every object level."""
    if not isinstance(s, dict):
        return s
    out = dict(s)
    if _is_object(out):
        props = {k: _strict(v) for k, v in out["properties"].items()}
        out["properties"] = props
        out["required"] = list(props.keys())
        out["additionalProperties"] = False
    if "items" in out:
        out["items"] = _strict(out["items"])
    return out


def parallel_schema(version: str | None = None) -> dict:
    s = copy.deepcopy(brief_task.vendor_schema(version or PROMPT_VERSION))
    for fid, f in s["properties"].items():
        value = f["properties"]["value"]
        if _is_object(value):
            # nested value objects: a field the company may not disclose stays expressible
            for k in ("date", "amount_usd"):
                if k in value["properties"]:
                    value["properties"][k] = _nullable(value["properties"][k])
        f["properties"]["value"] = _nullable(value)
        f["properties"]["notes"] = _nullable(f["properties"]["notes"])
        f["properties"]["citations"]["description"] = (
            "Source URLs whose pages support the answer; empty when status is unknown.")
    return _strict(s)


def task_spec(version: str | None = None) -> dict:
    return {"output_schema": {"type": "json", "json_schema": parallel_schema(version)}}


def body_for(c: dict, proc: str, run_date: str, version: str | None = None) -> dict:
    version = version or PROMPT_VERSION
    return {"input": brief_task.task_prompt(c["name"], c["domain"], run_date, version),
            "processor": proc,
            "task_spec": task_spec(version),
            "metadata": {"domain": c["domain"], "config_id": config_id(proc, version),
                         "run_date": run_date, "prompt_version": version}}


def size_check(body: dict) -> str:
    spec = len(json.dumps(body["task_spec"], separators=(",", ":")))
    inp = len(body["input"])
    msg = f"task_spec {spec:,} of {TASK_SPEC_MAX:,} chars; input {inp:,}; combined {spec + inp:,} of {COMBINED_MAX:,}"
    if spec > TASK_SPEC_MAX or spec + inp > COMBINED_MAX:
        sys.exit(f"over Parallel's size limits: {msg}")
    return msg


# ---- result handling --------------------------------------------------------------

def content_of(result: dict) -> dict | None:
    out = (result or {}).get("output") or {}
    c = out.get("content")
    if isinstance(c, dict):
        return c
    if isinstance(c, str):
        try:
            j = json.loads(c)
            return j if isinstance(j, dict) else None
        except ValueError:
            return None
    return None


def basis_by_field(result: dict) -> dict:
    out = (result or {}).get("output") or {}
    d = {}
    for b in out.get("basis") or []:
        if isinstance(b, dict) and isinstance(b.get("field"), str) and "." not in b["field"]:
            d[b["field"]] = b
    return d


def _iso(ts):
    if not isinstance(ts, str):
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def vendor_seconds(run: dict) -> float | None:
    a, b = _iso(run.get("created_at")), _iso(run.get("modified_at"))
    return (b - a).total_seconds() if a and b else None


def load_companies(csv_name: str, arg: str) -> list[dict]:
    rows = list(csv.DictReader(open(os.path.join(HERE, csv_name))))
    if arg == "all":
        return rows
    want = set(arg.split(","))
    return [r for r in rows if r["domain"] in want]


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
    rows, conf = [], {}
    for fn in sorted(os.listdir(rec_dir)):
        rec = json.load(open(os.path.join(rec_dir, fn)))
        t = brief_task.tally(rec)
        errs = brief_task.validate(rec)
        m = meta.get(rec["domain"], {})
        raw_path = os.path.join(run_dir, "raw", fn)
        raw = json.load(open(raw_path)) if os.path.exists(raw_path) else {}
        vsecs = vendor_seconds((raw.get("run") or {}))
        rows.append({"domain": rec["domain"], "band": m.get("band", "?"), "third": m.get("source_third", "?"),
                     "config": rec["config_id"], "cost_usd": rec.get("cost_usd"),
                     "latency_s": rec.get("latency_seconds"), "vendor_s": round(vsecs, 1) if vsecs else None,
                     **t, "schema_errors": len(errs),
                     "failed": 1 if rec.get("answers", {}).get("product_one_liner", {}).get("notes", "").startswith("normalizer") and t["asserted"] == 0 else 0})
        # Parallel's own basis: confidence per asserted field, and receipts present in basis but not in the schema
        bf = basis_by_field(raw.get("result") or {})
        c = conf.setdefault(rec["config_id"], {"high": 0, "medium": 0, "low": 0, "none": 0,
                                               "unknown_low": 0, "unknown_other": 0, "basis_only_cites": 0})
        for fid, ans in rec.get("answers", {}).items():
            b = bf.get(fid) or {}
            level = b.get("confidence") if b.get("confidence") in ("high", "medium", "low") else "none"
            if ans.get("status") == "asserted":
                c[level] += 1
                if not ans.get("citations") and b.get("citations"):
                    c["basis_only_cites"] += 1
            elif ans.get("status") == "unknown":
                c["unknown_low" if level == "low" else "unknown_other"] += 1
    rows.sort(key=lambda r: (r["config"], BAND_ORDER.get(r["band"], 9), r["domain"]))
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{'domain':22} {'band':6} {'config':22} {'cost':>6} {'secs':>6} {'vend_s':>6} {'assert':>6} {'unk':>4} {'nocite':>6} {'schErr':>6}")
    for r in rows:
        cost = f"{r['cost_usd']:.3f}" if isinstance(r["cost_usd"], (int, float)) else "?"
        secs = f"{r['latency_s']:.0f}" if isinstance(r["latency_s"], (int, float)) else "?"
        vs = f"{r['vendor_s']:.0f}" if isinstance(r["vendor_s"], (int, float)) else "?"
        print(f"{r['domain']:22} {r['band']:6} {r['config']:22} {cost:>6} {secs:>6} {vs:>6} "
              f"{r['asserted']:>6} {r['unknown']:>4} {r['asserted_no_cite']:>6} {r['schema_errors']:>6}")

    print("\nPer config x band (n, cost, median secs wall clock / vendor clock, mean unknowns of 17, asserted w/o citation, schema errors, empty outputs)")
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["config"], r["band"]), []).append(r)
    for (cfg, band), g in sorted(groups.items(), key=lambda kv: (kv[0][0], BAND_ORDER.get(kv[0][1], 9))):
        costs = [x["cost_usd"] for x in g if isinstance(x["cost_usd"], (int, float))]
        print(f"  {cfg:22} {band:6} n={len(g):<3} cost {_med(costs)}  secs {_med([x['latency_s'] for x in g])} / {_med([x['vendor_s'] for x in g])}  "
              f"unk {_mean([x['unknown'] for x in g])}  nocite {sum(x['asserted_no_cite'] for x in g)}  "
              f"schErr {sum(x['schema_errors'] for x in g)}  empty {sum(x['failed'] for x in g)}")
    for cfg in sorted({r["config"] for r in rows}):
        g = [r for r in rows if r["config"] == cfg]
        costs = [x["cost_usd"] for x in g if isinstance(x["cost_usd"], (int, float))]
        if costs:
            print(f"  {cfg}: {len(costs)} priced runs, total ${sum(costs):.2f}, "
                  f"${statistics.mean(costs):.3f}/account list price -> ${1000*statistics.mean(costs):,.0f} per 1,000 accounts")
    print("\nParallel basis per config (asserted fields by Parallel's own confidence; unknowns by confidence; asserted fields whose only receipts sit in basis, not in the schema)")
    for cfg, c in sorted(conf.items()):
        print(f"  {cfg:22} asserted high {c['high']}  medium {c['medium']}  low {c['low']}  no-basis {c['none']}   "
              f"unknown: low {c['unknown_low']}  other {c['unknown_other']}   basis-only receipts {c['basis_only_cites']}")
    print(f"\nsummary.csv written to {run_dir}/. Records are in records/, raw vendor results (run + output.content + output.basis) in raw/.")


def main() -> None:
    global PROMPT_VERSION
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="run folder name under runs/")
    ap.add_argument("--csv", default="scored_120.csv", help="company list with name and domain columns")
    ap.add_argument("--processors", default="core,pro,ultra")
    ap.add_argument("--prompt-version", default=brief_task.PROMPT_VERSION, choices=brief_task.PROMPT_VERSIONS,
                    help="task text version, recorded in metadata, the manifest and every record (brief_task.PROMPT_VERSION)")
    ap.add_argument("--companies", default="all", help="all, or comma-separated domains from the csv")
    ap.add_argument("--run-date", default=dt.date.today().isoformat())
    ap.add_argument("--smoke", action="store_true", help=f"1 company ({SMOKE_COMPANY}) at processor lite")
    ap.add_argument("--yes", action="store_true", help="actually call the API and spend")
    ap.add_argument("--summary", action="store_true", help="print the tables for an existing run, no API calls")
    ap.add_argument("--print-schema", action="store_true", help="print the Parallel-dialect schema and exit")
    ap.add_argument("--poll-every", type=int, default=15)
    ap.add_argument("--timeout-min", type=int, default=45)
    a = ap.parse_args()
    PROMPT_VERSION = a.prompt_version

    if a.print_schema:
        print(json.dumps(parallel_schema(), indent=1))
        return
    if a.smoke:
        a.run = a.run or f"{a.run_date}-smoke-parallel"
        a.processors, a.companies, a.csv = "lite", SMOKE_COMPANY, "scored_120.csv"
    if not a.run:
        sys.exit("--run is required (or --smoke)")
    run_dir = os.path.join(HERE, "runs", a.run)
    if a.summary:
        summarize(run_dir)
        return
    if not os.path.exists(os.path.join(HERE, a.csv)):
        sys.exit(f"{a.csv} not found; pass --csv with a company list (scored_120.csv)")

    procs = a.processors.split(",")
    unknown = [p for p in procs if p not in PRICE]
    if unknown:
        sys.exit(f"unknown processor(s) {unknown}; known: {', '.join(PRICE)}")
    targets = [(c, p) for c in load_companies(a.csv, a.companies) for p in procs]
    if not targets:
        sys.exit("no companies matched")
    worst = sum(PRICE[p] for _, p in targets)
    doms = sorted({c["domain"] for c, _ in targets})
    sizes = size_check(body_for(targets[0][0], targets[0][1], a.run_date))
    print(f"Plan: {len(targets)} Parallel Task runs ({', '.join(procs)}) on {len(doms)} companies from {a.csv}; run date {a.run_date}")
    print(f"Prompt version {PROMPT_VERSION}; config ids " + ", ".join(config_id(p) for p in procs))
    print(f"Worst case at list price: ${worst:.3f} (" + "; ".join(f"{p} ${PRICE[p]:.3f}/run fixed" for p in procs) + ")")
    print(f"Sizes: {sizes}")
    print(f"Output: {run_dir}/")
    man_path = os.path.join(run_dir, "manifest.json")
    if os.path.exists(man_path):
        had = json.load(open(man_path)).get("prompt_version") or "no recorded version"
        if had != PROMPT_VERSION:
            sys.exit(f"refused: {run_dir} holds a {had} run; this batch is {PROMPT_VERSION} (use another --run)")
    if not a.yes:
        print("Dry run: nothing sent. Add --yes to spend.")
        return

    key = load_key()
    os.makedirs(os.path.join(run_dir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "records"), exist_ok=True)
    state_path = os.path.join(run_dir, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    if not os.path.exists(man_path):
        now = dt.datetime.now().astimezone()
        json.dump({"vendor": "parallel", "endpoint": BASE, "client": "run_parallel_task.py",
                   "prompt_version": PROMPT_VERSION,
                   "schema_variant": "nested: the shared schema in Parallel's dialect (status, value, citations, notes per fact)",
                   "processors": procs, "config_ids": {p: config_id(p) for p in procs},
                   "csv": a.csv, "run_date": a.run_date,
                   "run_date_note": "the date in the task text and the records; 'started' is the real launch time",
                   "started": now.replace(tzinfo=None).isoformat(),
                   "started_local": now.isoformat(),
                   "started_utc": now.astimezone(dt.timezone.utc).isoformat(),
                   "price_per_run_usd": {p: PRICE[p] for p in procs},
                   "cost_basis": "list price per processor; the Task API returns no per-run cost; failed runs are not billed",
                   "source_policy": None, "webhook": None, "mcp_servers": None, "beta_headers": [],
                   "enable_events": "unset",
                   "task_spec": task_spec()}, open(man_path, "w"), indent=1)

    def tag(c, p):
        return f"{c['domain']}__{config_id(p)}"

    n_sub, stopped_402, n_planned = 0, None, 0
    for c, p in targets:
        t = tag(c, p)
        if os.path.exists(os.path.join(run_dir, "records", t + ".json")) or t in state:
            continue
        n_planned += 1
        if stopped_402:
            continue
        try:
            resp = call("POST", BASE, key, body_for(c, p, a.run_date))
        except RuntimeError as e:
            if "HTTP 402" in str(e):
                stopped_402 = f"{t}: {e}"
                print(f"HTTP 402 on submit ({t}). The account is out of credit; nothing further is submitted.")
                continue
            raise
        if not resp.get("run_id"):
            sys.exit(f"no run_id in create response for {t}: {json.dumps(resp)[:600]}")
        state[t] = {"id": resp["run_id"], "submitted": time.time(), "domain": c["domain"],
                    "name": c["name"], "processor": p, "created_at": resp.get("created_at"),
                    "warnings": resp.get("warnings")}
        json.dump(state, open(state_path, "w"), indent=1)
        n_sub += 1
        warn = f"  warnings={resp.get('warnings')}" if resp.get("warnings") else ""
        print(f"submitted {t}: {resp['run_id']} ({resp.get('status')}){warn}")
    print(f"{n_sub} submitted, {len(state) - n_sub} already in flight or done. Polling every {a.poll_every}s "
          f"for up to {a.timeout_min} min; Ctrl-C is safe, rerun to resume.")

    pending = {t: s for t, s in state.items()
               if not os.path.exists(os.path.join(run_dir, "records", t + ".json"))}
    deadline = time.time() + a.timeout_min * 60
    while pending and time.time() < deadline:
        for t, s in list(pending.items()):
            try:
                run = call("GET", f"{BASE}/{s['id']}", key)
                st = run.get("status")
                if st not in TERMINAL:
                    continue
                done_at = time.time()
                result = {}
                if st == "completed":
                    result = call("GET", f"{BASE}/{s['id']}/result?{urllib.parse.urlencode({'timeout': 30})}", key, timeout=90)
            except (RuntimeError, urllib.error.URLError, OSError) as e:
                if "HTTP 402" in str(e):
                    stopped_402 = stopped_402 or f"{t} (poll): {e}"
                print(f"poll error on {t}, will try again: {str(e)[:200]}")
                continue
            json.dump({"run": run, "result": result}, open(os.path.join(run_dir, "raw", t + ".json"), "w"), indent=1)
            rec = brief_task.normalize(
                content_of(result) or {}, company=s["name"], domain=s["domain"],
                config_id=config_id(s["processor"]), run_date=a.run_date,
                cost_usd=PRICE[s["processor"]] if st == "completed" else None,
                latency_seconds=done_at - s["submitted"], prompt_version=PROMPT_VERSION)
            json.dump(rec, open(os.path.join(run_dir, "records", t + ".json"), "w"), indent=1)
            err = f"  error={json.dumps(run.get('error'))[:200]}" if run.get("error") else ""
            print(f"{st:9} {t}  cost={PRICE[s['processor']] if st == 'completed' else 0}  "
                  f"{round(done_at - s['submitted'])}s wall  ({len(pending) - 1} left){err}")
            del pending[t]
        if pending:
            time.sleep(a.poll_every)
    if pending:
        print(f"\n{len(pending)} still running after {a.timeout_min} min; rerun the same command to keep collecting.")
    print()
    summarize(run_dir)
    if stopped_402:
        print(f"\nSTOPPED ON HTTP 402: {stopped_402}\n{n_planned - n_sub} of {n_planned} planned submissions were not sent.")
        sys.exit(2)


if __name__ == "__main__":
    main()
