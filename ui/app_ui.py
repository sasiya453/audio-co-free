"""
AudioMask Pro - Desktop User Interface
======================================

A dark-mode CustomTkinter front-end for :class:`core.audio_engine.AudioMasker`.

Design rules
------------
* **No DSP here.** The UI only builds a :class:`MaskSettings`, hands files to
  the engine on a background thread and renders progress.
* **Thread-safe.** The worker thread never touches Tk widgets. It pushes
  ``(kind, payload)`` tuples onto a :class:`queue.Queue` which the main loop
  drains every 100 ms via ``self.after``.
* **Responsive.** Heavy rendering runs in ``threading.Thread(daemon=True)``;
  Cancel sets the engine flag and the pipeline stops at the next stage boundary.

Run with ``python main.py`` from the repository root.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional

import customtkinter as ctk

from core.audio_engine import (
    SUPPORTED_INPUT_EXTENSIONS,
    AudioEngineError,
    AudioMasker,
    MaskSettings,
)

logger = logging.getLogger("audiomask.ui")

APP_TITLE = "AudioMask Pro"
APP_VERSION = "0.2.0"
WINDOW_SIZE = (880, 800)
MIN_SIZE = (800, 720)
POLL_MS = 100

# Output containers exposed in the UI (mp3 depends on libsndfile build, so it
# is intentionally left out of the default dropdown).
UI_OUTPUT_FORMATS = ("wav", "flac", "ogg")

# Glassmorphic palette -------------------------------------------------------
_BG = "#0f1117"
_PANEL = "#171a23"
_PANEL_ALT = "#1d212c"
_BORDER = "#2a2f3d"
_ACCENT = "#4f8cff"
_ACCENT_HOVER = "#3b74e0"
_DANGER = "#e0564f"
_DANGER_HOVER = "#c1443d"
_TEXT_MUTED = "#8b93a7"
_CONSOLE_BG = "#0a0c12"
_CONSOLE_FG = "#9fe3a3"


# --------------------------------------------------------------------------- #
# Message types used on the worker -> UI queue
# --------------------------------------------------------------------------- #
MSG_LOG = "log"            # payload: str
MSG_FILE_PROGRESS = "fp"   # payload: float 0..1
MSG_FILE_START = "fs"      # payload: (index:int, total:int, name:str)
MSG_FILE_DONE = "fd"       # payload: (index:int, total:int, out_path:str)
MSG_FILE_ERROR = "fe"      # payload: (index:int, total:int, name:str, err:str)
MSG_BATCH_DONE = "bd"      # payload: (ok:int, failed:int, cancelled:bool)


class _GlassFrame(ctk.CTkFrame):
    """Rounded panel with a subtle border - the building block of the layout."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", _PANEL)
        kwargs.setdefault("border_color", _BORDER)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("corner_radius", 14)
        super().__init__(master, **kwargs)


