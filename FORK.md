# Maintaining this fork

This repository tracks `https://github.com/jdbridge/wyoming-vulkan` on `upstream/main`.
Fork-specific commits add HA vocabulary biasing and GitHub image/update workflows. Keep new features in
separate commits so they remain easy to review when upstream changes.

## Image tags

Images are published to `ghcr.io/kordonskim/wyoming-vulkan` only after Linux container unit/protocol tests and
native binding ABI checks pass. GPU integration tests still need a Vulkan host.

| Build | Published tags |
| --- | --- |
| Push to `main`, or manual Docker workflow run on `main` | `latest`, `sha-<12-character commit>` |
| Push a release Git tag such as `v0.10.0-ha.1` | `0.10.0-ha.1`, `sha-<12-character commit>` |
| Pull request, or manual run on another branch | Checks only; no image published |

`latest` follows this fork's main branch. Release tags do not move `latest`, so releasing an older revision
cannot roll it back. Version strings name this fork's releases; the Python package version still identifies
the upstream software version. Choose a new release tag for each release, and do not move existing tags.

To release a tested commit already pushed to your fork:

```bash
git tag -a v0.10.0-ha.1 -m "Home Assistant vocabulary biasing release 1"
git push origin v0.10.0-ha.1
```

Use a pinned image tag in `deploy/.env`, for example:

```dotenv
WYOMING_VULKAN_IMAGE=ghcr.io/kordonskim/wyoming-vulkan:0.10.0-ha.1
```

The shipped Compose stack uses `pull_policy: never` for local builds. Pull the selected published image explicitly
before starting it:

```bash
docker pull ghcr.io/kordonskim/wyoming-vulkan:0.10.0-ha.1
cd deploy && docker compose up -d
```

Release and SHA tags remain available for rollback. For an exact image artifact, pin its registry digest.
HA credentials belong in a mounted token file, never in image tags, build arguments, the repository or the image.

## Update from jdbridge

In your fork's **Actions**, choose **Update from upstream**, then **Run workflow** on `main`.
It merges upstream into a new review branch and opens a PR; it never pushes directly to `main`.
The workflow explicitly dispatches **Checks** on that branch. Review its results and the PR before merging.
Merging the PR triggers the Docker workflow and publishes new `latest` and SHA tags after checks pass.
An already open upstream PR must be merged or closed before another is created.

Enable **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve
pull requests**. Repository/organization policy must allow the declared workflow permissions. No personal access
token is needed. If the PR's separate automatic checks request approval, use **Approve workflows to run**;
the explicitly dispatched Checks run is also available in Actions.

If an upstream merge conflicts with HA support or the image workflows, the update workflow stops without
changing main. Resolve locally using the steps below; do not discard the fork's feature commits.

```bash
# Once per clone (already configured in this working copy):
git remote add upstream https://github.com/jdbridge/wyoming-vulkan.git

# Start with a clean working tree:
git switch main
git pull --ff-only origin main
git fetch upstream --no-tags
git switch -c codex/upstream-update
git merge upstream/main
# Resolve conflicts, stage the resolved files, and complete the merge if necessary.
git push -u origin codex/upstream-update
```

Open a PR from that branch into your fork's main and wait for checks. Fetching with `--no-tags` keeps upstream
release tags separate from this fork's image releases. Do not use a force-sync or hard reset to update main:
that would discard the fork's changes.
