#!/usr/bin/env python3
"""Compare every scientific record across the sublattice-notation update."""

import json
from itertools import zip_longest
import sqlite3
import zlib
from pathlib import Path


HERE = Path(__file__).resolve().parent


def normalize(record):
    for old, new in (("LB", "ZL0"), ("LBConvention", "ZL0Convention")):
        if old in record:
            record[new] = record.pop(old)
    return record


def main():
    old = sqlite3.connect(f"file:{HERE / 'dist/SSGReciprocalOffline-0.1.3.sqlite'}?mode=ro", uri=True)
    new = sqlite3.connect(f"file:{HERE / 'dist/SSGReciprocalOffline-0.1.4.sqlite'}?mode=ro", uri=True)
    query = "SELECT label, reciprocal_record_zlib, o3_record_zlib FROM ssg_records ORDER BY label"
    count = 0
    for previous, current in zip_longest(old.execute(query), new.execute(query)):
        assert previous is not None and current is not None, "Record count changed"
        assert previous[0] == current[0]
        before = normalize(json.loads(zlib.decompress(previous[1])))
        after = json.loads(zlib.decompress(current[1]))
        assert before == after, current[0]
        assert previous[2] == current[2], current[0]
        count += 1
    assert count == 67475, count
    for table in ("magnetic_space_group_classes", "ordinary_space_group_classes",
                  "msg_realizations", "msg_realization_summary"):
        rows = f"SELECT * FROM {table} ORDER BY 1, 2"
        assert list(old.execute(rows)) == list(new.execute(rows)), table
    old.close()
    new.close()
    print(f"PASS: all {count} reciprocal and O(3) records, group identifications, and reverse links are unchanged.")


if __name__ == "__main__":
    main()
