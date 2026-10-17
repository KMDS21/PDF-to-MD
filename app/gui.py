"""Desktop GUI for the PDF-to-MD converter (CustomTkinter).

Creative, card-based layout designed for understandability (plan §7):

┌──────────────────────────────────────────────────────────┐
│  🎓  PDF · PPTX · DOCX · XLSX  →  Markdown               │
│      one-click lecture-material converter                │
├──────────────────────────────────────────────────────────┤
│  [ 📂 Select Folder… ]   path…                [Output…]  │
├──────────────────────────────────────────────────────────┤
│  Output mode:  ( Separate files | 📚 Merge into one )    │
│  ⓘ explanation of the selected mode                      │
├──────────────────────────────────────────────────────────┤
│  ☑ subfolders ☑ images ☑ notes ☑ OCR    [AI enhancement] │
├──────────────────────────────────────────────────────────┤
│  [ 🔃 Convert ] [ Cancel ] [ Open Output ]   ▓▓▓▓ 45%    │
├──────────────────────────────────────────────────────────┤
│  live log (✓ / ✗ / ⚠ per file)                           │
└──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app.converter import (
    ConversionOptions,
    convert_folder,
    find_files,
)

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

_POLL_MS = 100  # how often the UI drains the log queue

# palette — soft, modern accent colors used across the cards
CARD_COLOR = ("gray92", "gray17")
ACCENT = "#3b8ed0"
GOOD = "#2fa84f"
WARN = "#d9962f"
BAD = "#d64545"

_MODE_HELP = {
    "separate": "Each document becomes its own .md file — folder structure is mirrored.",
    "merge": "All documents are combined into ONE book .md, each source separated "
             "by a ─── divider. Perfect for printing or reading a whole course.",
}


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF-to-MD Converter")
        self.geometry("960x740")
        self.minsize(820, 620)

        self.input_dir: Path | None = None
        self.output_dir: Path | None = None
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.log_queue: Queue = Queue()
        self.progress_queue: Queue = Queue()

        self._build_ui()
        self.after(_POLL_MS, self._poll_queues)

    # ------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._build_header()
        self._build_source_card()
        self._build_mode_card()
        self._build_options_card()
        self._build_actions_row()
        self._build_log()

    # --- 1. header ------------------------------------------------------
    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=16)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="🎓", font=ctk.CTkFont(size=42)).grid(
            row=0, column=0, rowspan=2, padx=(16, 10), pady=12)
        ctk.CTkLabel(header, text="PDF → Markdown Studio",
                     font=ctk.CTkFont(size=24, weight="bold"),
                     anchor="w").grid(row=0, column=1, sticky="w", pady=(12, 0))
        ctk.CTkLabel(header,
                     text="Convert PDF · PPTX · DOCX · XLSX · images  into clean Markdown",
                     text_color="gray55", anchor="w",
                     font=ctk.CTkFont(size=13)).grid(row=1, column=1, sticky="w", pady=(0, 12))

    # --- 2. source folder ----------------------------------------------
    def _build_source_card(self) -> None:
        card = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=16)
        card.grid(row=1, column=0, sticky="ew", padx=14, pady=6)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(card, text="📂  Select Folder…", width=170, height=38,
                      corner_radius=10, command=self._pick_folder).grid(
            row=0, column=0, rowspan=2, padx=16, pady=14)

        self.folder_label = ctk.CTkLabel(card, text="No folder selected",
                                         anchor="w", font=ctk.CTkFont(size=14, weight="bold"))
        self.folder_label.grid(row=0, column=1, sticky="sw", pady=(14, 0))

        self.filecount_label = ctk.CTkLabel(card, text="📄 0 convertible files",
                                            anchor="w", text_color="gray55",
                                            font=ctk.CTkFont(size=12))
        self.filecount_label.grid(row=1, column=1, sticky="nw", pady=(0, 14))

        ctk.CTkButton(card, text="Output…", width=90, height=30,
                      fg_color="gray35", hover_color="gray45",
                      command=self._pick_output).grid(row=0, column=1, sticky="e", padx=8)
        self.output_label = ctk.CTkLabel(card, text="", anchor="e", text_color="gray55",
                                         font=ctk.CTkFont(size=12))
        self.output_label.grid(row=1, column=1, sticky="ne", padx=8, pady=(0, 14))

    # --- 3. output mode -------------------------------------------------
    def _build_mode_card(self) -> None:
        card = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=16)
        card.grid(row=2, column=0, sticky="ew", padx=14, pady=6)
        card.grid_columnconfigure(0, weight=1)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 2))
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row, text="Output mode:",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=(0, 12))
        self.mode_switch = ctk.CTkSegmentedButton(
            row, values=["📄  Separate files", "📚  Merge into one book"],
            command=self._mode_changed)
        self.mode_switch.set("📄  Separate files")
        self.mode_switch.grid(row=0, column=1, sticky="e")

        self.mode_help = ctk.CTkLabel(card, text=_MODE_HELP["separate"],
                                      text_color="gray55", anchor="w",
                                      font=ctk.CTkFont(size=12, slant="italic"))
        self.mode_help.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

    def _mode_changed(self, choice: str) -> None:
        key = "merge" if "Merge" in choice else "separate"
        self.mode_help.configure(text=_MODE_HELP[key])

    @property
    def merge_mode(self) -> bool:
        return "Merge" in self.mode_switch.get()

    # --- 4. options -----------------------------------------------------
    def _build_options_card(self) -> None:
        card = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=16)
        card.grid(row=3, column=0, sticky="ew", padx=14, pady=6)

        self.var_recursive = ctk.BooleanVar(value=True)
        self.var_images = ctk.BooleanVar(value=True)
        self.var_notes = ctk.BooleanVar(value=True)
        self.var_ocr = ctk.BooleanVar(value=True)
        self.var_ai = ctk.BooleanVar(value=False)

        checks = ctk.CTkFrame(card, fg_color="transparent")
        checks.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        for col, (text, var) in enumerate([
            ("Include subfolders", self.var_recursive),
            ("Extract images", self.var_images),
            ("Speaker notes", self.var_notes),
            ("OCR scanned pages", self.var_ocr),
        ]):
            ctk.CTkCheckBox(checks, text=text, variable=var,
                            font=ctk.CTkFont(size=13)).grid(row=0, column=col, padx=10, pady=4)

        ai_row = ctk.CTkFrame(card, fg_color="transparent")
        ai_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 10))
        ai_row.grid_columnconfigure(2, weight=1)

        ctk.CTkCheckBox(ai_row, text="✨ AI enhancement", variable=self.var_ai,
                        font=ctk.CTkFont(size=13),
                        command=self._toggle_ai).grid(row=0, column=0, padx=10)
        self.provider_var = ctk.StringVar(value="openai")
        self.provider_menu = ctk.CTkOptionMenu(ai_row, values=["openai", "gemini"],
                                               variable=self.provider_var, width=100, height=26)
        self.api_entry = ctk.CTkEntry(ai_row, placeholder_text="API key (memory only)", show="•",
                                      height=26)
        # hidden until the checkbox is ticked

    def _toggle_ai(self) -> None:
        if self.var_ai.get():
            self.provider_menu.grid(row=0, column=1, padx=6)
            self.api_entry.grid(row=0, column=2, sticky="ew", padx=6)
        else:
            self.provider_menu.grid_remove()
            self.api_entry.grid_remove()

    # --- 5. actions + progress -----------------------------------------
    def _build_actions_row(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="new", padx=14, pady=6)
        bar.grid_columnconfigure(5, weight=1)

        self.convert_btn = ctk.CTkButton(
            bar, text="🔃  Convert", width=150, height=40, corner_radius=12,
            fg_color=GOOD, hover_color="#268a42",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_conversion)
        self.convert_btn.grid(row=0, column=0, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(bar, text="Cancel", width=90, height=40,
                                        fg_color="gray35", hover_color="gray45",
                                        state="disabled", command=self._cancel)
        self.cancel_btn.grid(row=0, column=1, padx=4)

        self.open_btn = ctk.CTkButton(bar, text="Open Output", width=120, height=40,
                                      fg_color="gray25", hover_color="gray30",
                                      state="disabled", command=self._open_output)
        self.open_btn.grid(row=0, column=2, padx=4)

        self.log_btn = ctk.CTkButton(bar, text="📜 Log", width=80, height=40,
                                     fg_color="gray25", hover_color="gray30",
                                     command=self._open_log_file)
        self.log_btn.grid(row=0, column=3, padx=4)

        self.new_btn = ctk.CTkButton(bar, text="🔄 New Conversion", width=150, height=40,
                                     corner_radius=12, state="disabled",
                                     fg_color=ACCENT, hover_color="#2d7ab8",
                                     font=ctk.CTkFont(size=14, weight="bold"),
                                     command=self._reset_for_next)
        self.new_btn.grid(row=0, column=4, padx=(8, 0))

        self.progress = ctk.CTkProgressBar(bar, height=14, corner_radius=7)
        self.progress.grid(row=0, column=5, sticky="ew", padx=14)
        self.progress.set(0)

        self.percent_label = ctk.CTkLabel(bar, text="0%", width=48,
                                          font=ctk.CTkFont(size=14, weight="bold"))
        self.percent_label.grid(row=0, column=6)

        self.status_label = ctk.CTkLabel(bar, text="Ready", anchor="w", text_color="gray55",
                                         font=ctk.CTkFont(size=12))
        self.status_label.grid(row=1, column=0, columnspan=7, sticky="w", pady=(4, 0))

    # --- 6. log ----------------------------------------------------------
    def _build_log(self) -> None:
        self.log = ctk.CTkTextbox(self, corner_radius=12,
                                  font=ctk.CTkFont(family="Consolas", size=12))
        self.log.grid(row=5, column=0, sticky="nsew", padx=14, pady=(2, 14))
        self.grid_rowconfigure(4, weight=1)
        self.grid_rowconfigure(5, weight=2)
        self.log.configure(state="disabled")
        self._log("Welcome!  Select a folder of lecture files, choose a mode, then hit Convert.")

    # ----------------------------------------------------------- actions
    def _pick_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Select folder with lecture files")
        if not chosen:
            return
        self.input_dir = Path(chosen)
        self.folder_label.configure(text=str(self.input_dir))
        if self.output_dir is None:
            self._default_output()
        self._refresh_file_count()

    def _refresh_file_count(self) -> None:
        if self.input_dir is None:
            return
        files = find_files(self.input_dir, recursive=self.var_recursive.get())
        self.filecount_label.configure(text=f"📄 {len(files)} convertible file(s) found")
        for file in files[:12]:
            self._log(f"  • {file.relative_to(self.input_dir)}")
        if len(files) > 12:
            self._log(f"  … and {len(files) - 12} more")

    def _default_output(self) -> None:
        if self.input_dir is not None:
            self.output_dir = self.input_dir / "output"
            self.output_label.configure(text=f"→ {self.output_dir}")

    def _pick_output(self) -> None:
        chosen = filedialog.askdirectory(title="Select output folder")
        if chosen:
            self.output_dir = Path(chosen)
            self.output_label.configure(text=f"→ {self.output_dir}")

    def _collect_options(self) -> ConversionOptions:
        return ConversionOptions(
            recursive=self.var_recursive.get(),
            extract_images=self.var_images.get(),
            include_speaker_notes=self.var_notes.get(),
            ocr_enabled=self.var_ocr.get(),
            ai_enabled=self.var_ai.get(),
            ai_provider=self.provider_var.get(),
            ai_api_key=self.api_entry.get().strip(),
            merge_all=self.merge_mode,
        )

    def _start_conversion(self) -> None:
        if self.input_dir is None or not self.input_dir.exists():
            messagebox.showwarning("No folder", "Please select a folder first.")
            return
        if self.output_dir is None:
            self._default_output()
        if self.var_ai.get() and not self.api_entry.get().strip():
            messagebox.showwarning("AI enabled", "Enter an API key or disable AI enhancement.")
            return

        self.cancel_event.clear()
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.new_btn.configure(state="disabled")
        self.progress.set(0)
        self.percent_label.configure(text="0%")
        mode_text = "merged book" if self.merge_mode else "separate files"
        self.status_label.configure(text=f"Starting ({mode_text})…")

        options = self._collect_options()
        input_dir, output_dir = self.input_dir, self.output_dir
        self.worker = threading.Thread(
            target=self._run_conversion, args=(input_dir, output_dir, options), daemon=True)
        self.worker.start()

    def _run_conversion(self, input_dir: Path, output_dir: Path, options: ConversionOptions) -> None:
        try:
            results = convert_folder(
                input_dir, output_dir, options,
                progress_cb=lambda done, total, current:
                    self.progress_queue.put((done, total, current.name)),
                cancel_event=self.cancel_event,
                log_cb=lambda line: self.log_queue.put(line),
            )
            ok = sum(1 for r in results if r.success)
            self.log_queue.put(f"DONE:{ok}:{len(results)}:{output_dir}")
        except Exception as exc:  # surface unexpected errors in the UI
            self.log_queue.put(f"ERROR:{type(exc).__name__}: {exc}")

    def _cancel(self) -> None:
        self.cancel_event.set()
        self._log("Cancelling after the current file…")

    def _open_output(self) -> None:
        if self.output_dir and self.output_dir.exists():
            os.startfile(self.output_dir)  # Windows Explorer

    def _open_log_file(self) -> None:
        """Open today's persistent activity log in the default text editor."""
        from app import activity_log
        path = activity_log.today_log_path()
        if not path.exists():
            messagebox.showinfo("No log yet",
                                "The activity log will be created after your first conversion.")
            return
        os.startfile(path)

    def _reset_for_next(self) -> None:
        """Clear everything so the next batch can start without restarting the app."""
        # keep the selected folders (users usually convert another folder next),
        # but wipe all run state and messages
        self.cancel_event.clear()
        self.progress.set(0)
        self.percent_label.configure(text="0%")
        self.status_label.configure(text="Ready")
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.new_btn.configure(state="disabled")
        # drain any stale queue messages from the previous run
        for queue in (self.log_queue, self.progress_queue):
            while True:
                try:
                    queue.get_nowait()
                except Empty:
                    break
        # clear the log pane
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._log("Ready for the next conversion — press 🔃 Convert when you're set.")
        if self.input_dir is not None:
            self._refresh_file_count()

    # ------------------------------------------------------------ polling
    def _poll_queues(self) -> None:
        # drain progress first so the final DONE status (log queue) always wins
        try:
            while True:
                done, total, name = self.progress_queue.get_nowait()
                if total:
                    fraction = done / total
                    self.progress.set(fraction)
                    self.percent_label.configure(text=f"{round(fraction * 100)}%")
                self.status_label.configure(text=f"{done}/{total}  •  {name}")
        except Empty:
            pass
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line.startswith("DONE:"):
                    _, ok, total, out_dir = line.split(":", 3)
                    self._finish(ok=int(ok), total=int(total), out_dir=Path(out_dir))
                elif line.startswith("ERROR:"):
                    self._log(f"✗ {line[6:]}")
                    self._finish(failed=True)
                else:
                    self._log(line)
        except Empty:
            pass
        self.after(_POLL_MS, self._poll_queues)

    def _finish(self, ok: int | None = None, total: int | None = None,
                out_dir: Path | None = None, failed: bool = False) -> None:
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.new_btn.configure(state="normal")
        if out_dir:
            self.output_dir = out_dir
            self.open_btn.configure(state="normal")
        if failed:
            self.status_label.configure(text="✗ Failed — see log")
        elif ok is not None and total is not None:
            self.progress.set(1.0 if total else 0)
            self.percent_label.configure(text="100%" if total else "0%")
            self.status_label.configure(text=f"✅ Done: {ok}/{total} converted")
            self._log(f"All done — {ok}/{total} file(s) converted → {self.output_dir}")
            from app import activity_log
            self._log(f"📜 Full details saved to: {activity_log.today_log_path()}")
            self._log("Press 🔄 New Conversion to clear the screen for the next batch.")

    # ---------------------------------------------------------------- misc
    def _log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("pdf-to-md.converter")
        except Exception:
            pass
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
