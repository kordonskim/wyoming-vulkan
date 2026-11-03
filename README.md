# Wyoming Vulkan with Home Assistant vocabulary biasing

This is a **patch and Docker build repository** for [jdbridge/wyoming-vulkan](https://github.com/jdbridge/wyoming-vulkan).
Each build downloads upstream source, applies the HA vocabulary patch, runs checks, and publishes tagged images.
You do not need another fork or a manually synchronized copy of upstream code.

The patch adds conversation-exposed entity names, aliases, areas and floors to Whisper.cpp's `initial_prompt`,
including Medium and Large V3 Turbo. One asynchronous cache refreshes vocabulary without waiting during
transcription. Prompts use native token counting and a configurable budget. Parakeet, Wyoming endpoints and
Vulkan device initialization retain their existing behavior. HA tokens are supplied at runtime, never during builds.

## Build contents

- `upstream.json`: the exact jdbridge source revision to download.
- `patches/series`: the ordered patches to apply.
- `patches/0001-home-assistant-vocabulary.patch`: the HA feature, tests, configuration and documentation.
- `patches/0002-full-large-v3.patch`: adds full Large V3 Q5 to the model download catalog.
- `scripts/prepare-source.py`: download upstream and apply the patch series to a new `.build/upstream` directory.
- `scripts/fetch-models.sh`: deployment-compatible wrapper for the pinned upstream model downloader.
- `.github/workflows/`: checks, tagged images, and proposed upstream revision updates.

The pin makes a release reproducible. **Update from upstream** proposes the latest jdbridge main revision;
it does not merge upstream source files into this repository. GitHub may still label this existing repository
as a fork, but builds work from the downloaded revision and patches independently of that relationship.

## Images

Images: `ghcr.io/kordonskim/wyoming-vulkan`.

| Trigger | Image tags |
| --- | --- |
| Manually run Build Wyoming Vulkan on main, entering `v0.1.1` | `v0.1.1`, `latest`; creates Git tag `v0.1.1` |
| Push to main or push a Git tag | No image build |
| Pull request, or manually run Checks | Checks only; no publishing |

Images publish after container unit/protocol tests and native ABI checks pass. Real GPU integration tests
require a Vulkan host. Image labels record the upstream and build-repository revisions. Release image tags keep
the `v` prefix, such as `v0.1.0` and `v0.2.0`. `latest` follows the most recent successful manual release. Deploy any chosen version manually;
the workflows build images but do not update your running containers. See [maintenance and releases](FORK.md).

## Local build

Requires Git, Python 3.9+, Docker and a Linux container engine:

```bash
git clone https://github.com/kordonskim/wyoming-vulkan.git
cd wyoming-vulkan
python3 scripts/prepare-source.py
docker build -t wyoming-vulkan:ha .build/upstream
```

The script refuses to overwrite an existing destination. For another attempt, choose a new directory,
for example `python3 scripts/prepare-source.py --dest .build/rebuild-2`, and build from that directory.
Generated source is ignored by Git. The HA instructions and complete deployment configuration are in
`.build/upstream/README.md` and `.build/upstream/config/config.example.toml` after preparation.

## Deploy

For persistent Kubernetes deployments, see the [separate model-download Job example](examples/kubernetes-model-job/README.md).
It moves network preparation out of normal pod startup and replaces it with a quick read-only file check.

Existing init containers can continue cloning this repository and running `scripts/fetch-models.sh` directly.
The wrapper downloads the model script from the revision in `upstream.json`, applies the model catalog extension,
and forwards all arguments. It does not need Python or a prepared source tree. It requires Bash, Git, curl, sed and coreutils, matching the Alpine init
container packages below. The downloader verifies model checksums and reuses already downloaded models.

For Parakeet, Medium, Large V3 Turbo and full Large V3 Q5, use this init container
with the existing `data` volume. This downloads models only; it does not build or run the server image:

```yaml
initContainers:
  - name: fetch-models
    image: alpine:3.20
    command: ["/bin/sh", "-ec"]
    args:
      - |
        apk add --no-cache bash curl git coreutils ca-certificates
        git clone --depth 1 https://github.com/kordonskim/wyoming-vulkan.git /tmp/wyoming-vulkan
        bash /tmp/wyoming-vulkan/scripts/fetch-models.sh -d /data/models parakeet-q8_0 whisper-medium-q5_0 whisper-large-v3-turbo-q5_0 whisper-large-v3-q5_0
        mkdir -p /data/voices
    volumeMounts:
      - name: data
        mountPath: /data
```

Keep the application image pinned to your chosen release, such as
`ghcr.io/kordonskim/wyoming-vulkan:v0.1.0`. The init container above clones main so it receives the restored wrapper;
the historical `v0.1.0` Git tag predates that wrapper. For future releases containing the wrapper, clone the matching
release tag with `git clone --branch vX.Y.Z --depth 1 ...` to keep the downloader pin aligned with the image.

Use the prepared deployment files. Download the models and prepare your local environment:

```bash
cd .build/upstream
scripts/fetch-models.sh -d deploy/data/models
cp deploy/.env.example deploy/.env
```

Edit `deploy/.env` for your GPU, user IDs and image choice, e.g.
`WYOMING_VULKAN_IMAGE=ghcr.io/kordonskim/wyoming-vulkan:latest`. The stack uses `pull_policy: never`, so pull
published images explicitly before starting; a locally built `wyoming-vulkan:ha` image needs no pull.

```bash
docker pull ghcr.io/kordonskim/wyoming-vulkan:latest
cd deploy && docker compose up -d
```

For HA vocabulary biasing, put your HA long-lived token in `deploy/data/secrets/ha-token` within the prepared
source and set these nonsecret options in its `deploy/.env`:

```dotenv
HASS_API=http://homeassistant.local:8123/api
HASS_TOKEN_FILE=/data/secrets/ha-token
HASS_REFRESH_SECONDS=60
HASS_TIMEOUT=10
HASS_PROMPT_MAX_TOKENS=200
```

Make the token file readable by the container's configured user. Both environment files and token files stay
outside tracked source and Docker build context. Keep persistent models, tokens and deployment settings in a
stable external directory when preparing newer builds; the preparation script never migrates or deletes them.

## Full Large V3 alongside Turbo

Full Large V3 Q5 downloads as `whisper/ggml-large-v3-q5_0.bin` (1,081,140,203 bytes, approximately 1.08 GB).
The catalog pins the model revision and verifies its SHA-256. Download it with:

```bash
bash scripts/fetch-models.sh -d /data/models whisper-large-v3-q5_0
```

In Kubernetes, append `whisper-large-v3-q5_0` to your init container's existing download command, as above.
Then append [this configuration fragment](examples/large-v3.config.toml) to the `config.toml` in your ConfigMap.
It adds a separate full Large V3 model and endpoint on port **10314**, retaining your current Medium, Turbo
and Parakeet configuration. Your existing image, including `v0.1.0`, can load this model; no image rebuild is needed.

Also add the new port to the application container and its existing Kubernetes Service:

```yaml
# Add to containers[].ports:
- name: whisper-full-v3
  containerPort: 10314

# Add to the Service's spec.ports:
- name: whisper-full-v3
  port: 10314
  targetPort: whisper-full-v3
  protocol: TCP
```

Reapply your manifests and restart the Deployment so the init container downloads the model and the mounted
config is reloaded. Add the new endpoint to Home Assistant's Wyoming integration using the Service's reachable
address and port 10314. If using a NodePort or another external mapping, use that published port instead.
Select **Whisper Large V3 Q5** for speech-to-text in a voice assistant to compare with Turbo. Your existing
`[hass]` configuration and token enable vocabulary biasing for the new model automatically.

The generated README also documents separate Medium and Large V3 Turbo endpoints. No HA credentials are
required to build or test an image. Full Large V3 uses more runtime memory and may take longer to transcribe
than Turbo; model file size alone does not measure total GPU or system memory usage.
