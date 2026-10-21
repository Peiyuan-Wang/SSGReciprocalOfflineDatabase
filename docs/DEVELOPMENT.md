# Source Tests and Rebuilding

## Test the Reader

Requires Python 3.9+. The reader uses only the standard library; the source GUI
also needs Tcl/Tk 8.6+.

Download `SSGReciprocalOffline-0.1.6.sqlite` from the release and put it in `dist/`.
Then run from the repository root:

```bash
python3 -m unittest discover -v
python3 ssg_database_gui.py --check
python3 ssg_database_gui.py --gui-smoke
```

`--gui-smoke` opens and closes the window automatically. Without a downloaded
database, only the data-independent tests run. One test compares upstream
source records and is skipped when the separate paclet source data are absent.
Set `SSG_SOURCE_DATA` to the paclet's `Data` directory to include that comparison.

## Rebuild SQLite

The Git checkout does not contain the large scientific catalog. Download the
matching computational paclet, extract it as a ZIP, and locate its `Data/`
directory. Computational package 0.12.2 and database 0.1.6 contain the same
scientific records as package 0.12.1 and database 0.1.5.

```bash
python3 build_offline_database.py \
  --data-root /path/to/SSGReciprocalDatabase-0.12.2/Data \
  --output dist/SSGReciprocalOffline-0.1.6.sqlite
```

The command copies the catalog records into SQLite and builds search indexes.
It does not recompute the spin representations or group classification.
Use `--force` only when intentionally replacing an existing build output.

## Build a Packaged Viewer

First place the 0.1.6 SQLite file in `dist/`. Install PyInstaller in an isolated
Python 3.12 environment with Tcl/Tk 8.6+.

On macOS Apple Silicon:

```bash
python3 -m venv .build-venv
.build-venv/bin/python -m pip install pyinstaller
.build-venv/bin/python build_standalone_macos.py
```

On Windows x64:

```powershell
py -3.12 -m venv .build-venv
.build-venv\Scripts\python.exe -m pip install pyinstaller
.build-venv\Scripts\python.exe build_standalone_windows.py
```

The Windows archive includes the database. The macOS archive contains the app;
the same SQLite file is distributed separately. Outputs are written to `release/`.

The optional `build_macos_app.py` builds a small development launcher that
uses an installed Python runtime. It is distinct from the self-contained
release produced by `build_standalone_macos.py`.
