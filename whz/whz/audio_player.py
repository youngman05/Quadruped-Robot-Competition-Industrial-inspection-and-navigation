"""Small MP3 playback helper for fixed inspection announcements."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence


STATE_CODE = {
    "low": ("L", "A"),
    "middle": ("M", "N"),
    "high": ("H", "A"),
}


class AudioPlayer:
    """Play one MP3 file and return after the command exits."""

    def __init__(
        self,
        audio_dir: Path,
        timeout_sec: float = 10.0,
    ) -> None:
        self.audio_dir = Path(audio_dir)
        self.timeout_sec = float(timeout_sec)

    def audio_path_for(self, area: str, state_key: str) -> Path:
        level_code, status_code = STATE_CODE[state_key]
        name = f"{area}{level_code}{status_code}.mp3"
        return self.audio_dir / name

    def play(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        command = self._build_command(path)
        if not command:
            raise RuntimeError(
                "No MP3 player found. Install mpg123 or ffmpeg/ffplay."
            )

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=self.timeout_sec,
        )

    def _build_command(self, path: Path) -> Optional[Sequence[str]]:
        if shutil.which("mpg123"):
            return ["mpg123", "-q", str(path)]
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        return None
