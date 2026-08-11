"""Resource path helpers."""

from __future__ import annotations

from pathlib import Path


def package_share_dir() -> Path:
    try:
        from ament_index_python.packages import get_package_share_directory

        return Path(get_package_share_directory("whz"))
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parents[1]


def default_audio_dir() -> Path:
    return package_share_dir() / "assets" / "audio"


def default_template_dir() -> Path:
    return package_share_dir() / "assets" / "templates"


def default_model_path() -> Path:
    return package_share_dir() / "assets" / "models" / "gauge_best.pt"
