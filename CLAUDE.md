# Working on this project

Read `README.md` for what the system is and how it runs. This file is for
things a session picks up the hard way.

## Where things are

| | |
|---|---|
| This project | `w:\Extrusion DB\Die History` (= `\\file1\User\Extrusion DB\Die History`) |
| Die History workbooks (read-only, never write) | `\\lud-storage.whitehallindustries.com\EXTRUSION\EXTRUSION DIES` (`Z:` also works) |
| Inputs borrowed from the sibling project (read-only) | `Vision System Database\data\paducah-dies.txt`, `...\data\die_index.csv` |
| Every history-named file per die (this project's own scan) | `data\history_files.csv` |
| Billet-length archive (read-only, local file) | `Press History UI\v2\billet_fingerprints.db` |
| Database | `data\die_history.db` |

`tools/config.py` resolves all of this. Run `python tools\config.py` to see
what a machine actually resolves it to.

## This project depends on Vision System Database's crawl, on purpose

Rather than re-walk 1,448 die folders over SMB to find history files and
figure out which dies are Paducah's, `build_db.py` reads two files the
sibling project already maintains: `paducah-dies.txt` (from press recipes)
and `die_index.csv` (die folder -> die number/description, already
crawled). Both are read-only inputs here. If `die_index.csv` is stale - a
folder renamed since the last Vision crawl - a die will show a parse error
(`FileNotFoundError`) until Vision's own `build_die_index.py` refreshes it.
Two dies (1434, 1439, both non-Paducah) are in that state as of the first
full build.

If Vision System Database is ever restructured or moved, update
`DIEHIST_VISION_DIR` (env var) or the fallback path in `tools/config.py`.

**`die_index.csv`'s own `history_file` column is not used for which file to
open** (only for the die_no -> die_folder -> description mapping) - see the
next section. It records at most one filename per die folder, picked by
whichever file `os.scandir` happens to enumerate last during Vision's crawl;
a folder with more than one history-named file (98 of 1,247, as of the
first `scan_history_files.py` run) can end up on the wrong one with no
indication anything was dropped.

## Multiple history files per die folder are real, not a data-entry mistake

`tools/scan_history_files.py` records **every** history-named file per die
folder into `data/history_files.csv`; `build_db.py` reads that (falling
back to Vision's single-file-per-die `die_index.csv` if it hasn't been run
yet) and parses **all** of a die's candidate files, merging their copies
rather than picking one. This exists because of two confirmed cases that
need opposite handling from "just take the newest file":

- **Die 1307**: `"DIE 000 HISTORY SHEET.xls"` (2017, a leftover generic
  template - its only sheets are `XXXXXX`/`000`/`Master Page`, zero real
  copies) sits next to `"1307 Die History.xlsx"` (actively updated through
  2026, 58 real copies). Before this fix, `die_index.csv` had recorded the
  *old* file - die 1307 showed **zero** production history. Safe to just
  prefer the newer file here; the older one contributes nothing.
- **Die 685**: `"685 Die History - Paducah.xlsx"` (copies `52`, `65-114`)
  and `"685 Die History - Ludington dies only.xlsx"` (copies `39LUD`,
  `47LUD`, ..., `109`, `112`, `115-144`) are **both live and disjoint** -
  the die is genuinely run at both plants and each plant's copies are
  logged in its own file. Picking only the newer of the two (as an earlier
  version of this fix did, briefly) silently drops ~50 real copies.

So the actual rule (`build_db.py`'s `merge_copies()`) is: parse every
candidate file, keep one entry per `copy_no` across all of them, and only
when the *same* `copy_no` is found in more than one file does the more
recently modified file win. Checked against die 1103's `"... (TEST).xlsx"`
(an old partial snapshot of copies 1-2, superseded by the real file's more
complete versions of the same two copies) - the newest-wins rule correctly
discards the stale duplicate there without needing to special-case the
filename.

`scan_history_files.py` takes about 100s for the full ~1,250-die corpus (one
`os.scandir` per folder) - run it periodically (same cadence as Vision's own
`build_die_index.py`), not on every `build_db.py` run. If `data/history_files.csv`
doesn't exist yet, `build_db.py` falls back to Vision's one-file-per-die
crawl and prints a warning rather than failing.

## Rules learned from the sibling project, carried over here

**Bash cannot reach the dies share.** `\\lud-storage...` (and `Z:`) only
resolves through PowerShell/cmd on this machine - `ls` from the Bash tool
returns an empty listing with exit 0, which reads as "no data" rather than
as an error. Anything that opens a workbook (`build_db.py`, ad-hoc
inspection scripts) must run from PowerShell.

**The dies share is read-only.** Nothing here writes, moves, or deletes
anything under `EXTRUSION DIES`.

**A plain rerun of `build_db.py` is already a safe, fast no-op for unchanged
dies** - a die is skipped if its history file's mtime matches what's
recorded, so a rerun after an interruption or after Vision's `die_index.csv`
picks up new dies only does new/changed work. There is no separate "sync"
script the way the vision project has one; the same `build_db.py` command
serves both purposes here because there is exactly one file per die instead
of thousands of reports per die. **After a parser code change**, mtimes
haven't moved, so nothing will look new - pass `--force` to reparse
everything regardless of mtime.

## The two template families

Both are handled by one parser (`tools/parse_history.py`), anchor-based
(finds labels by text, not by row/column number) rather than positional,
because the two families put the same labels at different rows:

| | Extension | Production-history banner | Column headers | Nitride-trigger footer |
|---|---|---|---|---|
| old | `.xls` (needs `xlrd`, not `openpyxl` - it dropped `.xlsx` support at 2.0, which is why both libraries are dependencies) | ~row 21 | ~row 24 | absent - nitride events are inline rows in the production stream instead (billets column reads literally "nitride") |
| new | `.xlsx`/`.xlsm` | ~row 9 | ~row 12 | present, rows ~46-50 ("Do Not Change" / "Nitride Trigger 1/2/3") |

**The nitride-trigger footer reuses the pull-code column.** A naive
"scan every row below the header to `max_row`" for the last of the three
production-history column-blocks picks up "Do Not Change" and "Nitride
Trigger 1" as if they were pull codes, because that footer sits in the same
column. `parse_copy_sheet()` finds the footer's start row first and clips
every block's scan to end before it. If a fourth template variant shows up
with a differently-shaped footer, check that clip logic before trusting its
entry counts.

**A row counts as a production/nitride entry only if its date or pull-code
cell is non-blank.** This is what filters out the aggregate total rows
(pure numbers, blank date and pull code) and stray annotations (e.g. a
lone "Paducah" typed into a billets cell with nothing else on the row)
without needing to special-case either. It also means a few real data
points are deliberately *not* captured for v1: the "billets in die before
tracking began" baseline some sheets carry in the row just above the first
dated entry, and the numeric nitride-trigger thresholds themselves
(100/250-billet policy values) in the newer template's footer. Both are
visible in the source workbook if someone needs them; neither blocks the
production/nitride timeline that's actually in the database.

**Per-copy sheets are identified by name, not by content.** A sheet is
parsed if its name starts with `<num>-<num>` or `<num>_<num>` (e.g.
`1011-1`); "Master Page"/"Master Sheet" (with or without a die-number
prefix), `000`, and the occasional leftover `XXXXXX` sheet are template
stubs and are skipped by construction - they don't start with a number, so
there's no blacklist to maintain.

**The copy number keeps any trailing qualifier, on purpose.** A sheet named
`1121-32P4` becomes `copy_no = "32P4"`, not `"32"` - some dies (mostly older
Ludington-run ones) suffix the copy number with a press/position code
(`P4`), a plant tag (`lud`), or a head number (`2H`). Stripping it would risk
colliding two different sheets onto the same `copy_no` if a bare `"32"` and a
`"32P4"` both exist for the same die. This was originally a bug - the
sheet-name pattern required an exact `<num>-<num>` match, so every suffixed
sheet was silently skipped entirely (recovered ~588 copies / ~11,700 entries
across the full corpus once fixed, largest single count on 1121 which runs
`P4`/`P5` suffixes literally on every copy past 26). `CAST(copy_no AS
INTEGER)` (used for sort order throughout) still works on a suffixed value -
SQLite reads the leading numeric prefix and ignores the rest.

## Gross pounds extruded per die-copy

`tools/compute_pounds.py` adds `billet_length_median_in`, `billet_length_n`,
`butt_length_in`, `billets_total`, `gross_lbs` to `die_copy`:

    gross_lbs = billets_total * (billet_length_median_in - butt_length_in) * 4.9

- **`billets_total`** is this project's own `SUM(billets_num)` over
  `production_entry` - always present, doesn't depend on the other project.
- **`billet_length_median_in`** comes from the sibling `Press History UI`
  project's `v2/billet_fingerprints.db` (local SQLite, no credentials, 3
  years / 256k+ real per-billet lengths, indexed by `(profile, die_copy)` -
  matches our `(die_no, copy_no)` after taking `copy_no`'s leading integer,
  since the press PLC's own copy numbering doesn't carry the suffix
  qualifiers some Excel sheets do). Only ~4% of our die-copies (273/6,823 as
  of the first run) have a match - the archive only covers copies that ran
  in roughly the last 3 years, not this project's full multi-decade span.
  A copy with no match gets `gross_lbs = NULL`, never `0` - "unknown" and
  "zero pounds" must never be confused.
- **`butt_length_in`** is a fixed **0.8 inches** for every copy, confirmed
  by the user as the shop's actual standard - not a per-copy measurement.
  A live monitor (`picos`' `press_db.billet_cycles` Mongo collection,
  `butt_length_actual_in`) does log a real per-billet value, but only since
  it started (recently) and isn't wired up here; using it would mean
  blending a few weeks of live readings with a 3-year length archive for the
  same figure, which the user opted against in favor of one consistent
  constant.
- **4.9** is lb per linear inch for this billet diameter/alloy class, given
  by the user - not derived here.

`compute_pounds.py` is **not** run automatically by `build_db.py` - run it
by hand afterward (or add it to a pipeline script if this becomes routine).
It's also not idempotent-safe against a stale `billets_total` if
`build_db.py --force` re-ingests without a matching `compute_pounds.py`
rerun - the two are separate steps, always rerun both together after a
reparse.

## Cloud-hosted copy (MongoDB Atlas)

`cloud/` is a second, independent deployment of the same read API and
frontend, backed by MongoDB instead of the local SQLite file - unlike the
Vision System Database app, this one never needs to stream a source Excel
file at request time, so nothing here requires the dies share (or even the
local network) to be reachable from wherever it runs.

- **`tools/push_to_mongo.py`** reads the local `die_history.db` and upserts
  it into a new `die_history` database on the same shared Atlas cluster
  already used by Granco Saw Monitor (`granco_saw`) and picos (`press_db`) -
  same connection convention (`padpress1` user, cluster
  `cluster0.ywwxl.mongodb.net`, password from the `SQL_PASS` env var). Needs
  that credential in the environment to run; this project doesn't have it
  and doesn't prompt for it - get it the same place those two projects do.
  Safe to rerun (everything's an upsert).
- **`cloud/api/`** is a Flask app with the *same three routes* as the local
  `api/app.py` (`/api/summary`, `/api/dies`, `/api/die/<die_no>`), reading
  from Mongo instead of SQLite. `cloud/web/` is an unmodified copy of the
  local `web/` - both frontends hit the same relative `/api/...` paths, so
  neither needs to know which backend is actually running behind it.
- Mongo documents are shaped to make the API a near-passthrough: a `die`
  doc **is** the rollup `/api/dies` used to compute in SQL (down to the
  field names), and a `die_copy` doc carries its `entries` embedded as an
  array, so `/api/die/<die_no>` is one `find_one` plus one `find` - no
  aggregation pipeline needed against a free-tier cluster.
- Deployment (Render, Vercel, or otherwise) is left to whoever runs it -
  this session doesn't hold Render/Vercel/Mongo credentials. `cloud/vercel.json`
  mirrors Granco Saw Monitor's exact rewrite (`/(.*) -> /api/app`) for a
  zero-config Vercel deploy; for Render, point it at `cloud/`, install
  `cloud/requirements.txt`, and start with `gunicorn api.app:app` from
  inside `cloud/`.

## Traps in this environment

- **Bash heredocs mangle backslashes** - write Python containing Windows
  paths with the Write tool, not a heredoc.
- Sample workbooks pulled for parser development live in the session
  scratchpad, not in this project - they were throwaway fixtures, not data.

## Verifying work

```
python tools\config.py                 # resolved paths on this machine
python tools\parse_history.py <path>   # dry-run the parser on one workbook, no DB writes
python tools\build_db.py --paducah-only --limit 15   # small, fast validation pass
```

`build_db.py`'s own summary line (`done=/skipped=/error=`) and the API's
`/api/summary` (`n_errors`) are the numbers to check after a run - not
"did it print a traceback," since a single bad workbook is caught per-die
and recorded as `die.parse_error` rather than aborting the run.
