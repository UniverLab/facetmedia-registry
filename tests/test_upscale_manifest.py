"""The upscale manifest, its index entry, README row, and uv lockfile."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "upscale"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")

EXPECTED_MODEL_ID = "realesrgan-ncnn-vulkan-20220424-ubuntu"
EXPECTED_MODEL_SHA256 = "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96"
EXPECTED_MODEL_BYTES = 46931474
EXPECTED_RAM_GB = 2
EXPECTED_DISK_GB = 0.2


def test_upscale_is_registered_in_index_and_readme() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "upscale" in names
    assert "| image | upscale |" in README


def test_package_metadata_and_requirements() -> None:
    assert MANIFEST["name"] == "upscale"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["requires_facet"] == ">=0.1.0b2,<0.2"
    assert MANIFEST["protocol"] == 1
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["provider"] == "Xintao Wang · Real-ESRGAN ncnn Vulkan"
    assert MANIFEST["tool_name"] == "Real-ESRGAN"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert MANIFEST["requirements"] == {
        "gpu": False,
        "ram_gb": EXPECTED_RAM_GB,
        "disk_gb": EXPECTED_DISK_GB,
        "exclusive": True,
        "platforms": ["linux"],
    }


def test_licenses_and_pinned_model() -> None:
    licenses = [(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]]
    assert licenses == [
        ("realesrgan-ncnn-vulkan", "MIT"),
        ("Real-ESRGAN weights", "BSD-3-Clause"),
        ("pillow", "MIT-CMU"),
    ]
    models = MANIFEST["models"]
    assert len(models) == 1
    model = models[0]
    assert model["id"] == EXPECTED_MODEL_ID
    assert model["sha256"] == EXPECTED_MODEL_SHA256
    assert model["bytes"] == EXPECTED_MODEL_BYTES
    assert (
        model["path"]
        == "realesrgan-ncnn-vulkan-20220424-ubuntu/realesrgan-ncnn-vulkan-20220424-ubuntu.zip"
    )
    assert model["spdx"] == "BSD-3-Clause"
    assert model["commercial_use"] is True
    assert model["requires_acceptance"] is False


def test_pyproject_and_uv_lock() -> None:
    pyproject = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == ["pillow==13.0.0"]
    assert pyproject["tool"]["uv"]["package"] is False
    assert (PACKAGE / "uv.lock").is_file()


def test_enhance_capability_schema() -> None:
    cap = MANIFEST["capabilities"]["enhance"]
    assert cap["kind"] == "image"
    assert cap["preview"] == {"viewer": "image"}
    assert cap["summary"]
    assert cap["i18n"]["es"]["summary"]
    inputs = cap["inputs"]
    assert set(inputs) == {"image", "name", "scale", "model", "format"}
    assert inputs["image"]["type"] == "path" and inputs["image"]["required"] is True
    assert inputs["name"]["type"] == "string" and inputs["name"]["required"] is True
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["scale"]["values"] == ["2", "4"]
    assert inputs["scale"]["default"] == "4"
    assert inputs["model"]["values"] == [
        "realesrgan-x4plus",
        "realesrgan-x4plus-anime",
        "realesr-animevideov3",
    ]
    assert inputs["model"]["default"] == "realesrgan-x4plus"
    assert inputs["format"]["values"] == ["png", "jpg", "webp"]
    assert inputs["format"]["default"] == "png"
