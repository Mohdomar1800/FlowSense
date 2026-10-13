"""Model download + checksum verification, using file:// URLs instead of the network."""

import hashlib

import pytest

from agent.camera.models import ModelError, ModelFile, ensure_model


def _model(source, sha256):
    return ModelFile("model.onnx", source.as_uri(), sha256, "test")


def test_downloads_and_verifies(tmp_path):
    source = tmp_path / "source.onnx"
    source.write_bytes(b"weights")
    target_dir = tmp_path / "models"
    target_dir.mkdir()
    model = _model(source, hashlib.sha256(b"weights").hexdigest())

    path = ensure_model(model, target_dir)
    assert path.read_bytes() == b"weights"

    source.unlink()  # a verified local copy is reused without downloading again
    assert ensure_model(model, target_dir) == path


def test_rejects_tampered_download_and_leaves_nothing_behind(tmp_path):
    source = tmp_path / "source.onnx"
    source.write_bytes(b"something else")
    target_dir = tmp_path / "models"
    target_dir.mkdir()
    model = _model(source, hashlib.sha256(b"weights").hexdigest())

    with pytest.raises(ModelError, match="failed verification"):
        ensure_model(model, target_dir)
    assert list(target_dir.iterdir()) == []  # no partial or unverified file is kept


def test_replaces_a_corrupted_local_copy(tmp_path):
    source = tmp_path / "source.onnx"
    source.write_bytes(b"weights")
    target_dir = tmp_path / "models"
    target_dir.mkdir()
    (target_dir / "model.onnx").write_bytes(b"corrupt")
    model = _model(source, hashlib.sha256(b"weights").hexdigest())
    assert ensure_model(model, target_dir).read_bytes() == b"weights"


def test_unreachable_source_raises_model_error(tmp_path):
    model = ModelFile("model.onnx", (tmp_path / "missing.onnx").as_uri(), "0" * 64, "test")
    with pytest.raises(ModelError, match="could not download"):
        ensure_model(model, tmp_path)
