"""Preview a serverless-only deployment; --apply explicitly creates resources."""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

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


def runpod_api_key():
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        config = tomllib.loads((Path.home() / ".runpod" / "config.toml").read_text())
        key = config.get("apikey") or config.get("apiKey")
    if not isinstance(key, str) or not key.strip() or not key.isascii() or any(c.isspace() for c in key.strip()):
        raise ValueError("A valid Runpod API key is required; no credential value will be printed")
    return key.strip()


def ports_patch_plan(template_id):
    base = (os.environ.get("RUNPOD_REST_V2_URL") or "https://api.runpod.io/v2").rstrip("/")
    parsed = urlsplit(base)
    loopback = (parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.path == "/v2"
                and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment)
    if base != "https://api.runpod.io/v2" and not loopback:
        raise ValueError("Port patch permits only the official Runpod API or loopback testing")
    return {"method": "PATCH", "url": base + "/templates/" + quote(template_id, safe=""), "body": {"ports": []}}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward the API credential to a redirected recipient.


def clear_template_ports(template_id, key):
    patch = ports_patch_plan(template_id)
    request = urllib.request.Request(patch["url"], data=json.dumps(patch["body"]).encode(), method="PATCH",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        updated = json.load(response)
    if updated.get("id") != template_id or updated.get("serverless") is not True or updated.get("ports") != []:
        raise ValueError("Port removal was not verified on the created serverless template; endpoint not created")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Already built image, pinned as registry/image@sha256:<digest>")
    parser.add_argument("--registry-auth-id", help="Existing Runpod registry credential ID for private images; never pass a token here")
    parser.add_argument("--apply", action="store_true", help="Create a template and idle serverless endpoint; never submit a job")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}", args.image):
        parser.error("image must be pinned using @sha256:<64 lowercase hex characters>")
    template_args = template_command(args.image, args.registry_auth_id)
    patch = ports_patch_plan("<template-id>")
    if not args.apply:
        print(json.dumps([template_args, patch, endpoint_command("<template-id>")], indent=2))
        return
    key = runpod_api_key()
    template = invoke(template_args)
    print(f"Created serverless template {template['id']}", file=sys.stderr)
    clear_template_ports(template["id"], key)
    print("Verified serverless template ports: []", file=sys.stderr)
    endpoint = invoke(endpoint_command(template["id"]))
    print(json.dumps(endpoint, indent=2))


if __name__ == "__main__":
    main()
