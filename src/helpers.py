# src/helpers.py
import os
import json
import csv
import pytz
from datetime import datetime

def now_ist():
    """Return current datetime in Asia/Kolkata timezone."""
    return datetime.now(pytz.timezone("Asia/Kolkata"))

def save_json(obj, path):
    """Save Python object to JSON file (ensure folder exists)."""
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str, ensure_ascii=False)

def _normalize_cell(val):
    """Normalize value for CSV cell (serialize complex types)."""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, ensure_ascii=False)
        except Exception:
            return str(val)
    return val

def append_csv(data, filename):
    """
    Append list-of-dicts to CSV file. If file exists and new rows contain
    keys not present in the existing header, rewrite the CSV with the
    combined header (preserving old rows) and append new rows.
    Accepts a single dict or a list of dicts.
    """
    # Normalize input
    if data is None:
        return
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        raise TypeError("append_csv expects a dict or list of dicts")

    if not rows:
        return

    dirpath = os.path.dirname(filename)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)

    # Collect new fieldnames in order of first appearance
    new_fieldnames = []
    for r in rows:
        for k in r.keys():
            if k not in new_fieldnames:
                new_fieldnames.append(k)

    # If file exists read existing header and rows
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8", newline="") as rf:
            reader = csv.DictReader(rf)
            existing_fieldnames = reader.fieldnames or []
            existing_rows = list(reader)

        # Build final fieldnames preserving existing order first
        final_fieldnames = list(existing_fieldnames)
        for fn in new_fieldnames:
            if fn not in final_fieldnames:
                final_fieldnames.append(fn)

        # If final header is different from existing, rewrite file completely
        if set(final_fieldnames) != set(existing_fieldnames):
            with open(filename, "w", encoding="utf-8", newline="") as wf:
                writer = csv.DictWriter(wf, fieldnames=final_fieldnames)
                writer.writeheader()
                # write old rows (ensure they have all final fields)
                for r in existing_rows:
                    out = {fn: _normalize_cell(r.get(fn, "")) for fn in final_fieldnames}
                    writer.writerow(out)
                # write new rows
                for r in rows:
                    out = {fn: _normalize_cell(r.get(fn, "")) for fn in final_fieldnames}
                    writer.writerow(out)
        else:
            # Safe to append with existing header
            with open(filename, "a", encoding="utf-8", newline="") as af:
                writer = csv.DictWriter(af, fieldnames=existing_fieldnames)
                for r in rows:
                    # only include fields that writer expects
                    row_out = {k: _normalize_cell(v) for k, v in r.items() if k in existing_fieldnames}
                    writer.writerow(row_out)
    else:
        # File does not exist: create it with new_fieldnames header
        with open(filename, "w", encoding="utf-8", newline="") as wf:
            writer = csv.DictWriter(wf, fieldnames=new_fieldnames)
            writer.writeheader()
            for r in rows:
                out = {fn: _normalize_cell(r.get(fn, "")) for fn in new_fieldnames}
                writer.writerow(out)
