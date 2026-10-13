"""Downloads the vision models on first use and verifies them by SHA-256 before loading."""

import hashlib
import logging
import os
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelFile:
    filename: str
    url: str
    sha256: str
    license: str


FACE_MODEL = ModelFile(
    "face_detection_yunet_2023mar.onnx",
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "MIT (OpenCV Zoo)",
)
OBJECT_MODEL = ModelFile(
    "yolox_nano.onnx",
    "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx",
    "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d",
    "Apache-2.0 (Megvii YOLOX)",
)
MODELS = (FACE_MODEL, OBJECT_MODEL)


class ModelError(Exception):
    pass


def models_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = base / "FlowSense" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(model: ModelFile, directory: Path | None = None) -> Path:
    """Return the path of a verified copy of `model`, downloading it if needed."""
    directory = directory or models_dir()
    target = directory / model.filename
    if target.exists() and _sha256(target) == model.sha256:
        return target

    logger.info("downloading %s", model.filename)
    fd, temp_name = tempfile.mkstemp(dir=directory, suffix=".part")
    os.close(fd)
    temp = Path(temp_name)
    try:
        with urllib.request.urlopen(model.url, timeout=60) as response, temp.open("wb") as out:
            while chunk := response.read(1 << 16):
                out.write(chunk)
        actual = _sha256(temp)
        if actual != model.sha256:
            raise ModelError(f"{model.filename} failed verification (sha256 {actual})")
        temp.replace(target)  # atomic: a half-downloaded file is never used
    except OSError as error:
        raise ModelError(f"could not download {model.filename}: {error}") from error
    finally:
        temp.unlink(missing_ok=True)
    return target


def ensure_models(directory: Path | None = None) -> tuple[Path, Path]:
    return ensure_model(FACE_MODEL, directory), ensure_model(OBJECT_MODEL, directory)
