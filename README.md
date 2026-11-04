# ReelReveal

A Python CLI that samples an Instagram Reel and asks a configured local vision
model to identify visible **LPs / record sleeves**, or items you choose. Results
are timestamped, unverified candidates with visual evidence, not catalog matches.

## Install

Requires Python 3.11+, FFmpeg and ffprobe on PATH. On macOS install FFmpeg with
`brew install ffmpeg`; on Debian/Ubuntu use `sudo apt-get install ffmpeg`.

```sh
git clone https://github.com/fdurieux/reelreveal.git
cd reelreveal
./scripts/install.sh
. .venv/bin/activate
reelreveal --help
```

The installer creates `.venv`, installs the CLI and yt-dlp, and checks FFmpeg.
Use `./scripts/install.sh --dev` to include test and lint tools. It does not install
system packages, Ollama, or model weights. Windows users can install FFmpeg,
run `py -m venv .venv`, then `.venv\Scripts\python -m pip install -e ".[dev]"`.

## Identify items with a real provider

Install [Ollama](https://ollama.com/) separately, start its service, and download
an image-capable model supported by your machine. Set `MODEL` below to that exact
installed model name. ReelReveal intentionally has no implicit model or fabricated
fallback. A text-only model will fail when receiving images.

```sh
MODEL='your-installed-vision-model'
reelreveal 'https://www.instagram.com/reel/REEL_ID/' --model "$MODEL"
reelreveal 'https://www.instagram.com/reel/REEL_ID/' --model "$MODEL" --identify 'sneakers and brand names'
reelreveal --video ./authorized-reel.mp4 --model "$MODEL" --frames 12
```

`--video` skips Instagram access. You may also supply a URL with `--video` to keep
the canonical Reel URL as report provenance. `--identify` defaults to
`LPs and record sleeves`. The Ollama endpoint is fixed to `127.0.0.1:11434`;
frames are sent to that service. Model installation and inference behavior are
managed by Ollama. Its [generate API](https://docs.ollama.com/api/generate) supports
base64 images and JSON output. No paid cloud API or API key is required.

## Extraction without a model

```sh
reelreveal 'https://www.instagram.com/reel/REEL_ID/' --provider none
reelreveal --video ./authorized-reel.mp4 --provider none --frames 8 --output ./evidence
```

This performs real media extraction but **does not identify anything**. The report
has `status: "extracted_only"`, `provider: "none"`, and empty `items` arrays.
The normal analysis mode requires `--model` and fails clearly if inference fails.

Each successful run creates a unique directory beneath `--output` (default
`reelreveal-output`) containing JPEG evidence frames and `report.json`. Stdout is
one JSON document including `report_path`; errors are JSON with exit code 1.
Invalid command syntax uses argparse's stderr and exit code 2; interruption uses
130. Successful extraction or analysis exits 0, including when no items are found.
Model observations look like:

```json
{
  "timestamp_seconds": 1.25,
  "path": "/absolute/path/frame-000.jpg",
  "items": [{"label": "model candidate", "evidence": "visible details", "verified": false}]
}
```

That example describes the format, not an actual identification. Repeated sightings
remain separate per frame so the evidence remains auditable. Moving the output
folder requires updating absolute frame paths in the report.

## Instagram failures and privacy

Private/deleted Reels, login requirements, rate limits and extractor changes can
prevent retrieval. ReelReveal bounds retries and timeouts and gives recovery
instructions. It never bypasses permissions or silently substitutes another video.
Update the extractor with `.venv/bin/python -m pip install --upgrade yt-dlp`.
If authorized, pass `--cookies /path/to/cookies.txt` using a Netscape-format cookie
file; see the [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ).
Cookie jars are secrets: keep them out of Git. The CLI uses a temporary private
copy and removes downloaded media and cookies when its temporary context exits.
Only analyze media you are allowed to access.

## Architecture and limits

1. Validate an HTTPS Instagram `/reel/` or `/reels/` URL and discard query secrets.
2. Retrieve a single video through yt-dlp, or accept a local file. Downloads have
   a 180-second timeout and 100 MiB check (the downloader's size limit is best effort
   when size is unknown; the completed file is checked again).
3. Probe duration with ffprobe; sample 1–32 evenly spaced midpoint frames using
   FFmpeg, scaled within 1024×1024. Files over one hour are rejected.
4. Call the injectable `VisionProvider` interface once per frame. The Ollama
   implementation sends the image, target and an evidence-oriented prompt,
   validates JSON, and marks all candidates `verified: false`.
5. Save the report only after all frames succeed. Failed runs can leave evidence
   frames in their unique output directory; no success report is written.

Implemented: retrieval, local fallback, real JPEG sampling, working Ollama HTTP
integration, JSON schema validation, timestamped evidence, installation and CI.
External dependencies: yt-dlp's Instagram support, FFmpeg, and a separately
installed functioning vision model. **No real-world identification accuracy has
been established.** Automated provider tests use controlled HTTP responses;
no live Instagram retrieval or real model inference is part of CI.

Uniform sampling can miss brief appearances. Low resolution, motion blur,
occlusion and model hallucinations can produce omissions or incorrect candidates.
No OCR engine, audio identification, Discogs lookup, catalog verification, bounding
boxes, confidence calibration or cross-frame deduplication is implemented. Empty
results do not prove an item is absent. Review the evidence yourself. Requests are
sequential and can take up to 180 seconds per model call; media subprocesses have
120-second timeouts. Report paths and local source paths may reveal local directory
names; inspect before sharing reports.

## Tests

```sh
./scripts/install.sh --dev
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/behave
```

Unit tests cover URL validation, private-cookie handling, download errors, sampling,
provider requests and malformed responses, and CLI validation. A generated video
integration test runs real ffprobe/FFmpeg and checks the extraction-only JSON report;
it skips locally if FFmpeg is absent. Executable Gherkin scenarios in `features/`
cover default/custom targets, inaccessible Reels and honest extraction-only output.
GitHub Actions installs FFmpeg and runs these checks on Python 3.11, 3.12 and 3.13.

MIT licensed; see [LICENSE](LICENSE).
