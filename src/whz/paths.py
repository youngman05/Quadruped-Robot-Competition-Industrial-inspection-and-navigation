"""Resource path helpers."""

from __future__ import annotations

from pathlib import Path


def package_share_dir() -> Path:
    return Path(__file__).resolve().parent


def default_audio_dir() -> Path:
    return package_share_dir() / "assets" / "audio"


def default_template_dir() -> Path:
    return package_share_dir() / "assets" / "templates"
