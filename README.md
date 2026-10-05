# Qwen-Image-2.1 GGUF on Runpod Serverless

Serverless queue worker using Runpod's official ComfyUI handler, a pinned ComfyUI v0.38.0, and the leejet GGUF loader. No Pods, Network Volumes, SSH ports, or public ComfyUI interface.

## Status

The deployment configuration, local checks, and manual GitHub Actions build workflow are prepared. The image has not been built or published, and no GitHub repository, Runpod endpoint, or paid inference job has been created. Container startup and GPU inference are not yet verified. Publishing source, triggering a build, creating an endpoint, and running GPU verification remain behind the user's final approval.

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

The checks exercise real temporary cache files/symlinks and the deployment process with a fake CLI boundary. They do not prove container or GPU compatibility.

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

`--apply` creates a serverless template and idle endpoint only: it does not submit a job or wait for a GPU worker. A worker limit is not a monetary budget. If endpoint creation fails after template creation, its ID is printed to stderr; inspect `runpodctl template list` / `runpodctl serverless list` before retrying to avoid duplicate resources.

## Paid verification (requires separate approval)

`workflow.json` is a handler payload, not a UI-format workflow or an outer `input` wrapper. It uses a 1024 x 1024 latent, one image, 25 Euler steps, CFG 1, and no optional prompt-enhancement model.

```sh
# This invokes GPU compute and costs money. Do not run without approval.
runpodctl serverless run ENDPOINT_ID --input-file workflow.json --wait 15m > result.json
```

Confirm a completed job, a decodable non-empty image in `output.images[].data`, no model/node errors, and worker scale-down. A client wait timeout does not cancel a job. Download results promptly; Runpod retains asynchronous results for only a limited time.

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
