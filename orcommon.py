"""Shared helpers for OpenReview snapshot tooling (API2).

Nothing in here is venue-specific: pass any venue id such as
``ICLR.cc/2027/Conference`` or ``NeurIPS.cc/2026/Conference``.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import openreview

API2 = "https://api2.openreview.net"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
CRED_FILE = Path.home() / ".openreview" / "credentials.json"


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
def get_logger(name: str, logfile: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    log = logging.getLogger(name)
    log.setLevel(level)
    log.handlers.clear()
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    return log


# --------------------------------------------------------------------------- #
# errors / exception introspection
# --------------------------------------------------------------------------- #
class NeedsLogin(RuntimeError):
    """Raised when OpenReview refuses anonymous access (bot challenge / forbidden)."""


def err_payload(exc: BaseException) -> dict:
    if isinstance(exc, openreview.OpenReviewException) and exc.args:
        a = exc.args[0]
        if isinstance(a, dict):
            return a
        if isinstance(a, list) and a and isinstance(a[0], dict):
            return a[0]
    return {}


def err_name(exc: BaseException) -> str:
    return str(err_payload(exc).get("name", type(exc).__name__))


def err_status(exc: BaseException) -> int | None:
    st = err_payload(exc).get("status")
    try:
        return int(st)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# retry
# --------------------------------------------------------------------------- #
def with_retry(fn, *args, tries: int = 6, base: float = 2.0, cap: float = 90.0,
               logger: logging.Logger | None = None, what: str = "request", **kwargs):
    """Call fn with exponential backoff on transient failures.

    Bot-challenge / forbidden errors are NOT retried: they mean 'log in', not 'wait'.
    """
    last: BaseException | None = None
    for attempt in range(1, tries + 1):
        try:
            return fn(*args, **kwargs)
        except openreview.OpenReviewException as e:
            name, status = err_name(e), err_status(e)
            if name in ("ChallengeRequiredError",):
                raise NeedsLogin(
                    "OpenReview answered with a bot challenge. Anonymous access to /notes is "
                    "blocked; set OPENREVIEW_USERNAME / OPENREVIEW_PASSWORD and retry."
                ) from e
            if status is not None and status not in RETRYABLE_STATUS:
                raise
            last = e
        except Exception as e:  # network/transport layer
            if type(e).__name__ in ("KeyboardInterrupt", "SystemExit"):
                raise
            last = e
        if attempt == tries:
            break
        delay = min(cap, base ** attempt) * (0.7 + 0.6 * random.random())
        if logger:
            logger.warning("%s failed (%s: %s); retry %d/%d in %.1fs",
                           what, err_name(last), str(last)[:160], attempt, tries, delay)
        time.sleep(delay)
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
def load_credentials(username: str | None = None, password: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Return (username, password, token) from args, env, then ~/.openreview/credentials.json."""
    token = os.environ.get("OPENREVIEW_TOKEN") or None
    username = username or os.environ.get("OPENREVIEW_USERNAME") or os.environ.get("OPENREVIEW_EMAIL")
    password = password or os.environ.get("OPENREVIEW_PASSWORD")
    if not (username and password) and not token and CRED_FILE.is_file():
        try:
            data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            username = username or data.get("username") or data.get("email")
            password = password or data.get("password")
            token = token or data.get("token")
        except Exception:
            pass
    return username, password, token


def login(username: str | None = None, password: str | None = None, baseurl: str = API2,
          logger: logging.Logger | None = None, allow_guest: bool = False):
    """Return an authenticated OpenReviewClient (API2)."""
    username, password, token = load_credentials(username, password)
    if token:
        client = openreview.api.OpenReviewClient(baseurl=baseurl, token=token)
    elif username and password:
        client = with_retry(openreview.api.OpenReviewClient, baseurl=baseurl,
                            username=username, password=password,
                            logger=logger, what="login", tries=4)
    elif allow_guest:
        if logger:
            logger.warning("No credentials found - continuing as guest (most /notes calls will fail).")
        return openreview.api.OpenReviewClient(baseurl=baseurl)
    else:
        raise NeedsLogin(
            "No OpenReview credentials. Set OPENREVIEW_USERNAME and OPENREVIEW_PASSWORD "
            f"(or write them to {CRED_FILE})."
        )
    who = getattr(client, "user", None) or {}
    ident = (who.get("user") or {}).get("id") or username or "<token>"
    if logger:
        logger.info("Logged in to %s as %s", baseurl, ident)
    return client


def whoami(client) -> str:
    who = getattr(client, "user", None) or {}
    return (who.get("user") or {}).get("id") or "guest"


# --------------------------------------------------------------------------- #
# venue configuration
# --------------------------------------------------------------------------- #
def venue_config(client, venue_id: str, logger: logging.Logger | None = None) -> dict:
    """Flattened content dict of the venue group (works for guests too)."""
    grp = with_retry(client.get_group, venue_id, logger=logger, what=f"get_group({venue_id})")
    content = grp.content or {}
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in content.items()}


