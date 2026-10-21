#!/usr/bin/env python3
"""Build a self-contained Windows GUI and release archive."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


VERSION = "0.1.7"
HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def windows_architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def make_archive(source: Path, archive: Path, root_name: str) -> None:
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                output.write(path, Path(root_name) / path.relative_to(source))


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("The Windows release must be built on Windows")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter containing PyInstaller",
    )
    parser.add_argument("--clean", action="store_true", help="remove previous build outputs")
    parser.add_argument("--console", action="store_true", help="keep a console for build diagnostics")
    args = parser.parse_args()

    architecture = windows_architecture()
    build_root = HERE / "build" / "standalone-windows"
    dist_root = HERE / "release"
    app_name = "SSGReciprocalDatabase"
    app = build_root / "dist" / app_name
    database = HERE / "dist" / f"SSGReciprocalOffline-{VERSION}.sqlite"
    archive_root = f"{app_name}-Windows-{architecture}-{VERSION}"
    archive = dist_root / f"{archive_root}.zip"

    if not database.is_file():
        raise FileNotFoundError(f"Database release file is missing: {database}")
    if args.clean:
        shutil.rmtree(build_root, ignore_errors=True)
    build_root.mkdir(parents=True, exist_ok=True)
    dist_root.mkdir(parents=True, exist_ok=True)

    python_root = Path(sys.base_prefix).resolve()
    tcl_source = python_root / "tcl" / "tcl8.6"
    tk_source = python_root / "tcl" / "tk8.6"
    tkinter_extension = python_root / "DLLs" / "_tkinter.pyd"
    tcl_dll = python_root / "DLLs" / "tcl86t.dll"
    tk_dll = python_root / "DLLs" / "tk86t.dll"
    required_runtime_files = (tcl_source, tk_source, tkinter_extension, tcl_dll, tk_dll)
    missing = [path for path in required_runtime_files if not path.exists()]
    if missing:
        raise FileNotFoundError("Complete Tcl/Tk runtime is required: " + ", ".join(map(str, missing)))

    runtime_hook = build_root / "set_tk_runtime.py"
    runtime_hook.write_text(
        "import os, sys\n"
        "if getattr(sys, 'frozen', False):\n"
        "    os.environ['TCL_LIBRARY'] = os.path.join(sys._MEIPASS, '_tcl_data')\n"
        "    os.environ['TK_LIBRARY'] = os.path.join(sys._MEIPASS, '_tk_data')\n",
        encoding="ascii",
    )
    hooks_root = build_root / "hooks"
    pre_find_hooks = hooks_root / "pre_find_module_path"
    pre_find_hooks.mkdir(parents=True, exist_ok=True)
    (pre_find_hooks / "hook-tkinter.py").write_text(
        "def pre_find_module_path(hook_api):\n"
        "    # Tcl/Tk is collected explicitly by the Windows release builder.\n"
        "    return None\n",
        encoding="ascii",
    )
    (hooks_root / "hook-_tkinter.py").write_text(
        "# Tcl/Tk data and DLLs are collected explicitly by the release builder.\n",
        encoding="ascii",
    )

    command = [
        str(args.python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--console" if args.console else "--windowed",
        "--onedir",
        "--name",
        app_name,
        "--distpath",
        str(build_root / "dist"),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root),
        "--runtime-hook",
        str(runtime_hook),
        "--additional-hooks-dir",
        str(hooks_root),
        "--hidden-import",
        "tkinter",
        "--hidden-import",
        "tkinter.ttk",
        "--add-binary",
        f"{tkinter_extension};.",
        "--add-binary",
        f"{tcl_dll};.",
        "--add-binary",
        f"{tk_dll};.",
        "--add-data",
        f"{tcl_source};_tcl_data",
        "--add-data",
        f"{tk_source};_tk_data",
        str(HERE / "ssg_database_gui.py"),
    ]
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(build_root / "pyinstaller-cache")
    subprocess.run(command, check=True, cwd=HERE, env=environment)

    executable = app / f"{app_name}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller output is missing: {executable}")
    shutil.copy2(database, app / database.name)
    (app / "README.txt").write_text(
        "SSG Reciprocal Symmetry Offline Database\n"
        "\n"
        "Double-click SSGReciprocalDatabase.exe to start. Keep the EXE,\n"
        "the _internal folder, and the SQLite database together. No Python,\n"
        "Mathematica, Anaconda, or network connection is required.\n",
        encoding="utf-8",
    )

    make_archive(app, archive, archive_root)
    checksum_file = dist_root / "SHA256SUMS-Windows"
    checksum_file.write_text(
        f"{sha256(database)}  {database.name}\n"
        f"{sha256(archive)}  {archive.name}\n",
        encoding="ascii",
    )
    print(f"Application: {executable}")
    print(f"Archive: {archive}")
    print(f"Database: {database}")
    print(checksum_file.read_text(encoding="ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
