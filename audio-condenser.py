#!/usr/bin/env python3
"""
Audio Condenser — Build a condensed MP3 from video/audio using subtitle timestamps.
Keeps only the parts where subtitles appear (speech), drops silence.

Run from the command line (no extra deps) or with --gui for the graphical interface (requires tkinter).
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Supported formats
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".m4v", ".mp3"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
DEFAULT_PADDING = 0.08
DEFAULT_MERGE_GAP = 0.05
DEFAULT_BITRATE = 192


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _timestamp_to_sec(t: str) -> float:
    """Convert SRT/VTT timestamp (HH:MM:SS,mmm or HH:MM:SS.mmm) to seconds."""
    h, m, rest = t.split(":")
    s, ms = rest.replace(",", ".").split(".")[:2]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def parse_srt_intervals(path: Path) -> list[tuple[float, float]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pairs = re.findall(
        r"(\d\d:\d\d:\d\d[,.]\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d[,.]\d\d\d)", text
    )
    return [(_timestamp_to_sec(s), _timestamp_to_sec(e)) for s, e in pairs]


def parse_vtt_intervals(path: Path) -> list[tuple[float, float]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pairs = re.findall(
        r"(\d{2}:\d{2}:\d{2}\.\d{2,3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{2,3})", text
    )
    return [(_timestamp_to_sec(s), _timestamp_to_sec(e)) for s, e in pairs]


def parse_subtitle_intervals(path: Path) -> list[tuple[float, float]]:
    """Parse SRT or VTT; return list of (start_sec, end_sec)."""
    if path.suffix.lower() == ".vtt":
        return parse_vtt_intervals(path)
    return parse_srt_intervals(path)


def merge_intervals(
    intervals: list[tuple[float, float]], merge_gap: float
) -> list[tuple[float, float]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s - merged[-1][1] > merge_gap:
            merged.append([s, e])
        else:
            merged[-1][1] = max(merged[-1][1], e)
    return [(s, e) for s, e in merged]


def clean_stem(stem: str) -> str:
    s = re.sub(r"\[.*?\]", "", stem)
    s = re.sub(r"\(.*?downsub.*?\)", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(1080p|720p|480p|WEB[- ]DL|WEBRip|BluRay|x264|x265|H\.?264|H\.?265)\b",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+", " ", s).strip(" -_")
    return s if s else stem


def default_output_path(media_path: Path, out_dir: Path | None) -> Path:
    base = clean_stem(media_path.stem)
    target_dir = out_dir if out_dir else media_path.parent
    return target_dir / f"{base} — condensed.mp3"


def open_folder(path: Path) -> None:
    folder = str(path.parent)
    if sys.platform == "darwin":
        subprocess.run(["open", folder], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", folder], check=False)
    else:
        subprocess.run(["xdg-open", folder], check=False)


def run_condense(
    media: Path,
    subtitles: Path,
    out_mp3: Path,
    padding: float,
    merge_gap: float,
    bitrate_kbps: int,
    progress_cb,
    log_cb,
) -> None:
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg not found. Install it (e.g. brew install ffmpeg).")
    if not media.exists():
        raise FileNotFoundError(f"Media not found: {media}")
    if not subtitles.exists():
        raise FileNotFoundError(f"Subtitles not found: {subtitles}")

    intervals = parse_subtitle_intervals(subtitles)
    if not intervals:
        raise RuntimeError("No time intervals found in the subtitle file.")

    merged = merge_intervals(intervals, merge_gap)
    work_dir = out_mp3.parent / f".condense_work_{out_mp3.stem}"
    parts_dir = work_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    def ffmpeg(args: list) -> None:
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "ffmpeg failed")

    total = len(merged)
    part_files = []
    for i, (s, e) in enumerate(merged):
        start = max(0.0, s - padding)
        end = e + padding
        part = parts_dir / f"part_{i:05d}.wav"
        part_files.append(part)
        ffmpeg([
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(media),
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            str(part),
        ])
        progress_cb(i + 1, total)

    concat_file = work_dir / "concat.txt"
    with concat_file.open("w", encoding="utf-8") as f:
        for p in part_files:
            f.write(f"file '{p.as_posix()}'\n")

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    log_cb("Stitching and encoding MP3…")
    ffmpeg([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-acodec", "libmp3lame", "-b:a", f"{bitrate_kbps}k",
        str(out_mp3),
    ])
    try:
        shutil.rmtree(work_dir)
    except OSError:
        pass


# --- CLI ---

def _cli_main(args: argparse.Namespace) -> None:
    media = Path(args.media).resolve()
    subtitles = Path(args.subtitles).resolve()
    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    out_mp3 = Path(args.output).resolve() if args.output else default_output_path(media, out_dir)

    if not out_mp3.name.lower().endswith(".mp3"):
        sys.exit("Output path must end with .mp3")

    def progress_cb(done: int, total: int) -> None:
        print(f"  Segment {done}/{total}", end="\r", file=sys.stderr)

    def log_cb(msg: str) -> None:
        print(msg, file=sys.stderr)

    print(f"Media: {media}", file=sys.stderr)
    print(f"Subs:  {subtitles}", file=sys.stderr)
    print(f"Out:   {out_mp3}", file=sys.stderr)
    run_condense(
        media, subtitles, out_mp3,
        args.padding, args.merge_gap, args.bitrate,
        progress_cb, log_cb,
    )
    print("", file=sys.stderr)
    print(f"Created: {out_mp3}")


def _parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    p = argparse.ArgumentParser(
        description="Condense video/audio to speech-only MP3 using SRT or VTT timestamps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s talk.mp4 talk.srt
  %(prog)s lecture.mkv subs.vtt -o ./output/lecture-condensed.mp3
  %(prog)s --gui
""" % {"prog": Path(sys.argv[0]).name or "audio-condenser.py"},
    )
    p.add_argument("media", nargs="?", help="Video or audio file (MP4, MKV, MP3, etc.)")
    p.add_argument("subtitles", nargs="?", help="Subtitle file (SRT or VTT)")
    p.add_argument("-o", "--output", help="Output MP3 path (default: <media stem> — condensed.mp3)")
    p.add_argument("--output-dir", help="Output directory (used only if -o is not set)")
    p.add_argument("--padding", type=float, default=DEFAULT_PADDING, metavar="SEC",
                    help=f"Padding around each segment (default: {DEFAULT_PADDING})")
    p.add_argument("--merge-gap", type=float, default=DEFAULT_MERGE_GAP, metavar="SEC",
                    help=f"Merge segments closer than this (default: {DEFAULT_MERGE_GAP})")
    p.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE, metavar="K",
                    help=f"MP3 bitrate in kbps (default: {DEFAULT_BITRATE})")
    p.add_argument("--gui", action="store_true", help="Launch the graphical interface (requires tkinter)")
    return p, p.parse_args()


