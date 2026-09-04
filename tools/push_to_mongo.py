"""Push the local die_history.db up to MongoDB Atlas for the cloud API.

Run by hand after `build_db.py` (and `compute_pounds.py`, if you want the
gross-pounds figures included) - not part of either automatically, since
this is the one step that needs network egress and a credential neither of
those does.

Needs SQL_PASS in the environment (same convention as Granco Saw Monitor /
picos - see cloud/api/db.py). Get it from wherever those projects' secret/
file already keeps it, or from whoever manages the Atlas cluster; this
script does not have it and does not prompt for it.

Mongo documents are shaped to match the API's JSON responses almost
exactly (see cloud/api/app.py) - a `die` doc is the same rollup /api/dies
already computes in SQL, and a `die_copy` doc is a copy plus its entries
embedded as an array, so /api/die/<die_no> is a single find_one plus a
single find, no aggregation needed against the free tier.

Safe to rerun: every write is an upsert keyed by die_no (die) or
"<die_no>:<copy_no>" (die_copy), so a rerun after more dies get parsed
locally just updates what changed.
"""
import os
import sqlite3
import sys

import config

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cloud", "api"))
from db import ensure_indexes, get_db  # noqa: E402


def _leading_int(s):
    import re
    m = re.match(r"^\s*(\d+)", str(s or ""))
    return int(m.group(1)) if m else 0


def main():
    if "SQL_PASS" not in os.environ or not os.environ["SQL_PASS"]:
        print("SQL_PASS is not set - see this file's docstring for where to get it.")
        sys.exit(1)

    con = sqlite3.connect("file:%s?mode=ro" % config.DB_PATH.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row

    dbm = get_db()

    print("building die rollups...")
    die_rows = con.execute("""
        SELECT d.die_no, d.description, d.is_paducah, d.history_file, d.parse_error,
               COUNT(DISTINCT dc.id) AS n_copies,
               COALESCE(SUM(dc.n_entries), 0) AS n_entries,
               COALESCE(SUM(dc.total_billets_lifetime), 0) AS total_billets,
               SUM(dc.gross_lbs) AS total_lbs,
               COUNT(dc.gross_lbs) AS n_copies_with_lbs,
               MIN(dc.first_date) AS first_date,
               MAX(dc.last_date) AS last_date
        FROM die d
        LEFT JOIN die_copy dc ON dc.die_no = d.die_no
        GROUP BY d.die_no
    """).fetchall()

    die_ops = []
    from pymongo import UpdateOne
    for r in die_rows:
        doc = dict(r)
        doc["die_no_int"] = _leading_int(doc["die_no"])
        die_ops.append(UpdateOne({"die_no": doc["die_no"]}, {"$set": doc}, upsert=True))
    if die_ops:
        dbm.die.bulk_write(die_ops)
    print("  upserted %d die docs" % len(die_ops))

    print("building die_copy docs (with embedded entries)...")
    copies = con.execute("SELECT * FROM die_copy").fetchall()
    copy_ops = []
    for c in copies:
        cdoc = dict(c)
        copy_id = cdoc.pop("id")
        entries = con.execute("""
            SELECT seq, block, entry_date, date_raw, billets_raw, billets_num,
                   pull_code_raw, pull_code_norm, entry_type
            FROM production_entry WHERE copy_id = ? ORDER BY seq
        """, (copy_id,)).fetchall()
        cdoc["entries"] = [dict(e) for e in entries]
        cdoc["copy_sort"] = _leading_int(cdoc["copy_no"])
        mongo_id = "%s:%s" % (cdoc["die_no"], cdoc["copy_no"])
        copy_ops.append(UpdateOne({"_id": mongo_id}, {"$set": {**cdoc, "_id": mongo_id}}, upsert=True))
        if len(copy_ops) >= 500:
            dbm.die_copy.bulk_write(copy_ops)
            copy_ops = []
    if copy_ops:
        dbm.die_copy.bulk_write(copy_ops)
    print("  upserted %d die_copy docs" % len(copies))

    print("writing summary doc...")
    summary = con.execute("""
        SELECT COUNT(*) AS n_dies,
               SUM(is_paducah) AS n_paducah,
               (SELECT COUNT(*) FROM die_copy) AS n_copies,
               (SELECT COUNT(*) FROM production_entry) AS n_entries,
               (SELECT COUNT(*) FROM die WHERE parse_error IS NOT NULL) AS n_errors
        FROM die
    """).fetchone()
    dbm.meta.update_one({"_id": "summary"}, {"$set": dict(summary)}, upsert=True)

    ensure_indexes()
    con.close()
    print("done.")


if __name__ == "__main__":
    main()
