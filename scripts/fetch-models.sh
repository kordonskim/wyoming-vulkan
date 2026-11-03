#!/usr/bin/env bash
# Compatibility entry point for deployments that clone this patch repository.
# Run the pinned upstream downloader with this repository's model catalog extension.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
revision=$(sed -nE 's/^[[:space:]]*"revision":[[:space:]]*"([0-9a-f]{40})"[[:space:],]*$/\1/p' "$ROOT/upstream.json")
if [[ ! $revision =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Cannot read the pinned upstream revision from upstream.json' >&2
  exit 1
fi
work_parent=$(cd -- "${TMPDIR:-/tmp}" && pwd)
work_dir=$(mktemp -d "$work_parent/wyoming-models.XXXXXXXX")
cleanup() {
  # Bound recursive cleanup to the temporary directory created above.
  [[ "$work_dir" == "$work_parent"/wyoming-models.* && "$work_dir" != "$work_parent" ]] || return 1
  rm -rf -- "$work_dir"
}
trap cleanup EXIT
mkdir -p "$work_dir/scripts"
git -C "$work_dir" init --quiet
downloader="$work_dir/scripts/fetch-models.sh"
curl --fail --silent --show-error --location --retry 3 --proto '=https' \
  "https://raw.githubusercontent.com/jdbridge/wyoming-vulkan/$revision/scripts/fetch-models.sh" \
  --output "$downloader"
chmod +x "$downloader"
git -C "$work_dir" apply --check "$ROOT/patches/0002-full-large-v3.patch"
git -C "$work_dir" apply "$ROOT/patches/0002-full-large-v3.patch"
bash "$downloader" "$@"
