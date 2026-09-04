"""Diagnose whether parse_history.py is leaving data on the table.

Checks three distinct kinds of "missing data" separately so the ambiguous
complaint "we're missing a lot" can be pinned to an actual cause:

  1. Die folders with NO history file at all, per Vision's die_index.csv.
  2. Sheets inside a parsed workbook that don't match the "<num>-<num>"
     copy-sheet name pattern - i.e. real data sitting in a sheet we skip.
  3. Rows inside a matched block that have a billets number but no date and
     no pull code - these fail parse_history's "keep if date or pull_code
     non-blank" rule and are silently treated as aggregate/blank. If this
     count is high, that rule is wrong, not just imprecise.
"""
import csv
import json
import os
import re
from collections import Counter

import config
import parse_history


def main(paducah_only=True):
    with open(config.PADUCAH_LIST) as f:
        paducah = set(json.load(f))

    with open(config.DIE_INDEX_CSV, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("history_file")]

    all_rows = []
    with open(config.DIE_INDEX_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            all_rows.append(r)

    has_die_no = [r for r in all_rows if r.get("die_no")]
    no_history = [r for r in has_die_no if not r.get("history_file")]
    print("die folders with a die_no: %d" % len(has_die_no))
    print("  of those, NO history file found: %d" % len(no_history))
    pad_no_history = [r for r in no_history if r["die_no"] in paducah]
    print("  of those, Paducah dies with NO history file: %d" % len(pad_no_history))
    for r in pad_no_history:
        print("    ", r["die_folder"])

    if paducah_only:
        rows = [r for r in rows if r["die_no"] in paducah]
    print("\nauditing %d workbooks%s..." % (len(rows), " (paducah only)" if paducah_only else ""))

    skipped_names = Counter()
    orphan_row_examples = []
    n_orphan_rows = 0
    n_matched_sheets = 0
    n_entries_total = 0

    for i, r in enumerate(rows, 1):
        path = os.path.join(config.DIES_ROOT, r["die_folder"], r["history_file"])
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in (".xlsx", ".xlsm"):
                sheets = parse_history._grid_from_xlsx(path)
                datemode = None
            else:
                sheets, datemode = parse_history._grid_from_xls(path)
        except Exception as e:
            print("  [open failed] %s: %r" % (path, e))
            continue

        for name, grid, maxr, maxc in sheets:
            if not grid:
                continue
            if parse_history.SHEET_COPY_RE.match(name):
                n_matched_sheets += 1
                # re-derive footer + blocks the same way parse_copy_sheet does,
                # then look at every (billets non-blank, date+pull both blank) row
                footer_row = maxr + 1
                for (rr, cc), v in grid.items():
                    if isinstance(v, str):
                        up = v.strip().upper()
                        if up == "DO NOT CHANGE" or up.startswith("NITRIDE TRIGGER"):
                            footer_row = min(footer_row, rr)
                pull_hits = parse_history._find_labels(grid, "PULL CODE")
                for hr, hc in pull_hits:
                    date_col, billets_col, pull_col = hc - 2, hc - 1, hc
                    last_row = min(maxr, footer_row - 1)
                    for rr in range(hr + 1, last_row + 1):
                        date_raw = grid.get((rr, date_col))
                        billets_raw = grid.get((rr, billets_col))
                        pull_raw = grid.get((rr, pull_col))
                        if date_raw is None and pull_raw is None and billets_raw is not None:
                            n_orphan_rows += 1
                            if len(orphan_row_examples) < 15:
                                orphan_row_examples.append(
                                    (r["die_folder"], name, rr, billets_raw))
                parsed = parse_history.parse_copy_sheet(grid, maxr, xls_datemode=datemode)
                n_entries_total += len(parsed["entries"])
            else:
                nm = name.strip()
                if nm.upper() not in ("MASTER PAGE", "XXXXXX") and \
                   not re.search(r"master\s*page", nm, re.I):
                    skipped_names[nm] += 1
                else:
                    skipped_names["<placeholder: %s>" % nm] += 1

        if i % 50 == 0:
            print("  %d/%d..." % (i, len(rows)))

    print("\nmatched copy-sheets: %d, entries captured: %d" % (n_matched_sheets, n_entries_total))
    print("orphan rows (billets present, date+pull both blank): %d" % n_orphan_rows)
    for ex in orphan_row_examples:
        print("   ", ex)

    print("\nnon-placeholder skipped sheet names (top 30):")
    real_skips = {k: v for k, v in skipped_names.items() if not k.startswith("<placeholder")}
    for name, cnt in sorted(real_skips.items(), key=lambda kv: -kv[1])[:30]:
        print("  %5d  %r" % (cnt, name))
    n_placeholder = sum(v for k, v in skipped_names.items() if k.startswith("<placeholder"))
    print("placeholder skips (Master Page / XXXXXX): %d" % n_placeholder)
    print("total non-placeholder skipped sheets: %d" % sum(real_skips.values()))


if __name__ == "__main__":
    import sys
    main(paducah_only=("--all" not in sys.argv))
