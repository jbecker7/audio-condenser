#!/usr/bin/env bash
# Run Audio Condenser. With no args: try GUI; with media+subs: CLI.
# Examples: ./run.sh  |  ./run.sh video.mp4 subs.srt  |  ./run.sh --gui
cd "$(dirname "$0")"
exec python3 audio-condenser.py "$@"
