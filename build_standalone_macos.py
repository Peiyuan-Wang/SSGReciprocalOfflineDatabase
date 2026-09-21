#!/usr/bin/env python3
"""Build a self-contained arm64 macOS GUI and release archive."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        type=Path,
        default=HERE / ".build-venv" / "bin" / "python",
        help="Python interpreter containing PyInstaller",
    )
    parser.add_argument("--clean", action="store_true", help="remove previous build outputs")
    args = parser.parse_args()

    build_root = HERE / "build" / "standalone-macos"
    dist_root = HERE / "release"
    app_name = "SSG Reciprocal Database"
    app = build_root / "dist" / f"{app_name}.app"
    archive = dist_root / f"SSGReciprocalDatabase-macOS-arm64-{VERSION}.zip"
    database = HERE / "dist" / f"SSGReciprocalOffline-{VERSION}.sqlite"

    if args.clean:
        shutil.rmtree(build_root, ignore_errors=True)
        shutil.rmtree(dist_root, ignore_errors=True)
    build_root.mkdir(parents=True, exist_ok=True)
    dist_root.mkdir(parents=True, exist_ok=True)

    command = [
        str(args.python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        app_name,
        "--osx-bundle-identifier",
        "org.ssg.reciprocaldatabase.offline",
        "--target-arch",
        "arm64",
        "--distpath",
        str(build_root / "dist"),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root),
        str(HERE / "ssg_database_gui.py"),
    ]
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(build_root / "pyinstaller-cache")
    subprocess.run(command, check=True, cwd=HERE, env=environment)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        check=True,
    )
    if archive.exists():
        archive.unlink()
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)],
        check=True,
    )
    if not database.exists():
        raise FileNotFoundError(f"Database release file is missing: {database}")

    checksum_file = dist_root / "SHA256SUMS"
    checksum_file.write_text(
        f"{sha256(database)}  {database.name}\n"
        f"{sha256(archive)}  {archive.name}\n",
        encoding="ascii",
    )
    print(f"Application: {app}")
    print(f"Archive: {archive}")
    print(f"Database: {database}")
    print(checksum_file.read_text(encoding="ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
