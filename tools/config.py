"""Where things live. Every tool resolves paths through here.

Mirrors the pattern used by the sibling `Vision System Database` project:
settings are resolved here, overridable by environment variable, so the same
code runs on a workstation and on a service host without editing.

    DIEHIST_DIES_ROOT   the EXTRUSION DIES tree (read-only)
    DIEHIST_DATA_DIR    local working directory (database, staging)
    DIEHIST_VISION_DIR  the Vision System Database project (read-only inputs)

**UNC first, not a mapped drive.** Same reasoning as the Vision project: a
Windows service has no drive mappings, and UNC lists the dies root fast. `Z:`
is kept only as a last-resort fallback.

**The dies share is read-only.** Nothing here writes, moves, or deletes
anything under DIES_ROOT.

**Bash cannot reach the dies share.** `\\lud-storage...` (and its `Z:`
mapping) only resolves through PowerShell/cmd on this machine - a Bash `ls`
against it returns an empty listing with exit 0, which reads as "no data"
rather than as an error. Any tool here that touches DIES_ROOT must be run
from PowerShell, not Bash.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(_HERE)

# --- the dies share ------------------------------------------------------
DIES_UNC = os.path.join(r"\\lud-storage.whitehallindustries.com", "EXTRUSION",
                        "EXTRUSION DIES")
DIES_MAPPED = os.path.join("Z:", os.sep, "EXTRUSION DIES")


def _resolve_dies():
    env = os.environ.get("DIEHIST_DIES_ROOT")
    if env:
        return env
    for cand in (DIES_UNC, DIES_MAPPED):
        try:
            if os.path.isdir(cand):
                return cand
        except OSError:
            pass
    return DIES_UNC


DIES_ROOT = _resolve_dies()

# --- the sibling Vision System Database project --------------------------
# We reuse its confirmed-Paducah-dies list and its die_index.csv (die folder
# -> history file path, already crawled) instead of re-walking the share.
# Both are read-only inputs here; this project never writes into that one.
VISION_DIR = os.environ.get("DIEHIST_VISION_DIR") or os.path.normpath(
    os.path.join(PROJECT, "..", "Vision System Database"))
VISION_DATA = os.path.join(VISION_DIR, "data")
PADUCAH_LIST = os.path.join(VISION_DATA, "paducah-dies.txt")
DIE_INDEX_CSV = os.path.join(VISION_DATA, "die_index.csv")

# --- local working directory ---------------------------------------------
DATA_DIR = os.environ.get("DIEHIST_DATA_DIR") or os.path.join(PROJECT, "data")
DB_PATH = os.path.join(DATA_DIR, "die_history.db")

LOG_DIR = os.environ.get("DIEHIST_LOG_DIR") or os.path.join(DATA_DIR, "logs")


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


if __name__ == "__main__":
    print("PROJECT       : %s" % PROJECT)
    print("DIES_ROOT     : %s   (exists: %s)" % (DIES_ROOT, os.path.isdir(DIES_ROOT)))
    print("VISION_DIR    : %s   (exists: %s)" % (VISION_DIR, os.path.isdir(VISION_DIR)))
    print("PADUCAH_LIST  : %s   (exists: %s)" % (PADUCAH_LIST, os.path.exists(PADUCAH_LIST)))
    print("DIE_INDEX_CSV : %s   (exists: %s)" % (DIE_INDEX_CSV, os.path.exists(DIE_INDEX_CSV)))
    print("DATA_DIR      : %s" % DATA_DIR)
    print("DB_PATH       : %s   (exists: %s)" % (DB_PATH, os.path.exists(DB_PATH)))
