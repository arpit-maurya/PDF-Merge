"""
gui.py

Modern dark-themed CustomTkinter GUI for PDF Pair Merger.

This module is responsible only for presentation and user interaction. All
PDF manipulation is delegated to :mod:`pdf_engine`. The heavy PDF merge
work always runs on a background thread so the interface never freezes,
and progress/status/errors are marshalled back to the Tk main thread via
``after()``.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import ClassVar, List, Optional

import customtkinter as ctk

from pdf_engine import (
    MergeError,
    MergeSettings,
    Orientation,
    PaperSize,
    PDFPairMerger,
    ScaleMode,
)

# --------------------------------------------------------------------------
# Optional drag & drop support (tkinterdnd2)
# --------------------------------------------------------------------------

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND_IMPORT_OK = True
except ImportError:  # pragma: no cover - exercised only when dependency missing
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]
    _DND_IMPORT_OK = False


if _DND_IMPORT_OK:

    class _AppBase(ctk.CTk, TkinterDnD.DnDWrapper):
        """Root window base class that mixes in tkinterdnd2 drag-and-drop support."""

else:

    class _AppBase(ctk.CTk):  # type: ignore[no-redef]
        """Root window base class used when tkinterdnd2 is not installed."""


# --------------------------------------------------------------------------
# Persistent configuration
# --------------------------------------------------------------------------

@dataclass
class AppConfig:
    """User preferences persisted to a JSON file between application runs."""

    last_output_dir: str = field(default_factory=lambda: str(Path.home()))
    paper_size: str = PaperSize.A4.value
    orientation: str = Orientation.LANDSCAPE.value
    gap_mm: float = 10.0
    margin_mm: float = 10.0
    scale_mode: str = ScaleMode.FIT.value
    window_width: int = 1000
    window_height: int = 760

    CONFIG_PATH: ClassVar[Path] = Path.home() / ".pdf_pair_merger" / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        """Load configuration from disk, falling back to defaults on any error."""
        try:
            if cls.CONFIG_PATH.is_file():
                with open(cls.CONFIG_PATH, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                valid_fields = {f.name for f in dataclasses.fields(cls)}
                filtered = {key: value for key, value in raw.items() if key in valid_fields}
                return cls(**filtered)
        except Exception:
            pass
        return cls()

    def save(self) -> None:
        """Persist the current configuration to disk. Failures are silently ignored."""
        try:
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(dataclasses.asdict(self), handle, indent=2)
        except Exception:
            pass


# --------------------------------------------------------------------------
# File list model
# --------------------------------------------------------------------------

@dataclass
class FileListItem:
    """A single PDF entry displayed in the selection list."""

    path: str
    page_count: int

    @property
    def filename(self) -> str:
        """Base file name (without directory) for display purposes."""
        return os.path.basename(self.path)


# --------------------------------------------------------------------------
# Main application window
# --------------------------------------------------------------------------

class PDFPairMergerApp(_AppBase):
    """The PDF Pair Merger main window."""

    PAPER_SIZE_VALUES: List[str] = [size.value for size in PaperSize]
    ORIENTATION_VALUES: List[str] = [o.value for o in Orientation]
    SCALE_MODE_VALUES: List[str] = [m.value for m in ScaleMode]

    def __init__(self) -> None:
        """Build the window, all widgets, and load any saved configuration."""
        super().__init__()

        self.app_config: AppConfig = AppConfig.load()

        self.files: List[FileListItem] = []
        self.selected_index: Optional[int] = None
        self._processing: bool = False
        self.dnd_enabled: bool = False

        self._init_dnd()
        self._configure_window()
        self._build_fonts()
        self._build_layout()
        self._apply_loaded_config()
        self._rebuild_file_list_ui()
        self._update_control_buttons_state()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----------------------------------------------------------------------
    # Setup
    # ----------------------------------------------------------------------

    def _init_dnd(self) -> None:
        """Initialize tkinterdnd2 support on the root window, if available."""
        if not _DND_IMPORT_OK:
            return
        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.dnd_enabled = True
        except Exception:
            self.dnd_enabled = False

    def _configure_window(self) -> None:
        """Set window title, size, and minimum size."""
        self.title("PDF Pair Merger")
        self.minsize(900, 680)
        self.geometry(f"{self.app_config.window_width}x{self.app_config.window_height}")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def _build_fonts(self) -> None:
        """Create the CTkFont instances used throughout the interface."""
        self.font_title = ctk.CTkFont(size=24, weight="bold")
        self.font_subtitle = ctk.CTkFont(size=13)
        self.font_section = ctk.CTkFont(size=15, weight="bold")
        self.font_bold = ctk.CTkFont(size=13, weight="bold")
        self.font_normal = ctk.CTkFont(size=13)
        self.font_small = ctk.CTkFont(size=11)
        self.font_button = ctk.CTkFont(size=13, weight="bold")

    def _build_layout(self) -> None:
        """Construct the full widget tree."""
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        self._build_header(outer)

        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self._build_file_panel(body)
        self._build_settings_panel(body)

        self._build_action_panel(outer)

    def _build_header(self, parent: ctk.CTkFrame) -> None:
        """Build the title/subtitle header area."""
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(header, text="PDF Pair Merger", font=self.font_title, anchor="w")
        title.grid(row=0, column=0, sticky="w")

        subtitle = ctk.CTkLabel(
            header,
            text="Combine any number of PDFs, two at a time, side by side on printable pages.",
            font=self.font_subtitle,
            text_color="gray60",
            anchor="w",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

    # -- left panel: file list ----------------------------------------------

    def _build_file_panel(self, parent: ctk.CTkFrame) -> None:
        """Build the left-hand panel: add/remove/reorder PDF files."""
        panel = ctk.CTkFrame(parent, corner_radius=12)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)
        self.file_panel_frame = panel

        header_row = ctk.CTkFrame(panel, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header_row, text="PDF Files", font=self.font_section, anchor="w").grid(
            row=0, column=0, sticky="w"
        )

        self.add_button = ctk.CTkButton(
            header_row,
            text="+  Add PDFs",
            font=self.font_button,
            corner_radius=8,
            command=self._add_pdfs,
        )
        self.add_button.grid(row=0, column=1, sticky="e")

        hint_text = "Drag & drop PDF files anywhere in this panel, or use the button above."
        if not self.dnd_enabled:
            hint_text = "Use the button above to add PDF files (drag & drop unavailable)."
        self.drop_hint_label = ctk.CTkLabel(
            panel, text=hint_text, font=self.font_small, text_color="gray55", anchor="w"
        )
        self.drop_hint_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        self.file_list_scrollable = ctk.CTkScrollableFrame(panel, corner_radius=8, fg_color=("gray92", "gray14"))
        self.file_list_scrollable.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.file_list_scrollable.grid_columnconfigure(0, weight=1)

        controls_row = ctk.CTkFrame(panel, fg_color="transparent")
        controls_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        controls_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.move_up_button = ctk.CTkButton(
            controls_row,
            text="\u2191  Move Up",
            font=self.font_normal,
            corner_radius=8,
            fg_color="gray30",
            hover_color="gray25",
            command=lambda: self._move_selected(-1),
        )
        self.move_up_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.move_down_button = ctk.CTkButton(
            controls_row,
            text="\u2193  Move Down",
            font=self.font_normal,
            corner_radius=8,
            fg_color="gray30",
            hover_color="gray25",
            command=lambda: self._move_selected(1),
        )
        self.move_down_button.grid(row=0, column=1, sticky="ew", padx=4)

        self.remove_button = ctk.CTkButton(
            controls_row,
            text="\u2716  Remove",
            font=self.font_normal,
            corner_radius=8,
            fg_color="#8B2E2E",
            hover_color="#6E2424",
            command=self._remove_selected,
        )
        self.remove_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        self._register_drop_target(panel)
        self._register_drop_target(self.file_list_scrollable)

    # -- right panel: settings ------------------------------------------------

    def _build_settings_panel(self, parent: ctk.CTkFrame) -> None:
        """Build the right-hand panel: paper size, orientation, gap, margins, scale, output."""
        panel = ctk.CTkFrame(parent, corner_radius=12)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="Layout Settings", font=self.font_section, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(16, 10)
        )

        settings_grid = ctk.CTkFrame(panel, fg_color="transparent")
        settings_grid.grid(row=1, column=0, sticky="ew", padx=16)
        settings_grid.grid_columnconfigure(0, weight=1)

        self.paper_size_var = ctk.StringVar(value=PaperSize.A4.value)
        self.orientation_var = ctk.StringVar(value=Orientation.LANDSCAPE.value)
        self.gap_var = ctk.StringVar(value="10")
        self.margin_var = ctk.StringVar(value="10")
        self.scale_mode_var = ctk.StringVar(value=ScaleMode.FIT.value)

        self.paper_size_menu = self._add_option_row(
            settings_grid, 0, "Paper Size", self.paper_size_var, self.PAPER_SIZE_VALUES
        )
        self.orientation_menu = self._add_option_row(
            settings_grid, 1, "Orientation", self.orientation_var, self.ORIENTATION_VALUES
        )
        self.gap_entry = self._add_entry_row(settings_grid, 2, "Gap (mm)", self.gap_var)
        self.margin_entry = self._add_entry_row(settings_grid, 3, "Margins (mm)", self.margin_var)
        self.scale_menu = self._add_option_row(
            settings_grid, 4, "Scale", self.scale_mode_var, self.SCALE_MODE_VALUES
        )

        # -- output file section --
        ctk.CTkLabel(panel, text="Output File", font=self.font_section, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=16, pady=(20, 8)
        )

        output_row = ctk.CTkFrame(panel, fg_color="transparent")
        output_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        output_row.grid_columnconfigure(0, weight=1)

        default_output = os.path.join(self.app_config.last_output_dir, "merged_output.pdf")
        self.output_var = ctk.StringVar(value=default_output)
        self.output_entry = ctk.CTkEntry(
            output_row, textvariable=self.output_var, font=self.font_normal, corner_radius=8
        )
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.browse_button = ctk.CTkButton(
            output_row,
            text="Browse",
            font=self.font_button,
            corner_radius=8,
            width=90,
            command=self._browse_output,
        )
        self.browse_button.grid(row=0, column=1, sticky="e")

    def _add_option_row(
        self, parent: ctk.CTkFrame, row: int, label_text: str, variable: ctk.StringVar, values: List[str]
    ) -> ctk.CTkOptionMenu:
        """Add a labeled dropdown row and return the created CTkOptionMenu."""
        ctk.CTkLabel(parent, text=label_text, font=self.font_bold, anchor="w").grid(
            row=row * 2, column=0, sticky="w", pady=(8 if row else 0, 2)
        )
        menu = ctk.CTkOptionMenu(
            parent, values=values, variable=variable, font=self.font_normal, corner_radius=8
        )
        menu.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(0, 4))
        return menu

    def _add_entry_row(
        self, parent: ctk.CTkFrame, row: int, label_text: str, variable: ctk.StringVar
    ) -> ctk.CTkEntry:
        """Add a labeled numeric entry row and return the created CTkEntry."""
        ctk.CTkLabel(parent, text=label_text, font=self.font_bold, anchor="w").grid(
            row=row * 2, column=0, sticky="w", pady=(8, 2)
        )
        entry = ctk.CTkEntry(parent, textvariable=variable, font=self.font_normal, corner_radius=8)
        entry.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(0, 4))
        return entry

    # -- bottom panel: generate / progress -----------------------------------

    def _build_action_panel(self, parent: ctk.CTkFrame) -> None:
        """Build the bottom action bar: generate button, progress bar, status label."""
        panel = ctk.CTkFrame(parent, corner_radius=12)
        panel.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        panel.grid_columnconfigure(0, weight=1)

        self.generate_button = ctk.CTkButton(
            panel,
            text="Generate PDF",
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=10,
            height=44,
            command=self._on_generate_clicked,
        )
        self.generate_button.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))

        self.progress_bar = ctk.CTkProgressBar(panel, corner_radius=6, height=14)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.progress_bar.set(0)

        self.status_var = ctk.StringVar(value="Ready. Add PDF files to begin.")
        self.status_label = ctk.CTkLabel(
            panel, textvariable=self.status_var, font=self.font_small, text_color="gray60", anchor="w"
        )
        self.status_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))

    # ----------------------------------------------------------------------
    # Config <-> widgets
    # ----------------------------------------------------------------------

    def _apply_loaded_config(self) -> None:
        """Push values from the loaded :class:`AppConfig` into the relevant widgets."""
        if self.app_config.paper_size in self.PAPER_SIZE_VALUES:
            self.paper_size_var.set(self.app_config.paper_size)
        if self.app_config.orientation in self.ORIENTATION_VALUES:
            self.orientation_var.set(self.app_config.orientation)
        if self.app_config.scale_mode in self.SCALE_MODE_VALUES:
            self.scale_mode_var.set(self.app_config.scale_mode)
        self.gap_var.set(self._format_mm(self.app_config.gap_mm))
        self.margin_var.set(self._format_mm(self.app_config.margin_mm))

    @staticmethod
    def _format_mm(value: float) -> str:
        """Format a millimeter value for display, dropping a trailing '.0'."""
        if float(value).is_integer():
            return str(int(value))
        return str(value)

    def _persist_config(self) -> None:
        """Copy current widget state back into :attr:`app_config` and save it to disk."""
        self.app_config.paper_size = self.paper_size_var.get()
        self.app_config.orientation = self.orientation_var.get()
        self.app_config.scale_mode = self.scale_mode_var.get()
        try:
            self.app_config.gap_mm = float(self.gap_var.get())
        except ValueError:
            pass
        try:
            self.app_config.margin_mm = float(self.margin_var.get())
        except ValueError:
            pass
        self.app_config.window_width = self.winfo_width()
        self.app_config.window_height = self.winfo_height()
        self.app_config.save()

    def _on_close(self) -> None:
        """Handle the window close event: persist settings, then destroy the window."""
        self._persist_config()
        self.destroy()

    # ----------------------------------------------------------------------
    # Drag & drop
    # ----------------------------------------------------------------------

    def _register_drop_target(self, widget: ctk.CTkBaseClass) -> None:
        """Register ``widget`` as a PDF drop target, if drag & drop is available."""
        if not self.dnd_enabled:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event) -> None:
        """Handle files dropped onto the file panel."""
        try:
            raw_paths = self.tk.splitlist(event.data)
        except Exception:
            raw_paths = [event.data]

        pdf_paths = [p for p in raw_paths if p.lower().endswith(".pdf")]
        if not pdf_paths:
            messagebox.showwarning("No PDFs found", "Please drop one or more .pdf files.")
            return
        self._add_files(pdf_paths)

    # ----------------------------------------------------------------------
    # File list management
    # ----------------------------------------------------------------------

    def _add_pdfs(self) -> None:
        """Open a file picker dialog and add the chosen PDFs to the list."""
        paths = filedialog.askopenfilenames(
            title="Select PDF files",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not paths:
            return
        self._add_files(list(paths))

    def _add_files(self, paths: List[str]) -> None:
        """Validate and append a list of PDF file paths to :attr:`files`."""
        added = 0
        failed: List[str] = []

        for path in paths:
            if not path.lower().endswith(".pdf"):
                continue
            try:
                with self._open_pdf_for_inspection(path) as doc:
                    page_count = doc.page_count
                if page_count == 0:
                    failed.append(f"{os.path.basename(path)} (no pages)")
                    continue
            except Exception:
                failed.append(os.path.basename(path))
                continue

            self.files.append(FileListItem(path=path, page_count=page_count))
            added += 1

        if added:
            self.selected_index = len(self.files) - 1
            self._rebuild_file_list_ui()
            self._update_control_buttons_state()
            self.status_var.set(f"Added {added} file(s). Total: {len(self.files)}.")

        if failed:
            messagebox.showwarning(
                "Some files could not be added",
                "The following files could not be opened as valid PDFs:\n\n" + "\n".join(failed),
            )

    @staticmethod
    def _open_pdf_for_inspection(path: str):
        """Open a PDF just long enough to read its page count."""
        import fitz  # local import keeps GUI module import time minimal

        return fitz.open(path)

    def _select_row(self, index: int) -> None:
        """Mark ``index`` as the selected row and refresh the list's visuals."""
        if self._processing:
            return
        self.selected_index = index
        self._rebuild_file_list_ui()
        self._update_control_buttons_state()

    def _move_selected(self, direction: int) -> None:
        """Move the selected file up (-1) or down (+1) in the list."""
        if self.selected_index is None:
            return
        new_index = self.selected_index + direction
        if not (0 <= new_index < len(self.files)):
            return
        self.files[self.selected_index], self.files[new_index] = (
            self.files[new_index],
            self.files[self.selected_index],
        )
        self.selected_index = new_index
        self._rebuild_file_list_ui()
        self._update_control_buttons_state()

    def _remove_selected(self) -> None:
        """Remove the currently selected file from the list."""
        if self.selected_index is None:
            return
        del self.files[self.selected_index]
        if not self.files:
            self.selected_index = None
        elif self.selected_index >= len(self.files):
            self.selected_index = len(self.files) - 1
        self._rebuild_file_list_ui()
        self._update_control_buttons_state()
        self.status_var.set(f"Total: {len(self.files)} file(s).")

    def _rebuild_file_list_ui(self) -> None:
        """Recreate the visible rows inside the scrollable file list from :attr:`files`."""
        for widget in self.file_list_scrollable.winfo_children():
            widget.destroy()

        if not self.files:
            placeholder = ctk.CTkLabel(
                self.file_list_scrollable,
                text="No PDFs added yet.\n\nClick \u201c+ Add PDFs\u201d or drag & drop files here.",
                text_color="gray55",
                font=self.font_normal,
                justify="center",
            )
            placeholder.grid(row=0, column=0, pady=40)
            self._register_drop_target(placeholder)
            return

        for index, item in enumerate(self.files):
            is_selected = index == self.selected_index
            row_color = ("#3B82F6", "#1E4C8C") if is_selected else ("gray88", "gray20")
            text_color = ("white", "white") if is_selected else ("gray10", "gray90")

            row = ctk.CTkFrame(self.file_list_scrollable, fg_color=row_color, corner_radius=6)
            row.grid(row=index, column=0, sticky="ew", padx=2, pady=3)
            row.grid_columnconfigure(1, weight=1)

            order_label = ctk.CTkLabel(
                row, text=f"{index + 1}.", width=26, font=self.font_bold, text_color=text_color
            )
            order_label.grid(row=0, column=0, padx=(10, 2), pady=8, sticky="w")

            name_label = ctk.CTkLabel(
                row, text=item.filename, font=self.font_normal, anchor="w", text_color=text_color
            )
            name_label.grid(row=0, column=1, padx=4, pady=8, sticky="ew")

            pages_text = f"{item.page_count} page{'s' if item.page_count != 1 else ''}"
            pages_label = ctk.CTkLabel(
                row, text=pages_text, font=self.font_small, width=80, text_color=text_color
            )
            pages_label.grid(row=0, column=2, padx=(4, 10), pady=8, sticky="e")

            for widget in (row, order_label, name_label, pages_label):
                widget.bind("<Button-1>", lambda _event, i=index: self._select_row(i))

    def _update_control_buttons_state(self) -> None:
        """Enable/disable Move Up/Down/Remove based on the current selection."""
        if self._processing:
            return
        has_selection = self.selected_index is not None
        self.remove_button.configure(state="normal" if has_selection else "disabled")

        can_move_up = has_selection and self.selected_index > 0
        can_move_down = has_selection and self.selected_index < len(self.files) - 1
        self.move_up_button.configure(state="normal" if can_move_up else "disabled")
        self.move_down_button.configure(state="normal" if can_move_down else "disabled")

    # ----------------------------------------------------------------------
    # Output file selection
    # ----------------------------------------------------------------------

    def _browse_output(self) -> None:
        """Open a save-file dialog to choose the output PDF path."""
        initial_dir = self.app_config.last_output_dir
        if not os.path.isdir(initial_dir):
            initial_dir = str(Path.home())

        path = filedialog.asksaveasfilename(
            title="Save merged PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialdir=initial_dir,
            initialfile="merged_output.pdf",
        )
        if path:
            self.output_var.set(path)
            self.app_config.last_output_dir = os.path.dirname(path)

    # ----------------------------------------------------------------------
    # Generate PDF
    # ----------------------------------------------------------------------

    def _on_generate_clicked(self) -> None:
        """Validate inputs and kick off the merge process on a background thread."""
        if self._processing:
            return

        if not self.files:
            messagebox.showerror("No files", "Please add at least one PDF file.")
            return

        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror("No output file", "Please choose an output file name.")
            return
        if not output_path.lower().endswith(".pdf"):
            output_path += ".pdf"
            self.output_var.set(output_path)

        try:
            gap_mm = float(self.gap_var.get())
            margin_mm = float(self.margin_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Gap and margins must be numbers.")
            return

        if gap_mm < 0 or margin_mm < 0:
            messagebox.showerror("Invalid input", "Gap and margins must not be negative.")
            return

        if os.path.exists(output_path):
            overwrite = messagebox.askyesno(
                "File already exists",
                f"'{os.path.basename(output_path)}' already exists.\nDo you want to overwrite it?",
            )
            if not overwrite:
                return

        try:
            settings = MergeSettings(
                paper_size=PaperSize(self.paper_size_var.get()),
                orientation=Orientation(self.orientation_var.get()),
                gap_mm=gap_mm,
                margin_mm=margin_mm,
                scale_mode=ScaleMode(self.scale_mode_var.get()),
                output_path=output_path,
            )
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        input_paths = [item.path for item in self.files]

        self._set_processing_state(True)
        self.status_var.set("Starting...")
        self.progress_bar.set(0)

        worker = threading.Thread(target=self._run_merge, args=(input_paths, settings), daemon=True)
        worker.start()

    def _run_merge(self, input_paths: List[str], settings: MergeSettings) -> None:
        """Worker-thread entry point: perform the merge and report the outcome to the UI."""
        try:
            merger = PDFPairMerger(settings)
            result_path = merger.merge(input_paths, progress_cb=self._on_progress)
        except MergeError as exc:
            self.after(0, self._on_merge_error, str(exc))
        except Exception as exc:  # unexpected/unhandled failure
            self.after(0, self._on_merge_error, f"An unexpected error occurred: {exc}")
        else:
            self.after(0, self._on_merge_success, result_path)

    def _on_progress(self, done: int, total: int, message: str) -> None:
        """Progress callback invoked from the worker thread; marshals to the UI thread."""
        self.after(0, self._update_progress_ui, done, total, message)

    def _update_progress_ui(self, done: int, total: int, message: str) -> None:
        """Update the progress bar and status label (must run on the UI thread)."""
        if total > 0:
            self.progress_bar.set(done / total)
        self.status_var.set(message)

    def _on_merge_success(self, output_path: str) -> None:
        """Handle a successful merge (runs on the UI thread)."""
        self._set_processing_state(False)
        self.progress_bar.set(1.0)
        self.status_var.set(f"Done! Saved to {output_path}")

        self.app_config.last_output_dir = os.path.dirname(output_path)
        self._persist_config()

        messagebox.showinfo("Success", f"The merged PDF was created successfully:\n\n{output_path}")

    def _on_merge_error(self, message: str) -> None:
        """Handle a failed merge (runs on the UI thread)."""
        self._set_processing_state(False)
        self.progress_bar.set(0)
        self.status_var.set("An error occurred.")
        messagebox.showerror("Error", message)

    def _set_processing_state(self, processing: bool) -> None:
        """Enable/disable interactive widgets while a merge is in progress."""
        self._processing = processing
        state = "disabled" if processing else "normal"

        widgets = (
            self.add_button,
            self.remove_button,
            self.move_up_button,
            self.move_down_button,
            self.browse_button,
            self.generate_button,
            self.paper_size_menu,
            self.orientation_menu,
            self.scale_menu,
            self.gap_entry,
            self.margin_entry,
            self.output_entry,
        )
        for widget in widgets:
            widget.configure(state=state)

        if not processing:
            self._update_control_buttons_state()
