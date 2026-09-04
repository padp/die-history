"""Compute gross pounds extruded per die-copy.

    gross_lbs = billets_total * (median_billet_length_in - BUTT_LENGTH_IN) * LB_PER_IN

Billet length comes from the sibling "Press History UI" project's
`v2/billet_fingerprints.db` - a 3-year, 256k+ row per-billet archive keyed
by (profile=die number, die_copy=copy number), local SQLite, no
credentials needed. It has real per-billet lengths but no butt/discard
length field, so butt length uses a fixed standard (the shop's actual
practice - confirmed by the user, not a guess) rather than a per-copy
measurement: nothing in this codebase logs historical butt length long
enough to cover the archive (only a live, recently-started monitor does,
and it isn't wired up here yet - see CLAUDE.md).

billets_total is this project's own production_entry sum, not the
fingerprint archive's billet count - the fingerprint DB only goes back a
few years and doesn't cover the full Die History timeline, but every run's
billet count is already in the Excel-derived data regardless of whether a
matching fingerprint exists. A copy with no fingerprint match still gets a
billets_total; it just gets gross_lbs = NULL instead of a number, so
"unknown" and "zero" are never confused in the data.

Read-only against the fingerprints DB; writes only to this project's own
die_history.db. Safe to rerun any time (recomputes and overwrites).
"""
import argparse
import json
import re
import sqlite3
import statistics

import config

FINGERPRINTS_DB = r"w:\Extrusion DB\Press History UI\v2\billet_fingerprints.db"

BUTT_LENGTH_IN = 0.8   # shop-standard discard/butt length, confirmed by the user
LB_PER_IN = 4.9        # weight per linear inch for this billet diameter/alloy class

_LEADING_INT = re.compile(r"^\s*(\d+)")


def _leading_int(s):
    if s is None:
        return None
    m = _LEADING_INT.match(str(s))
    return m.group(1) if m else None


def load_billet_lengths():
    """{(die_no, copy_num): [billet_length, ...]} from the fingerprint archive."""
    con = sqlite3.connect("file:%s?mode=ro" % FINGERPRINTS_DB.replace("\\", "/"), uri=True)
    lengths = {}
    n_rows = n_used = 0
    for profile, die_copy, data in con.execute("SELECT profile, die_copy, data FROM fingerprints"):
        n_rows += 1
        die_no = _leading_int(profile)
        copy_num = _leading_int(die_copy)
        if die_no is None or copy_num is None:
            continue
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            continue
        if d.get("is_cleanout"):
            continue
        bl = d.get("billet_length")
        if not isinstance(bl, (int, float)) or bl <= 0:
            continue
        lengths.setdefault((die_no, copy_num), []).append(bl)
        n_used += 1
    con.close()
    print("fingerprint rows: %d, usable billet lengths: %d, distinct die-copies matched: %d" %
          (n_rows, n_used, len(lengths)))
    return lengths


def run():
    lengths = load_billet_lengths()

    dh = sqlite3.connect(config.DB_PATH)
    new_cols = {
        "billet_length_median_in": "REAL",
        "billet_length_n": "INTEGER",
        "butt_length_in": "REAL",
        "billets_total": "INTEGER",
        "gross_lbs": "REAL",
    }
    for col, coltype in new_cols.items():
        if not _has_col(dh, "die_copy", col):
            dh.execute("ALTER TABLE die_copy ADD COLUMN %s %s" % (col, coltype))

    # One pass over production_entry rather than one SUM query per copy -
    # copy_id has no index, so 6,800+ individual per-copy scans over a
    # 120k-row table (build_db.py only indexes die_no/entry_date/entry_type,
    # queried by die not by copy) took long enough to look hung.
    billets_by_copy = {}
    for copy_id, billets_num in dh.execute("""
        SELECT copy_id, billets_num FROM production_entry WHERE entry_type = 'production'
    """):
        billets_by_copy[copy_id] = billets_by_copy.get(copy_id, 0) + (billets_num or 0)

    copies = dh.execute("SELECT id, die_no, copy_no FROM die_copy").fetchall()
    n_matched = 0
    for copy_id, die_no, copy_no in copies:
        copy_num = _leading_int(copy_no)
        sample = lengths.get((die_no, copy_num)) if copy_num else None
        billets_total = billets_by_copy.get(copy_id, 0)

        if sample:
            median_len = statistics.median(sample)
            gross_lbs = billets_total * (median_len - BUTT_LENGTH_IN) * LB_PER_IN
            n_matched += 1
        else:
            median_len = None
            gross_lbs = None

        dh.execute("""
            UPDATE die_copy SET billet_length_median_in = ?, billet_length_n = ?,
                                 butt_length_in = ?, billets_total = ?, gross_lbs = ?
            WHERE id = ?
        """, (median_len, len(sample) if sample else None, BUTT_LENGTH_IN,
              billets_total, gross_lbs, copy_id))

    dh.commit()
    dh.close()
    print("die_copy rows updated: %d, matched a fingerprint: %d" % (len(copies), n_matched))


def _has_col(con, table, col):
    return any(r[1] == col for r in con.execute("PRAGMA table_info(%s)" % table))


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()
