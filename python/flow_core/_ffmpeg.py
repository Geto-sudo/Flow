"""FFmpeg binary discovery — uses imageio-ffmpeg's bundled binaries.

This lets Flow work without requiring ffmpeg/ffprobe on PATH.
Works on Windows, macOS, Linux.
"""
import os
import sys
import glob
import imageio_ffmpeg

# imageio-ffmpeg ships a versioned binary like ffmpeg-win-x86_64-v7.1.exe
# We resolve it dynamically and add our manually-downloaded ffprobe alongside.
_BIN_DIR = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())


def _find_binary(name: str) -> str:
    """Find a binary in _BIN_DIR by base name, ignoring version suffix.

    Looks for: name (e.g. ffmpeg.exe), name-* (versioned).
    Falls back to bare name (assumes PATH).
    """
    patterns = [name, name.split(".")[0] + "-*"]  # ffmpeg.exe, ffmpeg-*
    for pat in patterns:
        matches = glob.glob(os.path.join(_BIN_DIR, pat + (".exe" if sys.platform == "win32" else "")))
        if matches:
            return matches[0]
        # Also try without extension
        matches = glob.glob(os.path.join(_BIN_DIR, pat))
        if matches:
            return matches[0]
    return name  # PATH fallback


def ffmpeg_path() -> str:
    """Path to ffmpeg binary (bundled, no PATH needed)."""
    return _find_binary("ffmpeg")


def ffprobe_path() -> str:
    """Path to ffprobe binary. If not bundled, falls back to PATH lookup."""
    return _find_binary("ffprobe")
