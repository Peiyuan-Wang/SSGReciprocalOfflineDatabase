# MG Database

An offline viewer for the momentum-space symmetry data of 67,475 spin space
groups (SSGs). Search by SSG label or by the BNS number of a reciprocal
magnetic group (MG). The viewer uses the same scientific records as the
[MG Computational Package](https://github.com/Peiyuan-Wang/SSGReciprocalDatabase).

## Download and Open

Download the files from the [v0.1.6 release](https://github.com/Peiyuan-Wang/SSGReciprocalOfflineDatabase/releases/tag/v0.1.6).
The packaged viewers do not require Python, Mathematica, or an internet connection.

### macOS Apple Silicon

1. Download `SSGReciprocalDatabase-macOS-arm64-0.1.6.zip` and
   `SSGReciprocalOffline-0.1.6.sqlite`.
2. Extract the ZIP. Keep `SSG Reciprocal Database.app` and the SQLite file
   in the same folder.
3. Open the application. A file chooser is available if the database is elsewhere.

The application is ad-hoc signed and has not been notarized by Apple.
If macOS blocks it, first confirm that the download is from this release.
For this trusted application, follow Apple's
[Privacy & Security instructions](https://support.apple.com/en-au/102445)
and choose **Open Anyway**. The supplied macOS binary targets Apple Silicon;
Intel Macs can use the source workflow below.

### Windows 64-bit

1. Download `SSGReciprocalDatabase-Windows-x64-0.1.6.zip`.
2. Extract the complete ZIP.
3. Open `SSGReciprocalDatabase.exe`.

The Windows ZIP includes the database. Keep the executable, `_internal`
folder, and SQLite file together.

## Search and Interpret Results

In **SSG lookup**, enter a label from Xiao et al., such as `N6.9.19`.
Select a result to inspect:

| View | Content |
| --- | --- |
| Overview | Magnetic order, Bloch lattice, translation projectivity, intrinsic nonsymmorphicity, and MG identifiers. |
| Parent group generator | Spatial generators and their real-space Seitz operations. |
| SSG momentum symmetry | Momentum matrices, fractional translations, and unitary/antiunitary grading. |
| SSG O(3) representation | Spin matrices associated with the stored generators. |
| MG | Standard MG operations and the coordinate transformation from the SSG momentum basis. |
| Raw JSON | Full stored records for further calculation. |

In **MG reverse lookup**, enter a BNS number such as `7.24`. The result
lists the stored SSG realizations, an example, and the MG type.

The Bloch sublattice is `Z_{L_0}`; `L_F` is its reciprocal lattice.
Momentum acts as `k -> R_tilde_p k + kappa_p`, modulo integer reciprocal
vectors. The momentum matrix already includes the antiunitary sign.
Grading `s_p=0` is unitary and `s_p=1` is antiunitary.
A prime in an operation name identifies an antiunitary operation.

The displayed intrinsic nonsymmorphicity is the result of a common-origin
test over the complete operation set. The viewer reads precomputed records;
it does not recalculate the classification. Parameterized SSG families use
the representative choices described by the computational package.

## Run From Source

Requires Python 3.9+; the GUI also requires Tcl/Tk 8.6+.

1. Clone this repository or download its source ZIP.
2. Download the SQLite file from the release and put it in `dist/`.
3. Run:

~~~bash
python3 ssg_database_gui.py
~~~

Use an explicit path when the database is elsewhere:

~~~bash
python3 ssg_database_gui.py --database "/path/to/SSGReciprocalOffline-0.1.6.sqlite"
~~~

The command-line reader works without Tk:

~~~bash
python3 ssg_database_gui.py --check
python3 ssg_database_gui.py --bns 7.24
python3 ssg_database_gui.py --label N6.9.19
~~~

See [development and verification](docs/DEVELOPMENT.md) for source tests,
rebuilding SQLite from the paclet, and packaging the platform viewers.
[Data sources](docs/SOURCES.md) records the source relationship and citations.
