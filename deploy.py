"""Preview a serverless-only deployment; --apply explicitly creates resources."""

import argparse
import json
import re
import subprocess
import sys

from cache_models import MODEL_REFERENCE


def template_command(image, registry_auth_id=None):
    command = [
        "runpodctl", "template", "create", "--serverless",
        "--name", "qwen-image-21-gguf-cached",
        "--image", image, "--container-disk-in-gb", "30", "--volume-in-gb", "0",
        "--env", '{"COMFY_LOG_LEVEL":"INFO","SERVE_API_LOCALLY":"false","PUBLIC_KEY":""}',
    ]
    if registry_auth_id:
        command.extend(["--registry-auth-id", registry_auth_id])
    return command


def endpoint_command(template_id):
    return [
        "runpodctl", "serverless", "create", "--name", "qwen-image-21-gguf-cached",
        "--template-id", template_id, "--gpu-id", "NVIDIA GeForce RTX 4090",
        "--gpu-count", "1", "--workers-min", "0", "--workers-max", "1",
        "--idle-timeout", "1", "--flash-boot=true", "--execution-timeout", "600",
        "--scale-by", "delay", "--scale-threshold", "4", "--min-cuda-version", "12.8",
        "--model-reference", MODEL_REFERENCE,
    ]


def invoke(command):
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or not isinstance(response.get("id"), str) or not response["id"]:
        raise ValueError("runpodctl did not return a resource ID")
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Already built image, pinned as registry/image@sha256:<digest>")
    parser.add_argument("--registry-auth-id", help="Existing Runpod registry credential ID for private images; never pass a token here")
    parser.add_argument("--apply", action="store_true", help="Create a template and idle serverless endpoint; never submit a job")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}", args.image):
        parser.error("image must be pinned using @sha256:<64 lowercase hex characters>")
    template_args = template_command(args.image, args.registry_auth_id)
    if not args.apply:
        print(json.dumps([template_args, endpoint_command("<template-id>")], indent=2))
        return
    template = invoke(template_args)
    print(f"Created serverless template {template['id']}", file=sys.stderr)
    endpoint = invoke(endpoint_command(template["id"]))
    print(json.dumps(endpoint, indent=2))


if __name__ == "__main__":
    main()
