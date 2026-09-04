"""Parse a Die History workbook into normalized production/nitride records.

Two template families exist on the share, distinguished only by look, not by
extension alone:

    old   (.xls)          DIE/BACKER/BOLSTER labels at (2,6)/(4,6)/(6,6),
                           "PRODUCTION HISTORY" banner ~row 21, column headers
                           ("DATE","BILLETS","PULL CODE" x3) ~row 24, no
                           nitride-trigger footer.
    new   (.xlsx/.xlsm)    same label positions, banner ~row 9, headers ~row
                           12, plus a "Times Nitrided" / "Nitride Trigger"
                           footer around rows 11-14 and 46-50.

Both were confirmed identical in *position* across every sample pulled (six
dies spanning both plants, three vintages, one generic "DIE 000..." filename)
so this parser is anchor-based rather than positional: it locates each label
by text, not by row/column number, and would keep working if a future
template shifted rows around. It does not guess when a workbook does not
match the shape at all - such a sheet comes back with an entries list of []
and is left for a human to look at, not silently mis-parsed.

Per-copy sheets are the ones named "<num>-<num>" or "<num>_<num>" (e.g.
"1011-1"). Everything else - "Master Page", "XXXXXX", blank placeholder
sheets - is a template stub, not data, and is skipped by construction (it
simply never matches that name pattern).
"""
import datetime
import os
import re


# Copy-sheet names are not always the bare "<die>-<copy>": some carry a
# trailing qualifier - "1121-32P4" (press/position 4), "1105-12lud"
# (Ludington), "1102-35 2H" (2nd head). The qualifier is kept as part of
# copy_no (not stripped) so two sheets that share a copy number but differ
# only by qualifier don't collide - e.g. a bare "1121-32" and a "1121-32P4"
# would otherwise both become copy_no "32". SQLite's CAST(x AS INTEGER)
# still sorts these correctly (it reads the leading numeric prefix), so nothing
# downstream needs to change to order by copy number.
SHEET_COPY_RE = re.compile(r"^\s*(\d{2,5})[-_](\d{1,3})\s*(\S.*)?$")

_NITRIDE_RE = re.compile(r"nitrid", re.IGNORECASE)
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


class ParseError(Exception):
    pass


def _grid_from_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = []
    for name in wb.sheetnames:
        ws = wb[name]
        grid = {}
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if v is not None and str(v).strip() != "":
                    grid[(cell.row, cell.column)] = v
        maxr = ws.max_row or 0
        maxc = ws.max_column or 0
        out.append((name, grid, maxr, maxc))
    wb.close()
    return out


def _grid_from_xls(path):
    import xlrd
    wb = xlrd.open_workbook(path, formatting_info=False)
    out = []
    for name in wb.sheet_names():
        ws = wb.sheet_by_name(name)
        grid = {}
        for r in range(ws.nrows):
            for c in range(ws.ncols):
                v = ws.cell_value(r, c)
                if v != "":
                    grid[(r + 1, c + 1)] = v
        out.append((name, grid, ws.nrows, ws.ncols))
    return out, wb.datemode


