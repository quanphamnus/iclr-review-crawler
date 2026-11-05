#!/usr/bin/env python3
"""Preflight: are credentials working, and what is the venue's current state?

    python3 check_setup.py --venue ICLR.cc/2027/Conference
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orcommon as oc


def ms(t) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(t) / 1000))
    except Exception:
        return str(t)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", default="ICLR.cc/2027/Conference")
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--baseurl", default=oc.API2)
    args = ap.parse_args(argv)
    log = oc.get_logger("check")

    print("=" * 72)
    print(f"OpenReview preflight - {args.venue}")
    print("=" * 72)

    u, p, t = oc.load_credentials(args.username, args.password)
    print(f"credentials : username={'set' if u else 'MISSING'} "
          f"password={'set' if p else 'MISSING'} token={'set' if t else '-'}")
    try:
        client = oc.login(args.username, args.password, baseurl=args.baseurl, logger=log, allow_guest=True)
    except oc.NeedsLogin as e:
        print(f"login       : FAILED - {e}")
        return 3
    me = oc.whoami(client)
    print(f"login       : {'OK as ' + me if me != 'guest' else 'GUEST (notes API will be blocked)'}")

    try:
        cfg = oc.venue_config(client, args.venue, logger=log)
    except Exception as e:
        print(f"venue group : FAILED - {oc.err_name(e)}: {str(e)[:200]}")
        return 4
    print(f"venue       : {cfg.get('subtitle') or args.venue} - {cfg.get('title', '')}")
    print(f"              review_name={cfg.get('review_name')} rating={cfg.get('review_rating')} "
          f"confidence={cfg.get('review_confidence')}")
    print(f"              public_submissions={cfg.get('public_submissions')}")
    vids = oc.submission_venueids(cfg, args.venue)
    supers = oc.reply_invitation_ids(cfg, args.venue)

    ok = True
    print("-" * 72)
    for vid in vids:
        try:
            n = oc.count_notes(client, content={"venueid": vid}, logger=log)
            print(f"papers      : {n:>7,}  venueid={vid}")
        except oc.NeedsLogin as e:
            print(f"papers      : BLOCKED  venueid={vid} -> {e}")
            ok = False
            break
        except Exception as e:
            print(f"papers      : error    venueid={vid} -> {oc.err_name(e)}")
    print("-" * 72)
    for kind, inv in supers.items():
        try:
            inv_obj = oc.with_retry(client.get_invitation, inv, tries=2, logger=log, what=f"inv {kind}")
            state = "readable"
            extra = f" cdate={ms(inv_obj.cdate)}" if getattr(inv_obj, "cdate", None) else ""
        except Exception as e:
            state, extra = oc.err_name(e), ""
        try:
            n = oc.count_notes(client, parent_invitations=inv, logger=log)
            cnt = f"{n:,} notes visible"
        except oc.NeedsLogin:
            cnt, ok = "BLOCKED (login required)", False
        except Exception as e:
            cnt = f"0 notes ({oc.err_name(e)})"
        print(f"{kind:<12}: {cnt:<28} invitation={state}{extra}")
    print("-" * 72)

    try:
        n_rev = oc.count_notes(client, parent_invitations=supers["review"], logger=log)
    except Exception:
        n_rev = 0
    if n_rev > 0:
        sample = oc.with_retry(client.get_notes, parent_invitations=supers["review"], limit=3,
                              logger=log, what="sample") or []
        pub = sum(1 for s in sample if oc.is_public(getattr(s, "readers", [])))
        print(f"VERDICT     : reviews ARE visible ({n_rev:,}); {pub}/{len(sample)} sampled are public.")
        print("              -> run: python3 crawl_reviews.py --venue %s --label first-release" % args.venue)
        if sample:
            print(f"              sample review fields: "
                  f"{', '.join(sorted(oc.flatten_content(sample[0].content).keys()))}")
    else:
        print("VERDICT     : reviews are NOT out yet.")
        print("              -> start the watcher: python3 watch_and_crawl.py --venue %s" % args.venue)
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
