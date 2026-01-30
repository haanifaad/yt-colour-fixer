import logging
import os
import subprocess
from pathlib import Path

LOGGER_NAME = "yt_colour_fixer"


def setup_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def run_command(command: list[str], logger: logging.Logger) -> None:
    logger.info("Running command: %s", " ".join(command))
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout.strip())
    if result.stderr:
        logger.info(result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with code {result.returncode}: {' '.join(command)}")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def is_supported_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".mkv"}


def file_size_bytes(path: Path) -> int:
    return os.path.getsize(path)
