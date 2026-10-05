#!/usr/bin/env python3
"""Build the standalone SSG reciprocal-symmetry SQLite database.

The SQLite file is a read-only distribution artifact.  Every scientific record
is copied from the Mathematica paclet data without semantic transformation and
stored as compressed canonical JSON.  Normalized columns are search indexes,
not an independent calculation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Tuple


SCHEMA_VERSION = 3
DATABASE_VERSION = "0.1.4"
APPLICATION_ID = 0x53534752  # "SSGR"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def pack_json(value: Any) -> bytes:
    return zlib.compress(canonical_json(value), level=9)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def iter_parent_files(directory: Path) -> Iterator[Path]:
    def parent_number(path: Path) -> int:
        return int(path.stem.removeprefix("sg"))

    yield from sorted(directory.glob("sg*.json"), key=parent_number)


def bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(bool(value))


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA page_size = 4096;
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE source_files (
            relative_path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            byte_count INTEGER NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE ordinary_space_group_classes (
            class_key TEXT PRIMARY KEY,
            international_number INTEGER,
            international_symbol TEXT,
            hall_number INTEGER,
            status TEXT,
            record_zlib BLOB NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE magnetic_space_group_classes (
            class_key TEXT PRIMARY KEY,
            bns_number TEXT,
            uni_number INTEGER,
            magnetic_type INTEGER,
            status TEXT,
            record_zlib BLOB NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE parent_irrep_records (
            pir_label TEXT PRIMARY KEY,
            parent_space_group INTEGER NOT NULL,
            record_zlib BLOB NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE point_operation_names (
            record_id INTEGER PRIMARY KEY CHECK (record_id = 1),
            record_zlib BLOB NOT NULL
        );

        CREATE TABLE ssg_records (
            label TEXT PRIMARY KEY,
            parent_space_group INTEGER NOT NULL,
            magnetic_order TEXT,
            status TEXT,
            nonsymmorphic INTEGER,
            translation_projectivity TEXT,
            ordinary_class_key TEXT,
            magnetic_class_key TEXT,
            bns_number TEXT,
            magnetic_type INTEGER,
            reciprocal_record_zlib BLOB NOT NULL,
            o3_record_zlib BLOB NOT NULL,
            FOREIGN KEY (ordinary_class_key)
                REFERENCES ordinary_space_group_classes(class_key),
            FOREIGN KEY (magnetic_class_key)
                REFERENCES magnetic_space_group_classes(class_key)
        ) WITHOUT ROWID;

        CREATE TABLE msg_realizations (
            bns_number TEXT NOT NULL,
            label TEXT NOT NULL,
            is_example INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (bns_number, label),
            FOREIGN KEY (label) REFERENCES ssg_records(label)
        ) WITHOUT ROWID;

        CREATE TABLE msg_realization_summary (
            bns_number TEXT PRIMARY KEY,
            uni_number INTEGER,
            magnetic_type INTEGER,
            nonsymmorphic INTEGER,
            realized INTEGER,
            example_label TEXT,
            ssg_count INTEGER,
            record_zlib BLOB NOT NULL
        ) WITHOUT ROWID;

        CREATE INDEX idx_ssg_parent ON ssg_records(parent_space_group);
        CREATE INDEX idx_ssg_order ON ssg_records(magnetic_order);
        CREATE INDEX idx_ssg_nonsymmorphic ON ssg_records(nonsymmorphic);
        CREATE INDEX idx_ssg_bns ON ssg_records(bns_number);
        CREATE INDEX idx_msg_labels ON msg_realizations(label);
        """
    )
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def insert_classes(
    connection: sqlite3.Connection,
    ordinary_data: Dict[str, Any],
    magnetic_data: Dict[str, Any],
) -> None:
    connection.executemany(
        """
        INSERT INTO ordinary_space_group_classes VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                key,
                record.get("InternationalNumber"),
                record.get("InternationalSymbol"),
                record.get("HallNumber"),
                record.get("Status"),
                pack_json(record),
            )
            for key, record in ordinary_data["Classes"].items()
        ),
    )
    connection.executemany(
        """
        INSERT INTO magnetic_space_group_classes VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                key,
                record.get("BNSNumber"),
                record.get("UNINumber"),
                record.get("MagneticType"),
                record.get("Status"),
                pack_json(record),
            )
            for key, record in magnetic_data["Classes"].items()
        ),
    )


