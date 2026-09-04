"""Find every history-named file per die folder, not just one.

Vision System Database's build_die_index.py records a single history_file
per die: its per-folder scan keeps overwriting one variable on every
"*histor*.xls/.xlsx/.xlsm" match, so whichever file os.scandir happens to
enumerate last wins - not necessarily the right one, and definitely not
"all of them" when there's more than one.

That matters more than it sounds. Checked all 141 Paducah dies: 50 have
more than one history-named file in their folder, and 38 of those were
indexed against a file other than the most-recently-modified one - some
harmless (an old "DIE 000 HISTORY SHEET.xls" template stub with zero real
copy sheets, superseded by a real "<die> Die History.xlsx"), but at least
one (685) splits GENUINELY DIFFERENT copies across two files with no
overlap ("685 Die History - Paducah.xlsx" has copies 52/65-114; "685 Die
History - Ludington dies only.xlsx" has 39LUD/47LUD/.../109/112/115-144) -
picking only the newest of the two would silently drop ~50 real copies.

So: don't pick one file per die. Record every candidate, let build_db.py
parse and merge all of them, newest-file-wins only on an actual (die_no,
copy_no) collision (see build_db.py's merge_copies()).

Reuses die_index.csv's die_folder mapping rather than re-walking the whole
1,448-folder root; only rescans folders that already have a die_no and at
least one history_file recorded there. Read-only; writes only
data/history_files.csv. Takes a few minutes (one os.scandir per die
folder, ~1,247 of them) - run it periodically, same cadence as Vision's own
build_die_index.py, not on every build_db.py run.
"""
import csv
import os
import re
import time

import config

_CAND = re.compile(r"(?i)histor")
OUT = os.path.join(config.DATA_DIR, "history_files.csv")


def candidates_in(folder_path):
    """[(filename, mtime), ...] for every history-named workbook directly
    in `folder_path`, newest first."""
    out = []
    try:
        entries = list(os.scandir(folder_path))
    except OSError:
        return out
    for e in entries:
        if e.is_file() and _CAND.search(e.name) and \
           e.name.lower().endswith((".xls", ".xlsx", ".xlsm")):
            try:
                out.append((e.name, int(e.stat().st_mtime)))
            except OSError:
                continue
    out.sort(key=lambda c: c[1], reverse=True)
    return out


def run():
    config.ensure_dirs()
    with open(config.DIE_INDEX_CSV, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("die_no") and r.get("history_file")]

    t0 = time.time()
    out_rows = []
    n_multi = 0
    for i, r in enumerate(rows, 1):
        folder_path = os.path.join(config.DIES_ROOT, r["die_folder"])
        cands = candidates_in(folder_path)
        if len(cands) > 1:
            n_multi += 1
        for name, mtime in cands:
            out_rows.append({
                "die_no": r["die_no"], "die_folder": r["die_folder"],
                "history_file": name, "history_mtime": mtime,
            })
        if i % 200 == 0:
            print(f"{i}/{len(rows)}  {time.time()-t0:.0f}s", flush=True)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["die_no", "die_folder", "history_file", "history_mtime"])
        w.writeheader()
        w.writerows(out_rows)

    print(f"DONE {len(rows)} dies scanned, {len(out_rows)} candidate files found, "
          f"{n_multi} dies had more than one, {time.time()-t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    run()
