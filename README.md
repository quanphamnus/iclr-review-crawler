# OpenReview Review Snapshotter

Take immutable, timestamped snapshots of all public reviews (and optionally
meta-reviews, decisions and comments) of an OpenReview venue, then diff two
snapshots to see which reviews were added, removed or edited and how scores moved
after the rebuttal.

- **Immutable snapshots**: raw API JSONL + flat CSVs + a manifest with per-file and per-review SHA-256 hashes, so changes are detected from content rather than `tmdate`.
- **Resumable**: an interrupted crawl continues from its saved cursor.
- **Venue-agnostic**: field names (rating, confidence, ...) are read from the venue config, so it is not tied to ICLR 2027.
- **Fast**: bulk, cursor-paginated queries (~1000 notes/request); a full ICLR crawl takes minutes.

## Install

Uses [uv](https://docs.astral.sh/uv/) (Python 3.10+):

```bash
uv sync                  # creates .venv and installs dependencies
```

Commands below use `uv run`; alternatively activate the environment
(`source .venv/bin/activate`) and call `python` directly.
Plain pip also works: `pip install -r requirements.txt`.

## Authentication

OpenReview blocks anonymous access to `/notes`, so a (free) OpenReview account is required.
Put credentials in a `.env` file (git-ignored) and load it before running:

```bash
printf 'OPENREVIEW_USERNAME=you@example.com\nOPENREVIEW_PASSWORD=your-password\n' > .env
chmod 600 .env
set -a; . ./.env; set +a
```

Never commit credentials. The scripts only read the `OPENREVIEW_*` environment variables.

## Quick start

```bash
# 1. Check login and whether reviews are public yet (downloads nothing)
uv run python check_setup.py --venue ICLR.cc/2027/Conference

# 2. Take a snapshot
uv run python crawl_reviews.py --venue ICLR.cc/2027/Conference --label first-release

# 3. Later (e.g. after the rebuttal), take another one, with comments
uv run python crawl_reviews.py --venue ICLR.cc/2027/Conference --kinds all --label second

# 4. Compare the two
uv run python diff_snapshots.py \
  snapshots/ICLR_cc_2027_Conference/<first-release-dir> \
  snapshots/ICLR_cc_2027_Conference/<second-dir> \
  --out diff_out
```

Resume an interrupted crawl: `uv run python crawl_reviews.py --resume <snapshot-dir>`.

### Auto-snapshot the moment reviews go public

```bash
nohup uv run python watch_and_crawl.py --venue ICLR.cc/2027/Conference \
  --interval 300 --followups 24h,7d,21d > /dev/null 2>&1 &
```

The watcher polls every 5 minutes and fires only when enough reviews are readable
(`--min-count`, default 50) and at least one is public, so reviews of your own
papers cannot trigger it early. It then takes a `first-release` snapshot plus the
follow-ups. Progress is kept in `watch_state.json`; restarts do not duplicate snapshots.
Use `--once` to run it from cron, or `--notify-cmd` to run a command when done.

## Options (`crawl_reviews.py`)

| Flag | Meaning |
|---|---|
| `--venue` | venue group id (default `ICLR.cc/2027/Conference`) |
| `--label` | suffix for the snapshot directory |
| `--kinds` | `review,meta_review,decision` (default) or `all` (adds `comment`, `rebuttal`) |
| `--resume DIR` | continue an interrupted snapshot |
| `--limit N` | smoke test: N notes per stream (manifest marked `partial`) |
| `--skip-submissions` | do not download the papers themselves |
| `--replies-mode` | `parent` (bulk), `forum` (per-paper), `auto` (default) |
| `--sleep`, `--page-size` | politeness / paging controls |
| `--no-gzip`, `--no-csv` | output format |

## Output

```
snapshots/<venue>/<UTC-timestamp>_<label>/
├── raw/*.jsonl.gz     # notes exactly as returned by the API (archival copy)
├── reviews.csv        # one row per review; all content fields, content_sha256
├── papers.csv         # one row per paper: ratings, mean/min/max, forum URL
├── venue_config.json  # venue config at snapshot time
├── manifest.json      # counts, SHA-256 of every file, parameters, timing
└── crawl.log
```

`diff_snapshots.py` writes `diff.json` and `diff.md`: added/removed/edited reviews,
rating changes (before → after, with direction) and a unified diff of every edited text field.

## Data

This repository contains **code only**. Snapshots are hundreds of MB each
(`reviews.csv` alone is ~490 MB for ICLR 2027) and are git-ignored; reproduce them
by running the crawler with your own account.

Reviews are public but belong to their authors. Check OpenReview's terms and the
conference policy before redistributing them or training models on them. ICLR is
double-blind: do not attempt to deanonymize reviewers, and avoid publishing
labels about specific papers or authors based on unverified review claims.

## Tests

```bash
uv run python selftest.py     # offline: fake API with 10k reviews, covers paging, resume, diff, watcher
```

## Known limitations

- `--replies-mode forum` sees only direct replies of each paper; the default `parent` mode also gets comments nested under reviews.
- Only what your account can read is captured; before release you see just your own papers/reviews.
- A review deleted between snapshots appears in `removed_ids` of the diff.
