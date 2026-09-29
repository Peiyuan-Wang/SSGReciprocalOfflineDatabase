# SSG Reciprocal Offline Database v0.1.3

This release updates the read-only database and macOS GUI to the current
antiunitary-grading convention: `s_g = 0` denotes a unitary operation and
`s_g = 1` denotes an antiunitary operation. The GUI labels a group containing
antiunitary operations as magnetic, while retaining `antiunitary` for individual
operations. Momentum-space magnetic groups are labeled MNGs in the interface.

Assets include the SQLite database, a self-contained Apple Silicon macOS app,
and SHA-256 checksums. The app is ad-hoc signed but not Apple-notarized, so
macOS may require approval under Privacy & Security on first launch.
