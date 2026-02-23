# Audio Condenser

**Turn videos and podcasts into dense listening practice for language learning.** Give it a media file and an SRT or VTT file--it keeps only the parts where someone is speaking (using the subtitle timestamps) and outputs one condensed MP3 with the silence removed.

Use it to make **comprehensible input**[^1] more efficient: shorter files with less dead air, so you can loop dialogue, shadow lines, or just hear more target-language speech per minute. Great for drama, interviews, vlogs, or any content you already have subtitles for.

**Typical use:** Export SRT/VTT from iQiyi, Netflix, etc. or download them online; run Audio Condenser; get an MP3 of only the spoken parts for commutes, shadowing, or repeated listening without skipping through silence.

---

## Requirements

- **Python 3.10+** (standard library only for CLI)
- **FFmpeg**: must be installed and on your PATH
- **GUI (optional):** tkinter (often separate on Linux/Homebrew Python) and optionally [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) for drag-and-drop

---

## Installing FFmpeg

| Platform | Command |
|----------|--------|
| **macOS** | `brew install ffmpeg` |
| **Windows** | `choco install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) |
| **Linux** | `sudo apt install ffmpeg` (Debian/Ubuntu) or your distro’s package manager |

---

## Quick start (command line)

The default interface is the **command line** (no tkinter or extra packages needed).

```bash
# Condense a video with its subtitle file (output: "episode — condensed.mp3" in same folder)
python3 audio-condenser.py episode.mp4 episode.srt

# Put the listening practice file in a dedicated folder
python3 audio-condenser.py dialogue.mkv subs.vtt -o ./practice/dialogue-condensed.mp3

# If words get cut off at the start/end of lines, add a bit of padding
python3 audio-condenser.py episode.mp4 episode.srt --padding 0.12 --bitrate 256
```

Progress is printed to stderr; the final path is printed to stdout.

---

## Graphical interface (optional)

If you want a GUI, run with `--gui`:

```bash
python3 audio-condenser.py --gui
```

**If you see “No module named '_tkinter'”** (common with Homebrew Python on macOS):

- **Use the CLI** (no GUI needed):  
  `python3 audio-condenser.py <media> <subtitles>` as above.
- **Or install tkinter** for your Python version, e.g. on macOS:  
  `brew install python-tk@3.14` (match your Python version).

For drag-and-drop in the GUI, install:  
`pip install tkinterdnd2`

---

## Supported formats

| Input | Extensions |
|-------|------------|
| **Media** | MP4, MKV, MOV, M4V, MP3 |
| **Subtitles** | SRT, VTT |
| **Output** | MP3 only |

---

## CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `-o`, `--output` | &lt;media stem&gt; — condensed.mp3 | Output MP3 path |
| `--output-dir` | (same as media) | Output directory when not using `-o` |
| `--padding` | 0.08 | Extra seconds before/after each segment; increase (e.g. 0.12) if words are cut off |
| `--merge-gap` | 0.05 | Merge subtitle segments closer than this (seconds) |
| `--bitrate` | 192 | MP3 bitrate (64–320 kbps) |
| `--gui` | — | Launch the graphical interface instead |

---

## How it works

1. Parses the subtitle file (SRT or VTT) for start/end timestamps (each line of dialogue).
2. Merges segments that are very close together (within “Merge gap”) so you don’t get tiny gaps between phrases.
3. Extracts each segment from the media with a small “Padding” before and after so words aren’t clipped.
4. Concatenates the segments and encodes one MP3 — speech only, no silence.

All processing is done locally with FFmpeg; nothing is sent to the cloud.

[^1]: Loaded term... but I am not going to debate Stephen Krashen in a README.

