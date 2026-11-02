"""Offline fixtures only: no Vast.ai, SSH, model download or GPU execution."""
import contextlib
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
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
