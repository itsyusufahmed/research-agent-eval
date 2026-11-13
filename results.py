#!/usr/bin/env python3
"""The results tables for the research-agents eval, from the graded cells and the run records. Changes nothing it reads.

Reads grading/cells.csv (grade, status, truth status and the presence band of every cell) and records/*.json
(cost_usd, latency_seconds) from the three board run folders. Every number is computed here: score_views.views for the
net score and its company bootstrap, eval_common.bootstrap_ci for the accuracy intervals, paired_accuracy below with
eval_common.mcnemar_exact for the deltas between settings. Writes:

  grading/results.csv          one row per config: cost, accuracy, net score, right / wrong / blank, yield, trust
  grading/results_by_band.csv  accuracy by presence band (rich / medium / thin), pooled, equal-weighted, rich minus thin
  grading/setting_deltas.csv   each setting against the next one up within a vendor: accuracy and net deltas

  python3 results.py [--grading grading] [--runs runs/<a> runs/<b> ...] [--all-facts]

The withdrawn fact (eval_common.WITHDRAWN_FIELDS) is left out of every number. --all-facts includes it and writes
only the first table, to grading/results_all_facts.csv.

Definitions:
  graded        grade correct | wrong | unknown (ungraded cells left out, as score_views.py does)
  accuracy      correct on answerable / answerable; answerable = truth known
  trust         correct on answerable / asserted
  yield         asserted / graded cells
  wrong per asserted   wrong / asserted
  unfindable    truth_status unfindable; the graded such cells per config (those that every config answered
                unknown are ungraded and left out); abstention = status unknown, assertion = status asserted
  right / wrong / blank per 100 and net(p)   score_views.py; net at a wrong cost of 1 is the headline
  $ per 1,000   1000 x mean cost_usd over the config's records (list price; Clay from credits x $0.05 + $0.005 an action)
  latency       median latency_seconds (wall clock)
  setting delta second minus first accuracy in points on cells both ran with truth known, McNemar exact on the
                discordant cells, 95% company bootstrap (2,000 resamples, seed 20261108); net delta at cost 1 from
                score_views
  all right     companies with every scored fact correct
"""
from __future__ import annotations

import argparse
import collections
import csv
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import eval_common as ec          # noqa: E402
import score_views                # noqa: E402

csv.field_size_limit(10**9)

DEFAULT_GRADING = "grading"
DEFAULT_RUNS = ["runs/2026-11-10-v1-exa", "runs/2026-11-10-v1-nested-parallel", "runs/2026-11-10-v1-claygent"]

# ---- configs ----------------------------------------------------------------------------------------

VENDOR_NAME = {"exa": "Exa", "parallel": "Parallel", "clay": "Clay"}
LADDER = {"exa": [("medium", "exa-agent-medium-A-v1"), ("high", "exa-agent-high-B-v1"), ("xhigh", "exa-agent-xhigh-v1")],
          "parallel": [("core", "parallel-core-A-v1"), ("pro", "parallel-pro-B-v1"), ("ultra", "parallel-ultra-C-v1")],
          "clay": [("Luna", "claygent-luna-v1"), ("Auto", "claygent-auto-A-v1"), ("Argon", "claygent-argon-B-v1")]}
EXPECTED = sorted(c for v in LADDER.values() for _, c in v)
BANDS = ["rich", "medium", "thin"]
BAND_N = {}  # companies per band, filled from cells
FACTS = {"n": 0, "never_graded": 0, "never_graded_companies": 0}  # scored facts per company, filled from cells


def meta(cfg: str) -> dict:
    for vendor, steps in LADDER.items():
        for setting, c in steps:
            if c == cfg:
                return {"id": cfg, "vendor": vendor, "setting": setting, "label": f"{VENDOR_NAME[vendor]} {setting}",
                        "rank": [x for _, x in steps].index(c)}
    sys.exit(f"config {cfg} is not on the board")


def ladder_order(cfgs):
    def key(c):
        m = meta(c)
        return (list(LADDER).index(m["vendor"]), m["rank"])
    return sorted(cfgs, key=key)


