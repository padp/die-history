"""Build/refresh die_history.db from the Die History workbooks on the share.

Reads, read-only, never written back to:

    paducah-dies.txt    which die numbers run at Paducah, from press recipes
                         (Vision System Database)
    die_index.csv       die folder -> die number/description (Vision)
    history_files.csv   die folder -> every history-named file in it, not
                         just one (this project's own tools/scan_history_files.py -
                         falls back to die_index.csv's single-file-per-die
                         crawl if that hasn't been run yet)

A die can have more than one history-named file in its folder - a
years-stale duplicate sitting next to the real one, or (at least once,
die 685) two files that genuinely split different copies between them with
no overlap. Every candidate gets parsed and merged; on an actual (die_no,
copy_no) collision between two files, the more recently modified file's
copy wins. See scan_history_files.py's docstring for the concrete cases
this was built against.

Paducah dies are done first (`--paducah-only` to stop there entirely), and a
die already parsed since its candidate files' combined mtime signature
hasn't changed is skipped, so a rerun after an interruption only does
new/changed work.

Must run from PowerShell: it opens files on the dies share, which the Bash
tool cannot reach (see tools/config.py).
"""
import argparse
import csv
import datetime
import json
import os
import sqlite3
import sys
import time

import config
import parse_history

SCHEMA = """
CREATE TABLE IF NOT EXISTS die (
    die_no TEXT PRIMARY KEY,
    die_folder TEXT,
    description TEXT,
    is_paducah INTEGER DEFAULT 0,
    history_file TEXT,
    history_mtime INTEGER,
    parsed_mtime INTEGER,
    parsed_at TEXT,
    parse_error TEXT
);

CREATE TABLE IF NOT EXISTS die_copy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    die_no TEXT NOT NULL,
    copy_no TEXT NOT NULL,
    sheet_name TEXT,
    die_no_reported TEXT,
    backer_number TEXT,
    bolster_number TEXT,
    times_nitrided INTEGER,
    total_billets_lifetime INTEGER,
    n_entries INTEGER,
    first_date TEXT,
    last_date TEXT,
    UNIQUE(die_no, copy_no)
);

CREATE TABLE IF NOT EXISTS production_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_id INTEGER NOT NULL REFERENCES die_copy(id),
    die_no TEXT NOT NULL,
    copy_no TEXT NOT NULL,
    seq INTEGER,
    block INTEGER,
    entry_date TEXT,
    date_raw TEXT,
    billets_raw TEXT,
    billets_num REAL,
    pull_code_raw TEXT,
    pull_code_norm TEXT,
    entry_type TEXT
);

CREATE INDEX IF NOT EXISTS idx_prod_die ON production_entry(die_no);
CREATE INDEX IF NOT EXISTS idx_prod_date ON production_entry(entry_date);
CREATE INDEX IF NOT EXISTS idx_prod_type ON production_entry(entry_type);
CREATE INDEX IF NOT EXISTS idx_copy_die ON die_copy(die_no);
"""


def load_paducah_set():
    if not os.path.exists(config.PADUCAH_LIST):
        print("  [warning] no paducah-dies.txt at %s - treating all dies as non-Paducah"
              % config.PADUCAH_LIST)
        return set()
    with open(config.PADUCAH_LIST) as f:
        return set(json.load(f))


