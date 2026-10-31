"""Exercise pytest's local/CI contract in separate processes without Docker."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def selection_probe(tmp_path):
    with tempfile.TemporaryDirectory(prefix='_selection_probe_', dir=ROOT/'tests') as temporary:
        path = Path(temporary)/'test_probe.py'
        path.write_text('import pytest\n\ndef test_unit_probe():\n    assert True\n\n@pytest.mark.sandbox\ndef test_sandbox_probe():\n    assert True\n')
        binaries = tmp_path/'bin'
        binaries.mkdir()
        docker = binaries/'docker'
        docker.write_text('#!/bin/sh\necho "Docker unavailable for selection probe" >&2\nexit 97\n')
        docker.chmod(0o755)
        environment = {**os.environ, 'CI':'false', 'PATH':str(binaries)+os.pathsep+os.environ.get('PATH','')}
        environment.pop('STUDIO_TEST_SANDBOX_SOCKET', None)
        environment.pop('PYTEST_ADDOPTS', None)
        def run(*arguments, ci=False):
            return subprocess.run([sys.executable, '-m', 'pytest', '-q', '-c', str(ROOT/'pyproject.toml'), *arguments],
                                  cwd=ROOT, env={**environment,'CI':'true' if ci else 'false'},
                                  capture_output=True, text=True, timeout=45)
        yield path, run


def test_local_default_runs_units_and_skips_sandbox_without_docker(selection_probe):
    path, run = selection_probe
    result = run(str(path))
    assert result.returncode==0, result.stdout+result.stderr
    assert '1 passed, 1 skipped' in result.stdout


def test_ci_rejects_omitting_the_sandbox_opt_in(selection_probe):
    path, run = selection_probe
    result = run(str(path), '--collect-only', ci=True)
    assert result.returncode!=0
    assert 'CI must run the real sandbox checks' in result.stdout+result.stderr


def test_explicit_sandbox_run_fails_when_docker_is_unavailable(selection_probe):
    path, run = selection_probe
    result = run(str(path)+'::test_sandbox_probe', '--run-sandbox')
    assert result.returncode!=0
    assert 'Docker unavailable for selection probe' in result.stdout+result.stderr
    assert '1 skipped' not in result.stdout
