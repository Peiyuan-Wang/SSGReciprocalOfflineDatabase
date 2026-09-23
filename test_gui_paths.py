#!/usr/bin/env python3
"""Tests for cross-platform database discovery."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ssg_database_gui", HERE / "ssg_database_gui.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class DatabasePathTest(unittest.TestCase):
    def test_source_checkout_uses_dist_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "ssg_database_gui.py"
            database = root / "dist" / "SSGReciprocalOffline-0.1.0.sqlite"
            database.parent.mkdir()
            database.touch()
            with mock.patch.object(module, "__file__", str(script)):
                self.assertEqual(module.default_database_path(), database.resolve())

    def test_frozen_windows_app_uses_database_beside_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            executable = root / "release" / "SSGReciprocalDatabase.exe"
            database = executable.parent / "SSGReciprocalOffline-0.1.0.sqlite"
            bundle.mkdir()
            executable.parent.mkdir()
            executable.touch()
            database.touch()
            with (
                mock.patch.object(module, "__file__", str(bundle / "ssg_database_gui.py")),
                mock.patch.object(sys, "executable", str(executable)),
                mock.patch.object(sys, "frozen", True, create=True),
            ):
                self.assertEqual(module.default_database_path(), database.resolve())


if __name__ == "__main__":
    unittest.main()