def load_desc_map():
    """die_no -> description, from Vision's die_index.csv."""
    m = {}
    with open(config.DIE_INDEX_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("die_no"):
                m[r["die_no"]] = r.get("desc", "")
    return m


def load_history_candidates():
    """{die_no: {"die_folder": ..., "files": [(filename, mtime), ...]}} -
    every history-named file per die, from history_files.csv if it exists
    (tools/scan_history_files.py), else Vision's die_index.csv (one file
    per die - the thing that misses genuinely-split cases like die 685)."""
    path = os.path.join(config.DATA_DIR, "history_files.csv")
    by_die = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = by_die.setdefault(r["die_no"], {"die_folder": r["die_folder"], "files": []})
                d["files"].append((r["history_file"], int(r["history_mtime"])))
    else:
        print("  [warning] no data/history_files.csv - run tools/scan_history_files.py "
              "for full multi-file coverage; falling back to Vision's one-file-per-die crawl")
        with open(config.DIE_INDEX_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("die_no") and r.get("history_file"):
                    by_die[r["die_no"]] = {
                        "die_folder": r["die_folder"],
                        "files": [(r["history_file"], int(r["history_mtime"] or 0))],
                    }
    return by_die


def merge_copies(parsed_oldest_first):
    """parsed_oldest_first: [(mtime, parse_result), ...] sorted ascending.
    One die-copy dict per copy_no; where two source files both have the
    same copy_no, the copy from the more recently modified file wins
    (later in this list overwrites earlier) - see this file's module
    docstring."""
    merged = {}
    errors = []
    for _mtime, result in parsed_oldest_first:
        errors.extend(result["errors"])
        for copy in result["copies"]:
            merged[copy["copy_no"]] = copy
    return list(merged.values()), errors


def connect():
    config.ensure_dirs()
    con = sqlite3.connect(config.DB_PATH)
    con.executescript(SCHEMA)
    return con


def already_parsed(con, die_no, history_mtime, force=False):
    if force:
        return False
    row = con.execute("SELECT parsed_mtime FROM die WHERE die_no = ?", (die_no,)).fetchone()
    return row is not None and row[0] is not None and int(row[0]) == int(history_mtime)


def write_die_result(con, die_no, die_folder, description, is_paducah,
                      history_file, history_mtime, parse_result, error=None):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    con.execute("""
        INSERT INTO die (die_no, die_folder, description, is_paducah, history_file,
                          history_mtime, parsed_mtime, parsed_at, parse_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(die_no) DO UPDATE SET
            die_folder=excluded.die_folder, description=excluded.description,
            is_paducah=excluded.is_paducah, history_file=excluded.history_file,
            history_mtime=excluded.history_mtime, parsed_mtime=excluded.parsed_mtime,
            parsed_at=excluded.parsed_at, parse_error=excluded.parse_error
    """, (die_no, die_folder, description, int(is_paducah), history_file,
          int(history_mtime), int(history_mtime), now, error))

    if error is not None:
        return

    con.execute("DELETE FROM production_entry WHERE die_no = ?", (die_no,))
    con.execute("DELETE FROM die_copy WHERE die_no = ?", (die_no,))

    for copy in parse_result["copies"]:
        dates = [e["date"] for e in copy["entries"] if e["date"]]
        cur = con.execute("""
            INSERT INTO die_copy (die_no, copy_no, sheet_name, die_no_reported,
                                   backer_number, bolster_number, times_nitrided,
                                   total_billets_lifetime, n_entries, first_date, last_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (die_no, copy["copy_no"], copy["sheet_name"],
              str(copy["die_no_reported"]) if copy["die_no_reported"] is not None else None,
              str(copy["backer_number"]) if copy["backer_number"] is not None else None,
              str(copy["bolster_number"]) if copy["bolster_number"] is not None else None,
              copy["times_nitrided"], copy["total_billets_lifetime"], len(copy["entries"]),
              min(dates).isoformat() if dates else None,
              max(dates).isoformat() if dates else None))
        copy_id = cur.lastrowid
        con.executemany("""
            INSERT INTO production_entry (copy_id, die_no, copy_no, seq, block, entry_date,
                                           date_raw, billets_raw, billets_num,
                                           pull_code_raw, pull_code_norm, entry_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (copy_id, die_no, copy["copy_no"], e["seq"], e["block"],
             e["date"].isoformat() if e["date"] else None, e["date_raw"],
             e["billets_raw"], e["billets_num"], e["pull_code_raw"],
             e["pull_code_norm"], e["entry_type"])
            for e in copy["entries"]
        ])


def run(paducah_only=False, limit=None, budget=None, force=False):
    t0 = time.time()
    paducah = load_paducah_set()
    desc_map = load_desc_map()
    candidates = load_history_candidates()
    print("dies with a history file: %d (paducah dies known: %d)" % (len(candidates), len(paducah)))

    die_nos = list(candidates.keys())
    die_nos.sort(key=lambda d: (0 if d in paducah else 1, d))

    if paducah_only:
        die_nos = [d for d in die_nos if d in paducah]
        print("--paducah-only: restricting to %d dies" % len(die_nos))

    con = connect()
    n_done = n_skipped = n_error = 0
    for i, die_no in enumerate(die_nos, 1):
        if budget and time.time() - t0 > budget:
            print("budget of %ss reached, stopping at %d/%d" % (budget, i - 1, len(die_nos)))
            break
        if limit and n_done + n_skipped + n_error >= limit:
            print("limit of %d reached" % limit)
            break

        entry = candidates[die_no]
        die_folder = entry["die_folder"]
        files = sorted(entry["files"], key=lambda f: f[1])  # oldest first, so merge_copies'
                                                              # "later overwrites earlier" is
                                                              # "newer file wins"
        combined_mtime = max(m for _, m in files)
        history_file_display = "; ".join(f for f, _ in files)
        is_pad = die_no in paducah
        description = desc_map.get(die_no, "")

        if already_parsed(con, die_no, combined_mtime, force=force):
            n_skipped += 1
            continue

        parsed_oldest_first = []
        open_errors = []
        for fname, fmtime in files:
            path = os.path.join(config.DIES_ROOT, die_folder, fname)
            try:
                parsed_oldest_first.append((fmtime, parse_history.parse_workbook(path)))
            except Exception as e:
                open_errors.append("%s: %r" % (fname, e))

        merged_copies, parse_errors = merge_copies(parsed_oldest_first)
        all_errors = open_errors + parse_errors

        if not merged_copies and all_errors:
            write_die_result(con, die_no, die_folder, description, is_pad,
                              history_file_display, combined_mtime, None,
                              error="; ".join(all_errors))
            n_error += 1
            continue

        write_die_result(con, die_no, die_folder, description, is_pad,
                          history_file_display, combined_mtime, {"copies": merged_copies},
                          error="; ".join(all_errors) if all_errors else None)
        n_done += 1

        if i % 50 == 0:
            con.commit()
            print("%d/%d  done=%d skipped=%d error=%d  %.0fs" %
                  (i, len(die_nos), n_done, n_skipped, n_error, time.time() - t0))

    con.commit()
    con.close()
    print("DONE  done=%d skipped=%d error=%d  %.0fs" %
          (n_done, n_skipped, n_error, time.time() - t0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paducah-only", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--budget", type=float, default=None, help="stop after this many seconds")
    ap.add_argument("--force", action="store_true",
                    help="reparse even if the history file's mtime hasn't changed "
                         "(use after a parser code change)")
    args = ap.parse_args()
    run(paducah_only=args.paducah_only, limit=args.limit, budget=args.budget, force=args.force)
