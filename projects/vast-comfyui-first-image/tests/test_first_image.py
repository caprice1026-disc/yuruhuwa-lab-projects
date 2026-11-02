"""Offline fixtures only: no Vast.ai, SSH, model download or GPU execution."""
import contextlib
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zlib

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate = load("generate")
setup = load("setup_remote")


def png(width=768, height=1024):
    def chunk(name, value):
        return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value) & 0xFFFFFFFF)
    # A black synthetic test fixture, not a generated example image.
    data = zlib.compress((b"\0" + b"\0\0\0" * width) * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", data) + chunk(b"IEND", b"")


def success(filename="test.png"):
    return {"job-1": {"status": {"completed": True, "status_str": "success"},
                      "outputs": {"7": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}}}}


class FakeClient:
    def __init__(self, history=None, image=None):
        self.history = success() if history is None else history
        self.image = png() if image is None else image
        self.calls = []

    def request(self, route, payload=None, **kwargs):
        self.calls.append((route, payload))
        if route == "/prompt":
            return {"prompt_id": "job-1"}
        if route.startswith("/history/"):
            return self.history
        return self.image


class FirstImageTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("powershell") or shutil.which("pwsh"), "PowerShell is unavailable")
    def test_recovery_snippet_sets_variables_in_fresh_powershell(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        snippet = next(code for code in re.findall(r"```powershell\n(.*?)```", readme, re.S)
                       if "./outputs/recovered/" in code)
        # Run the documented snippet in an isolated new shell. SCP is a local stub:
        # no key is read and no SSH connection is made.
        script = """$ErrorActionPreference = 'Stop'
$script:answers = [System.Collections.Generic.Queue[string]]::new()
$script:answers.Enqueue('fixture.example.invalid')
$script:answers.Enqueue('2345')
$script:answers.Enqueue('fixture-user')
function Read-Host { $script:answers.Dequeue() }
function scp { $script:copiedArgs = @($args); $global:LASTEXITCODE = 0 }
""" + snippet + "\nConvertTo-Json -InputObject $script:copiedArgs -Compress\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recovery.ps1"
            path.write_text(script, encoding="utf-8-sig")
            result = subprocess.run([shutil.which("pwsh") or shutil.which("powershell"), "-NoProfile", "-File", str(path)], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = json.loads(result.stdout)
            self.assertIn("2345", [str(arg) for arg in args])
            self.assertIn("fixture-user@fixture.example.invalid:/workspace/vast-first-image/ComfyUI/output", args)
            self.assertTrue(str(args[1]).endswith("vast-first-image_ed25519"))
            self.assertTrue((Path(folder) / "outputs/recovered").is_dir())

    @unittest.skipUnless(shutil.which("powershell") or shutil.which("pwsh"), "PowerShell is unavailable")
    def test_status_and_history_from_fresh_powershell_only_get(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                requests.append(("GET", self.path))
                value = ({"system": {}, "devices": [{"type": "cuda", "name": "fixture GPU"}]}
                         if self.path == "/system_stats" else success())
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            def do_POST(self):
                requests.append(("POST", self.path))
                self.send_error(405)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="vast ps ") as folder:
                job = Path(folder) / "job.json"
                job.write_text('{"prompt_id":"job-1"}', encoding="utf-8")
                quote_ps = lambda value: "'" + str(value).replace("'", "''") + "'"
                script = (f"$ErrorActionPreference = 'Stop'\nSet-Location {quote_ps(ROOT)}\n"
                          f"& {quote_ps(sys.executable)} -X utf8 generate.py status --port {server.server_port} --wait-seconds 2\n"
                          "if ($LASTEXITCODE -ne 0) { throw 'status failed' }\n"
                          f"function Read-Host {{ {quote_ps(job)} }}\n"
                          "$jobFile = Read-Host 'job.json path'\n"
                          f"& {quote_ps(sys.executable)} -X utf8 generate.py history --port {server.server_port} --job-file \"$jobFile\"\n"
                          "if ($LASTEXITCODE -ne 0) { throw 'history failed' }\n")
                path = Path(folder) / "readonly.ps1"
                path.write_text(script, encoding="utf-8-sig")
                result = subprocess.run([shutil.which("pwsh") or shutil.which("powershell"), "-NoProfile", "-File", str(path)], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('"ready"', result.stdout)
                self.assertIn('"succeeded"', result.stdout)
                self.assertEqual(requests, [("GET", "/system_stats"), ("GET", "/history/job-1")])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_ready_retries_reads_until_cuda_is_reported(self):
        client = Mock()
        client.request.side_effect = [generate.URLError("not listening"),
            {"system": {}, "devices": [{"type": "cuda", "name": "fixture GPU"}]}]
        with patch.object(generate.time, "sleep"):
            result = generate.wait_ready(client)
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["generation_submitted"])
        self.assertEqual([call.args for call in client.request.call_args_list], [("/system_stats",)] * 2)

    def test_ready_timeout_is_bounded_and_never_posts(self):
        client = Mock()
        client.request.side_effect = generate.URLError("not listening")
        with patch.object(generate.time, "monotonic", side_effect=[0, 0, 0, 2, 2]), patch.object(generate.time, "sleep"), self.assertRaises(TimeoutError):
            generate.wait_ready(client, wait_seconds=1)
        client.request.assert_called_once_with("/system_stats", timeout=1)

    def test_ready_rejects_wrong_service_or_cpu_only(self):
        for response in ({}, {"system": {}, "devices": [{"type": "cpu", "name": "CPU"}]}):
            client = Mock()
            client.request.return_value = response
            with self.assertRaises((ValueError, RuntimeError)):
                generate.wait_ready(client)
            self.assertEqual(client.request.call_count, 1)

    def test_history_states_are_read_only_and_do_not_claim_missing_job_failed(self):
        cases = [(success(), {}, "succeeded"),
                 ({"job-1": {"status": {"status_str": "error"}}}, {}, "failed"),
                 ({}, {"queue_running": [[0, "job-1"]]}, "running"),
                 ({}, {"queue_pending": [[0, "job-1"]]}, "queued"),
                 ({}, {"queue_running": [], "queue_pending": []}, "unknown")]
        with tempfile.TemporaryDirectory() as folder:
            job_file = Path(folder) / "job.json"
            job_file.write_text('{"prompt_id":"job-1"}', encoding="utf-8")
            for history, queue, expected in cases:
                client = Mock()
                client.request.side_effect = [history, queue]
                result = generate.inspect_job(client, job_file)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["generation_submitted"])
                self.assertEqual(client.request.call_args_list[0].args, ("/history/job-1",))
                self.assertTrue(all(len(call.args) == 1 for call in client.request.call_args_list))
                self.assertEqual(list(Path(folder).iterdir()), [job_file])

    def test_history_rejects_missing_id_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "job.json"
            path.write_text('{}', encoding="utf-8")
            client = Mock()
            with self.assertRaises(ValueError):
                generate.inspect_job(client, path)
            client.request.assert_not_called()

    def test_history_requires_job_file(self):
        with patch.object(generate.Client, "request") as request, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(generate.main(["history"]), 1)
            request.assert_not_called()

    def test_read_only_cli_uses_real_http_without_creating_outputs(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                requests.append(("POST", self.path))
                self.send_error(405)
            def do_GET(self):
                requests.append(("GET", self.path))
                value = ({"system": {}, "devices": [{"type": "cuda", "name": "fixture GPU"}]}
                         if self.path == "/system_stats" else success())
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "job.json"
                path.write_text('{"prompt_id":"job-1"}', encoding="utf-8")
                for action, extra, expected in [("status", ["--wait-seconds", "2"], "ready"),
                                                ("history", ["--job-file", str(path)], "succeeded")]:
                    result = subprocess.run([sys.executable, str(ROOT / "generate.py"), action, "--port", str(server.server_port), *extra], cwd=folder, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["status"], expected)
                self.assertEqual(list(Path(folder).iterdir()), [path])
            self.assertEqual(requests, [("GET", "/system_stats"), ("GET", "/history/job-1")])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_workflow_has_only_core_nodes_and_one_image(self):
        graph = generate.workflow()
        self.assertEqual(len(graph), 7)
        self.assertEqual({n["class_type"] for n in graph.values()}, {"CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage"})
        self.assertEqual(graph["4"]["inputs"]["batch_size"], 1)
        self.assertEqual(graph["1"]["inputs"]["ckpt_name"], setup.model_spec()["filename"])

    def test_prompt_changes_only_text(self):
        old, new = generate.workflow(), generate.workflow("A red cup")
        old["2"]["inputs"]["text"] = "A red cup"
        self.assertEqual(old, new)

    def test_invalid_prompts(self):
        for prompt in ("", " ", "a" * 2001):
            with self.subTest(prompt_length=len(prompt)), self.assertRaises(ValueError):
                generate.workflow(prompt)

    def test_plan_makes_no_request(self):
        with patch.object(generate.Client, "request", side_effect=AssertionError("network")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(generate.main(["plan"]), 0)

    def test_port_range(self):
        for port in (0, 65536, True):
            with self.assertRaises(ValueError):
                generate.Client(port)

    def test_png_framing_crc_and_dimensions(self):
        data = png()
        self.assertEqual(generate.check_png(data, (768, 1024)), (768, 1024))
        corrupt = bytearray(data)
        corrupt[-13] ^= 1
        for bad in (b"<html>error</html>", data[:-1], bytes(corrupt), data + b"junk", png(1, 1)):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                generate.check_png(bad, (768, 1024))

    def test_saved_image_and_records_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            first = generate.generate(FakeClient(), generate.workflow(), folder)
            second = generate.generate(FakeClient(), generate.workflow(), folder)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), png())
            record = json.loads((first.parent / "result.json").read_text())
            self.assertFalse(record["instance_destroyed"])
            self.assertEqual(record["sha256"], hashlib.sha256(png()).hexdigest())

    def test_remote_filename_does_not_choose_local_path(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            client = FakeClient(history=success("../../outside.png"))
            image = generate.generate(client, generate.workflow(), folder)
            self.assertEqual(image.name, "image.png")
            self.assertIn("%2F", client.calls[-1][0])
            self.assertFalse((Path(folder) / "outside.png").exists())

    def test_remote_error_never_resubmits(self):
        client = FakeClient(history={"job-1": {"status": {"completed": False, "status_str": "error"}}})
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            generate.generate(client, generate.workflow(), folder)
        self.assertEqual(sum(route == "/prompt" for route, _ in client.calls), 1)

    def test_timeout_never_resubmits_or_destroys(self):
        client = FakeClient(history={})
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), patch.object(generate.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            generate.generate(client, generate.workflow(), folder, wait_seconds=1)
        self.assertEqual(client.calls[0][0], "/prompt")
        self.assertEqual(len(client.calls), 1)

    def test_corrupt_response_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                generate.generate(FakeClient(image=b"bad"), generate.workflow(), folder)
            self.assertEqual(list(Path(folder).rglob("result.json")), [])
            self.assertEqual(list(Path(folder).rglob("image.png")), [])

    def test_rejected_and_uncertain_submit_not_retried(self):
        for result in ({"error": "invalid"}, {}, {"prompt_id": "job-1", "node_errors": {"1": "missing"}}):
            with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), patch.object(generate.Client, "request", return_value=result) as request:
                with self.assertRaises(RuntimeError):
                    generate.generate(generate.Client(), generate.workflow(), folder)
                self.assertEqual(request.call_count, 1)

    def test_multiple_images_rejected(self):
        history = success()
        history["job-1"]["outputs"]["7"]["images"] *= 2
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            generate.generate(FakeClient(history=history), generate.workflow(), folder)

    def test_real_http_cli_loopback_integration(self):
        posts = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"prompt_id":"job-1"}')
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(png() if self.path.startswith("/view?") else json.dumps(success()).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "generate.py"), "generate", "--port", str(server.server_port), "--output-dir", folder], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(posts), 1)
                self.assertEqual(len(list(Path(folder).rglob("image.png"))), 1)
                self.assertIn("Destroy", result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_redirect_refused(self):
        with self.assertRaises(ValueError):
            generate.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_setup_plan_is_offline(self):
        with patch.object(setup, "install", side_effect=AssertionError("install")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup.main([]), 0)
        for command in setup.commands():
            self.assertTrue(all("\\" not in arg for arg in command))

    def test_setup_refuses_non_linux(self):
        with patch.object(setup.sys, "platform", "win32"), self.assertRaises(RuntimeError):
            setup.install()

    def test_setup_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup.sys, "platform", "linux"), patch.object(setup, "INSTALL", Path(folder)), self.assertRaises(FileExistsError):
            setup.install()

    def test_download_requires_exact_size_and_hash(self):
        body = b"synthetic model fixture"
        spec = {"url": "https://example.invalid/test", "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "model.safetensors"
            setup.download_model(spec, target, opener=lambda *a, **k: io.BytesIO(body))
            self.assertEqual(target.read_bytes(), body)
            self.assertFalse(target.with_suffix(".safetensors.part").exists())
            with self.assertRaises(FileExistsError):
                setup.download_model(spec, target)
        for bad in (body[:-1], body + b"extra", b"x" * len(body)):
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "model.safetensors"
                with self.assertRaises(ValueError):
                    setup.download_model(spec, target, opener=lambda *a, **k: io.BytesIO(bad))
                self.assertFalse(target.exists())

    def test_model_url_pinned_and_constraints_present(self):
        spec = setup.model_spec()
        self.assertIn("/resolve/" + spec["revision"] + "/", spec["url"])
        self.assertEqual(len(spec["sha256"]), 64)
        self.assertIn("torch==2.9.1", setup.CONSTRAINTS)


if __name__ == "__main__":
    unittest.main()