def _to_date(value, xls_datemode=None):
    """Best-effort date coercion. Returns a datetime.date or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, (int, float)):
        if xls_datemode is None:
            return None
        try:
            import xlrd
            dt = xlrd.xldate_as_datetime(value, xls_datemode)
            return dt.date()
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def _find_label(grid, label):
    """First cell whose text matches `label` exactly (case/space-insensitive)."""
    target = label.upper()
    for (r, c), v in grid.items():
        if isinstance(v, str) and v.strip().upper() == target:
            return (r, c)
    return None


def _find_labels(grid, label):
    target = label.upper()
    hits = []
    for (r, c), v in grid.items():
        if isinstance(v, str) and v.strip().upper() == target:
            hits.append((r, c))
    return sorted(hits)


def _value_right(grid, r, c, max_scan=8):
    for cc in range(c + 1, c + 1 + max_scan):
        v = grid.get((r, cc))
        if v is not None:
            return v
    return None


def _classify_entry(billets_raw, pull_code_raw):
    text = " ".join(x for x in (str(billets_raw or ""), str(pull_code_raw or "")))
    if _NITRIDE_RE.search(text):
        return "nitride"
    if billets_raw is not None and _NUM_RE.match(str(billets_raw).strip()):
        return "production"
    return "unknown"


def _numish(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if _NUM_RE.match(s):
        try:
            f = float(s)
            return int(f) if f == int(f) else f
        except ValueError:
            return None
    return None


def parse_copy_sheet(grid, maxr, xls_datemode=None):
    """Parse one per-copy sheet's grid into a dict of copy-level fields
    plus a list of production/nitride entries. `grid` is {(row,col): value}.
    """
    result = {
        "die_no_reported": None,
        "backer_number": None,
        "bolster_number": None,
        "times_nitrided": None,
        "total_billets_lifetime": None,
        "entries": [],
    }

    die_lbl = _find_label(grid, "DIE NUMBER")
    if die_lbl:
        result["die_no_reported"] = _value_right(grid, *die_lbl)
    backer_lbl = _find_label(grid, "BACKER NUMBER")
    if backer_lbl:
        result["backer_number"] = _value_right(grid, *backer_lbl)
    bolster_lbl = _find_label(grid, "BOLSTER NUMBER")
    if bolster_lbl:
        result["bolster_number"] = _value_right(grid, *bolster_lbl)
    nitrided_lbl = _find_label(grid, "Times Nitrided")
    if nitrided_lbl:
        r, c = nitrided_lbl
        # value sits one row below the label, same column, in this template
        result["times_nitrided"] = _numish(grid.get((r + 1, c)))
    # "Total Billets Through..." (lifetime total) is a distinct label from
    # the "Total Billets" *column header* higher up the sheet - match the
    # longer phrase first so the header does not shadow it.
    total_lbl = None
    for (r, c), v in grid.items():
        if isinstance(v, str) and v.strip().upper().startswith("TOTAL BILLETS THROUGH"):
            total_lbl = (r, c)
            break
    if total_lbl:
        r, c = total_lbl
        result["total_billets_lifetime"] = _numish(_value_right(grid, r, c, max_scan=4))

    # The "Do Not Change" nitride-trigger admin block (newer template only,
    # rows ~46-50) reuses the same columns as the production pull-code
    # blocks, so a plain "scan to max_row" picks up its labels as if they
    # were production entries. Clip every block's scan to end before it.
    footer_row = maxr + 1
    for (r, c), v in grid.items():
        if isinstance(v, str):
            up = v.strip().upper()
            if up == "DO NOT CHANGE" or up.startswith("NITRIDE TRIGGER"):
                footer_row = min(footer_row, r)

    pull_hits = _find_labels(grid, "PULL CODE")
    seq = 0
    for block_idx, (hr, hc) in enumerate(pull_hits):
        date_col = hc - 2
        billets_col = hc - 1
        pull_col = hc
        last_row = min(maxr, footer_row - 1)
        for r in range(hr + 1, last_row + 1):
            date_raw = grid.get((r, date_col))
            billets_raw = grid.get((r, billets_col))
            pull_raw = grid.get((r, pull_col))
            if date_raw is None and pull_raw is None:
                continue  # aggregate/blank/stray-annotation row; not an entry
            date_val = _to_date(date_raw, xls_datemode)
            pull_norm = str(pull_raw).strip().lower() if pull_raw is not None else None
            entry = {
                "seq": seq,
                "block": block_idx,
                "row": r,
                "date": date_val,
                "date_raw": None if date_raw is None else str(date_raw),
                "billets_raw": None if billets_raw is None else str(billets_raw),
                "billets_num": _numish(billets_raw),
                "pull_code_raw": None if pull_raw is None else str(pull_raw),
                "pull_code_norm": pull_norm,
                "entry_type": _classify_entry(billets_raw, pull_raw),
            }
            result["entries"].append(entry)
            seq += 1

    return result


def parse_workbook(path):
    """Parse a whole Die History workbook. Returns dict:
       {"copies": [...], "skipped_sheets": [...], "errors": [...]}
    Each item in "copies" carries copy-level fields (see parse_copy_sheet)
    plus "sheet_name" and "copy_no" (from the sheet name, authoritative -
    the workbook can have a stale/blank DIE NUMBER cell, but the sheet name
    is the one consistent part, same reasoning the vision project uses for
    report folder paths).
    """
    ext = os.path.splitext(path)[1].lower()
    out = {"copies": [], "skipped_sheets": [], "errors": []}
    try:
        if ext in (".xlsx", ".xlsm"):
            sheets = _grid_from_xlsx(path)
            datemode = None
        elif ext == ".xls":
            sheets, datemode = _grid_from_xls(path)
        else:
            out["errors"].append("unsupported extension: %s" % ext)
            return out
    except Exception as e:
        out["errors"].append("failed to open: %r" % e)
        return out

    for name, grid, maxr, maxc in sheets:
        m = SHEET_COPY_RE.match(name)
        if not m:
            out["skipped_sheets"].append(name)
            continue
        die_no = m.group(1)
        copy_no = m.group(2) + (m.group(3) or "").strip()
        try:
            parsed = parse_copy_sheet(grid, maxr, xls_datemode=datemode)
        except Exception as e:
            out["errors"].append("sheet %r: %r" % (name, e))
            continue
        parsed["sheet_name"] = name
        parsed["die_no_from_sheet"] = die_no
        parsed["copy_no"] = copy_no
        out["copies"].append(parsed)

    return out


if __name__ == "__main__":
    import sys
    import pprint

    for p in sys.argv[1:]:
        result = parse_workbook(p)
        print("\n====", p, "====")
        print("skipped sheets:", result["skipped_sheets"])
        if result["errors"]:
            print("errors:", result["errors"])
        for copy in result["copies"]:
            n_entries = len(copy["entries"])
            print(f"  sheet={copy['sheet_name']!r} die_no_from_sheet={copy['die_no_from_sheet']} "
                  f"copy_no={copy['copy_no']} die_reported={copy['die_no_reported']!r} "
                  f"backer={copy['backer_number']!r} bolster={copy['bolster_number']!r} "
                  f"times_nitrided={copy['times_nitrided']!r} "
                  f"total_billets={copy['total_billets_lifetime']!r} entries={n_entries}")
            for e in copy["entries"][:3]:
                print("    ", e)