def ladder_steps():
    """(first, second) for each step up within a vendor, in ladder order."""
    return [(steps[i][1], steps[i + 1][1]) for steps in LADDER.values() for i in range(len(steps) - 1)]


# ---- loading ----------------------------------------------------------------------------------------

def resolve(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def load_cells(grading, all_facts=False):
    rows = ec.scored(csv.DictReader(open(os.path.join(grading, "cells.csv"))), all_facts)
    cfgs = sorted({r["config_id"] for r in rows})
    if cfgs != EXPECTED:
        sys.exit(f"configs in {grading} differ from the nine on the board:\n  extra {sorted(set(cfgs) - set(EXPECTED))}\n"
                 f"  missing {sorted(set(EXPECTED) - set(cfgs))}")
    graded = [r for r in rows if r["grade"] != "ungraded"]
    FACTS["n"] = len({r["field"] for r in rows})
    never = {(r["domain"], r["field"]) for r in rows} - {(r["domain"], r["field"]) for r in graded}
    FACTS["never_graded"], FACTS["never_graded_companies"] = len(never), len({d for d, _ in never})
    for r in rows:
        BAND_N.setdefault(r["band"], set()).add(r["domain"])
    for b in BANDS:
        BAND_N[b] = len(BAND_N[b])
    return rows, graded


def load_runs(run_dirs):
    """{(domain, config): (cost, latency)} from records/*.json, or summary.csv where a folder has no records."""
    out = {}
    for d in run_dirs:
        d = resolve(d)
        if os.path.isdir(os.path.join(d, "records")):
            for tag, rec in ec.iter_records(d):
                cfg = rec.get("config_id") or tag.split("__", 1)[-1]
                out[(rec.get("domain") or tag.split("__", 1)[0], cfg)] = (rec.get("cost_usd"), rec.get("latency_seconds"))
        elif os.path.exists(os.path.join(d, "summary.csv")):
            for r in csv.DictReader(open(os.path.join(d, "summary.csv"))):
                num = lambda v: float(v) if v not in (None, "") else None
                out[(r["domain"], r["config"])] = (num(r.get("cost_usd")), num(r.get("latency_s")))
        else:
            print(f"warning: {d} has no records/ and no summary.csv", file=sys.stderr)
    return out


# ---- metrics ----------------------------------------------------------------------------------------

def paired_accuracy(graded, a, b, boot=False):
    """Accuracy of a and b on cells both answered with truth known (neither gap), McNemar exact, optional company bootstrap."""
    cell = collections.defaultdict(dict)
    for r in graded:
        if r["config_id"] in (a, b):
            cell[(r["domain"], r["field"])][r["config_id"]] = r
    pairs = [(c[a], c[b]) for c in cell.values() if a in c and b in c and c[a]["truth_status"] == "known"
             and c[b]["truth_status"] == "known" and c[a]["grade"] != "gap" and c[b]["grade"] != "gap"]
    if not pairs:
        return None
    ra = sum(x["grade"] == "correct" for x, _ in pairs)
    rb = sum(y["grade"] == "correct" for _, y in pairs)
    bb = sum(1 for x, y in pairs if x["grade"] == "correct" and y["grade"] != "correct")
    cc = sum(1 for x, y in pairs if x["grade"] != "correct" and y["grade"] == "correct")
    out = {"acc_a": 100 * ra / len(pairs), "acc_b": 100 * rb / len(pairs), "delta": 100 * (rb - ra) / len(pairs),
           "b": bb, "c": cc, "p": ec.mcnemar_exact(bb, cc), "n": len(pairs), "lo": None, "hi": None}
    if boot:
        per = collections.defaultdict(lambda: [0, 0, 0])
        for x, y in pairs:
            t = per[x["domain"]]
            t[0] += x["grade"] == "correct"; t[1] += y["grade"] == "correct"; t[2] += 1

        def stat(sample):
            n = sum(per[d][2] for d in sample)
            return 100 * (sum(per[d][1] for d in sample) - sum(per[d][0] for d in sample)) / n if n else None
        out["lo"], out["hi"] = ec.bootstrap_ci(sorted(per), stat)
    return out


def store_pairs(D, V):
    """Paired net differences from a score_views.views result, each with its paired accuracy, into D["P"]."""
    for q in V["pairs"]:
        k = (q["first"], q["second"])
        D["P"][k] = {"net_d": q["_d"], "net_lo": q["_lo"], "net_hi": q["_hi"], "clear": q["clear_of_zero"]}
        D["P"][k].update(paired_accuracy(D["graded"], *k, boot=True))


def add_pairs(D, keys):
    """The same for each (first, second) not yet in D["P"]; pairs naming a config off the board are dropped by views."""
    keys = [k for k in dict.fromkeys(keys) if k not in D["P"]]
    if keys:
        store_pairs(D, score_views.views(D["graded"], pairs=keys))


def compute(all_rows, graded, recs):
    """Every number the tables use, keyed by config; plus the paired differences."""
    by_cfg = collections.defaultdict(list)
    for r in graded:
        by_cfg[r["config_id"]].append(r)
    cfgs = sorted(by_cfg)
    companies = sorted({r["domain"] for r in graded})
    band_of = {r["domain"]: r["band"] for r in graded}

    # per company counts per config: [correct_on_answerable, answerable, asserted, wrong, correct_any]
    pc = {c: {d: [0, 0, 0, 0, 0] for d in companies} for c in cfgs}
    for r in graded:
        t = pc[r["config_id"]][r["domain"]]
        if r["truth_status"] == "known":
            t[1] += 1
            if r["grade"] == "correct":
                t[0] += 1
        if r["status"] == "asserted":
            t[2] += 1
        if r["grade"] == "wrong":
            t[3] += 1
        if r["grade"] == "correct":
            t[4] += 1

    def acc_stat(c, bands=None):
        def stat(sample):
            k = n = 0
            for d in sample:
                if bands is None or band_of[d] in bands:
                    k += pc[c][d][0]; n += pc[c][d][1]
            return 100 * k / n if n else None
        return stat

    def ew_stat(c):
        def stat(sample):
            accs = []
            for b in BANDS:
                k = n = 0
                for d in sample:
                    if band_of[d] == b:
                        k += pc[c][d][0]; n += pc[c][d][1]
                if n:
                    accs.append(k / n)
            return 100 * sum(accs) / len(accs) if accs else None
        return stat

    def wa_stat(c):
        def stat(sample):
            w = a = 0
            for d in sample:
                w += pc[c][d][3]; a += pc[c][d][2]
            return 100 * w / a if a else None
        return stat

    M = {}
    for c in cfgs:
        rows = by_cfg[c]
        known = [r for r in rows if r["truth_status"] == "known"]
        unfind = [r for r in rows if r["truth_status"] == "unfindable"]
        ck = sum(1 for r in known if r["grade"] == "correct")
        asserted = sum(1 for r in rows if r["status"] == "asserted")
        wrong = sum(1 for r in rows if r["grade"] == "wrong")
        m = {"n": len(rows), "answerable": len(known), "correct_known": ck, "asserted": asserted, "wrong": wrong,
             "accuracy": 100 * ck / len(known), "trust": 100 * ck / asserted, "yield": 100 * asserted / len(rows),
             "wrong_per_asserted": 100 * wrong / asserted,
             "unfindable_n": len(unfind), "abstained": sum(1 for r in unfind if r["status"] == "unknown"),
             "unfindable_asserted": sum(1 for r in unfind if r["status"] == "asserted"),
             "all_right": sum(1 for d in companies if pc[c][d][4] == FACTS["n"])}
        m["abstention"] = 100 * m["abstained"] / len(unfind)
        m["wrong_confident"] = 100 * m["unfindable_asserted"] / len(unfind)
        m["accuracy_ci"] = ec.bootstrap_ci(companies, acc_stat(c))
        m["wrong_per_asserted_ci"] = ec.bootstrap_ci(companies, wa_stat(c))
        m["band"] = {}
        for b in BANDS:
            br = [r for r in known if r["band"] == b]
            k = sum(1 for r in br if r["grade"] == "correct")
            m["band"][b] = {"accuracy": 100 * k / len(br), "n": len(br), "ci": ec.bootstrap_ci(companies, acc_stat(c, {b}))}
        ew = sum(m["band"][b]["accuracy"] for b in BANDS) / 3
        m["equal_weighted"] = {"accuracy": ew, "ci": ec.bootstrap_ci(companies, ew_stat(c))}

        # rich minus thin, with its interval
        def rt(sample, c=c):
            kr = nr = kt = nt = 0
            for d in sample:
                if band_of[d] == "rich":
                    kr += pc[c][d][0]; nr += pc[c][d][1]
                elif band_of[d] == "thin":
                    kt += pc[c][d][0]; nt += pc[c][d][1]
            return 100 * (kr / nr - kt / nt) if nr and nt else None
        m["rich_minus_thin"] = (m["band"]["rich"]["accuracy"] - m["band"]["thin"]["accuracy"], ec.bootstrap_ci(companies, rt))
        rs = [v for (d, cc), v in recs.items() if cc == c and d in pc[c]]
        costs = [x for x, _ in rs if isinstance(x, (int, float))]
        lats = sorted(x for _, x in rs if isinstance(x, (int, float)))
        if len(costs) != len(companies) or len(lats) != len(companies):
            sys.exit(f"{c}: {len(costs)} costs and {len(lats)} latencies for {len(companies)} companies in --runs")
        m["usd_per_1k"] = 1000 * statistics.mean(costs)
        m["cost_min"], m["cost_max"] = 1000 * min(costs), 1000 * max(costs)
        m["latency_median"] = statistics.median(lats)
        q = statistics.quantiles(lats, n=4)
        m["latency_p25"], m["latency_p75"] = q[0], q[2]
        M[c] = m

    # net scores and paired net differences (score_views recipe; the resamples are the same whatever the pair list)
    V = score_views.views(graded, pairs=list(dict.fromkeys(list(score_views.PAIRS) + ladder_steps())))
    for r in V["rows"]:
        M[r["config"]]["views"] = r
    D = {"cfgs": cfgs, "companies": companies, "M": M, "P": {}, "V": V, "graded": graded}
    store_pairs(D, V)
    return D


# ---- tables ----------------------------------------------------------------------------------------

def pfmt(p):
    if p is None:
        return "n/a"
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"


RESULT_COLUMNS = ["config_id", "usd_per_1k", "accuracy", "accuracy_lo", "accuracy_hi", "net_1", "net_1_lo", "net_1_hi",
                  "right_per_100", "wrong_per_100", "blank_per_100", "yield", "trust", "wrong_per_asserted",
                  "unfindable_abstained", "unfindable_graded", "latency_median_s", "all_right_companies"]


def f1(x):
    return f"{x:.1f}"


def result_rows(D):
    """One row per config in ladder order: rates and scores to 0.1; cost per 1,000 to the cent and
    median latency to 0.1 s, one step finer than the README's whole dollars and seconds."""
    out = []
    for c in ladder_order(D["cfgs"]):
        m, v = D["M"][c], D["M"][c]["views"]
        out.append({"config_id": c, "usd_per_1k": f"{m['usd_per_1k']:.2f}", "accuracy": f1(m["accuracy"]),
                    "accuracy_lo": f1(m["accuracy_ci"][0]), "accuracy_hi": f1(m["accuracy_ci"][1]),
                    "net_1": v["net_1"], "net_1_lo": v["net_1_lo"], "net_1_hi": v["net_1_hi"],
                    "right_per_100": v["right_per_100"], "wrong_per_100": v["wrong_per_100"], "blank_per_100": v["blank_per_100"],
                    "yield": f1(m["yield"]), "trust": f1(m["trust"]), "wrong_per_asserted": f1(m["wrong_per_asserted"]),
                    "unfindable_abstained": m["abstained"], "unfindable_graded": m["unfindable_n"],
                    "latency_median_s": f1(m["latency_median"]), "all_right_companies": m["all_right"]})
    return out


BAND_COLUMNS = ["config_id"] + [f"{b}{s}" for b in BANDS for s in ("", "_lo", "_hi")] + [
    "pooled", "pooled_lo", "pooled_hi", "equal_weighted", "equal_weighted_lo", "equal_weighted_hi",
    "rich_minus_thin", "rich_minus_thin_lo", "rich_minus_thin_hi"]
DELTA_COLUMNS = ["first", "second", "accuracy_delta", "accuracy_delta_lo", "accuracy_delta_hi", "second_only_right",
                 "first_only_right", "mcnemar_p", "net_delta", "net_delta_lo", "net_delta_hi", "clear_of_zero"]


def band_rows(D):
    """Accuracy per presence band, pooled, the equal-weighted mean of the three bands, and rich minus thin; 95% company bootstrap."""
    out = []
    for c in ladder_order(D["cfgs"]):
        m = D["M"][c]
        row = {"config_id": c}
        for b in BANDS:
            row[b], row[b + "_lo"], row[b + "_hi"] = f1(m["band"][b]["accuracy"]), f1(m["band"][b]["ci"][0]), f1(m["band"][b]["ci"][1])
        row.update({"pooled": f1(m["accuracy"]), "pooled_lo": f1(m["accuracy_ci"][0]), "pooled_hi": f1(m["accuracy_ci"][1]),
                    "equal_weighted": f1(m["equal_weighted"]["accuracy"]), "equal_weighted_lo": f1(m["equal_weighted"]["ci"][0]),
                    "equal_weighted_hi": f1(m["equal_weighted"]["ci"][1]), "rich_minus_thin": f"{m['rich_minus_thin'][0]:+.1f}",
                    "rich_minus_thin_lo": f"{m['rich_minus_thin'][1][0]:+.1f}", "rich_minus_thin_hi": f"{m['rich_minus_thin'][1][1]:+.1f}"})
        out.append(row)
    return out


def delta_rows(D):
    """Each setting against the next one up within a vendor, second minus first, on the same companies."""
    out = []
    for a, b in ladder_steps():
        q = D["P"][(a, b)]
        out.append({"first": a, "second": b, "accuracy_delta": f"{q['delta']:+.1f}", "accuracy_delta_lo": f"{q['lo']:+.1f}",
                    "accuracy_delta_hi": f"{q['hi']:+.1f}", "second_only_right": q["c"], "first_only_right": q["b"],
                    "mcnemar_p": pfmt(q["p"]), "net_delta": f"{q['net_d']:+.1f}", "net_delta_lo": f"{q['net_lo']:+.1f}",
                    "net_delta_hi": f"{q['net_hi']:+.1f}", "clear_of_zero": "yes" if q["clear"] else "no"})
    return out


def write_csv(path, columns, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    print("wrote", os.path.relpath(path, ROOT))


def main():
    ap = argparse.ArgumentParser(description="The results tables from the graded cells and the run records.")
    ap.add_argument("--grading", default=DEFAULT_GRADING, help="folder holding cells.csv; the tables are written there (default grading)")
    ap.add_argument("--runs", nargs="+", default=DEFAULT_RUNS, help="run folders with records/*.json (default: the three board runs)")
    ap.add_argument("--all-facts", action="store_true", help="include the withdrawn fact; writes only results_all_facts.csv")
    a = ap.parse_args()
    grading = resolve(a.grading)
    all_rows, graded = load_cells(grading, a.all_facts)
    D = compute(all_rows, graded, load_runs(a.runs))
    if a.all_facts:
        write_csv(os.path.join(grading, "results_all_facts.csv"), RESULT_COLUMNS, result_rows(D))
        return
    write_csv(os.path.join(grading, "results.csv"), RESULT_COLUMNS, result_rows(D))
    write_csv(os.path.join(grading, "results_by_band.csv"), BAND_COLUMNS, band_rows(D))
    write_csv(os.path.join(grading, "setting_deltas.csv"), DELTA_COLUMNS, delta_rows(D))


if __name__ == "__main__":
    main()
