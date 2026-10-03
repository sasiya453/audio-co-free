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


def _ensure_import_path() -> None:
    """Make ``core`` / ``ui`` importable whether run from source or frozen."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))


def _setup_logging() -> None:
    """Console + rotating file logging via :mod:`core.logging_setup`.
    Falls back to ``basicConfig`` if the module itself cannot be imported."""
    debug = bool(os.environ.get("AUDIOMASK_DEBUG"))
    try:
        from core.logging_setup import configure_logging, log_environment
        # Under PyInstaller --noconsole stderr is None; skip the stream handler.
        configure_logging(debug=debug, console=sys.stderr is not None)
        log_environment(logging.getLogger("audiomask.main"))
    except Exception:  # noqa: BLE001 - logging must never block start-up
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S")
        logging.getLogger("audiomask.main").warning(
            "Falling back to basic console logging", exc_info=True)


def _install_thread_excepthook(log: logging.Logger) -> None:
    """Route uncaught exceptions in worker threads to the log file."""
    import threading

    def _hook(args: threading.ExceptHookArgs) -> None:
        log.error("Uncaught exception in thread %s",
                  getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    try:
        threading.excepthook = _hook
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _ensure_import_path()
    _setup_logging()
    log = logging.getLogger("audiomask.main")
    _install_thread_excepthook(log)
    try:
        import customtkinter as ctk  # noqa: F401 - verify GUI deps early
        from ui.app_ui import AudioMaskApp
    except ImportError as exc:
        log.error("Missing dependency: %s", exc)
        _fatal_popup(f"A required component is missing:\n\n{exc}\n\n"
                     "Run:  pip install -r requirements.txt")
        return 1

    app = None
    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        app = AudioMaskApp()
        app.mainloop()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as exc:  # noqa: BLE001 - last-resort crash guard
        log.exception("Unhandled exception in UI loop")
        try:
            from core.logging_setup import active_log_path
            where = active_log_path()
        except Exception:  # noqa: BLE001
            where = None
        _fatal_popup(f"AudioMask Pro crashed:\n\n{exc!r}"
                     + (f"\n\nDetails were written to:\n{where}" if where else ""))
        return 2
    finally:
        if app is not None:
            try:
                app.shutdown()
            except Exception:  # noqa: BLE001
                pass
        logging.shutdown()
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
