#!/usr/bin/env python3
"""Compare two review snapshots: what was added, deleted, or edited after rebuttal.

    python3 diff_snapshots.py snapshots/.../20261103T...-first-release \
                              snapshots/.../20261201T...-followup-24h

Writes diff.json (machine-readable) and diff.md (readable) into --out, and prints
a summary. Text fields are compared line-by-line as a unified diff.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orcommon as oc


def load_reviews(snap: Path) -> dict[str, dict]:
    for rel in ("raw/reviews.jsonl.gz", "raw/reviews.jsonl"):
        p = snap / rel
        if p.is_file():
            break
    else:
        raise SystemExit(f"no raw/reviews.jsonl[.gz] in {snap}")
    out = {}
    for note in oc.read_jsonl(p):
        flat = oc.flatten_content(note.get("content"))
        out[note["id"]] = {
            "id": note["id"],
            "forum": note.get("forum"),
            "number": oc.paper_number_from_invitations(note.get("invitations")),
            "reviewer": oc.anon_reviewer(note.get("signatures")),
            "tmdate": note.get("tmdate") or note.get("mdate"),
            "readers": note.get("readers") or [],
            "content": flat,
            "hash": oc.content_hash(flat),
        }
    return out


def field_diff(old, new) -> list[str]:
    a = (old if isinstance(old, str) else json.dumps(old, ensure_ascii=False, indent=1, default=str)).splitlines()
    b = (new if isinstance(new, str) else json.dumps(new, ensure_ascii=False, indent=1, default=str)).splitlines()
    return list(difflib.unified_diff(a, b, lineterm="", n=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--out", default="", help="output dir (default: the 'after' snapshot)")
    ap.add_argument("--rating-field", default="rating")
    ap.add_argument("--max-diff-lines", type=int, default=40, help="cap per-field diff in diff.md")
    args = ap.parse_args(argv)

    before_dir, after_dir = Path(args.before).resolve(), Path(args.after).resolve()
    out_dir = Path(args.out).resolve() if args.out else after_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    old, new = load_reviews(before_dir), load_reviews(after_dir)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    common = set(old) & set(new)
    edited = sorted(i for i in common if old[i]["hash"] != new[i]["hash"])

    rf = args.rating_field
    rating_changes = []
    details = []
    for rid in edited:
        o, n = old[rid], new[rid]
        changed_fields = {}
        for k in sorted(set(o["content"]) | set(n["content"])):
            ov, nv = o["content"].get(k), n["content"].get(k)
            if ov != nv:
                changed_fields[k] = {"before": ov, "after": nv, "diff": field_diff(ov or "", nv or "")}
        ro, rn = oc.numeric(o["content"].get(rf)), oc.numeric(n["content"].get(rf))
        if ro is not None and rn is not None and ro != rn:
            rating_changes.append({"review_id": rid, "paper_number": n["number"], "forum": n["forum"],
                                   "reviewer": n["reviewer"], "before": ro, "after": rn,
                                   "delta": round(rn - ro, 3)})
        details.append({"review_id": rid, "paper_number": n["number"], "forum": n["forum"],
                        "reviewer": n["reviewer"], "fields": sorted(changed_fields),
                        "changes": changed_fields})

    summary = {
        "before": str(before_dir), "after": str(after_dir),
        "reviews_before": len(old), "reviews_after": len(new),
        "added": len(added), "removed": len(removed), "edited": len(edited),
        "rating_changes": len(rating_changes),
        "rating_up": sum(1 for r in rating_changes if r["delta"] > 0),
        "rating_down": sum(1 for r in rating_changes if r["delta"] < 0),
        "mean_rating_delta": round(sum(r["delta"] for r in rating_changes) / len(rating_changes), 4)
        if rating_changes else None,
    }
    oc.write_json(out_dir / "diff.json", {"summary": summary, "added_ids": added, "removed_ids": removed,
                                          "rating_changes": rating_changes, "edited": details})

    lines = ["# Review diff", "", f"- before: `{before_dir.name}` ({len(old)} reviews)",
             f"- after:  `{after_dir.name}` ({len(new)} reviews)",
             f"- added **{len(added)}**, removed **{len(removed)}**, edited **{len(edited)}**",
             f"- rating changed on **{len(rating_changes)}** reviews "
             f"(up {summary['rating_up']}, down {summary['rating_down']}, "
             f"mean delta {summary['mean_rating_delta']})", ""]
    if rating_changes:
        lines += ["## Rating changes", "", "| paper | reviewer | before | after | delta | forum |",
                  "|---|---|---|---|---|---|"]
        for r in sorted(rating_changes, key=lambda x: -abs(x["delta"]))[:200]:
            lines.append(f"| {r['paper_number']} | {r['reviewer']} | {r['before']:g} | {r['after']:g} | "
                         f"{r['delta']:+g} | https://openreview.net/forum?id={r['forum']} |")
        lines.append("")
    if details:
        lines += ["## Edited reviews", ""]
        for d in details[:500]:
            lines.append(f"### paper {d['paper_number']} · {d['reviewer']} · `{d['review_id']}`")
            lines.append(f"fields changed: {', '.join(d['fields'])}")
            for k, ch in d["changes"].items():
                dl = ch["diff"][:args.max_diff_lines]
                if dl:
                    lines += ["", f"**{k}**", "```diff", *dl, "```"]
            lines.append("")
    (out_dir / "diff.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nwrote {out_dir / 'diff.json'}\nwrote {out_dir / 'diff.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