def insert_point_operation_names(
    connection: sqlite3.Connection, data: Dict[str, Any]
) -> None:
    connection.execute(
        "INSERT INTO point_operation_names VALUES (1, ?)",
        (pack_json(data),),
    )


def load_o3_records(
    path: Path,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    data = load_json(path)
    return data.get("XiaoRecords", {}), data.get("PIRRecords", {})


def insert_ssg_records(
    connection: sqlite3.Connection,
    data_root: Path,
    ordinary_data: Dict[str, Any],
    magnetic_data: Dict[str, Any],
) -> Tuple[int, set[str]]:
    reciprocal_dir = data_root / "Reciprocal"
    o3_dir = data_root / "O3"
    labels: set[str] = set()
    count = 0

    for reciprocal_path in iter_parent_files(reciprocal_dir):
        parent = int(reciprocal_path.stem.removeprefix("sg"))
        o3_path = o3_dir / reciprocal_path.name
        if not o3_path.exists():
            raise FileNotFoundError(f"Missing O(3) shard: {o3_path}")

        reciprocal_data = load_json(reciprocal_path)
        o3_records, pir_records = load_o3_records(o3_path)
        rows = []
        shard_labels = set(reciprocal_data.get("Records", {}))
        if shard_labels != set(o3_records):
            missing_o3 = sorted(shard_labels - set(o3_records))[:5]
            extra_o3 = sorted(set(o3_records) - shard_labels)[:5]
            raise ValueError(
                f"Label mismatch for SG {parent}: missing O3={missing_o3}, "
                f"extra O3={extra_o3}"
            )

        for label, record in reciprocal_data["Records"].items():
            if label in labels:
                raise ValueError(f"Duplicate SSG label: {label}")
            if record.get("ParentSpaceGroup") != parent:
                raise ValueError(f"Parent-space-group mismatch for {label}")

            ordinary_key = ordinary_data["Labels"].get(label)
            magnetic_key = magnetic_data["Labels"].get(label)
            if ordinary_key is None or magnetic_key is None:
                raise ValueError(f"Missing identification class for {label}")
            magnetic_class = magnetic_data["Classes"][magnetic_key]
            rows.append(
                (
                    label,
                    parent,
                    record.get("MagneticOrder"),
                    record.get("Status"),
                    bool_to_int(record.get("Nonsymmorphic")),
                    record.get("TranslationProjectivity"),
                    ordinary_key,
                    magnetic_key,
                    magnetic_class.get("BNSNumber"),
                    magnetic_class.get("MagneticType"),
                    pack_json(record),
                    pack_json(o3_records[label]),
                )
            )
            labels.add(label)

        connection.executemany(
            """
            INSERT INTO ssg_records VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.executemany(
            "INSERT INTO parent_irrep_records VALUES (?, ?, ?)",
            ((label, parent, pack_json(record)) for label, record in pir_records.items()),
        )
        count += len(rows)
        print(f"SG {parent:03d}: inserted {len(rows):4d} records ({count:6d} total)")

    return count, labels


def insert_msg_realizations(
    connection: sqlite3.Connection, data: Dict[str, Any], valid_labels: set[str]
) -> None:
    for group in data["Groups"]:
        bns = str(group["BNS"])
        labels = group.get("SSGLabels", [])
        unknown = set(labels) - valid_labels
        if unknown:
            raise ValueError(f"Unknown realization labels for BNS {bns}: {sorted(unknown)[:5]}")
        connection.execute(
            """
            INSERT INTO msg_realization_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bns,
                group.get("UNI"),
                group.get("Type"),
                bool_to_int(group.get("Nonsymmorphic")),
                bool_to_int(group.get("Realized")),
                group.get("Example"),
                group.get("SSGCount", len(labels)),
                pack_json(group),
            ),
        )
        connection.executemany(
            "INSERT INTO msg_realizations VALUES (?, ?, ?)",
            ((bns, label, int(label == group.get("Example"))) for label in labels),
        )


