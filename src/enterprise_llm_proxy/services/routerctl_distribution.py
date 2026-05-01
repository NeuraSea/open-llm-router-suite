from __future__ import annotations

from pathlib import Path


class RouterctlDistributionService:
    def __init__(self, *, wheel_dir: Path) -> None:
        """
        wheel_dir: directory containing the pre-built wheel file.
        Built during Docker image build via: uv build --wheel --out-dir /app/dist
        """
        self._wheel_dir = wheel_dir

    def wheel_path(self, filename: str) -> Path:
        """Return path to the named wheel file. Raises FileNotFoundError if not found."""
        path = self._wheel_dir / filename
        if not path.name.endswith(".whl"):
            raise FileNotFoundError(
                f"{filename!r} is not a .whl file"
            )
        if not path.exists():
            raise FileNotFoundError(filename)
        return path

    def wheel_filename(self) -> str:
        """Return the filename of the first wheel found. Raises RuntimeError if none."""
        if not self._wheel_dir.exists():
            raise RuntimeError(
                f"routerctl wheel directory not found: {self._wheel_dir}\n"
                f"  In production this is built by the Dockerfile.\n"
                f"  For local development, run: uv build --wheel --out-dir {self._wheel_dir}"
            )
        wheels = list(self._wheel_dir.glob("*.whl"))
        if not wheels:
            raise RuntimeError(
                f"No .whl file found in {self._wheel_dir}\n"
                f"  Run: uv build --wheel --out-dir {self._wheel_dir}"
            )
        return wheels[0].name
