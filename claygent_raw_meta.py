#!/usr/bin/env python3
"""Clay metadata that rides inside a Claygent Function result.

Beside the 17 schema fields, item.result["<column>"] carries Clay extras:
  every config : reasoning, confidence, stepsTaken (list)
  Auto, Luna   : totalCreditsCharged (per row, fractional), timeTakenInSeconds
Some rows can also carry forcedToFinishEarlyBecauseOfCost, totalInputTokens, totalOutputTokens and
totalCostToAIProvider. So per-row Auto and Luna credits ARE in the API result; only the routed model
under Auto is not. Argon is a fixed 3 credits a row.

This script reads a run folder's raw/ and writes, under <run>/credits/:
  auto_credits_from_raw.csv   Domain,credits          (totalCreditsCharged per row)
  argon_credits_fixed.csv     Domain,credits          (3 a row, FIXED)
  luna_credits_from_raw.csv   Domain,credits          (totalCreditsCharged per row)
and prints a metadata summary per config: rows, credits sum/mean, provider cost sum/mean, forced-early count,
steps median, timeTakenInSeconds median. No answer content is printed. run_claygent.py --credits merges
each CSV into that model's records.

Usage: python3 claygent_raw_meta.py --run 2026-11-10-v1-claygent [--write]
"""
from __future__ import annotations
import argparse, csv, glob, json, os, statistics
import eval_common as ec

CONFIGS = {"claygent-auto-A-v1": "auto", "claygent-argon-B-v1": "argon", "claygent-luna-v1": "luna"}
FIXED = {"argon": 3.0}


def money(s):
    if s is None:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def inner_of(raw: dict):
    item = raw.get("item") or {}
    res = item.get("result")
    if isinstance(res, dict):
        for v in res.values():
            if isinstance(v, dict):
                return v, item.get("status")
    return {}, item.get("status")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--write", action="store_true", help="write the credits CSVs under <run>/credits/")
    a = ap.parse_args()
    run_dir = ec.run_dir_for(a.run)
    per = {m: [] for m in CONFIGS.values()}
    for p in sorted(glob.glob(os.path.join(run_dir, "raw", "*.json"))):
        tag = os.path.basename(p)[:-5]
        dom, _, cfg = tag.partition("__")
        m = CONFIGS.get(cfg)
        if not m:
            continue
        inner, status = inner_of(json.load(open(p)))
        per[m].append({
            "domain": dom, "status": status,
            "credits": inner.get("totalCreditsCharged"),
            "cost": money(inner.get("totalCostToAIProvider")),
            "forced": inner.get("forcedToFinishEarlyBecauseOfCost"),
            "steps": len(inner["stepsTaken"]) if isinstance(inner.get("stepsTaken"), list) else None,
            "secs": money(inner.get("timeTakenInSeconds")),
            "in_tok": inner.get("totalInputTokens"), "out_tok": inner.get("totalOutputTokens"),
        })

    def med(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(statistics.median(xs), 1) if xs else None

    print(f"{'config':8} {'rows':>4} {'complete':>8} {'credits_sum':>11} {'credits_mean':>12} {'cost_sum':>9} {'cost_mean':>9} "
          f"{'forced_early':>12} {'steps_med':>9} {'secs_med':>8} {'in_tok_med':>10} {'out_tok_med':>11}")
    for m, rows in per.items():
        cr = [r["credits"] for r in rows if isinstance(r["credits"], (int, float))]
        co = [r["cost"] for r in rows if isinstance(r["cost"], (int, float))]
        print(f"{m:8} {len(rows):>4} {sum(1 for r in rows if r['status']=='complete'):>8} "
              f"{(round(sum(cr),2) if cr else '-'):>11} {(round(sum(cr)/len(cr),3) if cr else '-'):>12} "
              f"{(round(sum(co),3) if co else '-'):>9} {(round(sum(co)/len(co),4) if co else '-'):>9} "
              f"{sum(1 for r in rows if r['forced'] is True):>12} {str(med([r['steps'] for r in rows])):>9} "
              f"{str(med([r['secs'] for r in rows])):>8} {str(med([r['in_tok'] for r in rows])):>10} {str(med([r['out_tok'] for r in rows])):>11}")

    if a.write:
        cdir = os.path.join(run_dir, "credits")
        os.makedirs(cdir, exist_ok=True)
        def dump(name, pairs):
            with open(os.path.join(cdir, name), "w", newline="") as f:
                w = csv.writer(f); w.writerow(["Domain", "credits"]); w.writerows(pairs)
            print(f"wrote {os.path.join(cdir, name)} ({len(pairs)} rows)")
        if per["auto"]:
            dump("auto_credits_from_raw.csv", [(r["domain"], r["credits"]) for r in per["auto"] if isinstance(r["credits"], (int, float))])
        if per["argon"]:
            dump("argon_credits_fixed.csv", [(r["domain"], FIXED["argon"]) for r in per["argon"]])
        if per["luna"]:
            dump("luna_credits_from_raw.csv", [(r["domain"], r["credits"]) for r in per["luna"] if isinstance(r["credits"], (int, float))])


if __name__ == "__main__":
    main()
