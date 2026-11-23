"""DirectLauncher の契約テスト(T031、T048。-m windows)。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from job_runner_agent.launcher.direct import DirectLauncher
from job_runner_agent.launcher.port import ProcessLauncher
from job_testing.contracts.process_launcher import ProcessLauncherContract

pytestmark = pytest.mark.windows


@pytest.fixture
def launcher() -> ProcessLauncher:
    return DirectLauncher()


@pytest.fixture
def python_exe() -> str:
    return sys.executable


@pytest.fixture
def workdir(tmp_path: Path) -> str:
    return str(tmp_path)


class TestDirectLauncher(ProcessLauncherContract):
    pass
