"""
AudioMask Pro - application entry point.

This is the module PyInstaller targets (Task 4). It wires up logging, makes
sure the repository root is importable when frozen, and launches the UI.

Usage
-----
    python main.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _setup_logging() -> None:
    """Console logging; Task 3 will extend this with a rotating file handler."""
    level = logging.DEBUG if os.environ.get("AUDIOMASK_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # librosa/numba are chatty at DEBUG level
    logging.getLogger("numba").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def _ensure_import_path() -> None:
    """Make ``core`` / ``ui`` importable whether run from source or frozen."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))


def main() -> int:
    _setup_logging()
    _ensure_import_path()
    log = logging.getLogger("audiomask.main")
    try:
        import customtkinter as ctk  # noqa: F401 - verify GUI deps early
        from ui.app_ui import AudioMaskApp
    except ImportError as exc:
        log.error("Missing dependency: %s", exc)
        _fatal_popup(f"A required component is missing:\n\n{exc}\n\n"
                     "Run:  pip install -r requirements.txt")
        return 1

    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        app = AudioMaskApp()
        app.mainloop()
    except Exception as exc:  # noqa: BLE001 - last-resort crash guard
        log.exception("Unhandled exception in UI loop")
        _fatal_popup(f"AudioMask Pro crashed:\n\n{exc!r}")
        return 2
    return 0


def _fatal_popup(message: str) -> None:
    """Best-effort native error dialog that works even if customtkinter is
    unavailable (falls back to stderr)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("AudioMask Pro", message)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
