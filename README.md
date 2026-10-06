# Qwen-Image-2.1 GGUF on Runpod Serverless

Serverless queue worker using Runpod's official ComfyUI handler, a pinned ComfyUI v0.38.0, and the leejet GGUF loader. No Pods or Network Volumes. The current authorized trial retains the template's default `22/tcp` and `8888/http` declarations; it does not intentionally enable SSH or a public ComfyUI interface.

## Status

The worker source and `linux/amd64` image have been published through a successful manual GitHub Actions build:

- Source: https://github.com/Gohans1/qwen-image21-runpod-worker
- Build: https://github.com/Gohans1/qwen-image21-runpod-worker/actions/runs/37368406033
- Built source commit: `05bc9e23f103b7cf1e6b0f5d0f6fdd6e9ba12433`
- Immutable image reference: `image-reference.txt`
- Verified in CI: 9 local behavior checks passed; the ComfyUI v0.38.0 CPU import smoke check passed, including ComfyUI-GGUF.

The image is public: anonymous GHCR manifest access and the `linux/amd64` digest were verified, and the live Runpod worker successfully pulled that digest without registry credentials.

One authorized GPU verification completed successfully on an RTX 4090 with PyTorch 2.11.0+cu128 and ComfyUI v0.38.0. The real mounted cache, all three selected models, GGUF loading, and the complete image workflow worked.

- Result: one decodable 1024 × 1024 RGBA PNG, 2,303,630 bytes; local artifact `test-output/qwen-image21.png` is gitignored.
- Initial queue/setup wait: 821.539 seconds; job execution: 30.759 seconds; ComfyUI reported 26.57 seconds for the prompt itself. This is one measurement, not a warm-start or two-hour inactivity guarantee.
- Observed account balance reduction: approximately $0.0143, below the approved $1 budget. Detailed endpoint billing records were still empty when checked; this balance change is not a guaranteed per-image price.
- The endpoint and its port declarations were retained. Workers were explicitly paused at `workersMin=workersMax=0` after verification; health showed zero workers, no queued/running jobs, one completed job, and no failures/retries. Reported current spend was $0/hour.
- ComfyUI runtime logs confirmed the service binds to `127.0.0.1:8188`. FlashBoot revival and performance after extended inactivity remain untested.

The user approved retaining the existing `22/tcp` and `8888/http` declarations for this trial. An attempted official API port patch returned Cloudflare `403` / error `1010`; this is not evidence of insufficient API-key permissions. The trial used `runpodctl` with the existing template rather than the strict no-port `deploy.py --apply` path, which remains unverified against the live API.

## Model cache

`deploy.py` assigns the pinned Hugging Face repository to the endpoint using `runpodctl --model-reference`. `cache_models.py` links the three required files from `/runpod-volume/huggingface-cache/hub/` into ComfyUI's model folders. It fails if the cache is missing; it never downloads models inside a billable worker or overwrites unrelated model files.

Selected files:

- `qwen-image-2.1-UC-Q4_K_M.gguf` (~4.60 GB)
- `text_encoders/qwen3vl_8b_int8_convrot.safetensors` (~9.35 GB)
- `vae/qwen_image_2.1_vae_bf16.safetensors` (~0.68 GB)

Runpod currently caches all quantizations in a repository, so the initial cache download can be approximately **105 GB**, not just the selected 14.63 GB. Cache download and container image pull are not billed as worker compute time. Initialization, model loading into memory, execution, idle timeout, and worker storage can still incur charges. Cached host availability and FlashBoot state retention are not guaranteed.

## Checks (no cloud resources)

```sh
uv run --no-project python -m unittest discover -s tests -v
```

The current 17 checks exercise real temporary cache files/symlinks and the deployment process with fake external CLI/localhost API boundaries. Port-removal regression checks failed before the fix and passed afterward. They do not prove container or GPU compatibility.

## Build and publish

A Docker-compatible builder and a container registry are required. Runpod accepts `linux/amd64` images. The published `5.10.0-base` image is pinned by digest; `5.11.0-base` was not available when this configuration was prepared. Model weights are not baked into the image.

```sh
docker build --platform linux/amd64 -t YOUR_REGISTRY/qwen-image-21:configured .
docker push YOUR_REGISTRY/qwen-image-21:configured
```

Use the resulting registry digest (`YOUR_REGISTRY/qwen-image-21@sha256:...`) for deployment. For a private image, register pull credentials with Runpod and pass their existing ID using `deploy.py --registry-auth-id REGISTRY_ID`. Never put a token in that argument or in source code. Do not publish code, run hosted builds, or change registry permissions without approval.

