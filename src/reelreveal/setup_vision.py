"""Install Ollama and prepare a local vision model; invoked by scripts/install.sh."""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1:11434"
DEFAULT_MODEL = "gemma3:4b"
INSTALL_URL = "https://ollama.com/install.sh"


class SetupError(Exception):
    """Setup failed; do not announce readiness."""


def api(path: str, payload: dict | None = None, timeout: int = 2) -> dict:
    request = urllib.request.Request(
        f"http://{HOST}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    # Match the CLI's fixed local server even when proxy variables are configured.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise SetupError("Ollama returned an unexpectedly large response.")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise SetupError("Ollama returned an invalid response.")
    return result


def ready() -> bool:
    try:
        version = api("/api/version").get("version")
        return isinstance(version, str) and bool(version)
    except (OSError, ValueError, SetupError):
        return False


def find_ollama() -> str | None:
    executable = shutil.which("ollama")
    if executable:
        return executable
    # Reuse the macOS application even when its CLI symlink is absent.
    for path in (
        "/Applications/Ollama.app/Contents/Resources/ollama",
        "/usr/local/bin/ollama",
        "/usr/bin/ollama",
    ):
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path
    return None


def install_ollama(env: dict[str, str]) -> str:
    executable = find_ollama()
    if executable:
        return executable
    if platform.system() not in {"Darwin", "Linux"}:
        raise SetupError(
            "Automatic Ollama installation supports macOS and Linux only. "
            "Install Ollama manually on Windows, or use --skip-vision."
        )
    if not shutil.which("curl"):
        raise SetupError("Install curl to download Ollama, or install Ollama manually and retry.")
    print(
        f"Installing Ollama using {INSTALL_URL} (may request administrator privileges).", flush=True
    )
    # Fetch completely before executing; do not run a partial download via a pipe.
    with tempfile.TemporaryDirectory(prefix="reelreveal-install-") as directory:
        installer = Path(directory) / "install-ollama.sh"
        subprocess.run(
            [
                "curl",
                "--fail",
                "--show-error",
                "--location",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--connect-timeout",
                "20",
                "--max-time",
                "120",
                "--output",
                str(installer),
                INSTALL_URL,
            ],
            check=True,
            timeout=130,
        )
        subprocess.run(["sh", str(installer)], check=True, env=env, timeout=1800)
    executable = find_ollama()
    if not executable:
        raise SetupError(
            "Ollama installer finished but its executable was not found. "
            "Add ollama to PATH and retry."
        )
    return executable


def wait_for_server(process: subprocess.Popen, log: Path, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        if process.poll() is not None:
            break
        time.sleep(1)
    raise SetupError(
        f"Ollama did not become ready at {HOST}. See {log}; "
        "check port conflicts and OS/hardware support, then retry."
    )


def stop_started_server(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def setup(model: str, state_dir: Path) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
        raise SetupError("Use a valid Ollama model name, for example gemma3:4b.")
    env = {**os.environ, "OLLAMA_HOST": HOST, "OLLAMA_NO_START": "1"}
    executable = install_ollama(env)
    process = None
    pid_file = state_dir / "ollama-serve.pid"
    try:
        if not ready():
            state_dir.mkdir(parents=True, exist_ok=True)
            log = state_dir / "ollama-serve.log"
            print(f"Starting local Ollama server; log: {log}", flush=True)
            with log.open("ab") as output:
                process = subprocess.Popen(
                    [executable, "serve"],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            wait_for_server(process, log)
            pid_file.write_text(str(process.pid) + "\n", encoding="utf-8")
        print(
            f"Pulling {model}; the default gemma3:4b download is about 3.4 GB. "
            "Existing layers are reused. This may take several minutes.",
            flush=True,
        )
        subprocess.run([executable, "pull", model], check=True, env=env, timeout=3600)
        info = api("/api/show", {"model": model}, timeout=30)
        capabilities = info.get("capabilities")
        if not isinstance(capabilities, list) or "vision" not in capabilities:
            raise SetupError(
                f"{model} does not report vision support. Select an image-capable "
                "model with --model, or update an older Ollama installation."
            )
        print(
            f"Vision setup complete: {model} reports image support. "
            "Inference and identification accuracy have not been tested."
        )
        if process:
            print(
                f"Ollama remains running (PID {process.pid}); PID file: {pid_file}. "
                "Stop it with kill <PID> when no longer needed."
            )
        print(f"Analyze with: .venv/bin/reelreveal 'REEL_URL' --model '{model}'")
    except BaseException:
        # Never stop a service that was running before this invocation.
        if process:
            stop_started_server(process)
            pid_file.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--state-dir", type=Path, default=Path(".venv"))
    args = parser.parse_args(argv)
    try:
        setup(args.model, args.state_dir.resolve())
        return 0
    except (SetupError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"Vision setup failed: {error}\nCheck network access, disk space, Ollama logs, "
            "and permissions. Retry the installer to resume, or use --skip-vision "
            "for extraction only.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Vision setup interrupted; rerun the installer to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
