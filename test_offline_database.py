#!/usr/bin/env python3
"""Consistency tests for the standalone database and its read layer."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
CATALOG = HERE.parent
DATA = CATALOG / "SSGReciprocalDatabase" / "Data"
DATABASES = sorted((HERE / "dist").glob("SSGReciprocalOffline-*.sqlite"))

spec = importlib.util.spec_from_file_location("ssg_database_gui", HERE / "ssg_database_gui.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
SSGDatabase = module.SSGDatabase
format_kmsg = module.format_kmsg
format_momentum_symmetry = module.format_momentum_symmetry
format_o3_representation = module.format_o3_representation
format_parent_generators = module.format_parent_generators


class OfflineDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DATABASES:
            raise unittest.SkipTest("Build the offline database before running tests")
        cls.path = DATABASES[-1]
        cls.database = SSGDatabase(cls.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.database.close()

    def test_integrity_and_counts(self) -> None:
        result = self.database.verify()
        self.assertEqual(result["Integrity"], "ok")
        self.assertEqual(result["SSGRecords"], 67475)
        self.assertEqual(result["O3Records"], 67475)

    def test_records_are_exact_source_copies(self) -> None:
        if not DATA.is_dir():
            self.skipTest("Source catalog is not available in this standalone checkout")
        samples = ("L1.1.1", "N6.9.19", "N143.10.1", "N143.16.1")
        source_cache = {}
        o3_cache = {}
        for label in samples:
            parent = int(label.split(".", 1)[0][1:])
            if parent not in source_cache:
                with (DATA / "Reciprocal" / f"sg{parent:03d}.json").open(
                    encoding="utf-8"
                ) as stream:
                    source_cache[parent] = json.load(stream)["Records"]
                with (DATA / "O3" / f"sg{parent:03d}.json").open(
                    encoding="utf-8"
                ) as stream:
                    o3_cache[parent] = json.load(stream)["XiaoRecords"]
            stored = self.database.get_ssg(label)
            self.assertIsNotNone(stored)
            self.assertEqual(stored["ReciprocalRecord"], source_cache[parent][label])
            self.assertEqual(stored["O3Record"], o3_cache[parent][label])

    def test_search_and_reverse_lookup(self) -> None:
        rows = self.database.search_ssg("N143.10.1")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["label"], "N143.10.1")
        bns = rows[0]["bns_number"]
        reverse = self.database.lookup_bns(bns)
        labels = {row["label"] for row in reverse["Labels"]}
        self.assertIn("N143.10.1", labels)
        self.assertEqual(reverse["Summary"]["ssg_count"], len(labels))

    def test_connection_is_query_only(self) -> None:
        with self.assertRaises(sqlite3.OperationalError):
            self.database.connection.execute("DELETE FROM metadata")

    def test_scientific_views_use_readable_matrix_notation(self) -> None:
        data = self.database.get_ssg("N143.10.1")
        record = data["ReciprocalRecord"]
        names = self.database.point_operation_names()
        generators = format_parent_generators(record, names)
        momentum = format_momentum_symmetry(
            record, data["MagneticSpaceGroup"], names
        )
        o3 = format_o3_representation(record, data["O3Record"], names)
        kmsg = format_kmsg(
            data["MagneticSpaceGroup"], data["OrdinarySpaceGroup"], names
        )
        self.assertIn("{R_g | t_g} = ⎡", generators)
        self.assertIn("A_g = ⎡", momentum)
        self.assertIn("kappa_g = ⎡", momentum)
        self.assertIn("rho(C3+) = ⎡", o3)
        self.assertIn("{A_g | kappa_g} = ⎡", kmsg)
        self.assertNotIn('"MomentumAffineAction"', momentum)
        self.assertNotIn("Element 1", momentum)
        self.assertNotIn("Operation 1", kmsg)
        self.assertIn("C3+", generators)

    def test_physical_operation_names_replace_numbered_placeholders(self) -> None:
        names = self.database.point_operation_names()

        mirror = self.database.get_ssg("N6.9.19")
        mirror_parent = format_parent_generators(mirror["ReciprocalRecord"], names)
        self.assertIn("Σ_y", mirror_parent)
        self.assertNotIn("g1", mirror_parent)

        antiunitary = self.database.get_ssg("N47.9.43")
        antiunitary_kmsg = format_kmsg(
            antiunitary["MagneticSpaceGroup"],
            antiunitary["OrdinarySpaceGroup"],
            names,
        )
        self.assertIn("Σ_y'", antiunitary_kmsg)
        self.assertNotIn("Operation 1", antiunitary_kmsg)


if __name__ == "__main__":
    unittest.main()
