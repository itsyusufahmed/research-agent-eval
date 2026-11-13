#!/usr/bin/env python3
"""Shared plumbing for the research-agents eval clients and grader.

Stdlib only. Reused by the run_*.py clients, grade.py, snapshot.py and
results.py so they agree on: where keys come from, how a run folder
is laid out, how a company list is read, Wilson and bootstrap intervals, McNemar,
and the canonical JSON hash. Nothing here talks to a vendor.

Keys: every script reads its API keys from environment variables. When a variable
is not set, env_key() falls back to a .env file in the repo root (plain KEY=VALUE
lines; .env.example lists every name). Key values are never printed or written.

Run folder layout (same as run_exa_agent.py / run_parallel_task.py):
  runs/<name>/manifest.json   what was run (prompt version, configs, csv, prices)
  runs/<name>/state.json      in-flight ids, so a rerun resumes instead of paying twice
  runs/<name>/raw/<tag>.json  the vendor's response, untouched except scrub_credentials()
  runs/<name>/records/<tag>.json  brief_schema.json records via brief_task.normalize
  runs/<name>/summary.csv     one row per record
  tag = <domain>__<config_id>
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env")
BAND_ORDER = {"rich": 0, "medium": 1, "thin": 2}
BANDS = ["rich", "medium", "thin"]
# Facts that were asked, answered and graded but are withdrawn from scoring (README, "Changes from the plan").
# Their rows stay in grading/cells.csv; score_views.py and results.py leave them out unless --all-facts.
WITHDRAWN_FIELDS = ("crm_stack_signal",)


def scored(rows, all_facts: bool = False):
    """rows (dicts with a `field`) without the withdrawn facts, or every row when all_facts is set."""
    return list(rows) if all_facts else [r for r in rows if r["field"] not in WITHDRAWN_FIELDS]


# ---- keys -----------------------------------------------------------------------

def env_key(name: str, required: bool = True) -> Optional[str]:
    """Read a key from the environment, else from the repo-root .env (KEY=VALUE lines). Never printed."""
    if os.environ.get(name):
        return os.environ[name]
    if os.path.exists(ENV):
        for line in open(ENV):
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if line.startswith(name + "="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    if required:
        sys.exit(f"missing {name}: set it in the environment or in .env in the repo root (see .env.example)")
    return None


def export_env(names: Iterable[str]) -> List[str]:
    """Put keys from .env into os.environ for a subprocess or an SDK; returns the names that were found."""
    found = []
    for n in names:
        v = env_key(n, required=False)
        if v:
            os.environ[n] = v
            found.append(n)
    return found


# ---- companies and run folders -----------------------------------------------------

def load_companies(csv_name: str, arg: str = "all") -> List[Dict[str, str]]:
    path = csv_name if os.path.isabs(csv_name) else os.path.join(HERE, csv_name)
    if not os.path.exists(path):
        sys.exit(f"{csv_name} not found")
    rows = list(csv.DictReader(open(path)))
    if arg == "all":
        return rows
    want = set(x.strip() for x in arg.split(",") if x.strip())
    rows = [r for r in rows if r["domain"] in want]
    missing = want - {r["domain"] for r in rows}
    if missing:
        sys.exit(f"not in {csv_name}: {sorted(missing)}")
    return rows


def company_meta(csv_name: str) -> Dict[str, Dict[str, str]]:
    path = csv_name if os.path.isabs(csv_name) else os.path.join(HERE, csv_name)
    if not os.path.exists(path):
        return {}
    return {r["domain"]: r for r in csv.DictReader(open(path))}


def run_dir_for(name: str) -> str:
    return os.path.join(HERE, "runs", name)


def ensure_run_dirs(run_dir: str) -> None:
    os.makedirs(os.path.join(run_dir, "raw"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "records"), exist_ok=True)


def load_json(path: str, default: Any = None) -> Any:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def dump_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def write_manifest_once(run_dir: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    path = os.path.join(run_dir, "manifest.json")
    if os.path.exists(path):
        return load_json(path)
    dump_json(path, manifest)
    return manifest


def record_path(run_dir: str, tag: str) -> str:
    return os.path.join(run_dir, "records", tag + ".json")


def iter_records(run_dir: str) -> Iterable[Tuple[str, Dict[str, Any]]]:
    rec_dir = os.path.join(run_dir, "records")
    if not os.path.isdir(rec_dir):
        return
    for fn in sorted(os.listdir(rec_dir)):
        if fn.endswith(".json"):
            yield fn[:-5], load_json(os.path.join(rec_dir, fn))


# ---- hashing ---------------------------------------------------------------------------

def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- third-party credentials in fetched pages --------------------------------------------
# Public pages embed credentials in their HTML: signed S3 image links (AWS temporary keys,
# session tokens, signatures), Google Maps browser keys, Mapbox tokens, sample keys in API docs.
# They belong to the site, not to this eval, and a saved copy should not republish them.

REDACTED = "REDACTED"
CREDENTIAL_PATTERNS = [
    ("aws-signed-url", re.compile(r"(X-Amz-(?:Credential|Security-Token|Signature))=[^&\s)\]\"'\\<>]+")),
    ("aws-key-id", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("mapbox-token", re.compile(r"(?<![A-Za-z0-9])[pst]k\.eyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+")),
    ("test-live-key", re.compile(r"(?<![A-Za-z0-9_])(?:test|live)_[0-9a-f]{32,40}(?![0-9a-f])")),
]


def scrub_credentials(text: str) -> Tuple[str, Dict[str, int]]:
    """Replace third-party credential values with REDACTED; return the text and a count per pattern."""
    counts: Dict[str, int] = {}
    for name, rx in CREDENTIAL_PATTERNS:
        repl = (lambda m: m.group(1) + "=" + REDACTED) if name == "aws-signed-url" else REDACTED
        text, n = rx.subn(repl, text)
        if n:
            counts[name] = n
    return text, counts


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- statistics ------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.959964) -> Tuple[Optional[float], Optional[float]]:
    """Wilson score interval for a proportion k/n."""
    if n <= 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / denom, (centre + half) / denom


def bootstrap_ci(items: Sequence[Any], stat_fn: Callable[[Sequence[Any]], Optional[float]],
                 n_boot: int = 2000, seed: int = 20261108, level: float = 0.95
                 ) -> Tuple[Optional[float], Optional[float]]:
    """Seeded percentile bootstrap: n_boot resamples of items with replacement, the level's percentile interval."""
    if not items:
        return None, None
    rng = random.Random(seed)
    n = len(items)
    vals = []
    for _ in range(n_boot):
        sample = [items[rng.randrange(n)] for _ in range(n)]
        v = stat_fn(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return None, None
    vals.sort()
    tail = (1.0 - level) / 2.0
    lo = vals[int(tail * len(vals))]
    hi = vals[min(len(vals) - 1, int((1.0 - tail) * len(vals)))]
    return lo, hi


def mcnemar_exact(b: int, c: int) -> Optional[float]:
    """Two-sided exact McNemar p-value on discordant pairs (b: A right & B wrong, c: A wrong & B right)."""
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def median(xs: Iterable[Any]) -> Optional[float]:
    v = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(v) if v else None


def mean(xs: Iterable[Any]) -> Optional[float]:
    v = [x for x in xs if isinstance(x, (int, float))]
    return statistics.mean(v) if v else None


def fmt(x: Any, nd: int = 2, pct: bool = False) -> str:
    if x is None:
        return "?"
    if pct:
        return f"{100 * x:.{nd}f}%"
    return f"{x:.{nd}f}"


# ---- summaries shared by the clients -------------------------------------------------

def summary_rows(run_dir: str, csv_name: str, extra: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None
                 ) -> List[Dict[str, Any]]:
    """One row per record: domain, band, third, config, cost, latency, tally, schema errors."""
    import brief_task
    meta = company_meta(csv_name)
    rows = []
    for tag, rec in iter_records(run_dir):
        t = brief_task.tally(rec)
        try:
            errs = brief_task.validate(rec)
        except ImportError:
            errs = ["jsonschema not installed"]
        m = meta.get(rec.get("domain"), {})
        first = rec.get("answers", {}).get("product_one_liner", {})
        row = {"domain": rec.get("domain"), "band": m.get("band", "?"), "third": m.get("source_third", "?"),
               "config": rec.get("config_id"), "cost_usd": rec.get("cost_usd"),
               "latency_s": rec.get("latency_seconds"), **t, "schema_errors": len(errs),
               "failed": 1 if str(first.get("notes", "")).startswith("normalizer") and t["asserted"] == 0 else 0}
        if extra:
            row.update(extra(tag, rec))
        rows.append(row)
    rows.sort(key=lambda r: (str(r["config"]), BAND_ORDER.get(r["band"], 9), str(r["domain"])))
    return rows


def write_summary_csv(run_dir: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    keys: List[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(run_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def print_summary(rows: List[Dict[str, Any]], run_dir: str, cost_label: str = "cost") -> None:
    if not rows:
        print("no records yet")
        return
    print(f"{'domain':24} {'band':6} {'config':26} {cost_label:>7} {'secs':>6} {'assert':>6} {'unk':>4} {'nocite':>6} {'schErr':>6}")
    for r in rows:
        cost = f"{r['cost_usd']:.3f}" if isinstance(r["cost_usd"], (int, float)) else "?"
        secs = f"{r['latency_s']:.0f}" if isinstance(r["latency_s"], (int, float)) else "?"
        print(f"{str(r['domain']):24} {str(r['band']):6} {str(r['config']):26} {cost:>7} {secs:>6} "
              f"{r['asserted']:>6} {r['unknown']:>4} {r['asserted_no_cite']:>6} {r['schema_errors']:>6}")
    print("\nPer config x band (n, cost min/median/max, median secs, mean unknowns of 17, asserted w/o citation, schema errors, empty outputs)")
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((str(r["config"]), str(r["band"])), []).append(r)
    for (cfg, band), g in sorted(groups.items(), key=lambda kv: (kv[0][0], BAND_ORDER.get(kv[0][1], 9))):
        costs = [x["cost_usd"] for x in g if isinstance(x["cost_usd"], (int, float))]
        lo = f"{min(costs):.3f}" if costs else "?"
        hi = f"{max(costs):.3f}" if costs else "?"
        print(f"  {cfg:26} {band:6} n={len(g):<3} cost {lo}/{fmt(median(costs), 3)}/{hi}  secs {fmt(median([x['latency_s'] for x in g]), 0)}  "
              f"unk {fmt(mean([x['unknown'] for x in g]), 1)}  nocite {sum(x['asserted_no_cite'] for x in g)}  "
              f"schErr {sum(x['schema_errors'] for x in g)}  empty {sum(x['failed'] for x in g)}")
    for cfg in sorted({str(r["config"]) for r in rows}):
        g = [r for r in rows if str(r["config"]) == cfg]
        costs = [x["cost_usd"] for x in g if isinstance(x["cost_usd"], (int, float))]
        if costs:
            print(f"  {cfg}: {len(costs)} priced runs, total ${sum(costs):.2f}, "
                  f"mean ${statistics.mean(costs):.4f}/account -> ${1000 * statistics.mean(costs):,.0f} per 1,000 accounts")
    print(f"\nsummary.csv written to {run_dir}/. Records in records/, raw vendor output in raw/.")