### Manual GitHub Actions alternative

`.github/workflows/build-image.yml` provides a builder when local Docker is unavailable. It runs only on `workflow_dispatch`, never automatically on push/PR. It intentionally skips private repositories to avoid consuming billable private-runner quota. It uses standard public-repository Ubuntu runners, a 30-minute timeout, pinned action commits, no external build caches or artifact uploads, and no Runpod credentials/API calls.

After approval to publish the configuration to a public repository, trigger **Build worker image (manual only)** manually. Unit checks and the Dockerfile's CPU import smoke check run before image publication. The run summary contains the immutable `ghcr.io/...@sha256:...` reference.

GHCR packages are initially private even when the source repository is public. Either keep the package private and configure Runpod registry pull credentials, or change package visibility only with explicit approval. Do not upload the local `AGENTS.md`, its git history, credentials, or other unrelated user files when preparing a public build repository.

The build workflow does not deploy to Runpod or start a GPU. GitHub's documentation states that standard public-repository runners are free and Container Registry storage/bandwidth is currently free; recheck policy before triggering hosted work.

## Preview / create an idle endpoint

```sh
# Preview only; no Runpod API calls.
uv run --no-project python deploy.py 'YOUR_REGISTRY/qwen-image-21@sha256:ACTUAL_DIGEST'

# Only after the image is built, published, checked, and deployment is approved.
uv run --no-project python deploy.py 'YOUR_REGISTRY/qwen-image-21@sha256:ACTUAL_DIGEST' --apply > endpoint.json
```

The image digest must contain 64 lowercase hexadecimal characters. Do not use `latest`.

Configuration:

| Setting | Value |
| --- | --- |
| GPU | RTX 4090, one GPU |
| Minimum / maximum workers | 0 / 1 |
| Idle timeout | 1 second |
| Execution timeout | 600 seconds |
| Scaling | Queue delay, threshold 4 seconds |
| FlashBoot | Enabled |
| Minimum CUDA | 12.8 |
| Container disk | 30 GB |
| Volume disk / Network Volume | 0 GB / none |

`--apply` requires Python 3.11+ and the existing `RUNPOD_API_KEY` or `~/.runpod/config.toml` credential. It uses the official API to explicitly set template `ports: []` and verifies the returned template before creating an endpoint; the CLI omits empty ports. The preview displays that PATCH without exposing credentials or making API calls. A refused/failed patch prevents endpoint creation.

`--apply` creates a serverless template and idle endpoint only: it does not submit a job or wait for a GPU worker. A worker limit is not a monetary budget. If endpoint creation fails after template creation, its ID is printed to stderr; inspect `runpodctl template list` / `runpodctl serverless list` before retrying to avoid duplicate resources.

## Paid verification (requires separate approval)

`workflow.json` is a handler payload, not a UI-format workflow or an outer `input` wrapper. It uses a 1024 x 1024 latent, one image, 25 Euler steps, CFG 1, and no optional prompt-enhancement model.

```sh
# This invokes GPU compute and costs money. Do not run without approval.
runpodctl serverless run ENDPOINT_ID --input-file workflow.json --wait 15m > result.json
```

Confirm a completed job, a decodable non-empty image in `output.images[].data`, no model/node errors, and worker scale-down. A client wait timeout does not cancel a job. The trial used an independent local 30-minute worker-stop timer, not a provider-enforced dollar cap. It was cancelled only after the successful result, explicit `workersMin=workersMax=0`, and verified zero workers. Do not automatically resubmit failed jobs. Download results promptly; Runpod retains asynchronous results for only a limited time.

### Resume the retained endpoint (requires a new approved run)

The retained endpoint is paused, not deleted. Re-enable at most one worker only when another paid request is approved, then stop workers after that request:

```sh
runpodctl serverless update ENDPOINT_ID --workers-min 0 --workers-max 1
# Submit an approved request, collect the result, then pause:
runpodctl serverless update ENDPOINT_ID --workers-min 0 --workers-max 0
```

## License

Qwen-Image-2.1 is subject to the Qwen Research License: research/evaluation only, not general commercial use. A separate commercial license is required for commercial use. The GGUF release's "Uncensored" label does not remove these restrictions.

## Sources

- https://docs.runpod.io/tutorials/serverless/comfyui
- https://docs.runpod.io/serverless/endpoints/model-caching
- https://docs.runpod.io/serverless/pricing
- https://github.com/runpod-workers/worker-comfyui
- https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.38.0
- https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF
- https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/billing/concepts/product-billing/github-packages
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
