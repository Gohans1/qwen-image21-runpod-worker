import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/gohans1/qwen-image-21@sha256:" + "a" * 64


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = self.root / "calls.jsonl"
        fake_cli = self.root / "runpodctl"
        # Only the external Runpod CLI is replaced; the deployment process is real.
        fake_cli.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['CLI_RECORD'], 'a') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if os.environ.get('CLI_FAIL_TEMPLATE'):\n"
            "    sys.exit(1)\n"
            "print(json.dumps({'id': 'tpl-test' if sys.argv[1] == 'template' else 'ep-test'}))\n"
        )
        fake_cli.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}", CLI_RECORD=str(self.record))

    def run_deploy(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "deploy.py"), *args],
            capture_output=True, text=True, env=self.env, timeout=10,
        )

    def test_default_only_previews_and_does_not_create_resources(self):
        result = self.run_deploy(IMAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.record.exists())
        plan = json.loads(result.stdout)
        self.assertEqual(plan[0][:2], ["runpodctl", "template"])
        self.assertEqual(plan[1][:2], ["runpodctl", "serverless"])

    def test_apply_creates_only_serverless_with_cost_controls_and_pinned_cache(self):
        result = self.run_deploy(IMAGE, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        template, endpoint = calls
        self.assertEqual(template[:2], ["template", "create"])
        self.assertIn("--serverless", template)
        self.assertEqual(template[template.index("--volume-in-gb") + 1], "0")
        self.assertEqual(endpoint[:2], ["serverless", "create"])
        required = {
            "--template-id": "tpl-test", "--workers-min": "0", "--workers-max": "1",
            "--gpu-count": "1", "--idle-timeout": "1", "--execution-timeout": "600",
            "--gpu-id": "NVIDIA GeForce RTX 4090", "--scale-by": "delay",
            "--min-cuda-version": "12.8",
            "--model-reference": "https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF:6b34e59458d3eb7ba6a6f86a116aed5253dc02c3",
        }
        for flag, value in required.items():
            with self.subTest(flag=flag):
                self.assertEqual(endpoint[endpoint.index(flag) + 1], value)
        self.assertIn("--flash-boot=true", endpoint)
        self.assertNotIn("--wait", endpoint)
        self.assertFalse(any(arg.startswith("--network-volume") for arg in endpoint))
        self.assertFalse(any(call[0] in {"pod", "network-volume"} for call in calls))
        self.assertEqual(json.loads(result.stdout)["id"], "ep-test")

    def test_mutable_image_tag_is_rejected_without_any_api_calls(self):
        result = self.run_deploy("ghcr.io/gohans1/qwen-image-21:latest", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256", result.stderr)
        self.assertFalse(self.record.exists())

    def test_private_image_uses_a_registry_reference_without_exposing_credentials(self):
        result = self.run_deploy(IMAGE, "--registry-auth-id", "registry-test", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        template = calls[0]
        self.assertEqual(template[template.index("--registry-auth-id") + 1], "registry-test")
        self.assertNotIn("--registry-auth-id", calls[1])

    def test_failed_template_creation_does_not_attempt_to_create_endpoint(self):
        self.env["CLI_FAIL_TEMPLATE"] = "1"
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["template", "create"])


if __name__ == "__main__":
    unittest.main()
