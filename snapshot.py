#!/usr/bin/env python3
"""Snapshot every cited URL in one or more run folders, within 24 hours of the run.

For each record under runs/<name>/records/, every citation URL (plus Exa's output.grounding URLs from raw/
with --include-grounding) is collected, deduplicated across the folders given, and fetched once:
  runs/<name>/snapshots/<sha1(url)>.json  = {url, fetched_at (UTC ISO), hours_after_run, fetched_via
      (firecrawl|urllib), status (HTTP status, or null with error), content_sha256 (of the full text,
      after eval_common.scrub_credentials replaces credentials the page embeds),
      chars, truncated, title, markdown (capped at --max-chars), error, archived_url}
  runs/<name>/snapshots/index.jsonl       = one line per fetch, history kept, so a second pass can show change
A URL cited in several of the given folders is fetched once and written under each (same hash key), so
grade.py finds it from any of them and nothing is fetched twice.

Fetch: Firecrawl v2 scrape first (POST https://api.firecrawl.dev/v2/scrape, Authorization: Bearer
FIRECRAWL_API_KEY, {"url", "formats": ["markdown"]} -> data.markdown, data.metadata.statusCode; 1 credit a
page), urllib with a browser UA on a Firecrawl error (status recorded); --no-firecrawl = urllib only.
hours_after_run is measured from the record's run_date at 00:00 UTC (the record carries no clock); a
snapshot more than 24 hours after the run is flagged as late.

Spend gate: the plan prints the URL count and the Firecrawl credit count; nothing is fetched without --yes.
--report prints dead URLs (status >= 400 or error), changed URLs (a later content hash differs from the
first) and never-fetched cited URLs, and writes snapshots/report.md in each folder; it fetches nothing.

grade.py imports the fetch helpers from here (url_key, fetch_urllib, fetch_firecrawl, fetch_wayback,
html_to_text, load_snapshot) so the grader and the snapshotter share one implementation and one hash key.

Usage:
  python3 snapshot.py --runs runs/2026-11-10-v1-exa                   # plan: URL and credit counts
  python3 snapshot.py --runs runs/2026-11-10-v1-exa runs/2026-11-10-v1-nested-parallel --yes
  python3 snapshot.py --runs runs/2026-11-10-v1-exa --no-firecrawl --yes   # urllib only, free
  python3 snapshot.py --runs runs/2026-11-10-v1-exa --report
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import eval_common as ec

HERE = os.path.dirname(os.path.abspath(__file__))
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
WAYBACK_AVAILABLE = "https://archive.org/wayback/available"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
MAX_BYTES = 3 * 1024 * 1024
MAX_CHARS_DEFAULT = 200000


# ---- helpers shared with grade.py -------------------------------------------------------------

def url_key(url: str) -> str:
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP and tag != "head":
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "td", "th"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and tag != "head" and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str):
    p = _TextExtractor()
    try:
        p.feed(html or "")
        p.close()
    except Exception:  # noqa: BLE001
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text, re.sub(r"\s+", " ", p.title).strip()


def fetch_urllib(url: str, timeout: int = 15) -> Dict[str, Any]:
    """{status, text, title, error, final_url, content_type}; never raises."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                               "Accept-Language": "en-US,en;q=0.9"})
    out: Dict[str, Any] = {"status": None, "text": "", "title": "", "error": None, "final_url": None, "content_type": None}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out["status"] = r.status
            out["final_url"] = r.geturl()
            out["content_type"] = r.headers.get("Content-Type", "")
            raw = r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        out["content_type"] = e.headers.get("Content-Type", "") if e.headers else ""
        try:
            raw = e.read(MAX_BYTES)
        except Exception:  # noqa: BLE001
            raw = b""
    except Exception as e:  # noqa: BLE001  (URLError, timeout, ssl, IncompleteRead, ...)
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return out
    ct = (out["content_type"] or "").lower()
    if "pdf" in ct or raw[:5] == b"%PDF-":
        out["text"] = ""
        out["title"] = ""
        out["error"] = f"pdf: {len(raw)} bytes, text not extracted by urllib"
        return out
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ct)
    if m:
        charset = m.group(1)
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    if "html" in ct or body.lstrip()[:1] == "<":
        out["text"], out["title"] = html_to_text(body)
    else:
        out["text"] = body
    return out


