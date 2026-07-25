"""
main.py

Entry point for the PDF Pair Merger desktop application.

Run with:
    python main.py
"""

from __future__ import annotations

import sys
import traceback

import customtkinter as ctk

from gui import PDFPairMergerApp


def main() -> None:
    """Configure global CustomTkinter appearance and launch the main window."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = PDFPairMergerApp()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # last-resort safety net so users always see something useful
        traceback.print_exc()
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "PDF Pair Merger - Fatal Error",
                f"The application encountered a fatal error and must close:\n\n{exc}",
            )
        except Exception:
            pass
        sys.exit(1)