def submission_venueids(cfg: dict, venue_id: str) -> list[str]:
    """Every venueid a paper of this venue can carry, 'under review' first."""
    keys = ("submission_venue_id", "withdrawn_venue_id", "desk_rejected_venue_id", "rejected_venue_id")
    out = [cfg[k] for k in keys if cfg.get(k)]
    out.append(venue_id)  # accepted papers end up on the bare venue id
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def reply_invitation_ids(cfg: dict, venue_id: str) -> dict[str, str]:
    """Map logical kind -> venue-level *super* invitation id (parent of per-paper ones)."""
    names = {
        "review": cfg.get("review_name") or "Official_Review",
        "meta_review": cfg.get("meta_review_name") or "Meta_Review",
        "decision": cfg.get("decision_name") or "Decision",
        "comment": cfg.get("comment_name") or "Official_Comment",
        "rebuttal": cfg.get("rebuttal_name") or "Author_Rebuttal",
    }
    return {kind: f"{venue_id}/-/{name}" for kind, name in names.items()}


# --------------------------------------------------------------------------- #
# paginated fetching
# --------------------------------------------------------------------------- #
def iter_note_pages(client, *, page_size: int = 1000, after: str | None = None,
                    sleep: float = 0.0, logger: logging.Logger | None = None,
                    label: str = "notes", **params) -> Iterator[tuple[list, int | None, str | None]]:
    """Yield (notes, total_count, next_cursor) pages using OpenReview's `after` cursor.

    Cursor pagination (sort=id + after=<last id>) is what openreview-py uses; unlike
    offset paging it stays correct and cheap over tens of thousands of notes, and the
    cursor can be checkpointed to resume an interrupted crawl.
    """
    params = {k: v for k, v in params.items() if v is not None}
    params.setdefault("sort", "id")
    total: int | None = None
    cursor = after
    while True:
        call = dict(params, limit=page_size)
        if cursor:
            call["after"] = cursor
        if total is None:
            call["with_count"] = True
        res = with_retry(client.get_notes, logger=logger, what=f"get_notes({label})", **call)
        if isinstance(res, tuple):
            batch, total = res[0], res[1]
        else:
            batch = res
        if not batch:
            return
        cursor = batch[-1].id
        yield batch, total, cursor
        if len(batch) < page_size:
            return
        if sleep:
            time.sleep(sleep)


def count_notes(client, logger: logging.Logger | None = None, **params) -> int:
    """Cheap 'how many notes match' probe (limit=1 + with_count)."""
    params = {k: v for k, v in params.items() if v is not None}
    res = with_retry(client.get_notes, limit=1, with_count=True, logger=logger,
                     what="count_notes", **params)
    if isinstance(res, tuple):
        return int(res[1] or 0)
    return len(res or [])


# --------------------------------------------------------------------------- #
# note helpers
# --------------------------------------------------------------------------- #
def note_to_dict(note) -> dict:
    """Full raw note as a plain dict (keeps every field for later forensics)."""
    d = note.to_json() if hasattr(note, "to_json") else dict(note)
    details = getattr(note, "details", None)
    if details:
        d.setdefault("details", details)
    return d


def flatten_content(content: dict | None) -> dict:
    """API2 content is {field: {'value': x}} -> {field: x}."""
    out = {}
    for k, v in (content or {}).items():
        out[k] = v.get("value") if isinstance(v, dict) and "value" in v else v
    return out


def content_hash(flat: dict) -> str:
    """Stable hash of a note's content, for detecting post-rebuttal edits."""
    blob = json.dumps(flat, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def numeric(value: Any) -> float | None:
    """Pull a number out of 8, '8', '8: accept', 'Rating: 3.5'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM_RE.search(value)
        if m:
            try:
                return float(m.group())
            except ValueError:
                return None
    return None


_PAPER_NUM_RE = re.compile(r"/(?:Submission|Paper)(\d+)/")


def paper_number_from_invitations(invitations: list[str] | None) -> int | None:
    for inv in invitations or []:
        m = _PAPER_NUM_RE.search(inv + "/")
        if m:
            return int(m.group(1))
    return None


def anon_reviewer(signatures: list[str] | None) -> str:
    for s in signatures or []:
        tail = s.rstrip("/").split("/")[-1]
        if tail:
            return tail
    return ""


def is_public(note_or_readers) -> bool:
    readers = getattr(note_or_readers, "readers", note_or_readers) or []
    return "everyone" in readers


# --------------------------------------------------------------------------- #
# io
# --------------------------------------------------------------------------- #
class JsonlWriter:
    """Append-only gzipped JSONL writer; flushes each record so a crash keeps data."""

    def __init__(self, path: Path, gzip_out: bool = True):
        self.path = Path(str(path) + ".gz") if gzip_out and not str(path).endswith(".gz") else Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = (gzip.open(self.path, "at", encoding="utf-8")
                    if str(self.path).endswith(".gz")
                    else open(self.path, "a", encoding="utf-8"))
        self.n = 0

    def write(self, obj: dict) -> None:
        self._fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self.n += 1

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class NullWriter:
    """Writer that discards everything (used when a pass only needs side effects)."""

    n = 0

    def write(self, obj: dict) -> None:
        self.n += 1

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def read_jsonl(path: Path) -> Iterator[dict]:
    path = Path(path)
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def slug(venue_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", venue_id).strip("_")


def utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
