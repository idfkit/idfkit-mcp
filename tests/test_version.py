"""The server can say which level it runs (feature 004, FR-017)."""

from __future__ import annotations

from importlib import metadata

import pytest

from idfkit_mcp.server import _parse_args, version_report  # pyright: ignore[reportPrivateUsage]


def test_version_report_names_both_installed_levels() -> None:
    report = version_report()
    assert report == f"idfkit-mcp {metadata.version('idfkit-mcp')} (idfkit {metadata.version('idfkit')})"


def test_version_flag_prints_the_report_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        _parse_args(["--version"])
    assert exited.value.code == 0
    assert capsys.readouterr().out.strip() == version_report()


def test_transport_parsing_is_unchanged() -> None:
    assert _parse_args(["--transport", "streamable-http"]).transport == "http"
    assert _parse_args([]).transport in {"stdio", "sse", "http"}
