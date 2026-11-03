"""Fetch the pinned upstream source and apply this repository's ordered patches.

Requires Python 3.9+ and Git. The destination must be new: existing sources are
never reset, deleted or overwritten. No HA credentials are needed for a build.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination: Path, revision=None):
    upstream = json.loads((ROOT / "upstream.json").read_text(encoding="utf-8"))
    repository = upstream["repository"]
    revision = revision or upstream["revision"]
    if repository != "https://github.com/jdbridge/wyoming-vulkan.git":
        raise ValueError("Expected jdbridge/wyoming-vulkan as the upstream repository")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Upstream revision must be a full 40-character commit SHA")

    patches = []
    for name in (ROOT / "patches/series").read_text(encoding="utf-8").splitlines():
        name = name.strip()
        if not name or name.startswith("#"):
            continue
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.patch", name):
            raise ValueError("Invalid patch name in patches/series")
        path = ROOT / "patches" / name
        if not path.is_file():
            raise ValueError(f"Missing patch: {name}")
        patches.append(path)
    if not patches or len(patches) != len(set(patches)):
        raise ValueError("patches/series must list unique patches")

    destination = destination.resolve()
    if destination == ROOT or not destination.is_relative_to(ROOT / ".build"):
        raise ValueError("Source destination must be inside this repository's .build directory")
    if destination.exists():
        raise ValueError("Destination already exists; choose a new --dest directory")

    destination.mkdir(parents=True)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(destination), *args], text=True).strip()

    git("init", "--quiet")
    git("remote", "add", "origin", repository)
    git("fetch", "--depth=1", "--no-tags", "origin", revision)
    git("checkout", "--quiet", "--detach", "FETCH_HEAD")
    if git("rev-parse", "HEAD") != revision:
        raise RuntimeError("Fetched revision does not match the upstream pin")
    # Check and stage each patch in series order; a conflict fails the build.
    for patch in patches:
        git("apply", "--check", "--index", str(patch))
        git("apply", "--index", str(patch))
    git("diff", "--cached", "--check")
    print(f"Prepared upstream {revision} with {len(patches)} patch(es) at {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=ROOT / ".build/upstream")
    parser.add_argument("--revision", help="test a candidate full upstream SHA without changing upstream.json")
    args = parser.parse_args()
    prepare(args.dest, args.revision)
