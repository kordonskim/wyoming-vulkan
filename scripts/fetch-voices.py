
#!/usr/bin/env python3
"""Download Piper voices and custom Jarvis voices into a Wyoming voice library."""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

PIPER_REPO = "rhasspy/piper-voices"
JARVIS_REPO = "jgkawell/jarvis"


def list_repo_files(repo, prefix=""):
    """List repository files using the paginated Hugging Face tree API."""
    root = f"https://huggingface.co/api/models/{repo}/tree/main"
    url = f"{root}/{quote(prefix, safe='/')}?recursive=true&limit=1000"
    files = set()

    while url:
        with urlopen(url, timeout=60) as response:
            items = json.load(response)
            links = response.headers.get("Link", "")

        for item in items:
            if item.get("type") == "file":
                files.add(item["path"])

        next_url = None
        for link in links.split(","):
            if 'rel="next"' in link:
                next_url = link.split(";")[0].strip().strip("<>")
                break

        url = next_url

    return files


def build_downloads(language, include_piper, include_jarvis):
    downloads = []

    if include_piper:
        if language == "all":
            prefix = ""
        elif "_" in language:
            prefix = f"{language.split('_')[0]}/{language}"
        else:
            prefix = language

        files = list_repo_files(PIPER_REPO, prefix)

        models = sorted(
            path for path in files
            if path.endswith(".onnx")
            and path + ".json" in files
        )

        for model in models:
            downloads.append((PIPER_REPO, model, model))
            downloads.append((PIPER_REPO, model + ".json", model + ".json"))

        print(f"Discovered {len(models)} Piper voices", flush=True)

    if include_jarvis:
        for quality in ("medium", "high"):
            remote = f"en/en_GB/jarvis/{quality}"

            for ext in ("onnx", "onnx.json"):
                source = f"{remote}/jarvis-{quality}.{ext}"
                target = f"{remote}/en_GB-jarvis-{quality}.{ext}"
                downloads.append((JARVIS_REPO, source, target))

        print("Added Jarvis Medium and High", flush=True)

    return downloads


def download(item, destination):
    repo, source, target = item

    output = destination / target
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.is_file() and output.stat().st_size > 0:
        return "SKIP", target

    url = (
        f"https://huggingface.co/{repo}/resolve/main/"
        f"{quote(source, safe='/')}"
    )

    partial = output.with_name(output.name + ".part")

    subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--retry", "5",
            "--retry-delay", "2",
            "--connect-timeout", "20",
            "--continue-at", "-",
            "--silent",
            "--show-error",
            "--output", str(partial),
            url,
        ],
        check=True,
    )

    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError(f"Empty download: {target}")

    partial.replace(output)
    return "DONE", target


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--destination", default="/data/voices")
    parser.add_argument("--language", default="en")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--piper-only", action="store_true")
    parser.add_argument("--jarvis-only", action="store_true")

    args = parser.parse_args()

    if args.piper_only and args.jarvis_only:
        parser.error("Choose either --piper-only or --jarvis-only")

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=True)

    downloads = build_downloads(
        language=args.language,
        include_piper=not args.jarvis_only,
        include_jarvis=not args.piper_only,
    )

    print(
        f"Processing {len(downloads)} files with "
        f"{args.workers} workers into {destination}",
        flush=True,
    )

    failures = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(download, item, destination): item
            for item in downloads
        }

        for future in as_completed(futures):
            try:
                status, path = future.result()
                print(f"[{status}] {path}", flush=True)
            except Exception as exc:
                item = futures[future]
                failures.append(item[2])
                print(f"[FAILED] {item[2]}: {exc}", flush=True)

    print(
        f"Completed: {len(downloads) - len(failures)}/{len(downloads)} files",
        flush=True,
    )

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
