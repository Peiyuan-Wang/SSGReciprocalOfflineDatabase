# SSG Reciprocal Symmetry Offline Database

This directory builds and reads a standalone offline database derived from the
same source records distributed by the `SSGReciprocalDatabase` Mathematica
paclet. It does not run a web server and the GUI does not recompute scientific
results.

## Downloaded release

Each release contains two principal assets:

1. `SSGReciprocalOffline-<version>.sqlite`: the database.
2. `SSGReciprocalDatabase-macOS-arm64-<version>.zip`: the self-contained GUI.

Unzip the application and keep the `.app` and `.sqlite` in the same folder.
Double-click the application to search the database. The application also
offers a file chooser when the database is stored elsewhere.

The macOS application bundles Python, Tk, and SQLite. It does not require
Anaconda, Mathematica, Python, a network connection, or a website. Version
0.1.0 targets Apple Silicon Macs. The application is ad-hoc signed but not
Apple-notarized; on first launch, macOS may require Control-clicking the app and
choosing **Open**.

Verify downloads from the release directory with:

```bash
shasum -a 256 -c SHA256SUMS
```

## Data model

The database contains exact compressed copies of:

- all reciprocal-symmetry records for 67,475 Xiao SSG labels;
- all corresponding O(3) representation records;
- ordinary space-group identifications;
- magnetic space-group identifications and BNS reverse lookups;
- parent-space-group PIR records;
- source-file SHA-256 hashes for provenance checks.

Normalized SQL columns provide fast searches. They are indexes over the source
records, not a separate calculation.

## Build

From this directory:

```bash
python3 build_offline_database.py --force
```

The result is written to `dist/SSGReciprocalOffline-0.1.0.sqlite`.

## Use the GUI

On macOS, double-click `launch_gui.command`, or run:

```bash
python3 ssg_database_gui.py
```

A lightweight macOS application wrapper can be built with:

```bash
python3 build_macos_app.py
```

Keep `SSG Reciprocal Database.app` and the `.sqlite` file in the same folder.
This development wrapper locates a local Python runtime with Tk 8.6; a fully
self-contained release build can bundle that runtime later. Its application
entry point is a native Mach-O launcher, so Finder and LaunchServices can keep
the GUI process attached to the app bundle.

For a self-contained Apple Silicon release, create an isolated build
environment and install PyInstaller:

```bash
python3 -m venv .build-venv
.build-venv/bin/python -m pip install pyinstaller
.build-venv/bin/python build_standalone_macos.py --clean
```

The release archive is written to `release/`. The application automatically
opens a database placed beside the `.app`; otherwise it presents a local file
chooser.

If the database is stored elsewhere:

```bash
python3 ssg_database_gui.py \
  --database /absolute/path/SSGReciprocalOffline-0.1.0.sqlite
```

The GUI supports:

- SSG label and BNS-number search;
- reciprocal lattice, status, and nonsymmorphicity inspection;
- stored reciprocal generators and full graded group elements;
- O(3) representation alternatives;
- corresponding standard ordinary and magnetic group records;
- BNS-to-SSG reverse lookup;
- raw JSON inspection for reproducibility.

The database is always opened with SQLite `mode=ro` and `query_only=ON`.

## Command-line checks

```bash
python3 ssg_database_gui.py --check
python3 ssg_database_gui.py --gui-smoke
python3 ssg_database_gui.py --label N143.10.1
python3 ssg_database_gui.py --bns 156.49
python3 -m unittest -v test_offline_database.py
```

## Runtime requirements

The current reader uses only Python's standard library: `sqlite3`, `zlib`,
`json`, and `tkinter`. The source launcher requires Tcl/Tk 8.6 or newer; the
obsolete Tk 8.5 bundled with macOS system Python does not render reliably on
current macOS releases. No Mathematica installation and no network connection
are required. The next packaging step can wrap the reader with a current Tk as
a macOS `.app` and Windows executable so end users do not need Python.

## Compatibility boundary

Database version `0.1.0` uses SQLite schema version `1`. The file records the
source catalog schemas and source hashes in its metadata. A GUI rejects unknown
schema versions instead of silently interpreting incompatible data.
