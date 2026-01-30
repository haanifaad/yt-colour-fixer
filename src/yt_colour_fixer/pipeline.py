import argparse
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
import zipfile

import cv2
import numpy as np

from yt_colour_fixer.utils import ensure_dir, file_size_bytes, is_supported_video, run_command, setup_logger

ProgressCallback = Callable[[str, float], None]


@dataclass
class VideoMetadata:
    fps: float
    width: int
    height: int
    duration: float


class PipelineError(Exception):
    pass


class VideoPipeline:
    def __init__(self, input_path: Path, output_dir: Path, progress: Optional[ProgressCallback] = None):
        self.input_path = input_path
        self.output_dir = output_dir
        self.progress = progress
        self.work_dir = Path(tempfile.mkdtemp(prefix="yt_colour_fixer_"))
        self.log_path = self.output_dir / "processing.log"
        ensure_dir(self.output_dir)
        self.logger = setup_logger(self.log_path)

    def run(self) -> Path:
        self.logger.info("Starting pipeline with input %s", self.input_path)
        try:
            source_video = self._handle_input()
            metadata = self._probe_video(source_video)
            video_only, audio_only = self._split_video_audio(source_video)
            frames_dir = self.work_dir / "frames"
            ensure_dir(frames_dir)
            self._extract_frames(video_only, frames_dir)
            enhanced_frames_dir = self.work_dir / "enhanced_frames"
            ensure_dir(enhanced_frames_dir)
            self._enhance_frames(frames_dir, enhanced_frames_dir)
            enhanced_audio = self._enhance_audio(audio_only)
            final_video = self._rebuild_video(enhanced_frames_dir, enhanced_audio, metadata)
            final_output = self._maybe_zip_output(final_video)
            self.logger.info("Pipeline complete: %s", final_output)
            return final_output
        finally:
            shutil.rmtree(self.work_dir, ignore_errors=True)

    def _update_progress(self, message: str, value: float) -> None:
        self.logger.info("Progress: %s (%.2f)", message, value)
        if self.progress:
            self.progress(message, value)

    def _handle_input(self) -> Path:
        self._update_progress("Handling input", 0.05)
        if not self.input_path.exists():
            raise PipelineError("Input path does not exist.")

        if self.input_path.suffix.lower() == ".zip":
            extract_dir = self.work_dir / "extracted"
            ensure_dir(extract_dir)
            with zipfile.ZipFile(self.input_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
            largest_video = None
            largest_size = -1
            for path in extract_dir.rglob("*"):
                if path.is_file() and is_supported_video(path):
                    size = file_size_bytes(path)
                    if size > largest_size:
                        largest_size = size
                        largest_video = path
            if not largest_video:
                raise PipelineError("No supported video found in ZIP.")
            return largest_video

        if is_supported_video(self.input_path):
            return self.input_path

        raise PipelineError("Unsupported input format.")

    def _probe_video(self, video_path: Path) -> VideoMetadata:
        self._update_progress("Probing video metadata", 0.1)
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,duration",
            "-of",
            "json",
            str(video_path),
        ]
        import subprocess
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise PipelineError("ffprobe failed to read metadata.")
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        rate = stream.get("r_frame_rate", "0/1")
        num, den = rate.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0
        duration = float(stream.get("duration", 0.0))
        return VideoMetadata(fps=fps, width=int(stream["width"]), height=int(stream["height"]), duration=duration)

    def _split_video_audio(self, video_path: Path) -> tuple[Path, Path]:
        self._update_progress("Splitting video/audio", 0.2)
        video_only = self.work_dir / "video_only.mkv"
        audio_only = self.work_dir / "audio_only.m4a"
        run_command([
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-an",
            "-c",
            "copy",
            str(video_only),
        ], self.logger)
        run_command([
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0:a:0",
            "-vn",
            "-c",
            "copy",
            str(audio_only),
        ], self.logger)
        return video_only, audio_only

    def _extract_frames(self, video_path: Path, frames_dir: Path) -> None:
        self._update_progress("Extracting frames", 0.3)
        run_command([
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vsync",
            "0",
            "-start_number",
            "1",
            str(frames_dir / "frame_%06d.png"),
        ], self.logger)

    def _enhance_frames(self, frames_dir: Path, output_dir: Path) -> None:
        frames = sorted(frames_dir.glob("frame_*.png"))
        total = len(frames)
        if total == 0:
            raise PipelineError("No frames extracted.")
        for index, frame_path in enumerate(frames, start=1):
            image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if image is None:
                raise PipelineError(f"Failed to read frame {frame_path}.")
            enhanced = enhance_frame(image)
            output_path = output_dir / frame_path.name
            cv2.imwrite(str(output_path), enhanced)
            if index % 50 == 0 or index == total:
                self._update_progress("Enhancing frames", 0.3 + 0.5 * (index / total))

    def _enhance_audio(self, audio_path: Path) -> Path:
        self._update_progress("Enhancing audio", 0.82)
        enhanced_audio = self.work_dir / "enhanced_audio.wav"
        run_command([
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-af",
            "loudnorm=I=-14:TP=-1:LRA=11,acompressor=threshold=-18dB:ratio=2:attack=20:release=250",
            "-acodec",
            "pcm_s16le",
            str(enhanced_audio),
        ], self.logger)
        return enhanced_audio

    def _rebuild_video(self, frames_dir: Path, audio_path: Path, metadata: VideoMetadata) -> Path:
        self._update_progress("Rebuilding video", 0.9)
        output_path = self.output_dir / "final_video.mp4"
        run_command([
            "ffmpeg",
            "-y",
            "-framerate",
            f"{metadata.fps:.3f}",
            "-i",
            str(frames_dir / "frame_%06d.png"),
            "-i",
            str(audio_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ], self.logger)
        return output_path

    def _maybe_zip_output(self, video_path: Path) -> Path:
        self._update_progress("Finalizing output", 1.0)
        size_limit = 2 * 1024 * 1024 * 1024
        if file_size_bytes(video_path) <= size_limit:
            return video_path
        zip_path = video_path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(video_path, arcname=video_path.name)
        return zip_path


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def enhance_frame(frame_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    l = lab[:, :, 0] / 255.0
    a = lab[:, :, 1] - 128.0
    b = lab[:, :, 2] - 128.0

    hue = (np.arctan2(b, a) / (2 * math.pi)) % 1.0
    chroma = np.sqrt(a ** 2 + b ** 2) / 128.0

    base_mod = (
        0.08 * np.sin(2 * math.pi * hue) +
        0.05 * np.sin(4 * math.pi * hue + 1.2)
    )

    shadow_weight = smoothstep(0.0, 0.15, l)
    highlight_weight = 1.0 - smoothstep(0.85, 1.0, l)
    mid_weight = shadow_weight * highlight_weight

    adjustment = base_mod * chroma * mid_weight
    adjustment = cv2.GaussianBlur(adjustment, (0, 0), 1.0)

    l_enhanced = np.clip(l * (1.0 + adjustment), 0.0, 1.0)
    lab[:, :, 0] = l_enhanced * 255.0
    lab[:, :, 1] = np.clip(a + 128.0, 0, 255)
    lab[:, :, 2] = np.clip(b + 128.0, 0, 255)

    enhanced_bgr = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    return enhanced_bgr


def main() -> None:
    parser = argparse.ArgumentParser(description="YT Colour Fixer pipeline")
    parser.add_argument("--input", required=True, type=Path, help="Input video or ZIP")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output directory")
    args = parser.parse_args()

    pipeline = VideoPipeline(args.input, args.output_dir)
    pipeline.run()


if __name__ == "__main__":
    main()
