from __future__ import annotations

import pytest
from pathlib import Path

from enterprise_llm_proxy.services.routerctl_distribution import RouterctlDistributionService


def test_wheel_filename_returns_name_of_first_wheel(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    wheel_file = wheel_dir / "enterprise_llm_proxy-0.1.0-py3-none-any.whl"
    wheel_file.write_bytes(b"fake wheel content")

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    assert service.wheel_filename() == "enterprise_llm_proxy-0.1.0-py3-none-any.whl"


def test_wheel_filename_raises_when_no_wheel(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    with pytest.raises(RuntimeError, match="No .whl file found"):
        service.wheel_filename()


def test_wheel_path_returns_path_for_existing_wheel(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    filename = "enterprise_llm_proxy-0.1.0-py3-none-any.whl"
    wheel_file = wheel_dir / filename
    wheel_file.write_bytes(b"fake wheel content")

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    result = service.wheel_path(filename)

    assert result == wheel_file
    assert result.exists()


def test_wheel_path_raises_for_filename_mismatch(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    actual_filename = "enterprise_llm_proxy-0.1.0-py3-none-any.whl"
    (wheel_dir / actual_filename).write_bytes(b"fake wheel content")

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    with pytest.raises(FileNotFoundError):
        service.wheel_path("enterprise_llm_proxy-9.9.9-py3-none-any.whl")


def test_wheel_path_raises_when_file_does_not_exist(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    with pytest.raises(FileNotFoundError):
        service.wheel_path("enterprise_llm_proxy-0.1.0-py3-none-any.whl")


def test_wheel_path_returns_cached_when_up_to_date(tmp_path: Path) -> None:
    """Pre-existing wheel is returned immediately without any rebuild."""
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    filename = "enterprise_llm_proxy-0.1.0-py3-none-any.whl"
    wheel_file = wheel_dir / filename
    wheel_file.write_bytes(b"pre-built wheel content")

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    result = service.wheel_path(filename)

    assert result == wheel_file
    # Content is unchanged — no rebuild occurred
    assert result.read_bytes() == b"pre-built wheel content"


def test_wheel_path_raises_for_non_whl_extension(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    # Create a file with a non-.whl extension
    tarball = wheel_dir / "enterprise_llm_proxy-0.1.0.tar.gz"
    tarball.write_bytes(b"tarball")

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    with pytest.raises(FileNotFoundError):
        service.wheel_path("enterprise_llm_proxy-0.1.0.tar.gz")


def test_wheel_filename_raises_with_helpful_message_when_dir_missing(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    # Do NOT create the directory

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    with pytest.raises(RuntimeError, match="uv build"):
        service.wheel_filename()


def test_wheel_filename_raises_with_helpful_message_when_no_wheels(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    # Directory exists but contains no .whl files

    service = RouterctlDistributionService(wheel_dir=wheel_dir)
    with pytest.raises(RuntimeError, match="uv build"):
        service.wheel_filename()
