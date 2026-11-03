#!/usr/bin/env bash
# Compatibility entry point for deployments that clone this patch repository.
# Run the model downloader from the same pinned jdbridge revision as the image.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
revision=$(sed -nE 's/^[[:space:]]*"revision":[[:space:]]*"([0-9a-f]{40})"[[:space:],]*$/\1/p' "$ROOT/upstream.json")
if [[ ! $revision =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Cannot read the pinned upstream revision from upstream.json' >&2
  exit 1
fi
downloader=$(mktemp)
trap 'rm -f -- "$downloader"' EXIT
curl --fail --silent --show-error --location --retry 3 --proto '=https' \
  "https://raw.githubusercontent.com/jdbridge/wyoming-vulkan/$revision/scripts/fetch-models.sh" \
  --output "$downloader"
bash "$downloader" "$@"