def fetch_firecrawl(url: str, key: str, timeout: int = 90) -> Dict[str, Any]:
    """{status, text, title, error}; status is the page's statusCode per Firecrawl; never raises."""
    body = json.dumps({"url": url, "formats": ["markdown"]}).encode()
    req = urllib.request.Request(FIRECRAWL_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    out: Dict[str, Any] = {"status": None, "text": "", "title": "", "error": None}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:300]
        out["error"] = f"firecrawl HTTP {e.code}: {msg}"
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"firecrawl {type(e).__name__}: {str(e)[:200]}"
        return out
    if not data.get("success", True):
        out["error"] = f"firecrawl: {str(data.get('error'))[:300]}"
        return out
    d = data.get("data") or {}
    meta = d.get("metadata") or {}
    out["status"] = meta.get("statusCode")
    out["text"] = d.get("markdown") or ""
    out["title"] = meta.get("title") or ""
    if out["status"] is None and out["text"]:
        out["status"] = 200
    return out


def fetch_wayback(url: str, run_date: str, timeout: int = 20) -> Dict[str, Any]:
    """Closest Wayback copy to run_date (YYYY-MM-DD); {status, text, title, error, archived_url, archived_at}."""
    ts = run_date.replace("-", "")[:8]
    q = urllib.parse.urlencode({"url": url, "timestamp": ts})
    out: Dict[str, Any] = {"status": None, "text": "", "title": "", "error": None, "archived_url": None, "archived_at": None}
    try:
        req = urllib.request.Request(f"{WAYBACK_AVAILABLE}?{q}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        out["error"] = f"wayback {type(e).__name__}: {str(e)[:200]}"
        return out
    closest = ((data.get("archived_snapshots") or {}).get("closest") or {})
    if not closest.get("url"):
        out["error"] = "wayback: no snapshot"
        return out
    out["archived_url"] = closest["url"]
    out["archived_at"] = closest.get("timestamp")
    got = fetch_urllib(closest["url"], timeout=timeout)
    out.update({"status": got["status"], "text": got["text"], "title": got["title"]})
    if got["error"]:
        out["error"] = got["error"]
    return out


def snapshot_path(run_dir: str, url: str) -> str:
    return os.path.join(run_dir, "snapshots", url_key(url) + ".json")


def load_snapshot(run_dirs: List[str], url: str) -> Optional[Dict[str, Any]]:
    for rd in run_dirs:
        p = snapshot_path(rd, url)
        if os.path.exists(p):
            return ec.load_json(p)
    return None


# ---- collecting ------------------------------------------------------------------------------

def resolve_run(arg: str) -> str:
    p = arg if os.path.isabs(arg) else os.path.join(HERE, arg)
    if not os.path.isdir(os.path.join(p, "records")):
        alt = ec.run_dir_for(arg)
        if os.path.isdir(os.path.join(alt, "records")):
            return alt
        sys.exit(f"no records/ under {arg}")
    return p


def collect_urls(run_dirs: List[str], include_grounding: bool, only=None) -> Dict[str, Dict[str, Any]]:
    """url -> {run_dirs: set, run_dates: set, fields: set}"""
    urls: Dict[str, Dict[str, Any]] = {}

    def add(u, rd, run_date, field):
        if not isinstance(u, str) or not u.startswith("http"):
            return
        u = u.strip()
        e = urls.setdefault(u, {"run_dirs": set(), "run_dates": set(), "fields": set()})
        e["run_dirs"].add(rd)
        if run_date:
            e["run_dates"].add(run_date)
        e["fields"].add(field)

    for rd in run_dirs:
        for tag, rec in ec.iter_records(rd):
            if only and rec.get("domain") not in only:
                continue
            run_date = rec.get("run_date")
            for fid, ans in (rec.get("answers") or {}).items():
                for u in (ans or {}).get("citations") or []:
                    add(u, rd, run_date, fid)
            if include_grounding:
                raw = ec.load_json(os.path.join(rd, "raw", tag + ".json"), None)
                if isinstance(raw, dict):
                    for g in ((raw.get("output") or {}).get("grounding") or []):
                        for c in (g or {}).get("citations") or []:
                            add((c or {}).get("url"), rd, run_date, "grounding:" + str(g.get("field")))
    return urls


def hours_after(run_dates, now: dt.datetime) -> Optional[float]:
    ds = sorted(d for d in run_dates if isinstance(d, str) and re.match(r"^\d{4}-\d{2}-\d{2}", d))
    if not ds:
        return None
    try:
        start = dt.datetime.strptime(ds[0][:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return round((now - start).total_seconds() / 3600.0, 1)


def snapshot_one(url: str, info: Dict[str, Any], key: Optional[str], max_chars: int) -> Dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    via = None
    got = None
    if key:
        got = fetch_firecrawl(url, key)
        via = "firecrawl"
        if got["error"] or got["status"] is None:
            fb = fetch_urllib(url)
            fb["error"] = (f"{got['error']}; urllib: {fb['error']}" if fb["error"] else got["error"])
            got, via = fb, "urllib"
    else:
        got = fetch_urllib(url)
        via = "urllib"
    text, _ = ec.scrub_credentials(got.get("text") or "")
    rec = {"url": url, "fetched_at": now.isoformat(), "hours_after_run": hours_after(info["run_dates"], now),
           "run_dates": sorted(info["run_dates"]), "fetched_via": via, "status": got.get("status"),
           "content_sha256": ec.sha256_hex(text) if text else None, "chars": len(text), "truncated": len(text) > max_chars,
           "title": (got.get("title") or "")[:300], "markdown": text[:max_chars], "error": got.get("error"),
           "final_url": got.get("final_url"), "archived_url": got.get("archived_url"), "fields": sorted(info["fields"])}
    if rec["hours_after_run"] is not None and rec["hours_after_run"] > 24:
        rec["late"] = True
    return rec


def write_snapshot(run_dirs, url, rec):
    for rd in run_dirs:
        os.makedirs(os.path.join(rd, "snapshots"), exist_ok=True)
        ec.dump_json(snapshot_path(rd, url), rec)
        line = {k: v for k, v in rec.items() if k != "markdown"}
        with open(os.path.join(rd, "snapshots", "index.jsonl"), "a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


# ---- report -----------------------------------------------------------------------------------

def report(run_dirs: List[str], include_grounding: bool, only=None) -> None:
    urls = collect_urls(run_dirs, include_grounding, only)
    for rd in run_dirs:
        snap_dir = os.path.join(rd, "snapshots")
        index_path = os.path.join(snap_dir, "index.jsonl")
        history: Dict[str, List[dict]] = {}
        if os.path.exists(index_path):
            for line in open(index_path):
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                history.setdefault(e.get("url"), []).append(e)
        cited = sorted(u for u, info in urls.items() if rd in info["run_dirs"])
        dead, changed, never, late = [], [], [], []
        for u in cited:
            h = history.get(u) or []
            if not h:
                never.append(u)
                continue
            last = h[-1]
            st = last.get("status")
            if last.get("error") or (isinstance(st, int) and st >= 400) or st is None:
                dead.append((u, st, last.get("error"), last.get("fetched_via")))
            hashes = [x.get("content_sha256") for x in h if x.get("content_sha256")]
            if len(hashes) >= 2 and hashes[-1] != hashes[0]:
                changed.append((u, len(h)))
            if any(x.get("late") for x in h):
                late.append(u)
        lines = [f"# Snapshot report: {os.path.basename(rd)}", "",
                 f"Cited URLs: {len(cited)} · snapshotted: {len(cited) - len(never)} · dead (status >= 400 or error): {len(dead)} · "
                 f"changed between passes: {len(changed)} · never fetched: {len(never)} · fetched > 24 h after the run: {len(late)}", ""]
        lines.append("## Dead or unreachable")
        lines += [f"- {u} · status {st} · via {via}" + (f" · {err}" if err else "") for u, st, err, via in dead] or ["- none"]
        lines += ["", "## Changed between passes (first and last content hash differ)"]
        lines += [f"- {u} · {n} fetches" for u, n in changed] or ["- none"]
        lines += ["", "## Never fetched"]
        lines += [f"- {u}" for u in never] or ["- none"]
        lines += ["", "## Fetched more than 24 hours after the run"]
        lines += [f"- {u}" for u in late] or ["- none"]
        text = "\n".join(lines) + "\n"
        print(text)
        if os.path.isdir(snap_dir) or cited:
            os.makedirs(snap_dir, exist_ok=True)
            with open(os.path.join(snap_dir, "report.md"), "w") as f:
                f.write(text)
            print(f"written: {os.path.join(snap_dir, 'report.md')}\n")


# ---- main --------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", nargs="+", required=True, help="run folders (runs/<name> or a name under runs/)")
    ap.add_argument("--include-grounding", action="store_true", help="also snapshot Exa output.grounding URLs from raw/")
    ap.add_argument("--only", default=None, help="comma list of domains (a one-company smoke)")
    ap.add_argument("--no-firecrawl", action="store_true", help="urllib only (free)")
    ap.add_argument("--force", action="store_true", help="refetch URLs that already have a snapshot (a second pass; history kept)")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS_DEFAULT)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--yes", action="store_true", help="actually fetch (Firecrawl credits unless --no-firecrawl)")
    ap.add_argument("--report", action="store_true", help="dead / changed / never-fetched report; fetches nothing")
    a = ap.parse_args()

    run_dirs = [resolve_run(r) for r in a.runs]
    only = set(x.strip() for x in a.only.split(",")) if a.only else None
    if a.report:
        report(run_dirs, a.include_grounding, only)
        return
    urls = collect_urls(run_dirs, a.include_grounding, only)
    have = {u for u in urls if load_snapshot(run_dirs, u)}
    todo = sorted(urls) if a.force else sorted(u for u in urls if u not in have)
    hosts = {}
    for u in todo:
        h = urllib.parse.urlsplit(u).netloc.lower()
        hosts[h] = hosts.get(h, 0) + 1
    n_rec = sum(1 for rd in run_dirs for _, r in ec.iter_records(rd) if not only or r.get("domain") in only)
    print(f"Plan: {len(urls)} distinct cited URLs across {n_rec} records in {len(run_dirs)} run folder(s)"
          + (" (grounding included)" if a.include_grounding else "") + f"; {len(have)} already snapshotted; {len(todo)} to fetch")
    if a.no_firecrawl:
        print("Fetch: urllib only, 0 Firecrawl credits")
    else:
        print(f"Fetch: Firecrawl v2 scrape first, urllib on error: worst case {len(todo)} credits (1 a page); needs FIRECRAWL_API_KEY (environment or .env)"
              f" ({'present' if ec.env_key('FIRECRAWL_API_KEY', required=False) else 'MISSING'})")
    top = sorted(hosts.items(), key=lambda kv: -kv[1])[:8]
    if top:
        print("Top hosts: " + ", ".join(f"{h} {n}" for h, n in top))
    now = dt.datetime.now(dt.timezone.utc)
    lates = sum(1 for u in todo if (hours_after(urls[u]["run_dates"], now) or 0) > 24)
    if lates:
        print(f"NOTE: {lates} of the URLs to fetch are more than 24 hours after their run date; the snapshot records it as late")
    for rd in run_dirs:
        print(f"Output: {rd}/snapshots/")
    if not a.yes:
        print("Dry run: nothing fetched. Add --yes to fetch.")
        return
    key = None if a.no_firecrawl else ec.env_key("FIRECRAWL_API_KEY")
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        futs = {pool.submit(snapshot_one, u, urls[u], key, a.max_chars): u for u in todo}
        try:
            for fut in as_completed(futs):
                u = futs[fut]
                try:
                    rec = fut.result()
                except Exception as e:  # noqa: BLE001
                    print(f"ERROR {u}: {e}")
                    continue
                write_snapshot(sorted(urls[u]["run_dirs"]), u, rec)
                done += 1
                print(f"{str(rec['status']):>4} {rec['fetched_via']:9} {rec['chars']:>7}ch  {u[:110]}" + (f"  {rec['error']}" if rec["error"] else ""))
        except KeyboardInterrupt:
            print("\nCtrl-C: rerun to continue; finished snapshots are kept.")
            pool.shutdown(wait=False, cancel_futures=True)
    print(f"\n{done} fetched in {round(time.time() - t0)}s. Report: python3 snapshot.py --runs {' '.join(a.runs)} --report")


if __name__ == "__main__":
    main()