class AudioMaskApp(ctk.CTk):
    """
    Main application window.

    Parameters
    ----------
    masker : AudioMasker, optional
        Inject a pre-configured engine (useful for tests). A default instance
        is created when omitted.
    """

    def __init__(self, masker: Optional[AudioMasker] = None) -> None:
        super().__init__(fg_color=_BG)

        self.masker = masker or AudioMasker()
        self.defaults = MaskSettings()
        self.limits = self.defaults.LIMITS

        self._files: List[Path] = []
        self._output_dir: Optional[Path] = None
        self._worker: Optional[threading.Thread] = None
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._running = False
        self._cancel_flag = threading.Event()
        self._controls: list = []  # widgets disabled while processing

        self._configure_window()
        self._build_layout()
        self._apply_defaults()
        self.after(POLL_MS, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log(f"{APP_TITLE} v{APP_VERSION} ready.")
        if not self.masker.ffmpeg_path:
            self.log("Note: FFmpeg not found on PATH - MP3/M4A decoding may "
                     "fall back to audioread or fail.")

    # ------------------------------------------------------------------ #
    # Window / layout
    # ------------------------------------------------------------------ #
    def _configure_window(self) -> None:
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        w, h = WINDOW_SIZE
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x, y = max((sw - w) // 2, 0), max((sh - h) // 2, 0)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:  # noqa: BLE001 - headless / odd WM
            self.geometry(f"{w}x{h}")
        self.minsize(*MIN_SIZE)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)  # console grows

    def _build_layout(self) -> None:
        self._build_header()
        self._build_source_panel()
        self._build_settings_panel()
        self._build_action_panel()
        self._build_console_panel()

    # -- header ---------------------------------------------------------- #
    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text=APP_TITLE,
                     font=ctk.CTkFont(size=26, weight="bold")
                     ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(hdr, text="Audio DSP masking suite  -  pitch, tempo, "
                               "spectral shaping & room simulation",
                     text_color=_TEXT_MUTED,
                     font=ctk.CTkFont(size=12)
                     ).grid(row=1, column=0, sticky="w")

        self.theme_switch = ctk.CTkSwitch(
            hdr, text="Dark", command=self._toggle_theme, width=80)
        self.theme_switch.select()
        self.theme_switch.grid(row=0, column=1, rowspan=2, sticky="e")

    # -- source files ---------------------------------------------------- #
    def _build_source_panel(self) -> None:
        panel = _GlassFrame(self)
        panel.grid(row=1, column=0, sticky="ew", padx=20, pady=6)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="SOURCE", text_color=_TEXT_MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, sticky="w",
                            padx=16, pady=(10, 2))

        self.btn_browse = ctk.CTkButton(
            panel, text="Browse files...", width=140,
            fg_color=_ACCENT, hover_color=_ACCENT_HOVER,
            command=self._pick_files)
        self.btn_browse.grid(row=1, column=0, padx=(16, 8), pady=6, sticky="w")

        self.file_box = ctk.CTkTextbox(
            panel, height=64, fg_color=_PANEL_ALT, border_width=0,
            font=ctk.CTkFont(family="Consolas", size=11), wrap="none")
        self.file_box.grid(row=1, column=1, rowspan=2, sticky="ew",
                           padx=8, pady=6)
        self.file_box.configure(state="disabled")

        self.btn_clear = ctk.CTkButton(
            panel, text="Clear", width=140, fg_color=_PANEL_ALT,
            hover_color=_BORDER, command=self._clear_files)
        self.btn_clear.grid(row=2, column=0, padx=(16, 8), pady=6, sticky="w")

        self.btn_outdir = ctk.CTkButton(
            panel, text="Output folder...", width=140,
            fg_color=_PANEL_ALT, hover_color=_BORDER,
            command=self._pick_output_dir)
        self.btn_outdir.grid(row=3, column=0, padx=(16, 8), pady=(6, 12),
                             sticky="w")
        self.lbl_outdir = ctk.CTkLabel(
            panel, text="(same folder as first input)", anchor="w",
            text_color=_TEXT_MUTED, font=ctk.CTkFont(size=11))
        self.lbl_outdir.grid(row=3, column=1, sticky="ew", padx=8,
                             pady=(6, 12))

        self._controls += [self.btn_browse, self.btn_clear, self.btn_outdir]

    # -- settings -------------------------------------------------------- #
    def _build_settings_panel(self) -> None:
        panel = _GlassFrame(self)
        panel.grid(row=2, column=0, sticky="ew", padx=20, pady=6)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        # Primary controls (left column) --------------------------------
        left = ctk.CTkFrame(panel, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=10)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="PRIMARY", text_color=_TEXT_MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=0, column=0, columnspan=2, sticky="w")

        lo, hi = self.limits["pitch_semitones"]
        self.sl_pitch, self.lbl_pitch = self._make_slider(
            left, 1, "Pitch shift", lo, hi,
            steps=int(round((hi - lo) / 0.1)),
            fmt=lambda v: f"{v:+.2f} st")

        lo, hi = self.limits["speed_factor"]
        self.sl_speed, self.lbl_speed = self._make_slider(
            left, 3, "Speed factor", lo, hi,
            steps=int(round((hi - lo) / 0.01)),
            fmt=lambda v: f"x{v:.3f}")

        # Advanced controls (right column) ------------------------------
        right = ctk.CTkFrame(panel, fg_color=_PANEL_ALT, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=10)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="ADVANCED", text_color=_TEXT_MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=0, column=0, columnspan=2, sticky="w",
                            padx=12, pady=(8, 0))

        self.sw_reverb = ctk.CTkSwitch(
            right, text="Micro-reverb (30 ms room)",
            command=self._sync_advanced_state, progress_color=_ACCENT)
        self.sw_reverb.grid(row=1, column=0, columnspan=2, sticky="w",
                            padx=12, pady=(8, 0))
        lo, hi = self.limits["reverb_mix"]
        self.sl_reverb, self.lbl_reverb = self._make_slider(
            right, 2, "Reverb mix", lo, hi, steps=100,
            fmt=lambda v: f"{v * 100:.0f} %", padx=12)

        self.sw_bandpass = ctk.CTkSwitch(
            right, text="Butterworth bandpass (80 Hz - 14 kHz)",
            command=self._sync_advanced_state, progress_color=_ACCENT)
        self.sw_bandpass.grid(row=4, column=0, columnspan=2, sticky="w",
                              padx=12, pady=(6, 0))
        lo, hi = self.limits["bandpass_intensity"]
        self.sl_bandpass, self.lbl_bandpass = self._make_slider(
            right, 5, "Filter intensity", lo, hi, steps=100,
            fmt=lambda v: f"{v * 100:.0f} %", padx=12)

        fmt_row = ctk.CTkFrame(right, fg_color="transparent")
        fmt_row.grid(row=7, column=0, columnspan=2, sticky="ew", padx=12,
                     pady=(6, 10))
        ctk.CTkLabel(fmt_row, text="Output format").pack(side="left")
        self.om_format = ctk.CTkOptionMenu(
            fmt_row, values=list(UI_OUTPUT_FORMATS), width=100,
            fg_color=_PANEL, button_color=_ACCENT,
            button_hover_color=_ACCENT_HOVER)
        self.om_format.pack(side="right")

        self.btn_reset = ctk.CTkButton(
            fmt_row, text="Reset", width=70, fg_color=_PANEL,
            hover_color=_BORDER, command=self._apply_defaults)
        self.btn_reset.pack(side="right", padx=(0, 10))

        self._controls += [self.sl_pitch, self.sl_speed, self.sw_reverb,
                           self.sl_reverb, self.sw_bandpass, self.sl_bandpass,
                           self.om_format, self.btn_reset]

    def _make_slider(self, parent, row: int, label: str, lo: float, hi: float,
                     steps: int, fmt, padx: int = 0):
        """Create label + slider + live value readout spanning two grid rows."""
        ctk.CTkLabel(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=padx, pady=(8, 0))
        value_lbl = ctk.CTkLabel(parent, text="", width=80, anchor="e",
                                 text_color=_ACCENT,
                                 font=ctk.CTkFont(family="Consolas", size=12,
                                                  weight="bold"))
        value_lbl.grid(row=row, column=1, sticky="e", padx=padx, pady=(8, 0))

        slider = ctk.CTkSlider(
            parent, from_=lo, to=hi, number_of_steps=steps,
            progress_color=_ACCENT, button_color=_ACCENT,
            button_hover_color=_ACCENT_HOVER,
            command=lambda v, l=value_lbl, f=fmt: l.configure(text=f(float(v))))
        slider.grid(row=row + 1, column=0, columnspan=2, sticky="ew",
                    padx=padx, pady=(2, 4))
        slider._am_fmt = fmt  # stash formatter for programmatic updates
        return slider, value_lbl

    # -- actions --------------------------------------------------------- #
    def _build_action_panel(self) -> None:
        panel = _GlassFrame(self)
        panel.grid(row=3, column=0, sticky="ew", padx=20, pady=6)
        panel.grid_columnconfigure(2, weight=1)

        self.btn_process = ctk.CTkButton(
            panel, text="Process", width=150, height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=_ACCENT, hover_color=_ACCENT_HOVER,
            command=self._start_processing)
        self.btn_process.grid(row=0, column=0, padx=(16, 8), pady=12)

        self.btn_cancel = ctk.CTkButton(
            panel, text="Cancel", width=110, height=38,
            fg_color=_DANGER, hover_color=_DANGER_HOVER,
            state="disabled", command=self._cancel_processing)
        self.btn_cancel.grid(row=0, column=1, padx=8, pady=12)

        prog = ctk.CTkFrame(panel, fg_color="transparent")
        prog.grid(row=0, column=2, sticky="ew", padx=(8, 16), pady=12)
        prog.grid_columnconfigure(0, weight=1)

        self.lbl_batch = ctk.CTkLabel(prog, text="Idle", anchor="w",
                                      text_color=_TEXT_MUTED,
                                      font=ctk.CTkFont(size=11))
        self.lbl_batch.grid(row=0, column=0, sticky="w")
        self.lbl_pct = ctk.CTkLabel(prog, text="0 %", anchor="e", width=50,
                                    text_color=_TEXT_MUTED,
                                    font=ctk.CTkFont(size=11))
        self.lbl_pct.grid(row=0, column=1, sticky="e")

        self.pb_file = ctk.CTkProgressBar(prog, height=10,
                                          progress_color=_ACCENT)
        self.pb_file.grid(row=1, column=0, columnspan=2, sticky="ew",
                          pady=(4, 2))
        self.pb_file.set(0)
        self.pb_total = ctk.CTkProgressBar(prog, height=4,
                                           progress_color=_TEXT_MUTED)
        self.pb_total.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.pb_total.set(0)

    # -- console --------------------------------------------------------- #
    def _build_console_panel(self) -> None:
        panel = _GlassFrame(self)
        panel.grid(row=4, column=0, sticky="nsew", padx=20, pady=(6, 18))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="STATUS CONSOLE", text_color=_TEXT_MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))

        self.console = ctk.CTkTextbox(
            panel, fg_color=_CONSOLE_BG, text_color=_CONSOLE_FG,
            font=ctk.CTkFont(family="Consolas", size=11), wrap="word",
            border_width=0, corner_radius=10)
        self.console.grid(row=1, column=0, sticky="nsew", padx=12,
                          pady=(0, 12))
        self.console.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Settings helpers
    # ------------------------------------------------------------------ #
    def _set_slider(self, slider: ctk.CTkSlider, label: ctk.CTkLabel,
                    value: float) -> None:
        slider.set(value)
        label.configure(text=slider._am_fmt(float(value)))

    def _apply_defaults(self) -> None:
        d = self.defaults
        self._set_slider(self.sl_pitch, self.lbl_pitch, d.pitch_semitones)
        self._set_slider(self.sl_speed, self.lbl_speed, d.speed_factor)
        self._set_slider(self.sl_reverb, self.lbl_reverb, d.reverb_mix)
        self._set_slider(self.sl_bandpass, self.lbl_bandpass,
                         d.bandpass_intensity)
        (self.sw_reverb.select if d.reverb_enabled
         else self.sw_reverb.deselect)()
        (self.sw_bandpass.select if d.bandpass_enabled
         else self.sw_bandpass.deselect)()
        fmt = d.output_format if d.output_format in UI_OUTPUT_FORMATS else "wav"
        self.om_format.set(fmt)
        self._sync_advanced_state()

    def _sync_advanced_state(self) -> None:
        """Grey out sub-sliders whose parent switch is off."""
        if self._running:
            return
        self.sl_reverb.configure(
            state="normal" if self.sw_reverb.get() else "disabled")
        self.sl_bandpass.configure(
            state="normal" if self.sw_bandpass.get() else "disabled")

    def build_settings(self) -> MaskSettings:
        """Snapshot the current widget values into a validated MaskSettings."""
        s = MaskSettings(
            pitch_semitones=round(float(self.sl_pitch.get()), 2),
            speed_factor=round(float(self.sl_speed.get()), 3),
            reverb_enabled=bool(self.sw_reverb.get()),
            reverb_mix=round(float(self.sl_reverb.get()), 3),
            bandpass_enabled=bool(self.sw_bandpass.get()),
            bandpass_intensity=round(float(self.sl_bandpass.get()), 3),
            output_format=self.om_format.get(),
        )
        return s.validate()

    # ------------------------------------------------------------------ #
    # File selection
    # ------------------------------------------------------------------ #
    def _pick_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_INPUT_EXTENSIONS)
        paths = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[("Audio files", patterns), ("All files", "*.*")])
        if not paths:
            return
        added = 0
        for p in paths:
            path = Path(p)
            if path.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
                self.log(f"Skipped unsupported file: {path.name}")
                continue
            if path not in self._files:
                self._files.append(path)
                added += 1
        self._refresh_file_box()
        self.log(f"Added {added} file(s); {len(self._files)} queued.")

    def _clear_files(self) -> None:
        self._files.clear()
        self._refresh_file_box()
        self.log("File list cleared.")

    def _refresh_file_box(self) -> None:
        self.file_box.configure(state="normal")
        self.file_box.delete("1.0", "end")
        if self._files:
            self.file_box.insert(
                "end", "\n".join(f"{i + 1:>2}. {p}" for i, p in
                                 enumerate(self._files)))
        else:
            self.file_box.insert("end", "No files selected.")
        self.file_box.configure(state="disabled")
        if self._output_dir is None:
            self.lbl_outdir.configure(
                text=(str(self._files[0].parent) if self._files
                      else "(same folder as first input)"))

    def _pick_output_dir(self) -> None:
        initial = (str(self._output_dir) if self._output_dir else
                   (str(self._files[0].parent) if self._files else
                    str(Path.home())))
        chosen = filedialog.askdirectory(title="Select output folder",
                                         initialdir=initial)
        if chosen:
            self._output_dir = Path(chosen)
            self.lbl_outdir.configure(text=str(self._output_dir))
            self.log(f"Output folder: {self._output_dir}")

    def _effective_output_dir(self, first_input: Path) -> Path:
        return self._output_dir or first_input.parent

    # ------------------------------------------------------------------ #
    # Processing (worker thread)
    # ------------------------------------------------------------------ #
    def _start_processing(self) -> None:
        if self._running:
            return
        if not self._files:
            messagebox.showwarning(APP_TITLE, "Please select at least one "
                                              "audio file first.")
            return
        try:
            settings = self.build_settings()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Invalid settings:\n{exc}")
            return

        files = list(self._files)
        out_dir = self._effective_output_dir(files[0])
        self._set_running(True)
        self._cancel_flag.clear()
        self.pb_file.set(0)
        self.pb_total.set(0)
        self.log(f"Starting batch: {len(files)} file(s) -> {out_dir}")
        self.log(f"Settings: pitch {settings.pitch_semitones:+.2f} st, "
                 f"speed x{settings.speed_factor:.3f}, "
                 f"reverb {'on' if settings.reverb_enabled else 'off'} "
                 f"({settings.reverb_mix:.2f}), "
                 f"bandpass {'on' if settings.bandpass_enabled else 'off'} "
                 f"({settings.bandpass_intensity:.2f}), "
                 f"format {settings.output_format}")

        self._worker = threading.Thread(
            target=self._worker_main, args=(files, out_dir, settings),
            name="AudioMaskWorker", daemon=True)
        self._worker.start()

    def _worker_main(self, files: List[Path], out_dir: Path,
                     settings: MaskSettings) -> None:
        """Runs on the background thread. Communicates ONLY via the queue."""
        ok = failed = 0
        total = len(files)
        cancelled = False

        def progress(frac: float, msg: str) -> None:
            self._queue.put((MSG_FILE_PROGRESS, frac))
            self._queue.put((MSG_LOG, f"    [{frac * 100:3.0f}%] {msg}"))

        for idx, path in enumerate(files, start=1):
            if self._cancel_flag.is_set():
                cancelled = True
                break
            self._queue.put((MSG_FILE_START, (idx, total, path.name)))
            t0 = time.perf_counter()
            try:
                out = self.masker.process_file(path, out_dir, settings,
                                               progress_cb=progress)
                ok += 1
                self._queue.put((MSG_FILE_DONE, (idx, total, str(out))))
                self._queue.put(
                    (MSG_LOG, f"    finished in {time.perf_counter() - t0:.1f}s"))
            except AudioEngineError as exc:
                if self._cancel_flag.is_set():
                    cancelled = True
                    self._queue.put((MSG_LOG, f"Cancelled during {path.name}"))
                    break
                failed += 1
                self._queue.put((MSG_FILE_ERROR,
                                 (idx, total, path.name, str(exc))))
            except MemoryError:
                failed += 1
                self._queue.put((MSG_FILE_ERROR,
                                 (idx, total, path.name,
                                  "Out of memory - file too large to process.")))
            except Exception as exc:  # noqa: BLE001 - last line of defence
                logger.exception("Unexpected error processing %s", path)
                failed += 1
                self._queue.put((MSG_FILE_ERROR,
                                 (idx, total, path.name,
                                  f"Unexpected error: {exc!r}")))

        self._queue.put((MSG_BATCH_DONE, (ok, failed, cancelled)))

    def _cancel_processing(self) -> None:
        if not self._running:
            return
        self._cancel_flag.set()
        self.masker.cancel()
        self.btn_cancel.configure(state="disabled", text="Cancelling...")
        self.log("Cancel requested - stopping after current stage...")

    # ------------------------------------------------------------------ #
    # Queue polling (main thread)
    # ------------------------------------------------------------------ #
    def _poll_queue(self) -> None:
        try:
            for _ in range(200):  # bounded drain per tick keeps UI smooth
                kind, payload = self._queue.get_nowait()
                self._handle_message(kind, payload)
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("Error while handling worker message")
        finally:
            self.after(POLL_MS, self._poll_queue)

    def _handle_message(self, kind: str, payload) -> None:
        if kind == MSG_LOG:
            self.log(payload)
        elif kind == MSG_FILE_PROGRESS:
            self.pb_file.set(payload)
            self.lbl_pct.configure(text=f"{payload * 100:.0f} %")
        elif kind == MSG_FILE_START:
            idx, total, name = payload
            self.pb_file.set(0)
            self.lbl_pct.configure(text="0 %")
            self.lbl_batch.configure(text=f"File {idx} / {total}: {name}")
            self.pb_total.set((idx - 1) / total)
            self.log(f"[{idx}/{total}] {name}")
        elif kind == MSG_FILE_DONE:
            idx, total, out = payload
            self.pb_total.set(idx / total)
            self.log(f"    -> {out}")
        elif kind == MSG_FILE_ERROR:
            idx, total, name, err = payload
            self.pb_total.set(idx / total)
            self.log(f"    ERROR: {err}")
        elif kind == MSG_BATCH_DONE:
            self._finish_batch(*payload)

    def _finish_batch(self, ok: int, failed: int, cancelled: bool) -> None:
        self._set_running(False)
        self.pb_file.set(1.0 if not cancelled else self.pb_file.get())
        status = ("Cancelled" if cancelled else
                  "Completed" if failed == 0 else "Completed with errors")
        self.lbl_batch.configure(text=f"{status}: {ok} ok, {failed} failed")
        self.log(f"Batch {status.lower()}: {ok} succeeded, {failed} failed.")
        if cancelled:
            return
        if failed and ok == 0:
            messagebox.showerror(
                APP_TITLE, f"All {failed} file(s) failed. See the console for "
                           "details.")
        elif failed:
            messagebox.showwarning(
                APP_TITLE, f"{ok} file(s) processed, {failed} failed. "
                           "See the console for details.")
        else:
            messagebox.showinfo(APP_TITLE, f"{ok} file(s) processed "
                                           "successfully.")

    # ------------------------------------------------------------------ #
    # UI state helpers
    # ------------------------------------------------------------------ #
    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "normal"
        for w in self._controls:
            try:
                w.configure(state=state)
            except Exception:  # noqa: BLE001
                pass
        self.btn_process.configure(
            state=state, text="Processing..." if running else "Process")
        self.btn_cancel.configure(
            state="normal" if running else "disabled", text="Cancel")
        if not running:
            self._sync_advanced_state()

    def _toggle_theme(self) -> None:
        ctk.set_appearance_mode("dark" if self.theme_switch.get() else "light")

    def log(self, message: str) -> None:
        """Append a timestamped line to the console (main thread only)."""
        stamp = time.strftime("%H:%M:%S")
        self.console.configure(state="normal")
        self.console.insert("end", f"[{stamp}] {message}\n")
        self.console.see("end")
        self.console.configure(state="disabled")
        logger.info(message)

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                    APP_TITLE, "Processing is still running. Cancel and quit?"):
                return
            self._cancel_flag.set()
            self.masker.cancel()
        self.destroy()


def run() -> None:
    """Convenience launcher used by ``main.py``."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = AudioMaskApp()
    app.mainloop()


if __name__ == "__main__":  # pragma: no cover
    run()
