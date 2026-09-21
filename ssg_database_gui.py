#!/usr/bin/env python3
"""Local read-only GUI for the SSG reciprocal-symmetry database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


EXPECTED_APPLICATION_ID = 0x53534752
EXPECTED_SCHEMA_VERSION = 1


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


class SSGDatabase:
    """Read-only access layer shared by the GUI and command-line checks."""

    def __init__(self, path: Path | str):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Database file not found: {self.path}")
        uri = f"file:{self.path.as_posix()}?mode=ro"
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

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None

    def metadata(self) -> Dict[str, str]:
        return dict(self.connection.execute("SELECT key, value FROM metadata"))

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
    candidates = sorted((directory / "dist").glob("SSGReciprocalOffline-*.sqlite"))
    candidates += sorted(directory.glob("SSGReciprocalOffline-*.sqlite"))
    if directory.name == "Resources" and directory.parent.name == "Contents":
        app_parent = directory.parents[2]
        candidates += sorted(app_parent.glob("SSGReciprocalOffline-*.sqlite"))
    executable = Path(sys.executable).resolve()
    if executable.parent.name == "MacOS" and executable.parent.parent.name == "Contents":
        app_parent = executable.parents[3]
        candidates += sorted(app_parent.glob("SSGReciprocalOffline-*.sqlite"))
    return candidates[-1] if candidates else None


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

        if tk.TkVersion < 8.6:
            raise RuntimeError(
                "The desktop GUI requires Tcl/Tk 8.6 or newer. "
                "The macOS system Python ships an obsolete Tk 8.5; use the "
                "packaged application or a current Python distribution."
            )

        self.tk = tk
        self.ttk = ttk
        self.database = database
        self.root = tk.Tk()
        self.root.title("SSG Reciprocal Symmetry Database")
        self.root.geometry("1260x780")
        self.root.minsize(960, 620)
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
        self.generators_text = self._text_tab("Generators")
        self.elements_text = self._text_tab("Full graded group")
        self.o3_text = self._text_tab("O(3) representation")
        self.identification_text = self._text_tab("Standard groups")
        self.raw_text = self._text_tab("Raw JSON")

    def _text_tab(self, title: str) -> Any:
        frame = self.ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(frame, text=title)
        text = self.tk.Text(frame, wrap="none", font=("Menlo", 11), padx=10, pady=10)
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
            "LB": record.get("LB"),
            "LB convention": record.get("LBConvention"),
            "Reason": record.get("Reason"),
        }
        overview_text = "\n".join(f"{key}: {compact(value)}" for key, value in overview.items())
        self._set_text(self.overview_text, overview_text)
        self._set_text(self.generators_text, record.get("ReciprocalGenerators", []))
        self._set_text(
            self.elements_text,
            record.get("GradedReciprocalGroupElements")
            or record.get("ReciprocalMomentumGroupElements")
            or [],
        )
        self._set_text(self.o3_text, data["O3Record"])
        self._set_text(
            self.identification_text,
            {
                "OrdinarySpaceGroup": data["OrdinarySpaceGroup"],
                "MagneticSpaceGroup": data["MagneticSpaceGroup"],
            },
        )
        self._set_text(
            self.raw_text,
            {"ReciprocalRecord": record, "O3Record": data["O3Record"]},
        )

    def _build_msg_tab(self) -> None:
        ttk = self.ttk
        pane = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(pane, text="MSG reverse lookup")
        search = ttk.Frame(pane)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="MSG BNS number:").pack(side="left")
        self.bns_query = self.tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.bns_query, width=18)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self.search_bns())
        ttk.Button(search, text="Find SSG realizations", command=self.search_bns).pack(side="left")

        self.msg_summary = self.tk.Text(pane, height=8, wrap="word", font=("Menlo", 11))
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
            self._set_text(self.msg_summary, "No MSG record found for this BNS number.")
            return
        display = {
            "BNS number": summary["bns_number"],
            "UNI number": summary["uni_number"],
            "Magnetic type": summary["magnetic_type"],
            "Nonsymmorphic MSG": bool(summary["nonsymmorphic"]),
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
        text = self.tk.Text(pane, wrap="word", font=("Menlo", 11), padx=10, pady=10)
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
