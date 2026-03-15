import csv
import os

def read_csv_dict(path, key):
    if not os.path.exists(path):
        return {}

    # Try UTF-8 with BOM first, then fall back to GBK for Chinese files
    try:
        with open(path, encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            return {row[key]: row for row in reader}
    except UnicodeDecodeError:
        with open(path, encoding='gbk') as f:
            reader = csv.DictReader(f)
            return {row[key]: row for row in reader}


def write_csv_dict(path, rows: dict):
    if not rows:
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        fieldnames = list(next(iter(rows.values())).keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows.values():
            writer.writerow(row)
