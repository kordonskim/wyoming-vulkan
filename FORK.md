# Maintaining the patch build

This repository contains a pinned upstream revision, a patch series and build workflows. The original full
source remains in Git history; current builds download jdbridge's source afresh. No force-sync or upstream
merge is needed. Existing repository URLs, image package names and history are preserved.

## Get upstream updates

In **Actions → Update from upstream**, run the workflow on `main`.

1. The job resolves jdbridge's current main commit.
2. It downloads that exact source and checks that the patch series applies cleanly.
3. It opens a PR changing only the revision in `upstream.json`.
4. It explicitly runs **Checks** on that PR branch: download, patch, build, unit/protocol tests and ABI checks.
5. Review the upstream changes and checks, then merge. Main's Docker workflow publishes tested tagged images.

A patch conflict stops the update; no image is published and the old pin remains unchanged. An already open
upstream update PR must be merged or closed before another is created. Real GPU tests still need your Vulkan host.

Enable **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve
pull requests**. Organization policy must permit the workflow's declared permissions. The built-in GitHub token
is sufficient; no personal access token or HA token is needed. Automatic PR checks may separately request approval;
the workflow explicitly dispatches Checks as well.

## Release an image

Main builds publish `latest` and `sha-<12-character commit>`. To publish a version for a tested commit:

```bash
git tag -a v0.10.0-ha.1 -m "Home Assistant vocabulary biasing release 1"
git push origin v0.10.0-ha.1
```

This publishes `ghcr.io/kordonskim/wyoming-vulkan:0.10.0-ha.1` and its SHA tag after checks, without moving
`latest`. Choose a new version for each release; do not move existing release tags. Pin the image tag in your
deployment's `WYOMING_VULKAN_IMAGE`, or pin its registry digest for an exact image artifact. Release versions
identify this build repository; the application's version still identifies the upstream software version.

## Change a patch

Prepare a fresh upstream source tree with `python3 scripts/prepare-source.py --dest .build/edit`.
The existing patches are staged in that tree's Git index against its upstream HEAD. Edit the generated source,
run its tests, and stage the intended changes **in the generated repository**. Never stage credentials or models.

Export the resulting diff relative to upstream HEAD to a temporary patch file:

```bash
git -C .build/edit diff --cached --binary --output=../../patches/0001-home-assistant-vocabulary.patch HEAD
```

The current series has one cumulative patch. If adding separate patches, export each against the source produced
by preceding patches and list them in `patches/series`. Validate a newly exported patch with a fresh preparation,
then commit the patch files and any pin change in this build repository. The export path above is relative to
`.build/edit`, placing it in the root `patches` directory.

To test a candidate revision without changing the pin:

```bash
python3 scripts/prepare-source.py --revision FULL_40_CHARACTER_SHA --dest .build/candidate
```

The script refuses to reuse existing destinations. Keep runtime data outside generated source directories when
updating deployments. For generated source's full Linux checks, use its `tests/run.sh` and `tests/check_abi.sh`;
the complete integration suite also needs downloaded models and a Vulkan GPU.
