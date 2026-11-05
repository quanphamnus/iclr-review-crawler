#!/usr/bin/env python3
"""Offline end-to-end test: fake OpenReview client -> crawl -> CSV -> diff.

Runs without credentials and without network, so the pipeline can be verified
before reviews are released.

    python3 selftest.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import orcommon as oc
import crawl_reviews
import diff_snapshots
import watch_and_crawl

VENUE = "TEST.cc/2027/Conference"
N_PAPERS, N_REV_PER_PAPER = 2500, 4


class FakeNote:
    def __init__(self, d):
        self.__dict__["_d"] = d

    def __getattr__(self, k):
        try:
            return self._d[k]
        except KeyError:
            raise AttributeError(k)

    def to_json(self):
        return dict(self._d)


class FakeGroup:
    content = {
        "subtitle": {"value": "TEST 2027"}, "title": {"value": "Test Venue"},
        "review_name": {"value": "Official_Review"}, "meta_review_name": {"value": "Meta_Review"},
        "decision_name": {"value": "Decision"}, "review_rating": {"value": "rating"},
        "review_confidence": {"value": "confidence"},
        "submission_venue_id": {"value": f"{VENUE}/Submission"},
        "withdrawn_venue_id": {"value": f"{VENUE}/Withdrawn_Submission"},
        "desk_rejected_venue_id": {"value": f"{VENUE}/Desk_Rejected_Submission"},
        "rejected_venue_id": {"value": f"{VENUE}/Rejected_Submission"},
    }


class FakeClient:
    """Mimics API2 cursor pagination (sort=id + after=<last id>) and with_count."""

    user = {"user": {"id": "~Test_User1"}}

    def __init__(self, bump_ratings: bool = False, extra_reviews: int = 0,
                 public: bool = True, only_reviews: int | None = None,
                 support_parent: bool = True):
        self.bump = bump_ratings
        self.public = public
        self.support_parent = support_parent
        self.calls = 0
        self.papers, self.reviews = [], []
        for i in range(1, N_PAPERS + 1):
            fid = f"paper{i:05d}"
            vid = f"{VENUE}/Submission" if i % 50 else f"{VENUE}/Withdrawn_Submission"
            self.papers.append(FakeNote({
                "id": fid, "number": i, "forum": fid, "invitations": [f"{VENUE}/-/Submission"],
                "readers": ["everyone"], "signatures": [f"{VENUE}/Submission{i}/Authors"],
                "cdate": 1762000000000, "tcdate": 1762000000000, "mdate": 1762000000000,
                "tmdate": 1762000000000,
                "content": {"title": {"value": f"Paper {i}: on the thing"},
                            "venueid": {"value": vid},
                            "keywords": {"value": ["alpha", "beta"]},
                            "primary_area": {"value": "representation learning"}},
            }))
            for r in range(N_REV_PER_PAPER):
                rating = 3 + (i + r) % 6
                if self.bump and i % 7 == 0 and r == 0:
                    rating += 2  # simulate a post-rebuttal score raise
                weak = "Weakness one.\nWeakness two." + (" Addressed in rebuttal." if self.bump and i % 5 == 0 else "")
                self.reviews.append(FakeNote({
                    "id": f"rev{i:05d}_{r}", "forum": fid, "replyto": fid, "number": r + 1,
                    "invitations": [f"{VENUE}/Submission{i}/-/Official_Review"],
                    "parentInvitations": [f"{VENUE}/-/Official_Review"],
                    "readers": ["everyone"] if public else [f"{VENUE}/Submission{i}/Reviewers"],
                    "signatures": [f"{VENUE}/Submission{i}/Reviewer_x{r}"],
                    "cdate": 1762500000000, "tcdate": 1762500000000,
                    "mdate": 1762600000000 if self.bump else 1762500000000,
                    "tmdate": 1762600000000 if self.bump else 1762500000000,
                    "content": {"summary": {"value": f"Summary for paper {i} by reviewer {r}."},
                                "strengths": {"value": "Strong idea."},
                                "weaknesses": {"value": weak},
                                "questions": {"value": "Why?"},
                                "rating": {"value": f"{rating}: marginal"},
                                "confidence": {"value": str(3 + r % 3)}},
                }))
        for j in range(extra_reviews):  # late-arriving reviews
            self.reviews.append(FakeNote({
                "id": f"revLATE_{j}", "forum": "paper00001", "replyto": "paper00001", "number": 9,
                "invitations": [f"{VENUE}/Submission1/-/Official_Review"],
                "readers": ["everyone"], "signatures": [f"{VENUE}/Submission1/Reviewer_late{j}"],
                "cdate": 1763000000000, "tcdate": 1763000000000, "mdate": 1763000000000,
                "tmdate": 1763000000000,
                "content": {"summary": {"value": "Late review."}, "rating": {"value": "6: accept"},
                            "confidence": {"value": "4"}},
            }))

        if only_reviews is not None:
            self.reviews = self.reviews[:only_reviews]
        self.by_forum: dict[str, list] = {}
        for r in self.reviews:
            self.by_forum.setdefault(r.forum, []).append(r)

    def get_group(self, gid, **kw):
        return FakeGroup()

    def get_invitation(self, iid, **kw):
        return FakeNote({"id": iid, "cdate": 1762500000000})

    def get_notes(self, **kw):
        self.calls += 1
        if kw.get("parent_invitations") and not self.support_parent:
            pool = []            # API that ignores/rejects the bulk parent query
        elif kw.get("parent_invitations", "").endswith("/Official_Review"):
            pool = self.reviews
        elif kw.get("parent_invitations"):
            pool = []
        elif kw.get("content", {}).get("venueid"):
            vid = kw["content"]["venueid"]
            pool = [p for p in self.papers if p.content["venueid"]["value"] == vid]
        else:
            pool = []
        pool = sorted(pool, key=lambda n: n.id)
        if kw.get("details") == "directReplies":
            pool = [FakeNote({**pap.to_json(),
                              "details": {"directReplies": [r.to_json() for r in self.by_forum.get(pap.id, [])]}})
                    for pap in pool]
        after = kw.get("after")
        if after:
            ids = [n.id for n in pool]
            pool = pool[ids.index(after) + 1:] if after in ids else []
        limit = kw.get("limit") or 1000
        page = pool[:limit]
        return (page, len(pool) + (0 if not after else 0)) if kw.get("with_count") else page


def run(label: str, tmp: Path, client, extra_args=None) -> Path:
    oc_login = oc.login
    oc.login = lambda *a, **k: client  # type: ignore[assignment]
    try:
        argv = ["--venue", VENUE, "--out", str(tmp), "--label", label, "--sleep", "0",
                "--kinds", "review,meta_review,decision"] + (extra_args or [])
        rc = crawl_reviews.main(argv)
        assert rc == 0, f"crawl exited {rc}"
    finally:
        oc.login = oc_login  # type: ignore[assignment]
    snaps = sorted((tmp / oc.slug(VENUE)).glob(f"*_{label}"))
    assert snaps, "no snapshot dir created"
    return snaps[-1]


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        raise SystemExit(1)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="orselftest-"))
    try:
        print(f"\n[1] crawl 'first release' ({N_PAPERS} papers, {N_PAPERS * N_REV_PER_PAPER} reviews)")
        c1 = FakeClient()
        snap1 = run("first-release", tmp, c1)
        m1 = json.loads((snap1 / "manifest.json").read_text())
        n_rev = m1["counts"]["review"]
        n_sub = sum(v for k, v in m1["counts"].items() if k.startswith("submissions["))
        check(n_rev == N_PAPERS * N_REV_PER_PAPER, f"all reviews fetched across pages: {n_rev}")
        check(n_sub == N_PAPERS, f"all papers fetched across venueids: {n_sub}")
        check((snap1 / "raw/reviews.jsonl.gz").is_file(), "raw reviews written gzipped")
        check(m1["counts"]["meta_review"] == 0, "empty stream handled (meta_review=0)")

        with open(snap1 / "reviews.csv", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))   # multi-line review text is quoted, so parse properly
        check(len(rows) == n_rev, f"reviews.csv has one row per review: {len(rows)}")
        for col in ("paper_number", "paper_title", "rating_num", "content_sha256", "weaknesses"):
            check(col in rows[0], f"reviews.csv column '{col}' present")
        check(rows[0]["paper_title"] == "Paper 1: on the thing", "paper title joined onto review row")
        check("\n" in rows[0]["weaknesses"], "multi-line review text preserved intact")
        check(rows[0]["rating_num"] not in ("", None) and float(rows[0]["rating_num"]) >= 3,
              f"rating parsed out of '8: marginal' style string -> {rows[0]['rating_num']}")
        check(len({r["content_sha256"] for r in rows}) > n_rev * 0.9, "content hashes are distinct per review")
        with open(snap1 / "papers.csv", encoding="utf-8", newline="") as fh:
            papers = list(csv.DictReader(fh))
        check(len(papers) == N_PAPERS, f"papers.csv has one row per paper: {len(papers)}")
        check(papers[0]["n_reviews"] == str(N_REV_PER_PAPER), "papers.csv counts reviews per paper")
        check(papers[0]["rating_mean"] and float(papers[0]["rating_mean"]) > 0, "papers.csv aggregates ratings")
        check(any(p["venueid"].endswith("Withdrawn_Submission") for p in papers), "withdrawn papers included")
        check(all(f["sha256"] for f in m1["files"].values()), "manifest hashes every file")

        print("\n[2] resume after interruption")
        c2 = FakeClient()
        partial = run("partial", tmp, c2, ["--limit", "1200", "--no-csv"])
        p_before = json.loads((partial / "_progress.json").read_text())
        rev_done = [v for k, v in p_before["streams"].items() if k.startswith("review::")][0]
        check(not rev_done["done"] and rev_done["n"] == 1200, f"stopped mid-stream at {rev_done['n']}")
        oc_login = oc.login
        oc.login = lambda *a, **k: c2  # type: ignore[assignment]
        try:
            rc = crawl_reviews.main(["--venue", VENUE, "--out", str(tmp), "--resume", str(partial),
                                     "--sleep", "0", "--kinds", "review,meta_review,decision"])
        finally:
            oc.login = oc_login  # type: ignore[assignment]
        check(rc == 0, "resume run exited 0")
        m2 = json.loads((partial / "manifest.json").read_text())
        check(m2["counts"]["review"] == N_PAPERS * N_REV_PER_PAPER,
              f"resume completed the stream: {m2['counts']['review']}")
        ids = [n["id"] for n in oc.read_jsonl(partial / "raw/reviews.jsonl.gz")]
        check(len(ids) == len(set(ids)), f"no duplicate notes after resume: {len(ids)} unique")

        print("\n[3] crawl 'post-rebuttal' and diff")
        c3 = FakeClient(bump_ratings=True, extra_reviews=3)
        snap2 = run("followup-24h", tmp, c3)
        rc = diff_snapshots.main([str(snap1), str(snap2)])
        check(rc == 0, "diff exited 0")
        d = json.loads((snap2 / "diff.json").read_text())
        s = d["summary"]
        check(s["added"] == 3, f"detected {s['added']} added reviews")
        check(s["removed"] == 0, "no spurious removals")
        exp_bump = len([i for i in range(1, N_PAPERS + 1) if i % 7 == 0])
        check(s["rating_changes"] == exp_bump, f"detected {s['rating_changes']} rating changes (expected {exp_bump})")
        check(s["rating_up"] == exp_bump and s["rating_down"] == 0, "rating deltas signed correctly")
        exp_edit = len(set([i for i in range(1, N_PAPERS + 1) if i % 7 == 0]) |
                       set()) + len([i for i in range(1, N_PAPERS + 1) if i % 5 == 0]) * N_REV_PER_PAPER \
            - len([i for i in range(1, N_PAPERS + 1) if i % 35 == 0])
        check(s["edited"] == exp_edit, f"detected {s['edited']} edited reviews (expected {exp_edit})")
        md = (snap2 / "diff.md").read_text(encoding="utf-8")
        check("Addressed in rebuttal" in md, "diff.md shows the reworded text")
        check("| before | after |" in md.replace("reviewer | ", ""), "diff.md has a rating table")

        print("\n[4] watcher trigger gating")
        state = tmp / "wstate.json"
        base = ["--venue", VENUE, "--out", str(tmp), "--once", "--dry-run",
                "--state", str(state), "--log", str(tmp / "watch.log")]

        def watch(client, extra):
            oc_login = oc.login
            oc.login = lambda *a, **k: client  # type: ignore[assignment]
            try:
                state.unlink(missing_ok=True)
                return watch_and_crawl.main(base + extra)
            finally:
                oc.login = oc_login  # type: ignore[assignment]

        check(watch(FakeClient(only_reviews=0), []) == 1, "no reviews visible -> does not fire")
        check(watch(FakeClient(only_reviews=4), []) == 1, "4 reviews < --min-count 50 -> does not fire")
        check(watch(FakeClient(public=False), []) == 1,
              "many reviews but none public (own paper / own review) -> does not fire")
        check(watch(FakeClient(public=False), ["--no-require-public"]) == 0,
              "--no-require-public overrides the public check")
        check(watch(FakeClient(), []) == 0, "public reviews above threshold -> fires")
        check(watch(FakeClient(only_reviews=60), ["--min-count", "60"]) == 0, "--min-count boundary fires at ==")
        check(watch_and_crawl.off_label(3600) == "followup-1h"
              and watch_and_crawl.off_label(86400 * 3) == "followup-3d"
              and watch_and_crawl.off_label(1800) == "followup-30m", "follow-up labels formatted")
        check(watch_and_crawl.parse_offsets("30m,6h,2d") == [1800, 21600, 172800], "offset parsing")

        print("\n[5] direct-replies fallback (API without bulk parent query)")
        c5 = FakeClient(support_parent=False)
        snap5 = run("fallback", tmp, c5)
        m5 = json.loads((snap5 / "manifest.json").read_text())
        check(m5["counts"]["review"] == N_PAPERS * N_REV_PER_PAPER,
              f"fallback harvested every review from paper replies: {m5['counts']['review']}")
        with open(snap5 / "reviews.csv", encoding="utf-8", newline="") as fh:
            rows5 = list(csv.DictReader(fh))
        check(len(rows5) == N_PAPERS * N_REV_PER_PAPER, "fallback reviews flatten into reviews.csv")
        check(rows5[0]["paper_title"].startswith("Paper "), "fallback rows still joined to paper metadata")
        ids5 = [n["id"] for n in oc.read_jsonl(snap5 / "raw/reviews.jsonl.gz")]
        check(len(ids5) == len(set(ids5)), "fallback produced no duplicates")
        check(watch_and_crawl is not None, "watcher module importable")

        print("\nALL CHECKS PASSED")
        print(f"(fake API calls: {c1.calls} for snapshot 1 - cursor pagination, 1000 notes/request)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
