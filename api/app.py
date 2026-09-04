"""Die History API - Flask over the SQLite index built by tools/build_db.py.

Serves the web UI and read-only JSON. Mirrors the sibling Vision System
Database app's shape (waitress, read-only DB connection, static web/ dir)
but is otherwise a separate app on its own port.
"""
import os
import sqlite3

from flask import Flask, jsonify, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
WEB = os.path.join(PROJECT, "web")
DB_PATH = os.environ.get("DIEHIST_DB") or os.path.join(PROJECT, "data", "die_history.db")

app = Flask(__name__, static_folder=None)


def q(sql, args=(), one=False):
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    return (rows[0] if rows else None) if one else rows


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEB, filename)


@app.get("/api/summary")
def summary():
    row = q("""
        SELECT COUNT(*) AS n_dies,
               SUM(is_paducah) AS n_paducah,
               (SELECT COUNT(*) FROM die_copy) AS n_copies,
               (SELECT COUNT(*) FROM production_entry) AS n_entries,
               (SELECT COUNT(*) FROM die WHERE parse_error IS NOT NULL) AS n_errors
        FROM die
    """, one=True)
    return jsonify(row)


@app.get("/api/dies")
def dies():
    paducah_only = request.args.get("paducah_only", "1") == "1"
    query = (request.args.get("q") or "").strip()

    where = []
    args = []
    if paducah_only:
        where.append("d.is_paducah = 1")
    if query:
        where.append("(d.die_no LIKE ? OR d.description LIKE ?)")
        args += ["%%%s%%" % query, "%%%s%%" % query]
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = q("""
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
        %s
        GROUP BY d.die_no
        ORDER BY d.is_paducah DESC, CAST(d.die_no AS INTEGER)
    """ % where_sql, args)
    return jsonify(rows)


@app.get("/api/die/<die_no>")
def die_detail(die_no):
    die = q("SELECT * FROM die WHERE die_no = ?", (die_no,), one=True)
    if die is None:
        return jsonify({"error": "not found"}), 404

    copies = q("""
        SELECT * FROM die_copy WHERE die_no = ?
        ORDER BY CAST(copy_no AS INTEGER)
    """, (die_no,))
    entries = q("""
        SELECT * FROM production_entry WHERE die_no = ?
        ORDER BY CAST(copy_no AS INTEGER), seq
    """, (die_no,))

    by_copy = {}
    for e in entries:
        by_copy.setdefault(e["copy_no"], []).append(e)
    for c in copies:
        c["entries"] = by_copy.get(c["copy_no"], [])

    die["copies"] = copies
    return jsonify(die)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5058)
    args = ap.parse_args()

    from waitress import serve
    print("Die History serving on http://%s:%d  (db: %s)" % (args.host, args.port, DB_PATH))
    serve(app, host=args.host, port=args.port)
