import json
import subprocess

import pytest

from services.llm.providers.claude_code import ClaudeRunner
from services.llm.runner import LLMError


def _completed(payload, returncode=0, stderr=""):
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class Recorder:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _runner(result, tmp_path):
    recorder = Recorder(result)
    return ClaudeRunner(binary="claude", cwd=tmp_path, run=recorder), recorder


def test_run_builds_headless_command_and_returns_structured_output(tmp_path):
    ok = _completed({"is_error": False, "structured_output": {"x": 1}, "total_cost_usd": 0.1})
    runner, recorder = _runner(ok, tmp_path)
    result = runner.run("SYS", "PROMPT", {"type": "object"})
    cmd, kwargs = recorder.calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert kwargs["input"] == "PROMPT"
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["cwd"] == str(tmp_path)
    assert result.data == {"x": 1}
    assert result.cost_usd == 0.1


@pytest.mark.parametrize(
    "result",
    [
        _completed({}, returncode=1, stderr="boom"),
        _completed("not json"),
        _completed({"is_error": True, "result": "limite atingido"}),
        _completed({"is_error": False, "result": "texto sem schema"}),
        subprocess.TimeoutExpired(cmd="claude", timeout=1),
    ],
)
def test_failures_raise_llm_error(result, tmp_path):
    runner, _ = _runner(result, tmp_path)
    with pytest.raises(LLMError):
        runner.run("s", "p", {})


def test_missing_binary_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("services.llm.providers.claude_code.shutil.which", lambda name: None)
    with pytest.raises(LLMError, match="claude"):
        ClaudeRunner(cwd=tmp_path).run("s", "p", {})


def test_available_runs_version(tmp_path):
    recorder = Recorder(subprocess.CompletedProcess([], 0, "2.1.0", ""))
    assert ClaudeRunner(binary="claude", cwd=tmp_path, run=recorder).available()
    assert recorder.calls[0][0] == ["claude", "--version"]


def test_available_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("services.llm.providers.claude_code.shutil.which", lambda name: None)
    assert not ClaudeRunner(cwd=tmp_path).available()


def test_os_error_becomes_llm_error(tmp_path):
    runner, _ = _runner(PermissionError("negado"), tmp_path)
    with pytest.raises(LLMError):
        runner.run("s", "p", {})
