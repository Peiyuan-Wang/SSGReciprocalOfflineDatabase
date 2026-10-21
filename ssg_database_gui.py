#!/usr/bin/env python3
"""Local read-only GUI for the SSG reciprocal-symmetry database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zlib
from fractions import Fraction
from math import gcd
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


EXPECTED_APPLICATION_ID = 0x53534752
EXPECTED_SCHEMA_VERSION = 3


def configure_windows_dpi() -> None:
    """Opt into native per-monitor scaling before Tk creates any windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # -4 is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        # Older Windows versions or restricted hosts can still use Tk's default.
        pass


def unpack_json(payload: bytes | None) -> Any:
    if payload is None:
        return None
    return json.loads(zlib.decompress(payload).decode("utf-8"))


def compact(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def scalar_text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def column_vector(value: Any) -> List[List[Any]]:
    if not isinstance(value, list):
        return [[value]]
    result = []
    for item in value:
        if isinstance(item, list) and len(item) == 1:
            result.append([item[0]])
        else:
            result.append([item])
    return result


def identity_matrix(size: int = 3) -> List[List[int]]:
    return [[int(row == column) for column in range(size)] for row in range(size)]


def matrix_key(matrix: Any) -> str:
    if matrix in ("E", "I"):
        matrix = identity_matrix()
    return json.dumps(matrix, sort_keys=True, separators=(",", ":"))


def determinant_3(matrix: List[List[Any]]) -> Fraction:
    a = [[Fraction(value) for value in row] for row in matrix]
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def inverse_transpose_3(matrix: List[List[Any]]) -> List[List[Any]]:
    a = [[Fraction(value) for value in row] for row in matrix]
    determinant = determinant_3(matrix)
    if determinant == 0:
        raise ValueError("Point-operation matrix is singular")
    cofactors = [
        [
            (-1) ** (row + column)
            * (
                a[(row + 1) % 3][(column + 1) % 3]
                * a[(row + 2) % 3][(column + 2) % 3]
                - a[(row + 1) % 3][(column + 2) % 3]
                * a[(row + 2) % 3][(column + 1) % 3]
            )
            for column in range(3)
        ]
        for row in range(3)
    ]
    result = []
    for row in cofactors:
        converted = []
        for value in row:
            value /= determinant
            converted.append(int(value) if value.denominator == 1 else str(value))
        result.append(converted)
    return result


def matrix_product(left: List[List[int]], right: List[List[int]]) -> List[List[int]]:
    return [
        [sum(left[row][inner] * right[inner][column] for inner in range(3)) for column in range(3)]
        for row in range(3)
    ]


def matrix_order(matrix: List[List[int]], maximum: int = 12) -> Optional[int]:
    product = identity_matrix()
    for order in range(1, maximum + 1):
        product = matrix_product(product, matrix)
        if product == identity_matrix():
            return order
    return None


def primitive_null_vector(matrix: List[List[int]], eigenvalue: int) -> Optional[List[int]]:
    shifted = [
        [matrix[row][column] - eigenvalue * int(row == column) for column in range(3)]
        for row in range(3)
    ]
    candidates = []
    for x in range(-3, 4):
        for y in range(-3, 4):
            for z in range(-3, 4):
                vector = [x, y, z]
                if vector == [0, 0, 0]:
                    continue
                if all(sum(row[index] * vector[index] for index in range(3)) == 0 for row in shifted):
                    divisor = gcd(gcd(abs(x), abs(y)), abs(z)) or 1
                    vector = [value // divisor for value in vector]
                    first = next(value for value in vector if value)
                    if first < 0:
                        vector = [-value for value in vector]
                    candidates.append(vector)
    if not candidates:
        return None
    return min({tuple(vector) for vector in candidates}, key=lambda vector: (sum(abs(x) for x in vector), vector))


def axis_label(vector: Optional[List[int]]) -> str:
    labels = {(1, 0, 0): "x", (0, 1, 0): "y", (0, 0, 1): "z"}
    if vector is None:
        return ""
    key = tuple(vector)
    return labels.get(key, "[" + " ".join(str(value) for value in vector) + "]")


def normalize_operation_name(name: str) -> str:
    if name.startswith("σ"):
        return "Σ_" + name[1:]
    return name


def infer_operation_name(matrix: List[List[int]]) -> str:
    if matrix == identity_matrix():
        return "E"
    if matrix == [[-1, 0, 0], [0, -1, 0], [0, 0, -1]]:
        return "I"
    determinant = int(determinant_3(matrix))
    order = matrix_order(matrix)
    if determinant == 1:
        return f"C{order or '?'}{axis_label(primitive_null_vector(matrix, 1))}"
    if order == 2:
        return "Σ_" + axis_label(primitive_null_vector(matrix, -1))
    return f"S{order or '?'}{axis_label(primitive_null_vector(matrix, -1))}"


def point_operation_name(
    matrix: List[List[int]], space_group: Any, naming_data: Optional[Dict[str, Any]]
) -> str:
    if naming_data:
        bravais = naming_data.get("SpaceGroupBravais", {}).get(str(space_group))
        for entry in naming_data.get("Rotations", {}).get(bravais, []):
            if entry.get("Matrix") == matrix:
                return normalize_operation_name(entry.get("Name", ""))
    return infer_operation_name(matrix)


def spatial_matrix_from_momentum(linear: List[List[int]], grading: int) -> List[List[int]]:
    return inverse_transpose_3([[(1 - 2 * grading) * value for value in row] for row in linear])


def magnetic_operation_name(
    operation: Dict[str, Any], space_group: Any, naming_data: Optional[Dict[str, Any]]
) -> str:
    grading = operation.get("Grading", 1 if operation.get("Antiunitary") else 0)
    action = operation.get("MomentumAffineAction", [None, None])
    linear = operation.get("MatrixOfRtildeInReciprocalBasis") or action[0]
    spatial = spatial_matrix_from_momentum(linear, grading)
    name = point_operation_name(spatial, space_group, naming_data)
    return name + ("'" if grading == 1 else "")


def operation_signature(operation: Dict[str, Any]) -> str:
    action = operation.get("MomentumAffineAction", [None, None])
    linear = operation.get("MatrixOfRtildeInReciprocalBasis") or action[0]
    shift = operation.get("FractionalMomentumShiftKappa") or action[1]
    grading = operation.get("Grading", 1 if operation.get("Antiunitary") else 0)
    return matrix_key([linear, shift, grading])


def input_operation_names(
    magnetic: Dict[str, Any], naming_data: Optional[Dict[str, Any]]
) -> Dict[str, str]:
    space_group = magnetic.get("ReferenceSpaceGroupNumber")
    result = {}
    inputs = magnetic.get("InputOperations", [])
    for correspondence in magnetic.get("InputToStandardOperations", []):
        index = correspondence.get("InputIndex", 0) - 1
        standard = correspondence.get("StandardOperation", {})
        if 0 <= index < len(inputs):
            result[operation_signature(inputs[index])] = magnetic_operation_name(
                standard, space_group, naming_data
            )
    return result


def translation_name(translation: Any) -> str:
    vector = [row[0] for row in column_vector(translation)]
    axes = {(1, 0, 0): "T_x", (0, 1, 0): "T_y", (0, 0, 1): "T_z"}
    return axes.get(tuple(vector), "T_[" + " ".join(map(str, vector)) + "]")


def matrix_lines(matrix: Any, divider_after: Optional[int] = None) -> List[str]:
    if matrix in ("E", "I"):
        matrix = identity_matrix()
    if not isinstance(matrix, list) or not matrix:
        return [scalar_text(matrix)]
    rows = [row if isinstance(row, list) else [row] for row in matrix]
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    texts = [[scalar_text(value) for value in row] for row in normalized]
    column_widths = [max(len(row[column]) for row in texts) for column in range(width)]
    output = []
    for row_index, row in enumerate(texts):
        entries = []
        for column, value in enumerate(row):
            entries.append(value.rjust(column_widths[column]))
            if divider_after is not None and column + 1 == divider_after:
                entries.append("│")
        body = "  ".join(entries)
        if len(texts) == 1:
            left, right = "[", "]"
        elif row_index == 0:
            left, right = "⎡", "⎤"
        elif row_index == len(texts) - 1:
            left, right = "⎣", "⎦"
        else:
            left, right = "⎢", "⎥"
        output.append(f"{left} {body} {right}")
    return output


def labeled_matrix(label: str, matrix: Any) -> List[str]:
    lines = matrix_lines(matrix)
    if len(lines) == 1:
        return [f"{label} = {lines[0]}"]
    prefix = f"{label} = "
    return [prefix + lines[0]] + [" " * len(prefix) + line for line in lines[1:]]


def seitz_lines(rotation: Any, translation: Any, label: str = "{R_g | t_g}") -> List[str]:
    if rotation in ("E", "I"):
        rotation = identity_matrix()
    vector = [row[0] for row in column_vector(translation)]
    augmented = []
    for index, row in enumerate(rotation):
        augmented.append(list(row) + [vector[index] if index < len(vector) else 0])
    lines = matrix_lines(augmented, divider_after=len(rotation[0]))
    prefix = f"{label} = "
    return [prefix + lines[0]] + [" " * len(prefix) + line for line in lines[1:]]


def side_by_side(blocks: Iterable[List[str]], gap: str = "      ") -> List[str]:
    blocks = list(blocks)
    if not blocks:
        return []
    height = max(len(block) for block in blocks)
    widths = [max((len(line) for line in block), default=0) for block in blocks]
    output = []
    for row in range(height):
        pieces = []
        for block, width in zip(blocks, widths):
            pieces.append((block[row] if row < len(block) else "").ljust(width))
        output.append(gap.join(pieces).rstrip())
    return output


def section_rule(title: str) -> str:
    return f"{title}\n{'─' * max(12, len(title))}"


def format_parent_generators(
    record: Dict[str, Any], naming_data: Optional[Dict[str, Any]] = None
) -> str:
    derivations = record.get("GeneratorDerivation", [])
    if not derivations:
        return "No parent-group generator derivation is stored for this label."
    output = [
        "Parent-space-group generators used to construct the SSG momentum symmetry.",
        "Matrices are written in the parent direct-lattice basis.",
        "",
    ]
    parent_space_group = record.get("ParentSpaceGroup")
    for index, item in enumerate(derivations, start=1):
        rotation = item.get("seitz_rotation", identity_matrix())
        if rotation in ("E", "I") and "translation" in item.get("physical_role", ""):
            name = translation_name(item.get("seitz_translation", [[0], [0], [0]]))
        else:
            name = point_operation_name(rotation, parent_space_group, naming_data)
        role = item.get("physical_role", "-")
        output.extend([section_rule(f"{name}   ({role})")])
        output.extend(
            seitz_lines(
                item.get("seitz_rotation", identity_matrix()),
                item.get("seitz_translation", [[0], [0], [0]]),
            )
        )
        output.append(f"det rho({name}) = {scalar_text(item.get('det_rho'))}")
        eta = item.get("EtaP")
        if eta is not None:
            output.append(f"eta_{name} = {compact(eta)}")
        output.append("")
    return "\n".join(output)


def format_momentum_symmetry(
    record: Dict[str, Any],
    magnetic: Optional[Dict[str, Any]] = None,
    naming_data: Optional[Dict[str, Any]] = None,
) -> str:
    elements = record.get("GradedReciprocalGroupElements") or []
    if not elements:
        return "No full graded momentum-symmetry elements are stored for this label."
    output = [
        "Complete SSG momentum symmetry modulo reciprocal-lattice translations.",
        "Each element acts as k -> R_tilde_p k + kappa_p and carries grading s_p.",
        "",
    ]
    names = input_operation_names(magnetic or {}, naming_data)
    standard_space_group = (magnetic or {}).get("ReferenceSpaceGroupNumber")
    for element in elements:
        grading = element.get("Grading", 1 if element.get("Antiunitary") else 0)
        character = "antiunitary" if grading == 1 else "unitary"
        name = names.get(operation_signature(element))
        if name is None:
            name = magnetic_operation_name(element, standard_space_group, naming_data)
        output.append(section_rule(f"{name}   ({character}, s_p = {grading})"))
        action = element.get("MomentumAffineAction", [None, None])
        linear = element.get("MatrixOfRtildeInReciprocalBasis") or action[0]
        shift = element.get("FractionalMomentumShiftKappa") or action[1]
        output.extend(
            side_by_side(
                [
                    labeled_matrix("R_tilde_p", linear),
                    labeled_matrix("kappa_p", column_vector(shift)),
                ]
            )
        )
        output.append("")
    return "\n".join(output)


def format_o3_representation(
    record: Dict[str, Any],
    o3_record: Dict[str, Any],
    naming_data: Optional[Dict[str, Any]] = None,
) -> str:
    alternatives = o3_record.get("Alternatives", [])
    canonical = o3_record.get("CanonicalAlternative", 0)
    alternative = alternatives[canonical] if alternatives and canonical < len(alternatives) else {}
    output = [
        f"Parent space group: {o3_record.get('ParentSpaceGroup', '-')}",
        f"Magnetic order: {o3_record.get('MagneticOrder', '-')}",
        f"O(3) type: {o3_record.get('O3Type', '-')}",
        f"Canonical constituents: {' + '.join(alternative.get('Constituents', [])) or '-'}",
        f"Xiao Appendix-F entry: {o3_record.get('AppendixFDisplay', '-')}",
        "",
        "The following matrices are rho(g) in the canonical three-dimensional spin basis.",
        "",
    ]
    derivations = record.get("GeneratorDerivation", [])
    parent_space_group = record.get("ParentSpaceGroup")
    for index, item in enumerate(derivations, start=1):
        rotation = item.get("seitz_rotation", identity_matrix())
        if rotation in ("E", "I") and "translation" in item.get("physical_role", ""):
            name = translation_name(item.get("seitz_translation", [[0], [0], [0]]))
        else:
            name = point_operation_name(rotation, parent_space_group, naming_data)
        rho = item.get("rho_O3")
        output.append(section_rule(f"rho({name}) in O(3)"))
        output.extend(labeled_matrix(f"rho({name})", rho))
        output.append(f"det rho({name}) = {scalar_text(item.get('det_rho'))}")
        proper = item.get("proper_spin_rotation")
        if proper is not None and proper != rho:
            output.extend(labeled_matrix(f"R_spin({name})", proper))
        output.append("")
    if not derivations:
        output.append("No generator matrices are stored for this label.")
    return "\n".join(output)


def format_kmsg(
    magnetic: Dict[str, Any],
    ordinary: Dict[str, Any],
    naming_data: Optional[Dict[str, Any]] = None,
) -> str:
    output = [
        f"BNS number: {magnetic.get('BNSNumber', '-')}",
        f"UNI number: {magnetic.get('UNINumber', '-')}",
        f"Magnetic type: {magnetic.get('MagneticType', '-')}",
        f"Identification status: {magnetic.get('Status', '-')}",
        f"Ungraded k-space group: No. {ordinary.get('InternationalNumber', '-')} "
        f"{ordinary.get('InternationalSymbol', '-')}",
        "",
        "Coordinate transformation to the standard MG setting:",
    ]
    output.extend(
        side_by_side(
            [
                labeled_matrix("C", magnetic.get("CoordinateMatrix")),
                labeled_matrix("theta", column_vector(magnetic.get("OriginShift", []))),
            ]
        )
    )
    output.extend([f"Convention: {magnetic.get('CoordinateConvention', '-')}", ""])

    input_names = input_operation_names(magnetic, naming_data)
    standard_space_group = magnetic.get("ReferenceSpaceGroupNumber")
    sections = (
        (
            "Input MG operations in the SSG momentum basis",
            magnetic.get("InputOperations", []),
            input_names,
        ),
        (
            "Corresponding operations in the standard BNS setting",
            magnetic.get("StandardPrimitiveOperations", []),
            {},
        ),
    )
    for title, operations, stored_names in sections:
        output.extend([section_rule(title), ""])
        for operation in operations:
            grading = operation.get("Grading", 1 if operation.get("Antiunitary") else 0)
            action = operation.get("MomentumAffineAction", [None, None])
            linear = operation.get("MatrixOfRtildeInReciprocalBasis") or action[0]
            shift = operation.get("FractionalMomentumShiftKappa") or action[1]
            prime = "antiunitary" if grading == 1 else "unitary"
            name = stored_names.get(operation_signature(operation))
            if name is None:
                name = magnetic_operation_name(operation, standard_space_group, naming_data)
            output.append(f"{name}   ({prime}, s_g = {grading})")
            output.extend(seitz_lines(linear, column_vector(shift), label="{R_tilde_p | kappa_p}"))
            output.append("")
    return "\n".join(output)


class SSGDatabase:
    """Read-only access layer shared by the GUI and command-line checks."""

    def __init__(self, path: Path | str):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Database file not found: {self.path}")
        uri = self.path.as_uri() + "?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only = ON")
        application_id = self.connection.execute("PRAGMA application_id").fetchone()[0]
        schema_version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if application_id != EXPECTED_APPLICATION_ID:
            self.close()
            raise ValueError("This is not an SSG reciprocal-symmetry database")
        if schema_version != EXPECTED_SCHEMA_VERSION:
            self.close()
            raise ValueError(
                f"Unsupported database schema {schema_version}; "
                f"expected {EXPECTED_SCHEMA_VERSION}"
            )
        self._point_operation_names: Optional[Dict[str, Any]] = None

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None

    def metadata(self) -> Dict[str, str]:
        return dict(self.connection.execute("SELECT key, value FROM metadata"))

    def point_operation_names(self) -> Dict[str, Any]:
        if self._point_operation_names is None:
            row = self.connection.execute(
                "SELECT record_zlib FROM point_operation_names WHERE record_id = 1"
            ).fetchone()
            self._point_operation_names = unpack_json(row[0]) if row else {}
        return self._point_operation_names

    def search_ssg(self, query: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        query = query.strip()
        if query:
            rows = self.connection.execute(
                """
                SELECT label, parent_space_group, magnetic_order, status,
                       nonsymmorphic, translation_projectivity, bns_number,
                       magnetic_type
                FROM ssg_records
                WHERE label = ? OR label LIKE ? OR bns_number = ?
                ORDER BY CASE WHEN label = ? THEN 0 ELSE 1 END,
                         parent_space_group, label
                LIMIT ?
                """,
                (query, query + "%", query, query, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT label, parent_space_group, magnetic_order, status,
                       nonsymmorphic, translation_projectivity, bns_number,
                       magnetic_type
                FROM ssg_records
                ORDER BY parent_space_group, label LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_ssg(self, label: str) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            """
            SELECT s.*, o.record_zlib AS ordinary_zlib,
                   m.record_zlib AS magnetic_zlib
            FROM ssg_records AS s
            LEFT JOIN ordinary_space_group_classes AS o
              ON o.class_key = s.ordinary_class_key
            LEFT JOIN magnetic_space_group_classes AS m
              ON m.class_key = s.magnetic_class_key
            WHERE s.label = ?
            """,
            (label,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["ReciprocalRecord"] = unpack_json(result.pop("reciprocal_record_zlib"))
        result["O3Record"] = unpack_json(result.pop("o3_record_zlib"))
        result["OrdinarySpaceGroup"] = unpack_json(result.pop("ordinary_zlib"))
        result["MagneticSpaceGroup"] = unpack_json(result.pop("magnetic_zlib"))
        return result

    def lookup_bns(self, bns_number: str) -> Dict[str, Any]:
        summary = self.connection.execute(
            "SELECT * FROM msg_realization_summary WHERE bns_number = ?",
            (bns_number.strip(),),
        ).fetchone()
        labels = self.connection.execute(
            """
            SELECT r.label, r.is_example, s.parent_space_group,
                   s.magnetic_order, s.nonsymmorphic
            FROM msg_realizations AS r
            JOIN ssg_records AS s ON s.label = r.label
            WHERE r.bns_number = ?
            ORDER BY r.is_example DESC, s.parent_space_group, r.label
            """,
            (bns_number.strip(),),
        ).fetchall()
        if summary is None:
            return {"Summary": None, "Labels": []}
        summary_dict = dict(summary)
        summary_dict["Record"] = unpack_json(summary_dict.pop("record_zlib"))
        return {"Summary": summary_dict, "Labels": [dict(row) for row in labels]}

    def verify(self) -> Dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "Integrity": integrity,
            "SSGRecords": self.connection.execute(
                "SELECT COUNT(*) FROM ssg_records"
            ).fetchone()[0],
            "O3Records": self.connection.execute(
                "SELECT COUNT(*) FROM ssg_records WHERE o3_record_zlib IS NOT NULL"
            ).fetchone()[0],
            "OrdinaryClasses": self.connection.execute(
                "SELECT COUNT(*) FROM ordinary_space_group_classes"
            ).fetchone()[0],
            "MagneticClasses": self.connection.execute(
                "SELECT COUNT(*) FROM magnetic_space_group_classes"
            ).fetchone()[0],
            "MSGRealizationLinks": self.connection.execute(
                "SELECT COUNT(*) FROM msg_realizations"
            ).fetchone()[0],
        }


def default_database_path() -> Optional[Path]:
    directory = Path(__file__).resolve().parent
    search_directories: List[Path] = []

    # A frozen application keeps the database beside its executable. PyInstaller
    # places __file__ in its internal bundle directory, so it cannot be the only
    # location checked on Windows.
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        if executable.parent.name == "MacOS" and executable.parent.parent.name == "Contents":
            search_directories.append(executable.parents[3])
        else:
            search_directories.append(executable.parent)
    if directory.name == "Resources" and directory.parent.name == "Contents":
        search_directories.append(directory.parents[2])
    search_directories.extend((directory / "dist", directory))

    seen = set()
    for candidate_directory in search_directories:
        resolved = candidate_directory.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates = sorted(resolved.glob("SSGReciprocalOffline-*.sqlite"))
        if candidates:
            return candidates[-1]
    return None


def choose_database_path() -> Optional[Path]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    selected = filedialog.askopenfilename(
        title="Choose the SSG reciprocal-symmetry database",
        filetypes=(("SSG SQLite database", "*.sqlite"), ("All files", "*")),
    )
    root.destroy()
    return Path(selected) if selected else None


def add_labeled_value(parent: Any, row: int, label: str, value: str) -> None:
    import tkinter as tk
    from tkinter import ttk

    ttk.Label(parent, text=label + ":", style="Field.TLabel").grid(
        row=row, column=0, sticky="ne", padx=(0, 10), pady=3
    )
    widget = tk.Text(parent, height=max(1, min(4, value.count("\n") + 1)), wrap="word")
    widget.insert("1.0", value)
    widget.configure(state="disabled", relief="flat", background=parent.cget("background"))
    widget.grid(row=row, column=1, sticky="ew", pady=3)


class SSGDatabaseGUI:
    def __init__(self, database: SSGDatabase):
        import tkinter as tk
        from tkinter import ttk

        configure_windows_dpi()
        if tk.TkVersion < 8.6:
            raise RuntimeError(
                "The desktop GUI requires Tcl/Tk 8.6 or newer. "
                "Use the packaged application or a current Python distribution."
            )

        self.tk = tk
        self.ttk = ttk
        self.database = database
        self.root = tk.Tk()
        self.root.title("SSG Reciprocal Symmetry Database")
        width = min(1500, max(1180, self.root.winfo_screenwidth() - 100))
        height = min(850, max(680, self.root.winfo_screenheight() - 120))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1180, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        style = ttk.Style(self.root)
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
        style.configure("Title.TLabel", font=("TkDefaultFont", 17, "bold"))
        style.configure("Section.TLabel", font=("TkDefaultFont", 12, "bold"))
        style.configure("Field.TLabel", font=("TkDefaultFont", 10, "bold"))
        style.configure("Treeview", rowheight=24)

        header = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        header.pack(fill="x")
        ttk.Label(header, text="SSG Reciprocal Symmetry Database", style="Title.TLabel").pack(
            side="left"
        )
        metadata = database.metadata()
        ttk.Label(
            header,
            text=f"v{metadata.get('database_version', '?')}  |  read-only",
        ).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._build_ssg_tab()
        self._build_msg_tab()
        self._build_info_tab()
        self.search_ssg()

    def _build_ssg_tab(self) -> None:
        ttk = self.ttk
        pane = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(pane, text="SSG lookup")

        search = ttk.Frame(pane)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="SSG label or BNS number:").pack(side="left")
        self.ssg_query = self.tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.ssg_query, width=28)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self.search_ssg())
        ttk.Button(search, text="Search", command=self.search_ssg).pack(side="left")
        ttk.Button(search, text="Clear", command=self.clear_ssg_search).pack(
            side="left", padx=(6, 0)
        )
        self.ssg_status = ttk.Label(search, text="")
        self.ssg_status.pack(side="right")

        horizontal = ttk.Panedwindow(pane, orient="horizontal")
        horizontal.pack(fill="both", expand=True)
        left = ttk.Frame(horizontal)
        right = ttk.Frame(horizontal)
        horizontal.add(left, weight=2)
        horizontal.add(right, weight=5)

        columns = ("label", "order", "nsg", "bns")
        self.ssg_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for column, text, width in (
            ("label", "SSG label", 140),
            ("order", "Order", 95),
            ("nsg", "k-NSG", 60),
            ("bns", "BNS", 75),
        ):
            self.ssg_tree.heading(column, text=text)
            self.ssg_tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.ssg_tree.yview)
        self.ssg_tree.configure(yscrollcommand=scroll.set)
        self.ssg_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.ssg_tree.bind("<<TreeviewSelect>>", self.show_selected_ssg)

        self.detail_tabs = ttk.Notebook(right)
        self.detail_tabs.pack(fill="both", expand=True)
        self.overview_text = self._text_tab("Overview")
        self.generators_text = self._text_tab("Parent group generator")
        self.elements_text = self._text_tab("SSG momentum symmetry (R_tilde_p, κ_p, s_p)")
        self.o3_text = self._text_tab("SSG O(3) representation")
        self.identification_text = self._text_tab("MG")
        self.raw_text = self._text_tab("Raw JSON")

    def _text_tab(self, title: str) -> Any:
        frame = self.ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(frame, text=title)
        text = self.tk.Text(frame, wrap="none", font="TkFixedFont", padx=10, pady=10)
        y_scroll = self.ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        x_scroll = self.ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text.configure(state="disabled")
        return text

    def _set_text(self, widget: Any, value: Any) -> None:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def clear_ssg_search(self) -> None:
        self.ssg_query.set("")
        self.search_ssg()

    def search_ssg(self) -> None:
        rows = self.database.search_ssg(self.ssg_query.get())
        self.ssg_tree.delete(*self.ssg_tree.get_children())
        for row in rows:
            self.ssg_tree.insert(
                "",
                "end",
                iid=row["label"],
                values=(
                    row["label"],
                    row["magnetic_order"] or "-",
                    "Yes" if row["nonsymmorphic"] else "No",
                    row["bns_number"] or "-",
                ),
            )
        suffix = " (first 500)" if len(rows) == 500 else ""
        self.ssg_status.configure(text=f"{len(rows)} result(s){suffix}")
        if rows:
            self.ssg_tree.selection_set(rows[0]["label"])
            self.ssg_tree.focus(rows[0]["label"])
            self.show_selected_ssg()

    def show_selected_ssg(self, _event: Any = None) -> None:
        selection = self.ssg_tree.selection()
        if not selection:
            return
        data = self.database.get_ssg(selection[0])
        if data is None:
            return
        record = data["ReciprocalRecord"]
        overview = {
            "SSG label": data["label"],
            "Parent space group": data["parent_space_group"],
            "Magnetic order": data["magnetic_order"],
            "Status": data["status"],
            "Momentum-space nonsymmorphic": bool(data["nonsymmorphic"]),
            "Translation projectivity": data["translation_projectivity"],
            "BNS number": data["bns_number"],
            "Magnetic type": data["magnetic_type"],
            "ZL0": record.get("ZL0"),
            "ZL0 convention": record.get("ZL0Convention"),
            "Reason": record.get("Reason"),
        }
        overview_lines = []
        for key, value in overview.items():
            if key == "ZL0" and isinstance(value, list):
                overview_lines.extend(labeled_matrix("Z_{L_0}", value))
            else:
                overview_lines.append(f"{key}: {compact(value)}")
        overview_text = "\n".join(overview_lines)
        self._set_text(self.overview_text, overview_text)
        naming_data = self.database.point_operation_names()
        self._set_text(
            self.generators_text, format_parent_generators(record, naming_data)
        )
        self._set_text(
            self.elements_text,
            format_momentum_symmetry(record, data["MagneticSpaceGroup"], naming_data),
        )
        self._set_text(
            self.o3_text,
            format_o3_representation(record, data["O3Record"], naming_data),
        )
        self._set_text(
            self.identification_text,
            format_kmsg(
                data["MagneticSpaceGroup"], data["OrdinarySpaceGroup"], naming_data
            ),
        )
        self._set_text(
            self.raw_text,
            {"ReciprocalRecord": record, "O3Record": data["O3Record"]},
        )

    def _build_msg_tab(self) -> None:
        ttk = self.ttk
        pane = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(pane, text="MG reverse lookup")
        search = ttk.Frame(pane)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="MG BNS number:").pack(side="left")
        self.bns_query = self.tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.bns_query, width=18)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self.search_bns())
        ttk.Button(search, text="Find SSG realizations", command=self.search_bns).pack(side="left")

        self.msg_summary = self.tk.Text(pane, height=8, wrap="word", font="TkFixedFont")
        self.msg_summary.pack(fill="x", pady=(0, 8))
        self.msg_summary.configure(state="disabled")
        columns = ("label", "example", "parent", "order", "nsg")
        self.msg_tree = ttk.Treeview(pane, columns=columns, show="headings")
        for column, text, width in (
            ("label", "SSG label", 180),
            ("example", "Example", 70),
            ("parent", "Parent SG", 85),
            ("order", "Magnetic order", 130),
            ("nsg", "k-NSG", 70),
        ):
            self.msg_tree.heading(column, text=text)
            self.msg_tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(pane, orient="vertical", command=self.msg_tree.yview)
        self.msg_tree.configure(yscrollcommand=scroll.set)
        self.msg_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def search_bns(self) -> None:
        result = self.database.lookup_bns(self.bns_query.get())
        self.msg_tree.delete(*self.msg_tree.get_children())
        summary = result["Summary"]
        if summary is None:
            self._set_text(self.msg_summary, "No MG record found for this BNS number.")
            return
        display = {
            "BNS number": summary["bns_number"],
            "UNI number": summary["uni_number"],
            "Magnetic type": summary["magnetic_type"],
            "Nonsymmorphic MG": bool(summary["nonsymmorphic"]),
            "Realized by catalogued SSG": bool(summary["realized"]),
            "SSG count": summary["ssg_count"],
            "Example": summary["example_label"],
        }
        self._set_text(
            self.msg_summary,
            "\n".join(f"{key}: {compact(value)}" for key, value in display.items()),
        )
        for row in result["Labels"]:
            self.msg_tree.insert(
                "",
                "end",
                values=(
                    row["label"],
                    "Yes" if row["is_example"] else "",
                    row["parent_space_group"],
                    row["magnetic_order"] or "-",
                    "Yes" if row["nonsymmorphic"] else "No",
                ),
            )

    def _build_info_tab(self) -> None:
        pane = self.ttk.Frame(self.notebook, padding=14)
        self.notebook.add(pane, text="Database info")
        info = {
            "File": str(self.database.path),
            **self.database.metadata(),
            **self.database.verify(),
        }
        text = self.tk.Text(pane, wrap="word", font="TkFixedFont", padx=10, pady=10)
        text.insert("1.0", "\n".join(f"{key}: {compact(value)}" for key, value in info.items()))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

    def close(self) -> None:
        self.database.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="path to the SQLite database")
    parser.add_argument("--check", action="store_true", help="verify the database and exit")
    parser.add_argument(
        "--gui-smoke",
        action="store_true",
        help="construct and render the GUI once, report widget counts, and exit",
    )
    parser.add_argument("--label", help="print one SSG record as JSON and exit")
    parser.add_argument("--bns", help="print all SSG realizations for one BNS number")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = args.database or default_database_path()
    if path is None and not (args.check or args.label or args.bns or args.gui_smoke):
        path = choose_database_path()
    if path is None:
        print(
            "No database found. Pass --database /path/to/SSGReciprocalOffline.sqlite",
            file=sys.stderr,
        )
        return 2
    try:
        database = SSGDatabase(path)
        if args.check:
            print(json.dumps(database.verify(), indent=2, sort_keys=True))
            database.close()
            return 0
        if args.label:
            print(json.dumps(database.get_ssg(args.label), ensure_ascii=False, indent=2))
            database.close()
            return 0
        if args.bns:
            print(json.dumps(database.lookup_bns(args.bns), ensure_ascii=False, indent=2))
            database.close()
            return 0
        gui = SSGDatabaseGUI(database)
        if args.gui_smoke:
            gui.root.update_idletasks()

            def descendants(widget: Any) -> Iterable[Any]:
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            widgets = list(descendants(gui.root))
            print(
                json.dumps(
                    {
                        "Window": gui.root.title(),
                        "Width": gui.root.winfo_width(),
                        "Height": gui.root.winfo_height(),
                        "Widgets": len(widgets),
                        "Treeviews": sum(
                            1 for widget in widgets if widget.winfo_class() == "Treeview"
                        ),
                        "Notebooks": sum(
                            1 for widget in widgets if widget.winfo_class() == "TNotebook"
                        ),
                        "Tabs": [
                            widget.tab(tab, "text")
                            for widget in widgets
                            if widget.winfo_class() == "TNotebook"
                            for tab in widget.tabs()
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            gui.close()
            return 0
        gui.run()
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
