"""Command-line entry point; stdout is a single JSON document."""

import argparse
import json
import tempfile
from pathlib import Path

from .core import OllamaVision, ReelRevealError, analyze, download, extract, normalize_url


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Analyze visible items in an Instagram Reel.")
    result.add_argument("url", nargs="?", help="HTTPS Instagram Reel URL")
    result.add_argument(
        "--video", type=Path, help="Authorized local video; skips Instagram retrieval"
    )
    result.add_argument("--identify", default="LPs and record sleeves", help="Items to look for")
    result.add_argument("--provider", choices=["ollama", "none"], default="ollama")
    result.add_argument(
        "--model", help="Installed Ollama vision model name (required for analysis)"
    )
    result.add_argument("--frames", type=int, default=8, help="Uniform samples, 1–32 (default 8)")
    result.add_argument(
        "--cookies", type=Path, help="Netscape cookie file for authorized retrieval"
    )
    result.add_argument("--output", type=Path, default=Path("reelreveal-output"))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not args.url and not args.video:
            raise ReelRevealError("Provide a Reel URL or --video FILE.")
        url = normalize_url(args.url) if args.url else None
        if not 1 <= args.frames <= 32:
            raise ReelRevealError("--frames must be between 1 and 32.")
        target = args.identify.strip()
        if not target or len(target) > 500:
            raise ReelRevealError("--identify must contain 1–500 characters.")
        if args.provider == "ollama" and (not args.model or not args.model.strip()):
            raise ReelRevealError(
                "Select --model NAME for Ollama, or --provider none for extraction only."
            )
        provider = OllamaVision(args.model) if args.provider == "ollama" else None
        args.output.mkdir(parents=True, exist_ok=True)
        # Unique directory prevents overwriting earlier evidence or failed runs.
        output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output.resolve()))
        with tempfile.TemporaryDirectory(prefix="reelreveal-") as temporary:
            video = (
                args.video.resolve() if args.video else download(url, Path(temporary), args.cookies)
            )
            frames = extract(video, output, args.frames)
            observations = analyze(frames, target, provider)
        report = {
            "schema_version": 1,
            "status": "analyzed" if provider else "extracted_only",
            "source": url or str(args.video.resolve()),
            "target": target,
            "provider": args.provider,
            "model": args.model if provider else None,
            "warning": "Model candidates are unverified; empty items do not prove absence.",
            "frames": observations,
        }
        report_path = output / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**report, "report_path": str(report_path)}, indent=2))
        return 0
    except (ReelRevealError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, ReelRevealError)
            else "Cannot read or write local files; check paths and permissions."
        )
        print(json.dumps({"status": "error", "error": message}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "error", "error": "Interrupted."}))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
