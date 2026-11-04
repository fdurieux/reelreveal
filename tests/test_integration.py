"""Real generated media; no Instagram network or model required."""

import json
import shutil
import subprocess

import pytest

from reelreveal.cli import main


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_local_video_end_to_end(tmp_path, capsys):
    video = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:d=2",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
    )
    assert (
        main(
            [
                "--video",
                str(video),
                "--provider",
                "none",
                "--frames",
                "2",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "extracted_only"
    assert len(result["frames"]) == 2
    assert all(not frame["items"] for frame in result["frames"])
    for frame in result["frames"]:
        from pathlib import Path

        assert Path(frame["path"]).read_bytes().startswith(b"\xff\xd8")
    from pathlib import Path

    assert json.loads(Path(result["report_path"]).read_text())["provider"] == "none"
