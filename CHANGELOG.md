# Changelog

All notable changes to Flow are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `verify()` verb: metadata + content checks, re-loop friendly diff
- `executor.py`: trim/split/ripple/cut/remove_object action support
- `planner.py`: 11 intent patterns + `cuts_to_trims()` helper
- `planner.py` pattern intents: `keep_only:<label>`, `remove_label:<label>`,
  `tagged_scenes:<tag>`, `first_n:<sec>`, `last_n:<sec>`, `trim:<start>-<end>`
- `video_parser.py`: 4-phase progressive build
  - Phase 1: ffprobe metadata + ffmpeg scene detection
  - Phase 2: faster-whisper transcripts (+ optional diarization)
  - Phase 3: CLIP zero-shot tags + YOLOv8 + EasyOCR + OpenCV YuNet faces
  - Phase 4: VAD silencedetect + per-event RMS via astats + librosa beats
    + wav2vec2-superb-er emotion (1 classification per video)
- `_ffmpeg.py`: bundled ffmpeg/ffprobe discovery (no PATH dep)
- `__main__.py` CLI: `py -m flow_core <video_or_folder> [options]`
- `process_video()` / `process_folder()` / `build_graph_smart()` /
  `auto_depth()`: smart entry points with auto-save + skip-if-done
- `cuts_to_trims()` helper: convert cut actions to trim actions
- Apache 2.0 LICENSE
- PyPI-ready `pyproject.toml` with `[vision]`, `[audio]`, `[all]` extras
- README, .gitignore, this CHANGELOG

### Changed
- ProjectGraph: `AudioSegment` now has `start`/`end` (was `time`-only)
- ProjectGraph: `DetectedObject` now has `label`, `confidence`, `bbox`,
  `attributes` fields (filled by YOLO, faces, OCR, CLIP)
- Project structure: `crates/flow-core/` → `python/`

## [0.2.0] - Earlier sessions

### Added
- Initial 5-verb API: `observe` / `query` / `plan` / `execute` / `verify`
- Typed `ProjectGraph` with DAG edges
- First integration of MobileCLIP-S2 for visual tags
- First integration of faster-whisper for transcripts

## [0.1.0] - Initial

### Added
- Initial scaffold: scene detection, metadata, basic graph
