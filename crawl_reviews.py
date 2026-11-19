#!/usr/bin/env python3
"""Snapshot every review (and meta-review / decision / comment) of an OpenReview venue.

Each run writes an immutable, timestamped snapshot: raw JSONL exactly as the API
returned it, plus flat CSVs and a manifest with per-note content hashes. Two
snapshots can then be compared with diff_snapshots.py (e.g. first public version
vs. post-rebuttal).

    python3 crawl_reviews.py --venue ICLR.cc/2027/Conference

Resume an interrupted run:

    python3 crawl_reviews.py --resume snapshots/ICLR_cc_2027_Conference/20261103T...
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orcommon as oc

DEFAULT_KINDS = ["review", "meta_review", "decision"]
ALL_KINDS = ["review", "meta_review", "decision", "comment", "rebuttal"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--venue", default="ICLR.cc/2027/Conference", help="venue group id (default: %(default)s)")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "snapshots"),
                   help="root directory for snapshots")
    p.add_argument("--resume", metavar="SNAPSHOT_DIR", help="continue an interrupted snapshot")
    p.add_argument("--label", default="", help="suffix for the snapshot dir, e.g. 'first-release'")
    p.add_argument("--kinds", default=",".join(DEFAULT_KINDS),
                   help=f"comma list from {ALL_KINDS}, or 'all' (default: %(default)s)")
    p.add_argument("--skip-submissions", action="store_true", help="do not crawl the papers themselves")
    p.add_argument("--replies-mode", choices=["auto", "parent", "forum"], default="auto",
                   help="how to find reviews: 'parent' = one bulk query per kind; 'forum' = walk every "
                        "paper's direct replies; 'auto' = parent, falling back to forum (default)")
    p.add_argument("--page-size", type=int, default=1000, help="notes per request (default: %(default)s)")
    p.add_argument("--sleep", type=float, default=0.25, help="seconds between pages (default: %(default)s)")
    p.add_argument("--limit", type=int, default=0, help="stop each stream after N notes (testing)")
    p.add_argument("--no-gzip", action="store_true", help="write plain .jsonl instead of .jsonl.gz")
    p.add_argument("--no-csv", action="store_true", help="skip the CSV derivation step")
    p.add_argument("--username", help="OpenReview email (else $OPENREVIEW_USERNAME)")
    p.add_argument("--password", help="OpenReview password (else $OPENREVIEW_PASSWORD)")
    p.add_argument("--baseurl", default=oc.API2)
    return p.parse_args(argv)


# --------------------------------------------------------------------------- #
# progress bookkeeping (makes a run resumable)
# --------------------------------------------------------------------------- #
class Progress:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"streams": {}}

    def get(self, stream: str) -> dict:
        return self.data["streams"].setdefault(stream, {"cursor": None, "done": False, "n": 0})

    def save(self) -> None:
        oc.write_json(self.path, self.data)


def crawl_stream(client, progress: Progress, stream: str, writer: oc.JsonlWriter, *,
                 args, log, on_note=None, **params) -> int:
    """Fetch one paginated note stream into `writer`, honouring resume + limit."""
    st = progress.get(stream)
    if st["done"]:
        log.info("[%s] already complete (%d notes) - skipping", stream, st["n"])
        return st["n"]
    if st["cursor"]:
        log.info("[%s] resuming after note id %s (%d already saved)", stream, st["cursor"], st["n"])

    n = st["n"]
    t0 = time.time()
    try:
        for batch, total, cursor in oc.iter_note_pages(
            client, page_size=args.page_size, after=st["cursor"], sleep=args.sleep,
            logger=log, label=stream, **params
        ):
            if args.limit:
                room = args.limit - n
                if room < len(batch):
                    # trim to the exact limit and keep the cursor on the last note we actually
                    # wrote, so a later --resume continues from there without gaps or repeats
                    batch = batch[:max(room, 0)]
                    cursor = batch[-1].id if batch else st["cursor"]
            for note in batch:
                writer.write(oc.note_to_dict(note))
                if on_note:
                    on_note(note)
                n += 1
            writer.flush()
            st["cursor"], st["n"] = cursor, n
            progress.save()
            rate = n / max(time.time() - t0, 1e-6)
            log.info("[%s] %d/%s notes (%.0f/s)", stream, n, total if total is not None else "?", rate)
            if args.limit and n >= args.limit:
                log.warning("[%s] stopping at --limit %d (snapshot is PARTIAL)", stream, args.limit)
                return n
    except oc.NeedsLogin:
        raise
    except Exception as e:
        log.error("[%s] aborted after %d notes: %s: %s", stream, n, oc.err_name(e), str(e)[:300])
        st["n"] = n
        progress.save()
        raise

    st["done"] = True
    st["n"] = n
    progress.save()
    log.info("[%s] done: %d notes in %.1fs", stream, n, time.time() - t0)
    return n


def _invitation_readable(client, inv_id: str, log) -> bool:
    try:
        oc.with_retry(client.get_invitation, inv_id, tries=2, logger=log, what=f"get_invitation({inv_id})")
        return True
    except Exception as e:
        log.info("invitation %s not readable (%s) - reviews are probably not released",
                 inv_id, oc.err_name(e))
        return False


def crawl_direct_replies(client, progress, snap: Path, kinds: list[str], supers: dict,
                         vids: list[str], *, args, log, gz: bool) -> dict[str, int]:
    """Harvest replies by re-walking submissions with details=directReplies.

    Slower than the bulk parent_invitations query (it re-reads every paper) but it only
    needs the papers to be listable. Note: it sees replies *to the paper* - a review is
    one, a comment nested under a review is not.
    """
    if not kinds:
        return {}
    suffix = {k: supers[k].split("/-/")[-1] for k in kinds}
    writers = {k: oc.JsonlWriter(snap / f"raw/{k}s.jsonl", gzip_out=gz) for k in kinds}
    counts = {k: 0 for k in kinds}
    seen: set[str] = set()

    def on_note(note):
        details = getattr(note, "details", None) or {}
        for reply in details.get("directReplies") or []:
            rid = reply.get("id")
            if rid in seen:
                continue
            invs = reply.get("invitations") or []
            for k in kinds:
                if any(i.endswith("/-/" + suffix[k]) for i in invs):
                    writers[k].write(reply)
                    counts[k] += 1
                    if rid:
                        seen.add(rid)
                    break

    try:
        for vid in vids:
            crawl_stream(client, progress, f"replies::{vid}", oc.NullWriter(),
                         args=args, log=log, on_note=on_note,
                         content={"venueid": vid}, details="directReplies")
            for w in writers.values():
                w.flush()
            log.info("direct-replies pass after %s: %s", vid, counts)
    finally:
        for w in writers.values():
            w.close()
    return counts


# --------------------------------------------------------------------------- #
# CSV derivation
# --------------------------------------------------------------------------- #
BASE_REVIEW_COLS = ["paper_number", "forum", "paper_title", "paper_venueid", "review_id",
                    "reviewer", "signatures", "invitation", "readers", "is_public",
                    "rating_num", "confidence_num", "cdate", "tcdate", "mdate", "tmdate",
                    "replyto", "content_sha256"]


def derive_csvs(snap: Path, cfg: dict, log) -> dict:
    """Stream the raw JSONL back out into reviews.csv / papers.csv (no big in-memory lists)."""
    reviews_raw = _existing(snap, "raw/reviews.jsonl")
    subs_raw = _existing(snap, "raw/submissions.jsonl")
    stats = {}

    paper_meta: dict[str, dict] = {}
    if subs_raw:
        for note in oc.read_jsonl(subs_raw):
            flat = oc.flatten_content(note.get("content"))
            paper_meta[note["id"]] = {
                "number": note.get("number"),
                "title": flat.get("title") or "",
                "venueid": flat.get("venueid") or "",
                "keywords": flat.get("keywords") or "",
                "primary_area": flat.get("primary_area") or flat.get("area") or "",
            }
        log.info("loaded metadata for %d papers", len(paper_meta))

    if not reviews_raw:
        log.warning("no raw/reviews.jsonl found - nothing to flatten")
        return stats

    rating_field = cfg.get("review_rating") or "rating"
    conf_field = cfg.get("review_confidence") or "confidence"

    # pass 1: which content fields exist across all reviews
    content_keys: set[str] = set()
    for note in oc.read_jsonl(reviews_raw):
        content_keys.update(oc.flatten_content(note.get("content")).keys())
    extra_cols = sorted(content_keys)
    log.info("review content fields: %s", ", ".join(extra_cols) or "(none)")

    # pass 2: write rows
    per_paper: dict[str, list[float]] = {}
    out_csv = snap / "reviews.csv"
    n = 0
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BASE_REVIEW_COLS + extra_cols, extrasaction="ignore")
        w.writeheader()
        for note in oc.read_jsonl(reviews_raw):
            flat = oc.flatten_content(note.get("content"))
            forum = note.get("forum") or ""
            meta = paper_meta.get(forum, {})
            rating = oc.numeric(flat.get(rating_field))
            row = {
                "paper_number": meta.get("number") or oc.paper_number_from_invitations(note.get("invitations")),
                "forum": forum,
                "paper_title": meta.get("title", ""),
                "paper_venueid": meta.get("venueid", ""),
                "review_id": note.get("id"),
                "reviewer": oc.anon_reviewer(note.get("signatures")),
                "signatures": ";".join(note.get("signatures") or []),
                "invitation": ";".join(note.get("invitations") or []),
                "readers": ";".join(note.get("readers") or []),
                "is_public": oc.is_public(note.get("readers")),
                "rating_num": rating,
                "confidence_num": oc.numeric(flat.get(conf_field)),
                "cdate": note.get("cdate"), "tcdate": note.get("tcdate"),
                "mdate": note.get("mdate"), "tmdate": note.get("tmdate"),
                "replyto": note.get("replyto"),
                "content_sha256": oc.content_hash(flat),
            }
            for k in extra_cols:
                v = flat.get(k)
                row[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
            row = {k: (v.replace("\x00", "") if isinstance(v, str) else v) for k, v in row.items()}
            w.writerow(row)
            n += 1
            if rating is not None and forum:
                per_paper.setdefault(forum, []).append(rating)
    stats["reviews_csv_rows"] = n
    log.info("wrote %s (%d rows)", out_csv, n)

    if paper_meta:
        out_papers = snap / "papers.csv"
        with open(out_papers, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["paper_number", "forum", "title", "venueid", "primary_area", "keywords",
                        "n_reviews", "ratings", "rating_mean", "rating_min", "rating_max", "url"])
            for fid, meta in sorted(paper_meta.items(), key=lambda kv: (kv[1]["number"] or 0)):
                rs = per_paper.get(fid, [])
                kw = meta["keywords"]
                w.writerow([
                    meta["number"], fid, meta["title"], meta["venueid"], meta["primary_area"],
                    ";".join(kw) if isinstance(kw, list) else kw,
                    len(rs), ";".join(f"{r:g}" for r in rs),
                    f"{sum(rs)/len(rs):.3f}" if rs else "",
                    f"{min(rs):g}" if rs else "", f"{max(rs):g}" if rs else "",
                    f"https://openreview.net/forum?id={fid}",
                ])
        stats["papers_csv_rows"] = len(paper_meta)
        log.info("wrote %s (%d rows)", out_papers, len(paper_meta))
    return stats


def _existing(snap: Path, rel: str) -> Path | None:
    for cand in (snap / (rel + ".gz"), snap / rel):
        if cand.is_file():
            return cand
    return None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    args = parse_args(argv)
    kinds = ALL_KINDS if args.kinds.strip() == "all" else [k.strip() for k in args.kinds.split(",") if k.strip()]
    bad = [k for k in kinds if k not in ALL_KINDS]
    if bad:
        print(f"unknown --kinds: {bad}; valid: {ALL_KINDS}", file=sys.stderr)
        return 2

    if args.resume:
        snap = Path(args.resume).resolve()
        if not snap.is_dir():
            print(f"--resume: {snap} is not a directory", file=sys.stderr)
            return 2
    else:
        stamp = oc.utc_stamp() + (f"_{args.label}" if args.label else "")
        snap = Path(args.out).resolve() / oc.slug(args.venue) / stamp
        snap.mkdir(parents=True, exist_ok=True)

    log = oc.get_logger("crawl", snap / "crawl.log")
    log.info("snapshot dir: %s", snap)
    log.info("venue=%s kinds=%s", args.venue, kinds)

    try:
        client = oc.login(args.username, args.password, baseurl=args.baseurl, logger=log)
    except oc.NeedsLogin as e:
        log.error("%s", e)
        return 3

    cfg = oc.venue_config(client, args.venue, logger=log)
    oc.write_json(snap / "venue_config.json", cfg)
    supers = oc.reply_invitation_ids(cfg, args.venue)
    vids = oc.submission_venueids(cfg, args.venue)
    log.info("submission venueids: %s", vids)
    log.info("reply invitations: %s", {k: supers[k] for k in kinds})

    progress = Progress(snap / "_progress.json")
    gz = not args.no_gzip
    counts: dict[str, int] = {}
    started = time.time()
    writers: list[oc.JsonlWriter] = []
    try:
        # ---- papers -------------------------------------------------------
        if not args.skip_submissions:
            w = oc.JsonlWriter(snap / "raw/submissions.jsonl", gzip_out=gz)
            writers.append(w)
            for vid in vids:
                counts[f"submissions[{vid}]"] = crawl_stream(
                    client, progress, f"submissions::{vid}", w,
                    args=args, log=log, content={"venueid": vid},
                )
            w.close()

        # ---- reviews and friends ------------------------------------------
        if args.replies_mode in ("auto", "parent"):
            for kind in kinds:
                inv = supers[kind]
                w = oc.JsonlWriter(snap / f"raw/{kind}s.jsonl", gzip_out=gz)
                writers.append(w)
                try:
                    counts[kind] = crawl_stream(
                        client, progress, f"{kind}::{inv}", w,
                        args=args, log=log, parent_invitations=inv,
                    )
                except Exception as e:
                    name, status = oc.err_name(e), oc.err_status(e)
                    if status in (403, 404) or name in ("ForbiddenError", "NotFoundError"):
                        # normal before release: the invitation exists but is not readable yet
                        log.warning("[%s] not available yet (%s) - continuing", kind, name)
                        counts[kind] = progress.get(f"{kind}::{inv}")["n"]
                    else:
                        raise
                finally:
                    w.close()

        # Fallback: if the bulk query found no reviews even though papers exist and the
        # review invitation is readable, walk each paper's direct replies instead.
        n_papers = sum(v for k, v in counts.items() if k.startswith("submissions["))
        need_fallback = args.replies_mode == "forum" or (
            args.replies_mode == "auto" and "review" in kinds and not counts.get("review")
            and (n_papers > 0 or args.skip_submissions) and _invitation_readable(client, supers["review"], log)
        )
        if need_fallback:
            harvest = [k for k in kinds if not counts.get(k)]
            log.warning("using direct-replies fallback for %s (bulk query returned nothing)", harvest)
            got = crawl_direct_replies(client, progress, snap, harvest, supers, vids,
                                       args=args, log=log, gz=gz)
            counts.update(got)

        # ---- CSVs ---------------------------------------------------------
        csv_stats = {} if args.no_csv else derive_csvs(snap, cfg, log)
    finally:
        for w in writers:
            w.close()

    files = {}
    for p in sorted(snap.rglob("*")):
        if p.is_file() and p.name not in ("manifest.json", "crawl.log"):
            files[str(p.relative_to(snap))] = {"bytes": p.stat().st_size, "sha256": oc.file_sha256(p)}

    manifest = {
        "venue": args.venue,
        "snapshot_dir": str(snap),
        "snapshot_utc": oc.utc_stamp(),
        "finished_epoch": int(time.time()),
        "duration_sec": round(time.time() - started, 1),
        "crawled_by": oc.whoami(client),
        "baseurl": args.baseurl,
        "kinds": kinds,
        "counts": counts,
        "csv": csv_stats,
        "partial": bool(args.limit),
        "args": vars(args),
        "files": files,
    }
    oc.write_json(snap / "manifest.json", manifest)
    log.info("counts: %s", json.dumps(counts))
    log.info("snapshot complete -> %s", snap)
    print(snap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
