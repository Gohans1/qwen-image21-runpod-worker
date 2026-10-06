"""Expose the pinned Runpod model cache to ComfyUI without runtime downloads."""

import os
from pathlib import Path

MODEL_REVISION = "511a4f966b5e6684d383e0287cd9685c5f3d897c"
MODEL_REFERENCE = (
    "https://huggingface.co/Gohans/qwen-image21-selected:"
    + MODEL_REVISION
)
HUB_DIR = Path("/runpod-volume/huggingface-cache/hub")
MODEL_FILES = {
    "qwen-image-2.1-UC-Q4_K_M.gguf": "diffusion_models/qwen-image-2.1-UC-Q4_K_M.gguf",
    "text_encoders/qwen3vl_8b_int8_convrot.safetensors": "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    "vae/qwen_image_2.1_vae_bf16.safetensors": "vae/qwen_image_2.1_vae_bf16.safetensors",
}


def find_snapshot(hub_dir=HUB_DIR):
    """Scan the Hugging Face cache directory to find a snapshot containing the required models."""
    if not hub_dir.is_dir():
        raise FileNotFoundError(f"No valid model snapshot found; cache directory does not exist: {hub_dir}")

    candidates = []
    for model_dir in hub_dir.iterdir():
        if not model_dir.is_dir() or not model_dir.name.startswith("models--"):
            continue
        snapshots_dir = model_dir / "snapshots"
        if not snapshots_dir.is_dir():
            continue
        for snapshot in snapshots_dir.iterdir():
            if snapshot.is_dir() and all((snapshot / src).is_file() for src in MODEL_FILES):
                candidates.append(snapshot)

    if not candidates:
        raise FileNotFoundError(
            f"No valid model snapshot found in {hub_dir} containing required files: {list(MODEL_FILES.keys())}"
        )
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def link_models(snapshot=None, models=Path("/comfyui/models"), hub_dir=HUB_DIR):
    if snapshot is None:
        snapshot = find_snapshot(hub_dir)
    pairs = [(snapshot / source, models / target) for source, target in MODEL_FILES.items()]
    missing = [str(source) for source, _ in pairs if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "Runpod model cache is missing required files; configure Model as "
            f"{MODEL_REFERENCE}. No runtime download will be attempted: {missing}"
        )
    for source, target in pairs:
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != source.resolve():
                raise FileExistsError(f"Refusing to overwrite existing model: {target}")
    for source, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_symlink():
            target.symlink_to(source)


if __name__ == "__main__":
    link_models()
    print("Qwen-Image-2.1: cached model files are ready", flush=True)
    os.execv("/start.sh", ["/start.sh"])
