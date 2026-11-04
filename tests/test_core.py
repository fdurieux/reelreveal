import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from reelreveal.cli import main
from reelreveal.core import (
    OllamaVision,
    ReelRevealError,
    analyze,
    download,
    extract,
    normalize_url,
    run,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/reel/Ab_-12/?igsh=secret",
        "https://www.instagram.com/reels/Ab_-12/",
    ],
)
def test_canonical_url(url):
    assert normalize_url(url) == "https://www.instagram.com/reel/Ab_-12/"


@pytest.mark.parametrize(
    "url",
    [
        "http://instagram.com/reel/a",
        "https://instagram.com.evil/reel/a",
        "https://evil@instagram.com/reel/a",
        "https://instagram.com:123/reel/a",
        "https://instagram.com/p/a",
        "file:///reel/a",
        "https://instagram.com:bad/reel/a",
    ],
)
def test_invalid_url(url):
    with pytest.raises(ReelRevealError):
        normalize_url(url)


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired("x", 1),
        subprocess.CalledProcessError(1, "x", stderr="SECRET"),
    ],
)
def test_safe_process_errors(error):
    with (
        patch("reelreveal.core.subprocess.run", side_effect=error),
        pytest.raises(ReelRevealError) as result,
    ):
        run(["tool"])
    assert "SECRET" not in str(result.value)


def test_inaccessible_reel(tmp_path):
    with (
        patch("reelreveal.core.run", side_effect=ReelRevealError("SECRET")),
        pytest.raises(ReelRevealError, match="--video") as result,
    ):
        download("https://www.instagram.com/reel/a/", tmp_path)
    assert "SECRET" not in str(result.value)


def test_cookies_copied_and_missing_download_rejected(tmp_path):
    source = tmp_path / "cookies.txt"
    source.write_text("private")
    dest = tmp_path / "download"
    dest.mkdir()
    with (
        patch("reelreveal.core.run") as call,
        pytest.raises(ReelRevealError, match="No complete video"),
    ):
        download("https://www.instagram.com/reel/a/", dest, source)
    assert str(source) not in call.call_args[0][0]
    assert source.read_text() == "private"
    assert (dest / "session-cookies.txt").stat().st_mode & 0o777 == 0o600


def test_sampling(tmp_path):
    video = tmp_path / "video.mp4"
    video.touch()

    def fake_run(command):
        if command[0] == "ffprobe":
            return '{"format":{"duration":"10"}}'
        Path(command[-1]).write_bytes(b"jpeg")
        return ""

    with patch("reelreveal.core.run", side_effect=fake_run):
        frames = extract(video, tmp_path, 2)
    assert [f["timestamp_seconds"] for f in frames] == [2.5, 7.5]


@pytest.mark.parametrize("duration", ["NaN", "-1", "3601", "0"])
def test_invalid_duration(tmp_path, duration):
    video = tmp_path / "video"
    video.touch()
    with (
        patch("reelreveal.core.run", return_value=json.dumps({"format": {"duration": duration}})),
        pytest.raises(ReelRevealError),
    ):
        extract(video, tmp_path, 1)


def test_no_provider_never_identifies():
    assert analyze([{"path": "a", "timestamp_seconds": 1}], "records", None)[0]["items"] == []


def test_ollama_contract(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"image")
    body = {"response": json.dumps({"items": [{"label": "candidate", "evidence": "visible text"}]})}
    with patch("reelreveal.core.urllib.request.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
        result = OllamaVision("vision-model").identify(frame, "shoes")
    payload = json.loads(request.call_args[0][0].data)
    assert payload["images"] == ["aW1hZ2U="]
    assert "shoes" in payload["prompt"]
    assert result[0]["verified"] is False


@pytest.mark.parametrize(
    "body",
    [
        b"bad",
        b"{}",
        b'{"response":"{}"}',
        b'{"response":"{\\"items\\": [3]}"}',
        b'{"response":"{\\"items\\": [{\\"label\\": \\"x\\"}]}"}',
    ],
)
def test_invalid_provider_response(tmp_path, body):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"image")
    with patch("reelreveal.core.urllib.request.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = body
        with pytest.raises(ReelRevealError, match="Vision request failed"):
            OllamaVision("vision-model").identify(frame, "records")


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["https://evil.com/reel/x"],
        ["--video", "x", "--frames", "33"],
        ["--video", "x"],
        ["--video", "x", "--provider", "none", "--identify", " "],
    ],
)
def test_cli_validation(args, capsys):
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_download_success(tmp_path):
    def completed(command, timeout):
        (tmp_path / "source.mp4").write_bytes(b"media")
        assert "--ignore-config" in command
        assert "--no-playlist" in command
        assert timeout == 180

    with patch("reelreveal.core.run", side_effect=completed):
        assert download("https://www.instagram.com/reel/a/", tmp_path).name == "source.mp4"


def test_unavailable_provider(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    with (
        patch("reelreveal.core.urllib.request.urlopen", side_effect=ConnectionRefusedError()),
        pytest.raises(ReelRevealError, match="Start Ollama"),
    ):
        OllamaVision("vision-model").identify(frame, "records")


def test_failed_analysis_never_writes_success(tmp_path, capsys):
    frames = [{"path": str(tmp_path / "frame.jpg"), "timestamp_seconds": 1}]
    with (
        patch("reelreveal.cli.extract", return_value=frames),
        patch("reelreveal.cli.analyze", side_effect=ReelRevealError("Vision unavailable")),
    ):
        assert (
            main(["--video", "sample.mp4", "--model", "vision-model", "--output", str(tmp_path)])
            == 1
        )
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    assert not list(tmp_path.rglob("report.json"))


def test_missing_decoded_frame(tmp_path):
    video = tmp_path / "source.mp4"
    video.touch()
    with (
        patch("reelreveal.core.run", return_value='{"format":{"duration":"1"}}'),
        pytest.raises(ReelRevealError, match="could not decode"),
    ):
        extract(video, tmp_path, 1)
