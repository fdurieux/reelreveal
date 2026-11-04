"""Setup behavior with controlled external commands; no system install or model downloads."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from reelreveal import setup_vision as vision


def test_existing_ollama_is_not_reinstalled():
    with (
        patch.object(vision, "find_ollama", return_value="/bin/ollama"),
        patch.object(vision.subprocess, "run") as run,
    ):
        assert vision.install_ollama({}) == "/bin/ollama"
    run.assert_not_called()


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_official_installer_downloaded_before_execution(system):
    with (
        patch.object(vision, "find_ollama", side_effect=[None, "/bin/ollama"]),
        patch.object(vision.platform, "system", return_value=system),
        patch.object(vision.shutil, "which", return_value="/bin/curl"),
        patch.object(vision.subprocess, "run") as run,
    ):
        assert vision.install_ollama({"OLLAMA_NO_START": "1"}) == "/bin/ollama"
    first, second = run.call_args_list
    assert first.args[0][0] == "curl"
    assert first.args[0][-1] == "https://ollama.com/install.sh"
    assert second.args[0][0] == "sh"
    assert second.kwargs["env"]["OLLAMA_NO_START"] == "1"


def test_failed_download_never_executes_script():
    with (
        patch.object(vision, "find_ollama", return_value=None),
        patch.object(vision.platform, "system", return_value="Linux"),
        patch.object(vision.shutil, "which", return_value="/bin/curl"),
        patch.object(
            vision.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "curl")
        ) as run,
        pytest.raises(subprocess.CalledProcessError),
    ):
        vision.install_ollama({})
    assert run.call_count == 1


def test_unsupported_platform():
    with (
        patch.object(vision, "find_ollama", return_value=None),
        patch.object(vision.platform, "system", return_value="Windows"),
        pytest.raises(vision.SetupError, match="macOS and Linux"),
    ):
        vision.install_ollama({})


def test_reuse_server_and_pull_custom_model_locally(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.invalid")
    with (
        patch.object(vision, "install_ollama", return_value="/bin/ollama"),
        patch.object(vision, "ready", return_value=True),
        patch.object(vision.subprocess, "Popen") as start,
        patch.object(vision.subprocess, "run") as run,
        patch.object(vision, "api", return_value={"capabilities": ["completion", "vision"]}) as api,
    ):
        vision.setup("gemma3:12b", tmp_path)
    start.assert_not_called()
    assert run.call_args.args[0] == ["/bin/ollama", "pull", "gemma3:12b"]
    assert run.call_args.kwargs["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    api.assert_called_once_with("/api/show", {"model": "gemma3:12b"}, timeout=30)


def test_start_server_leaves_running_after_success(tmp_path):
    process = Mock(pid=1234)
    with (
        patch.object(vision, "install_ollama", return_value="/bin/ollama"),
        patch.object(vision, "ready", return_value=False),
        patch.object(vision.subprocess, "Popen", return_value=process) as start,
        patch.object(vision, "wait_for_server") as wait,
        patch.object(vision.subprocess, "run"),
        patch.object(vision, "api", return_value={"capabilities": ["vision"]}),
    ):
        vision.setup(vision.DEFAULT_MODEL, tmp_path)
    wait.assert_called_once()
    assert start.call_args.args[0] == ["/bin/ollama", "serve"]
    assert start.call_args.kwargs["start_new_session"] is True
    assert (tmp_path / "ollama-serve.pid").read_text().strip() == "1234"
    process.terminate.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        vision.SetupError("startup failed"),
        subprocess.CalledProcessError(1, "ollama"),
        subprocess.TimeoutExpired("ollama", 3600),
    ],
)
def test_failed_setup_cleans_up_only_its_server(tmp_path, failure):
    process = Mock(pid=1234)
    process.poll.return_value = None
    with (
        patch.object(vision, "install_ollama", return_value="/bin/ollama"),
        patch.object(vision, "ready", return_value=False),
        patch.object(vision.subprocess, "Popen", return_value=process),
        patch.object(vision, "wait_for_server"),
        patch.object(vision.subprocess, "run", side_effect=failure),
        pytest.raises(type(failure)),
    ):
        vision.setup(vision.DEFAULT_MODEL, tmp_path)
    process.terminate.assert_called_once()
    assert not (tmp_path / "ollama-serve.pid").exists()


@pytest.mark.parametrize("capabilities", [[], ["completion"], None, "vision"])
def test_text_only_or_unknown_model_fails(tmp_path, capabilities, capsys):
    with (
        patch.object(vision, "install_ollama", return_value="/bin/ollama"),
        patch.object(vision, "ready", return_value=True),
        patch.object(vision.subprocess, "run"),
        patch.object(vision, "api", return_value={"capabilities": capabilities}),
    ):
        assert vision.main(["--state-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "does not report vision support" in captured.err
    assert "Vision setup complete" not in captured.out


def test_wait_for_server_is_bounded(tmp_path):
    process = Mock()
    process.poll.return_value = None
    with (
        patch.object(vision, "ready", return_value=False),
        patch.object(vision.time, "monotonic", side_effect=[0, 0, 61]),
        patch.object(vision.time, "sleep"),
        pytest.raises(vision.SetupError, match="did not become ready"),
    ):
        vision.wait_for_server(process, tmp_path / "log")


@pytest.mark.parametrize("model", ["", "--help", "contains spaces", "x;echo bad"])
def test_invalid_model_fails_before_install(tmp_path, model):
    with (
        patch.object(vision, "install_ollama") as install,
        pytest.raises(vision.SetupError, match="valid Ollama model"),
    ):
        vision.setup(model, tmp_path)
    install.assert_not_called()


def test_local_api_json_contract():
    response = Mock()
    response.read.return_value = b'{"capabilities":["vision"]}'
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=response)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    with patch.object(vision.urllib.request, "build_opener", return_value=opener):
        assert vision.api("/api/show", {"model": "gemma3:4b"}) == {"capabilities": ["vision"]}
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:11434/api/show"
    assert json.loads(request.data) == {"model": "gemma3:4b"}


@pytest.fixture
def installer(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(root / "scripts/install.sh", tmp_path / "scripts/install.sh")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    venv_bin = tmp_path / ".venv/bin"
    venv_bin.mkdir(parents=True)
    shim = f"#!{sys.executable}\n" + (
        "import json, os, sys\n"
        'if os.environ.get("FAIL_VISION") and "reelreveal.setup_vision" in sys.argv:\n'
        "    sys.exit(1)\n"
        'with open(os.environ["INSTALL_CALLS"], "a") as f:\n'
        '    f.write(json.dumps(sys.argv[1:]) + "\\n")\n'
    )
    for path in [binaries / "python3", venv_bin / "python"]:
        path.write_text(shim)
        path.chmod(0o755)
    for name in ["ffmpeg", "ffprobe"]:
        (binaries / name).write_text("#!/bin/sh\nexit 0\n")
        (binaries / name).chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "PYTHON": str(binaries / "python3"),
        "INSTALL_CALLS": str(log),
    }
    env.pop("OLLAMA_MODEL", None)
    return tmp_path / "scripts/install.sh", env, log


@pytest.mark.parametrize(
    "args,expected",
    [
        ([], "gemma3:4b"),
        (["--dev", "--model", "gemma3:12b"], "gemma3:12b"),
        (["--skip-vision", "--dev"], None),
    ],
)
def test_shell_installer_wiring(installer, args, expected):
    script, env, log = installer
    subprocess.run(["sh", str(script), *args], env=env, check=True, capture_output=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    vision_calls = [call for call in calls if "reelreveal.setup_vision" in call]
    if expected:
        assert vision_calls == [["-m", "reelreveal.setup_vision", "--model", expected]]
    else:
        assert not vision_calls
    assert any("install" in call and ("-e" in call) for call in calls)


def test_installer_model_environment_override(installer):
    script, env, log = installer
    subprocess.run(["sh", str(script)], env={**env, "OLLAMA_MODEL": "gemma3:12b"}, check=True)
    assert "gemma3:12b" in log.read_text()


@pytest.mark.parametrize("args", [["--model"], ["--unknown"]])
def test_installer_bad_options_do_not_install(installer, args):
    script, env, log = installer
    result = subprocess.run(["sh", str(script), *args], env=env, capture_output=True)
    assert result.returncode == 2
    assert not log.exists()


def test_installer_never_announces_success_after_vision_failure(installer):
    script, env, _ = installer
    result = subprocess.run(
        ["sh", str(script)], env={**env, "FAIL_VISION": "1"}, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "Ready." not in result.stdout
