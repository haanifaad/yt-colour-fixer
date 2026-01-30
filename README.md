# YT Colour Fixer

Desktop export-only tool for preprocessing large videos for quality enhancement. The pipeline follows a strict order: file handling, split video/audio, extract frames, per-color LAB enhancement, audio enhancement, rebuild video, and auto-zip output.

## Features
- ZIP-aware input handling with largest-video detection.
- Disk-based frame extraction and processing (no full video in RAM).
- Per-color brightness enhancement in LAB color space with smooth transitions.
- YouTube-safe audio loudness normalization and light compression.
- Rebuilds video with original FPS and Rec.709 metadata.
- Optional auto-zip when output is very large.

## Requirements
- Python 3.11+
- FFmpeg + ffprobe available on PATH
- Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Run (GUI)
```bash
python -m yt_colour_fixer.app
```

## Run (CLI)
```bash
python -m yt_colour_fixer.pipeline --input /path/to/video_or_zip --output-dir /path/to/output
```

## Notes
- Supported input formats: mp4, mov, mkv, zip.
- Output is written to the selected output directory.
- Large outputs are automatically zipped when they exceed the default size threshold (2 GiB).
