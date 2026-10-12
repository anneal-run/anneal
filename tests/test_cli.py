import subprocess
import sys

import pytest

import anneal
from anneal.cli import main


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: anneal" in capsys.readouterr().out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"anneal {anneal.__version__}"


def test_console_script_entry_point() -> None:
    """Integration: the installed `anneal` module runs as a process."""
    result = subprocess.run(
        [sys.executable, "-m", "anneal.cli", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("anneal ")
