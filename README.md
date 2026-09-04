# Die History

A searchable web interface for the "Die History" Excel sheets that live
inside every die's folder on the EXTRUSION share - production runs
(date, billet count, pull code) and nitride cycle events, per die-copy.

Sibling project to `Vision System Database`, which flagged this as unbuilt
future work in its own README. This project reuses that project's confirmed
Paducah-dies list and its crawl of the share (`die_index.csv`) rather than
re-walking 1,448 die folders itself - see `CLAUDE.md` for how that
dependency works.

Everything here treats the dies share as **read-only**. Nothing is written
to, moved on, or deleted from `Z:\EXTRUSION DIES`.

---

## Where the data comes from

Each die folder holds at least one workbook, named inconsistently -
`"1011 Die History.xlsx"`, `"DIE 1006 HISTORY SHEET.xls"`,
`"Die 312 History Sheet.xls"` - with one sheet per die-copy (`"1011-1"`,
`"1011-2"`, ...) plus a blank "Master Page" template sheet. Each per-copy
sheet is a grid: die/backer/bolster number, then up to three parallel
DATE/BILLETS/PULL CODE column-blocks of production entries, and - on the
newer template only - a nitride-trigger summary.

**1,247 die folders have a history workbook, 1,355 history-named files
between them** - 98 folders have more than one (a stale duplicate, or, at
least once, two files that genuinely split different copies with no
overlap - see `CLAUDE.md`). This project parses and merges every file in a
folder rather than picking just one, so nothing gets silently dropped
either way. Of those dies, **1,245** are indexed here (2 reference a file
that no longer exists at that path - see Known gaps). All 141
confirmed-Paducah dies (same recipe-based confirmation Vision uses) have at
least one history file - the fullest coverage of any die subset on the
share, which is why this interface defaults to Paducah first and
prioritizes them.

Two template vintages exist, told apart by look rather than by file
extension alone:

| | Extension | Nitride events recorded as |
|---|---|---|
| older | `.xls` | an inline row in the production stream (billets column reads "nitride") |
| newer | `.xlsx` / `.xlsm` | inline rows, **plus** a "Times Nitrided" / trigger-threshold summary |

`tools/parse_history.py` handles both with one anchor-based parser (finds
labels by text, not by fixed row numbers) rather than one parser per
vintage - see `CLAUDE.md` for the specifics of what does and doesn't get
captured.

---

## What's in the database

`data/die_history.db` (SQLite):

| Table | What |
|---|---|
| `die` | die number, folder, description, `is_paducah`, source file, parse status |
| `die_copy` | one row per die-copy sheet: backer/bolster number, nitride count, lifetime billet total, date range, plus gross-pounds fields (see below) |
| `production_entry` | one row per production or nitride entry: date, billets, pull code (raw and normalized), and `entry_type` (`production` / `nitride` / `unknown`) |

`entry_type` is inferred, not read from a labeled column: `nitride` when the
billets or pull-code text mentions nitriding, `production` when the billets
cell parses as a number, `unknown` otherwise (e.g. "not recorded", "??" -
real gaps in what was written down at the time, kept rather than dropped).

---

## Gross pounds extruded

`tools/compute_pounds.py` adds a gross-pounds estimate to each die-copy:

```
gross_lbs = billets_total * (median_billet_length_in - 0.8) * 4.9
```

- `billets_total` is summed from this project's own parsed production
  entries - always available.
- The median billet length comes from the sibling `Press History UI`
  project's 3-year, 256,502-billet archive, matched by die + copy number.
  Only die-copies that actually ran within roughly the last 3 years have a
  match (**273 of 6,823 copies** as of the first run, across 38 dies) -
  older or long-inactive copies show "no billet-length match" rather than a
  guessed number.
- `0.8` (inches) is the shop's standard butt/discard length, applied to
  every copy as a fixed constant rather than a per-copy measurement - see
  `CLAUDE.md` for why (a live per-billet reading exists but only recently
  started being logged, nowhere near the 3-year span the billet-length
  archive covers).
- `4.9` is lb per linear inch for this billet diameter/alloy, given directly
  rather than derived.

Run it after `build_db.py` (it reads `production_entry`, which a rebuild
replaces):

