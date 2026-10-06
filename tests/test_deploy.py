import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/gohans1/qwen-image-21@sha256:" + "a" * 64


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = self.root / "calls.jsonl"
        self.state = self.root / "template.json"
        self.state.write_text(json.dumps({"id": "tpl-test", "serverless": True, "ports": ["22/tcp", "8888/http"]}))
        self.patch_status = 200
        self.keep_ports = False
        self.response_override = {}
        self.requests = []
        case = self

        class TemplateAPI(BaseHTTPRequestHandler):
            def do_PATCH(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                case.requests.append({"path": self.path, "body": body, "authorization": self.headers.get("Authorization")})
                template = json.loads(case.state.read_text())
                if case.patch_status == 200 and not case.keep_ports:
                    template.update(body)
                    case.state.write_text(json.dumps(template))
                payload = json.dumps(template | case.response_override).encode()
                self.send_response(case.patch_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), TemplateAPI)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.api_url = f"http://127.0.0.1:{server.server_port}/v2"
        fake_cli = self.root / "runpodctl"
        # Only external CLI/API boundaries are faked; the deployment process is real.
        fake_cli.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['CLI_RECORD'], 'a') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if os.environ.get('CLI_FAIL_TEMPLATE'):\n"
            "    sys.exit(1)\n"
            "template = json.load(open(os.environ['CLI_TEMPLATE_STATE']))\n"
            "print(json.dumps(template if sys.argv[1] == 'template' else {'id': 'ep-test', 'ports': template['ports']}))\n"
        )
        fake_cli.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}", CLI_RECORD=str(self.record),
                        CLI_TEMPLATE_STATE=str(self.state), HOME=str(self.root), RUNPOD_API_KEY="test-only-key",
                        RUNPOD_REST_V2_URL=self.api_url)

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
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[1]["method"], "PATCH")
        self.assertEqual(plan[1]["body"], {"ports": []})
        self.assertEqual(plan[2][:2], ["runpodctl", "serverless"])
        self.assertEqual(self.requests, [])

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

    def test_endpoint_inherits_no_ports_after_the_authenticated_template_patch(self):
        result = self.run_deploy(IMAGE, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["ports"], [])
        self.assertEqual(self.requests, [{"path": "/v2/templates/tpl-test", "body": {"ports": []},
                                         "authorization": "Bearer test-only-key"}])

    def test_patch_failure_does_not_create_endpoint(self):
        self.patch_status = 503
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual([call[:2] for call in calls], [["template", "create"]])

    def test_unremoved_ports_do_not_create_endpoint_even_when_patch_returns_success(self):
        self.keep_ports = True
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual([call[:2] for call in calls], [["template", "create"]])

    def test_api_key_is_read_from_the_existing_cli_toml_without_logging_it(self):
        self.env.pop("RUNPOD_API_KEY")
        config = self.root / ".runpod" / "config.toml"
        config.parent.mkdir()
        config.write_text('apikey = "saved-test-only-key"\n')
        result = self.run_deploy(IMAGE, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["authorization"], "Bearer saved-test-only-key")
        self.assertNotIn("saved-test-only-key", result.stdout + result.stderr)

    def test_missing_credentials_do_not_create_resources(self):
        self.env.pop("RUNPOD_API_KEY")
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.requests, [])

    def test_untrusted_api_host_is_rejected_before_any_resources_are_created(self):
        self.env["RUNPOD_REST_V2_URL"] = "https://example.invalid/v2"
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.requests, [])

    def test_template_identity_and_serverless_kind_are_verified_before_deployment(self):
        for override in ({"id": "another-template"}, {"serverless": False}):
            with self.subTest(response=override):
                self.record.write_text("")
                self.response_override = override
                result = self.run_deploy(IMAGE, "--apply")
                self.assertNotEqual(result.returncode, 0)
                calls = [json.loads(line) for line in self.record.read_text().splitlines()]
                self.assertEqual([call[:2] for call in calls], [["template", "create"]])

    def test_invalid_auth_is_rejected_without_logging_it_or_creating_resources(self):
        secret = "invalid-test-key\nnever-print-this"
        self.env["RUNPOD_API_KEY"] = secret
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(self.requests, [])

    def test_failed_template_creation_does_not_attempt_to_create_endpoint(self):
        self.env["CLI_FAIL_TEMPLATE"] = "1"
        result = self.run_deploy(IMAGE, "--apply")
        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(line) for line in self.record.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["template", "create"])


if __name__ == "__main__":
    unittest.main()