def validate_database(connection: sqlite3.Connection, expected_labels: set[str]) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise ValueError(f"Foreign-key violations: {violations[:5]}")

    count = connection.execute("SELECT COUNT(*) FROM ssg_records").fetchone()[0]
    if count != len(expected_labels):
        raise ValueError(f"Expected {len(expected_labels)} SSG rows, found {count}")

    stored = {row[0] for row in connection.execute("SELECT label FROM ssg_records")}
    if stored != expected_labels:
        raise ValueError("Stored SSG label set differs from the source label set")

    for label in ("N143.10.1", "N143.16.1", "L1.1.1"):
        if label in expected_labels:
            row = connection.execute(
                "SELECT reciprocal_record_zlib, o3_record_zlib FROM ssg_records WHERE label=?",
                (label,),
            ).fetchone()
            for payload in row:
                json.loads(zlib.decompress(payload).decode("utf-8"))

    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"SQLite integrity check failed: {integrity}")


def source_paths(data_root: Path) -> Iterable[Path]:
    yield from iter_parent_files(data_root / "Reciprocal")
    yield from iter_parent_files(data_root / "O3")
    for name in (
        "SpaceGroupIdentification.json",
        "MagneticSpaceGroupIdentification.json",
        "MagneticSpaceGroupRealizations.json",
        "SpaceGroupIrepRotationNames.json",
    ):
        yield data_root / name


def build_database(data_root: Path, output: Path, force: bool = False) -> None:
    data_root = data_root.resolve()
    output = output.resolve()
    if output.exists() and not force:
        raise FileExistsError(f"Output already exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)

    ordinary_path = data_root / "SpaceGroupIdentification.json"
    magnetic_path = data_root / "MagneticSpaceGroupIdentification.json"
    realizations_path = data_root / "MagneticSpaceGroupRealizations.json"
    ordinary_data = load_json(ordinary_path)
    magnetic_data = load_json(magnetic_path)
    realization_data = load_json(realizations_path)
    point_operation_names = load_json(data_root / "SpaceGroupIrepRotationNames.json")

    ordinary_labels = set(ordinary_data["Labels"])
    magnetic_labels = set(magnetic_data["Labels"])
    if ordinary_labels != magnetic_labels:
        raise ValueError("Ordinary and magnetic identification label sets differ")

    temporary = Path(
        tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)[1]
    )
    try:
        connection = sqlite3.connect(temporary)
        try:
            create_schema(connection)
            insert_classes(connection, ordinary_data, magnetic_data)
            insert_point_operation_names(connection, point_operation_names)
            count, stored_labels = insert_ssg_records(
                connection, data_root, ordinary_data, magnetic_data
            )
            if stored_labels != ordinary_labels:
                missing = sorted(ordinary_labels - stored_labels)[:10]
                extra = sorted(stored_labels - ordinary_labels)[:10]
                raise ValueError(f"Source label mismatch: missing={missing}, extra={extra}")
            insert_msg_realizations(connection, realization_data, stored_labels)

            metadata = {
                "database_name": "SSG Reciprocal Symmetry Offline Database",
                "database_version": DATABASE_VERSION,
                "schema_version": str(SCHEMA_VERSION),
                "record_count": str(count),
                "storage_format": "canonical JSON compressed with zlib level 9",
                "scientific_source": "SSGReciprocalDatabase Mathematica paclet data",
                "source_reciprocal_schema": str(
                    load_json(next(iter_parent_files(data_root / "Reciprocal"))).get(
                        "SchemaVersion", ""
                    )
                ),
                "source_magnetic_schema": str(magnetic_data.get("SchemaVersion", "")),
                "scope": (
                    "Offline read-only distribution of existing catalog records; "
                    "no scientific result is recomputed by the GUI"
                ),
            }
            connection.executemany(
                "INSERT INTO metadata VALUES (?, ?)", metadata.items()
            )
            connection.executemany(
                "INSERT INTO source_files VALUES (?, ?, ?)",
                (
                    (
                        str(path.relative_to(data_root)),
                        sha256_file(path),
                        path.stat().st_size,
                    )
                    for path in source_paths(data_root)
                ),
            )
            validate_database(connection, ordinary_labels)
            connection.commit()
            connection.execute("VACUUM")
            connection.commit()
        finally:
            connection.close()

        os.replace(temporary, output)
        print(f"Built {output}")
        print(f"Size: {output.stat().st_size / (1024 * 1024):.2f} MiB")
        print(f"SHA256: {sha256_file(output)}")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    catalog_dir = script_dir.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=catalog_dir / "SSGReciprocalDatabase" / "Data",
        help="Mathematica paclet Data directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "dist" / f"SSGReciprocalOffline-{DATABASE_VERSION}.sqlite",
        help="output SQLite file",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        build_database(args.data_root, args.output, args.force)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
