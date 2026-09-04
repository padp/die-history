"""Die History API - Flask on MongoDB Atlas.

Same route shapes as the local api/app.py (the one backed by SQLite),
so web/ is the exact same frontend unchanged - it just talks to whichever
of the two is running. Read-only: everything here is written by
tools/push_to_mongo.py, run by hand after a local build.

Reads are open (this is the shop's own production-history numbers, same
sensitivity level as Granco's cut-timing data, which is open for the same
reason - see that project's api/app.py). There is no write/ingest endpoint
here at all: this API never accepts data, only serves what push_to_mongo.py
already pushed.
"""
import os
import re

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from db import get_db

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")

app = Flask(__name__, static_folder=None)
CORS(app)


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEB, filename)


@app.get("/api/summary")
def summary():
    db = get_db()
    doc = db.meta.find_one({"_id": "summary"}, {"_id": 0})
    return jsonify(doc or {})


@app.get("/api/dies")
def dies():
    db = get_db()
    paducah_only = request.args.get("paducah_only", "1") == "1"
    query = (request.args.get("q") or "").strip()

    filt = {}
    if paducah_only:
        filt["is_paducah"] = 1
    if query:
        pattern = re.escape(query)
        filt["$or"] = [
            {"die_no": {"$regex": pattern, "$options": "i"}},
            {"description": {"$regex": pattern, "$options": "i"}},
        ]

    rows = list(db.die.find(filt, {"_id": 0}).sort([("is_paducah", -1), ("die_no_int", 1)]))
    return jsonify(rows)


@app.get("/api/die/<die_no>")
def die_detail(die_no):
    db = get_db()
    die = db.die.find_one({"die_no": die_no}, {"_id": 0})
    if die is None:
        return jsonify({"error": "not found"}), 404

    copies = list(
        db.die_copy.find({"die_no": die_no}, {"_id": 0}).sort("copy_sort", 1)
    )
    die["copies"] = copies
    return jsonify(die)


if __name__ == "__main__":
    # Local smoke-test only - Render/Vercel are expected to invoke `app`
    # directly (gunicorn / the Vercel Python runtime), never this block. But
    # if a Render service ends up configured with a start command of
    # `python api/app.py` instead of gunicorn, PORT (Render sets this, not a
    # fixed value) still has to be honored or Render's proxy gets a 502
    # against whatever port it's actually listening for.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5059)), debug=True)