# --- GUI (optional, only imported when --gui) ---

def _gui_main() -> None:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    DND_AVAILABLE = False
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        DND_AVAILABLE = True
    except ImportError:
        TkinterDnD = None
        DND_FILES = None

    class App:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("Audio Condenser")
            self.root.minsize(720, 560)
            self.root.geometry("820x600")

            self.media_var = tk.StringVar()
            self.subs_var = tk.StringVar()
            self.out_var = tk.StringVar()
            self.out_dir_var = tk.StringVar()
            self.padding_var = tk.DoubleVar(value=DEFAULT_PADDING)
            self.merge_gap_var = tk.DoubleVar(value=DEFAULT_MERGE_GAP)
            self.bitrate_var = tk.IntVar(value=DEFAULT_BITRATE)
            self.status_var = tk.StringVar(value="Ready.")
            self.progress_var = tk.DoubleVar(value=0.0)

            self._build_ui()
            self._maybe_enable_dnd()
            self._update_run_button()

            if not have_ffmpeg():
                messagebox.showwarning(
                    "FFmpeg not found",
                    "ffmpeg was not found on your PATH.\n\n"
                    "Install it first, e.g.:\n  macOS: brew install ffmpeg\n  Windows: choco install ffmpeg",
                )

        def _build_ui(self) -> None:
            pad = {"padx": 12, "pady": 8}
            main = ttk.Frame(self.root, padding=12)
            main.pack(fill="both", expand=True)

            title = ttk.Label(
                main,
                text="Condense audio by subtitle timestamps",
                font=("Helvetica", 14, "bold"),
            )
            title.pack(anchor="w", **pad)

            subtitle = ttk.Label(
                main,
                text="Drop a video/audio file and an SRT or VTT file, or use Browse. Output: one MP3 with only the spoken parts.",
                font=("Helvetica", 11),
                foreground="gray",
            )
            subtitle.pack(anchor="w", pady=(0, 4))

            self.drop = ttk.Label(
                main,
                text="Drop media + subtitles here" + (" (or use Browse below)" if not DND_AVAILABLE else ""),
                relief="solid",
                padding=24,
                anchor="center",
                font=("Helvetica", 12),
            )
            self.drop.pack(fill="x", pady=8)

            grid = ttk.Frame(main)
            grid.pack(fill="x", **pad)

            ttk.Label(grid, text="Media:", width=14, anchor="w").grid(row=0, column=0, sticky="w", pady=4)
            ttk.Entry(grid, textvariable=self.media_var, width=60).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
            ttk.Button(grid, text="Browse…", command=self._pick_media).grid(row=0, column=2, pady=4)

            ttk.Label(grid, text="Subtitles:", width=14, anchor="w").grid(row=1, column=0, sticky="w", pady=4)
            ttk.Entry(grid, textvariable=self.subs_var, width=60).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
            ttk.Button(grid, text="Browse…", command=self._pick_subs).grid(row=1, column=2, pady=4)

            ttk.Label(grid, text="Output folder:", width=14, anchor="w").grid(row=2, column=0, sticky="w", pady=4)
            ttk.Entry(grid, textvariable=self.out_dir_var, width=60).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
            ttk.Button(grid, text="Choose…", command=self._pick_out_dir).grid(row=2, column=2, pady=4)

            ttk.Label(grid, text="Output MP3:", width=14, anchor="w").grid(row=3, column=0, sticky="w", pady=4)
            ttk.Entry(grid, textvariable=self.out_var, width=60).grid(row=3, column=1, sticky="ew", padx=6, pady=4)
            ttk.Button(grid, text="Set default", command=self._set_default_output).grid(row=3, column=2, pady=4)

            for var in (self.media_var, self.subs_var, self.out_var):
                var.trace_add("write", lambda *a: self._update_run_button())
            grid.columnconfigure(1, weight=1)

            opts = ttk.LabelFrame(main, text="Options", padding=8)
            opts.pack(fill="x", **pad)

            opt_row = ttk.Frame(opts)
            opt_row.pack(fill="x")
            ttk.Label(opt_row, text="Padding (sec):").pack(side="left", padx=(0, 6))
            ttk.Spinbox(opt_row, from_=0.0, to=0.5, increment=0.01, textvariable=self.padding_var, width=8).pack(side="left", padx=(0, 16))
            ttk.Label(opt_row, text="Merge gap (sec):").pack(side="left", padx=(0, 6))
            ttk.Spinbox(opt_row, from_=0.0, to=0.5, increment=0.01, textvariable=self.merge_gap_var, width=8).pack(side="left", padx=(0, 16))
            ttk.Label(opt_row, text="Bitrate (kbps):").pack(side="left", padx=(0, 6))
            ttk.Spinbox(opt_row, from_=64, to=320, increment=16, textvariable=self.bitrate_var, width=8).pack(side="left")

            btns = ttk.Frame(main)
            btns.pack(fill="x", **pad)
            self.run_btn = ttk.Button(btns, text="Create condensed MP3", command=self._on_run)
            self.run_btn.pack(side="left")
            ttk.Button(btns, text="Open output folder", command=self._open_output_folder).pack(side="left", padx=8)

            ttk.Separator(main, orient="horizontal").pack(fill="x", pady=8)
            ttk.Progressbar(main, variable=self.progress_var, maximum=100).pack(fill="x", **pad)
            ttk.Label(main, textvariable=self.status_var).pack(anchor="w", **pad)

            log_frame = ttk.LabelFrame(main, text="Log", padding=4)
            log_frame.pack(fill="both", expand=True, **pad)
            self.log = tk.Text(log_frame, height=8, wrap="word", font=("Menlo", 11), padx=6, pady=6)
            self.log.pack(fill="both", expand=True)
            self.log.insert("end", "Tip: If words get cut off, increase Padding to about 0.10–0.12.\n")

        def _maybe_enable_dnd(self) -> None:
            if not DND_AVAILABLE:
                return
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self._on_drop)
            self.drop.configure(text="Drop MP4 / MP3 + SRT / VTT here")

        def _update_run_button(self) -> None:
            media = self.media_var.get().strip()
            subs = self.subs_var.get().strip()
            out = self.out_var.get().strip()
            ready = (
                media and Path(media).exists()
                and subs and Path(subs).exists()
                and out and out.lower().endswith(".mp3")
            )
            self.run_btn.configure(state="normal" if ready else "disabled")

        def _log(self, msg: str) -> None:
            self.log.insert("end", msg.rstrip() + "\n")
            self.log.see("end")

        def _pick_media(self) -> None:
            p = filedialog.askopenfilename(
                filetypes=[
                    ("Video / Audio", " ".join(f"*{e}" for e in sorted(MEDIA_EXTENSIONS))),
                    ("Video", "*.mp4 *.mkv *.mov *.m4v"),
                    ("Audio", "*.mp3"),
                    ("All files", "*.*"),
                ],
            )
            if p:
                self.media_var.set(p)
                self._auto_match_subs()
                self._set_default_output()

        def _pick_subs(self) -> None:
            p = filedialog.askopenfilename(
                filetypes=[("Subtitles (SRT / VTT)", "*.srt *.vtt"), ("All files", "*.*")],
            )
            if p:
                self.subs_var.set(p)
                self._set_default_output()

        def _pick_out_dir(self) -> None:
            p = filedialog.askdirectory()
            if p:
                self.out_dir_var.set(p)
                self._set_default_output()

        def _set_default_output(self) -> None:
            media = Path(self.media_var.get()) if self.media_var.get() else None
            if not media or not media.exists():
                return
            out_dir = Path(self.out_dir_var.get()) if self.out_dir_var.get() else None
            self.out_var.set(str(default_output_path(media, out_dir)))

        def _auto_match_subs(self) -> None:
            try:
                media = Path(self.media_var.get())
                if not media.exists():
                    return
                for ext in SUBTITLE_EXTENSIONS:
                    cand = media.with_suffix(ext)
                    if cand.exists():
                        self.subs_var.set(str(cand))
                        return
                subs = []
                for ext in SUBTITLE_EXTENSIONS:
                    subs.extend(media.parent.glob(f"*{ext}"))
                if not subs:
                    return
                def score(p: Path) -> int:
                    return sum(1 for x, y in zip(media.stem.lower(), p.stem.lower()) if x == y)
                best = max(subs, key=score)
                if score(best) >= max(6, len(media.stem) // 4):
                    self.subs_var.set(str(best))
            except Exception:
                pass

        def _on_drop(self, event) -> None:
            raw = event.data
            paths = []
            cur, in_brace = "", False
            for ch in raw:
                if ch == "{":
                    in_brace, cur = True, ""
                elif ch == "}":
                    in_brace = False
                    if cur:
                        paths.append(cur)
                        cur = ""
                elif ch == " " and not in_brace:
                    if cur:
                        paths.append(cur)
                        cur = ""
                else:
                    cur += ch
            if cur:
                paths.append(cur)
            for p in paths:
                pth = Path(p)
                if pth.suffix.lower() in SUBTITLE_EXTENSIONS:
                    self.subs_var.set(str(pth))
                elif pth.suffix.lower() in MEDIA_EXTENSIONS:
                    self.media_var.set(str(pth))
            self._auto_match_subs()
            self._set_default_output()

        def _open_output_folder(self) -> None:
            out = self.out_var.get().strip()
            if out:
                open_folder(Path(out))

        def _on_run(self) -> None:
            media = Path(self.media_var.get().strip())
            subs = Path(self.subs_var.get().strip())
            out = Path(self.out_var.get().strip())

            if not media.exists():
                messagebox.showerror("Missing media", "Please select a valid media file.")
                return
            if not subs.exists():
                messagebox.showerror("Missing subtitles", "Please select a valid SRT or VTT file.")
                return
            if not out.name.lower().endswith(".mp3"):
                messagebox.showerror("Invalid output", "Output path must end with .mp3")
                return

            try:
                padding = float(self.padding_var.get())
                merge_gap = float(self.merge_gap_var.get())
                bitrate = int(self.bitrate_var.get())
            except (ValueError, tk.TclError):
                messagebox.showerror("Invalid options", "Padding, merge gap and bitrate must be valid numbers.")
                return
            if not (0 <= padding <= 0.5 and 0 <= merge_gap <= 0.5):
                messagebox.showerror("Invalid options", "Padding and merge gap must be between 0 and 0.5.")
                return
            if not 64 <= bitrate <= 320:
                messagebox.showerror("Invalid options", "Bitrate must be between 64 and 320.")
                return

            self.run_btn.configure(state="disabled")
            self.progress_var.set(0)
            self.status_var.set("Working…")
            self._log(f"Media: {media}")
            self._log(f"Subs:  {subs}")
            self._log(f"Out:   {out}")

            def progress_cb(done: int, total: int) -> None:
                self.root.after(0, lambda: self.progress_var.set(100.0 * done / total))
                self.root.after(0, lambda: self.status_var.set(f"Cutting segments: {done}/{total}"))

            def log_cb(msg: str) -> None:
                self.root.after(0, lambda: self._log(msg))

            def worker() -> None:
                import threading
                try:
                    run_condense(media, subs, out, padding, merge_gap, bitrate, progress_cb, log_cb)
                    self.root.after(0, lambda: self.progress_var.set(100))
                    self.root.after(0, lambda: self.status_var.set("Done."))
                    self.root.after(0, lambda: self._log("Done."))
                    self.root.after(0, lambda: messagebox.showinfo("Done", f"Created:\n{out}"))
                except Exception as e:
                    self.root.after(0, lambda: self.status_var.set("Error."))
                    self.root.after(0, lambda: self._log(f"Error: {e}"))
                    self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
                finally:
                    self.root.after(0, lambda: self.run_btn.configure(state="normal"))

            threading.Thread(target=worker, daemon=True).start()

    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    try:
        ttk.Style(root).theme_use("aqua")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


def main() -> None:
    parser, args = _parse_args()

    # CLI when both media and subtitles are given
    if args.media and args.subtitles:
        _cli_main(args)
        return

    # Otherwise try GUI (explicit --gui or no arguments)
    try:
        _gui_main()
    except ImportError as e:
        if "_tkinter" in str(e) or "tkinter" in str(e).lower():
            print("GUI requires tkinter, which is not available in this Python install.", file=sys.stderr)
            print("", file=sys.stderr)
            print("Use the command line instead:", file=sys.stderr)
            print("  python3 audio-condenser.py <media> <subtitles> [-o output.mp3]", file=sys.stderr)
            print("", file=sys.stderr)
            print("To get the GUI on macOS with Homebrew Python, install python-tk:", file=sys.stderr)
            print("  brew install python-tk@3.14   # or your Python version", file=sys.stderr)
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
