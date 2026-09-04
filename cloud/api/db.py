"""MongoDB connection helper.

Same connection pattern as the rest of this codebase (Fetch Log Data,
Granco Saw Monitor, picos): username and cluster host inline, only the
password read from an env var (SQL_PASS) rather than a full connection-
string env var. This project gets its own database (die_history) on the
same shared Atlas cluster, same reasoning as Granco's db.py: a project gets
its own database rather than landing in whatever the default happens to be.
"""
import os

from pymongo import MongoClient

DB_NAME = "die_history"

_client = None


def get_db():
    global _client
    if _client is None:
        sql_pass = os.environ["SQL_PASS"]
        _client = MongoClient(
            f"mongodb+srv://padpress1:{sql_pass}@cluster0.ywwxl.mongodb.net/"
            "?retryWrites=true&w=majority&appName=Cluster0"
        )
    return _client[DB_NAME]


def ensure_indexes():
    db = get_db()
    db.die.create_index("die_no", unique=True)
    db.die.create_index("is_paducah")
    db.die.create_index("die_no_int")
    db.die_copy.create_index([("die_no", 1), ("copy_sort", 1)])