```
python tools\compute_pounds.py
```

Local-only - no share or network access needed, just the local
`die_history.db` and the (also local) fingerprint archive.

---

## Cloud-hosted version

`cloud/` is a second deployment of the same read API and frontend, backed by
MongoDB Atlas instead of local SQLite - it never needs to open a source
Excel file at request time, so (unlike Vision System Database's app) it
isn't tied to the plant network or a machine with the share mounted.

```
python tools\push_to_mongo.py     # needs SQL_PASS - see CLAUDE.md
```

pushes the local database up to a new `die_history` database on the same
shared Atlas cluster Granco Saw Monitor and picos already use. `cloud/api/`
serves the identical three JSON routes as the local API, and `cloud/web/`
is an unmodified copy of `web/` - point either frontend at either backend
and it just works, since both hit the same relative `/api/...` paths.

Deploying `cloud/` (Render, Vercel, or otherwise) is left to whoever runs
it - this project doesn't hold hosting or database credentials.
`cloud/vercel.json` mirrors Granco Saw Monitor's exact rewrite for a
zero-config Vercel deploy; for Render, install `cloud/requirements.txt` and
start with `gunicorn api.app:app` from inside `cloud/`.

---

## Running it

```
pip install -r requirements.txt
python api\app.py                        # this machine only, port 5058
python api\app.py --host 0.0.0.0         # serve the whole plant network
```

Then open <http://127.0.0.1:5058>, or `http://<this-machine>:5058` from
anyone else's desk. Runs under waitress, read-only against the database, so
concurrent viewers are safe.

`scheduled\run_webapp.cmd [host]` wraps the same command for a shortcut /
scheduled task, matching the Vision System Database convention.

### Filters

Die number or description search, plus a **Paducah Only / View All** scope
toggle in the masthead (defaults to Paducah, same convention as the vision
project's interface). Per-die view shows every copy as its own card with
its full production/nitride timeline.

---

## Building / refreshing the database

```
python tools\scan_history_files.py                     # ~100s - every history file per die, not just one
python tools\build_db.py --paducah-only --limit 15      # small, fast sanity check
python tools\build_db.py --paducah-only                 # all 141 Paducah dies (~3 min)
python tools\build_db.py                                 # everything with a history file (~10 min)
```

`scan_history_files.py` only needs rerunning periodically (new files
showing up on the share) - `build_db.py` falls back to Vision's
one-file-per-die crawl with a warning if it's never been run, but that
crawl is known to sometimes pick the wrong file (or miss a second one
entirely) when a folder has more than one - see `CLAUDE.md`.

Must run from **PowerShell**, not Bash - it opens workbooks on the dies
share, which the Bash tool cannot reach (see `CLAUDE.md`).

Safe to rerun any time: a die whose history file's mtime hasn't changed
since it was last parsed is skipped, so picking up newly-edited workbooks
(someone added this month's production run) is the same command, not a
separate sync step. `--budget SECONDS` stops cleanly at a time boundary if
run inside something with a wall-clock limit.

### Known gaps (v1)

- Two dies (1434, 1439, neither Paducah) reference a history file that Vision's
  `die_index.csv` recorded but which no longer exists at that path on the
  share - a stale-crawl issue upstream, not a parser bug. They'll clear once
  Vision re-crawls.
- The newer template's numeric nitride-trigger thresholds (the "send for
  nitride every N billets" policy values) aren't captured, only the
  `times_nitrided` count and lifetime billet total. They're visible in the
  source workbook if needed.
- Gross pounds only has real billet-length coverage for ~4% of copies (the
  ones that ran in roughly the last 3 years); butt length is a fixed
  estimate for every copy, not a measurement. See "Gross pounds extruded"
  above.
- The cloud copy isn't deployed - `cloud/` is ready to push to Render/Vercel
  whenever whoever holds those credentials wants to.
- No scheduled/nightly refresh is wired up yet - `build_db.py` (and,
  separately, `compute_pounds.py` and `push_to_mongo.py`) are run by hand.
  Worth adding (mirroring Vision's `run_nightly.cmd`) if this becomes
  something people check daily rather than periodically.
