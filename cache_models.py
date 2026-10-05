"""Expose the pinned Runpod model cache to ComfyUI without runtime downloads."""

import os
from pathlib import Path

MODEL_REVISION = "6b34e59458d3eb7ba6a6f86a116aed5253dc02c3"
MODEL_REFERENCE = (
    "https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF:"
    + MODEL_REVISION
)
SNAPSHOT = Path(
    "/runpod-volume/huggingface-cache/hub/"
    "models--abenzerps--Qwen-Image-2.1-Uncensored-GGUF/snapshots/"
) / MODEL_REVISION
MODEL_FILES = {
    "qwen-image-2.1-UC-Q4_K_M.gguf": "diffusion_models/qwen-image-2.1-UC-Q4_K_M.gguf",
    "text_encoders/qwen3vl_8b_int8_convrot.safetensors": "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    "vae/qwen_image_2.1_vae_bf16.safetensors": "vae/qwen_image_2.1_vae_bf16.safetensors",
}


def link_models(snapshot=SNAPSHOT, models=Path("/comfyui/models")):
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
