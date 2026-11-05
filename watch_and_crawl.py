#!/usr/bin/env python3
"""Poll OpenReview until reviews go public, then crawl them immediately.

Trigger logic: every --interval seconds ask the API how many notes exist under the
venue's Official_Review super-invitation. Fire when that count reaches --min-count
and (unless --no-require-public) at least one sampled review is readable by
'everyone' - so a review you wrote yourself, or reviews of your own paper, cannot
set the whole crawl off early.

    python3 watch_and_crawl.py --venue ICLR.cc/2027/Conference --interval 300

Single check (for cron):

    python3 watch_and_crawl.py --once
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orcommon as oc

HERE = Path(__file__).resolve().parent


def parse_offsets(spec: str) -> list[int]:
    """'2h,12h,36h' or '7200,43200' -> seconds."""
    out = []
    for tok in (t.strip().lower() for t in spec.split(",") if t.strip()):
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", tok)
        if not m:
            raise argparse.ArgumentTypeError(f"bad offset {tok!r}; use 30m, 2h, 1d or plain seconds")
        mult = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        out.append(int(float(m.group(1)) * mult))
    return sorted(out)


def off_label(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"followup-{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"followup-{seconds // 3600}h"
    return f"followup-{max(seconds // 60, 1)}m"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--venue", default="ICLR.cc/2027/Conference")
    p.add_argument("--interval", type=float, default=300, help="seconds between checks (default: %(default)s)")
    p.add_argument("--min-count", type=int, default=50,
                   help="reviews visible before firing (default: %(default)s)")
    p.add_argument("--no-require-public", action="store_true",
                   help="fire even if no sampled review is public yet")
    p.add_argument("--once", action="store_true", help="check once and exit (exit 0 = crawled)")
    p.add_argument("--followups", default="", type=str,
                   help="extra snapshots after the first, e.g. '6h,24h,3d'")
    p.add_argument("--state", default=str(HERE / "watch_state.json"))
    p.add_argument("--out", default=str(HERE / "snapshots"))
    p.add_argument("--log", default=str(HERE / "watch.log"))
    p.add_argument("--notify-cmd", default="",
                   help="shell command run after each crawl; $SNAPSHOT_DIR is set")
    p.add_argument("--crawl-args", default="", help="extra args forwarded to crawl_reviews.py")
    p.add_argument("--dry-run", action="store_true", help="report state, never crawl")
    p.add_argument("--username")
    p.add_argument("--password")
    p.add_argument("--baseurl", default=oc.API2)
    return p.parse_args(argv)


def load_state(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"first_crawl_epoch": None, "snapshots": [], "checks": 0, "last_count": 0}


def probe(client, venue: str, log) -> tuple[int, int, int]:
    """Return (total_reviews_visible, sampled, public_in_sample)."""
    cfg = oc.venue_config(client, venue, logger=log)
    inv = oc.reply_invitation_ids(cfg, venue)["review"]
    try:
        total = oc.count_notes(client, parent_invitations=inv, logger=log)
    except Exception as e:
        if oc.err_status(e) in (403, 404) or oc.err_name(e) in ("ForbiddenError", "NotFoundError"):
            return 0, 0, 0
        raise
    if total <= 0:
        return 0, 0, 0
    sample = oc.with_retry(client.get_notes, parent_invitations=inv, limit=5,
                           sort="tcdate:desc", logger=log, what="sample reviews") or []
    pub = sum(1 for n in sample if oc.is_public(getattr(n, "readers", [])))
    return total, len(sample), pub


def run_crawl(args, label: str, log) -> Path | None:
    cmd = [sys.executable, str(HERE / "crawl_reviews.py"),
           "--venue", args.venue, "--out", args.out, "--label", label]
    if args.crawl_args:
        cmd += shlex.split(args.crawl_args)
    log.info("launching: %s", " ".join(shlex.quote(c) for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    tail = (proc.stdout or "").strip().splitlines()
    snap = Path(tail[-1]) if proc.returncode == 0 and tail else None
    if proc.returncode != 0:
        log.error("crawl failed (exit %d): %s", proc.returncode, (proc.stderr or "")[-2000:])
        return None
    log.info("crawl finished -> %s", snap)
    if args.notify_cmd and snap:
        try:
            subprocess.run(args.notify_cmd, shell=True, timeout=120,
                           env={**os.environ, "SNAPSHOT_DIR": str(snap)})
        except Exception as e:
            log.warning("notify-cmd failed: %s", e)
    return snap


def main(argv=None) -> int:
    args = parse_args(argv)
    log = oc.get_logger("watch", Path(args.log))
    state_path = Path(args.state)
    state = load_state(state_path)
    offsets = parse_offsets(args.followups) if args.followups else []

    try:
        client = oc.login(args.username, args.password, baseurl=args.baseurl, logger=log)
    except oc.NeedsLogin as e:
        log.error("%s", e)
        return 3

    log.info("watching %s every %.0fs (min-count=%d, require-public=%s, followups=%s)",
             args.venue, args.interval, args.min_count, not args.no_require_public,
             args.followups or "none")

    while True:
        state["checks"] = state.get("checks", 0) + 1
        try:
            total, sampled, pub = probe(client, args.venue, log)
        except oc.NeedsLogin as e:
            log.error("%s", e)
            return 3
        except Exception as e:
            log.warning("probe error (%s: %s) - will retry", oc.err_name(e), str(e)[:200])
            total = sampled = pub = -1

        if total >= 0:
            state["last_count"] = total
            log.info("check #%d: %d review notes visible (%d/%d sampled are public)",
                     state["checks"], total, pub, sampled)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        oc.write_json(state_path, state)

        ready = total >= args.min_count and (args.no_require_public or pub > 0)

        if ready and state.get("first_crawl_epoch") is None:
            if args.dry_run:
                log.info("DRY RUN: would crawl now")
                return 0
            log.info("REVIEWS ARE OUT - crawling now")
            snap = run_crawl(args, "first-release", log)
            state["first_crawl_epoch"] = int(time.time())
            if snap:
                state["snapshots"] = state.get("snapshots", []) + [{"label": "first-release",
                                                                   "dir": str(snap),
                                                                   "epoch": state["first_crawl_epoch"],
                                                                   "review_count": total}]
            oc.write_json(state_path, state)
            if not offsets:
                return 0

        # follow-up snapshots (post-rebuttal versions)
        if state.get("first_crawl_epoch") and offsets:
            labels = [off_label(o) for o in offsets]
            done = {s["label"] for s in state.get("snapshots", [])}
            elapsed = time.time() - state["first_crawl_epoch"]
            for off, label in zip(offsets, labels):
                if label in done or elapsed < off:
                    continue
                snap = run_crawl(args, label, log)
                state.setdefault("snapshots", []).append(
                    {"label": label, "dir": str(snap) if snap else None,
                     "epoch": int(time.time()), "review_count": state["last_count"]})
                done.add(label)
                oc.write_json(state_path, state)
            if all(lbl in done for lbl in labels):
                log.info("all follow-up snapshots done")
                return 0

        if args.once:
            return 0 if state.get("first_crawl_epoch") else 1
        time.sleep(max(args.interval, 30))


if __name__ == "__main__":
    raise SystemExit(main())
