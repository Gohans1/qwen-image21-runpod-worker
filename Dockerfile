# Published 5.10.0-base linux/amd64 image; 5.11.0-base is not published.
FROM runpod/worker-comfyui:5.10.0-base@sha256:5e77b7d8ad559abcb02cca08165e400bef7372bdd9f599811c746019cb410de8

# ComfyUI v0.38.0 adds native Qwen-Image-2.1 support missing from the base.
RUN git -C /comfyui fetch --depth=1 origin 6b747c0428c343e1417219641db93a4fb7cb69ae \
    && git -C /comfyui checkout --detach FETCH_HEAD \
    && uv pip install -r /comfyui/requirements.txt \
        'transformers==4.57.6' 'huggingface-hub==0.36.2' 'gguf==0.19.0'

# Diffusion GGUF only; no optional GGUF tokenizer dependencies are needed.
RUN git clone https://github.com/leejet/ComfyUI-GGUF /comfyui/custom_nodes/ComfyUI-GGUF \
    && git -C /comfyui/custom_nodes/ComfyUI-GGUF checkout 373048b8403a7820620065210a691263d4da0a61

# Same CPU-only import smoke check used by the upstream worker build.
RUN cd /comfyui && timeout 300 python main.py --quick-test-for-ci --cpu

COPY cache_models.py /cache_models.py
ENV COMFY_LOG_LEVEL=INFO \
    SERVE_API_LOCALLY=false \
    PUBLIC_KEY="" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
CMD ["python", "-u", "/cache_models.py"]
