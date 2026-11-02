"""One image through an existing, local SSH tunnel. Never rents or destroys GPUs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
import uuid
import zlib

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    """A tunnel endpoint must not redirect our workflow to another server."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("HTTP redirect refused; check the local SSH tunnel")


class Client:
    def __init__(self, port=8188):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be 1..65535")
        self.base = f"http://127.0.0.1:{port}"
        # Do not send loopback requests through HTTP_PROXY or an OS proxy.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, route, payload=None, *, timeout=30, binary=False):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + route, data=data,
                          headers={"Content-Type": "application/json"})
        limit = MAX_IMAGE_BYTES if binary else MAX_JSON_BYTES
        with self.opener.open(request, timeout=timeout) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Server response exceeds the size limit")
        return body if binary else json.loads(body)


def workflow(prompt=None):
    """Only the positive text is configurable; the model and graph stay fixed."""
    graph = json.loads((ROOT / "workflow.api.json").read_text(encoding="utf-8"))
    if prompt is not None:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
            raise ValueError("prompt must contain 1..2000 characters")
        graph["2"]["inputs"]["text"] = prompt
    return graph


def check_png(data, expected_size):
    """Check PNG framing, chunk CRCs and dimensions before reporting a saved file."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Response is not a PNG")
    offset, dimensions, has_data = 8, None, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG data")
        chunk = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != crc:
            raise ValueError("PNG checksum mismatch")
        if dimensions is None and kind != b"IHDR":
            raise ValueError("PNG must start with IHDR")
        if kind == b"IHDR":
            if dimensions is not None or length != 13:
                raise ValueError("Invalid PNG header")
            dimensions = struct.unpack(">II", chunk[:8])
            if dimensions != expected_size:
                raise ValueError("PNG dimensions differ from the workflow")
        if kind == b"IDAT":
            has_data = True
        if kind == b"IEND":
            if length != 0 or end != len(data) or not has_data:
                raise ValueError("Invalid PNG ending")
            return dimensions
        offset = end
    raise ValueError("PNG has no IEND")


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def wait_ready(client, *, wait_seconds=120, poll_seconds=2):
    """Read system stats until reachable; never submit a prompt or rent a GPU."""
    if not 1 <= wait_seconds <= 1800:
        raise ValueError("wait_seconds must be 1..1800")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        try:
            stats = client.request("/system_stats", timeout=min(5, max(0.1, deadline - time.monotonic())))
        except HTTPError:
            raise
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
            continue
        if not isinstance(stats, dict) or not isinstance(stats.get("system"), dict) or not isinstance(stats.get("devices"), list):
            raise ValueError("Unexpected /system_stats response; check the SSH tunnel destination")
        devices = [item.get("name") for item in stats["devices"]
                   if isinstance(item, dict) and item.get("type") == "cuda" and isinstance(item.get("name"), str)]
        if not devices:
            raise RuntimeError("ComfyUI responded but no CUDA device was reported")
        return {"status": "ready", "endpoint": "/system_stats", "cuda_devices": devices,
                "generation_submitted": False}
    raise TimeoutError("ComfyUI did not become ready; check the SSH screen and budget before continuing")


def inspect_job(client, job_file):
    """Read one saved prompt's history and queue state. No resubmission or recovery."""
    record = json.loads(Path(job_file).read_text(encoding="utf-8"))
    prompt_id = record.get("prompt_id") if isinstance(record, dict) else None
    if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 128:
        raise ValueError("job.json has no valid prompt_id")
    history = client.request("/history/" + quote(prompt_id, safe=""))
    if not isinstance(history, dict):
        raise ValueError("Unexpected history response")
    job = history.get(prompt_id)
    result = {"prompt_id": prompt_id, "status": "unknown", "generation_submitted": False}
    if job:
        status = job.get("status", {}) if isinstance(job, dict) else {}
        if status.get("status_str") == "error":
            result["status"] = "failed"
            return result
        if status.get("completed") is True and status.get("status_str") == "success":
            result["status"] = "succeeded"
            result["images"] = job.get("outputs", {}).get("7", {}).get("images", [])
            return result
    queue = client.request("/queue")
    if not isinstance(queue, dict):
        raise ValueError("Unexpected queue response")
    for key, label in (("queue_running", "running"), ("queue_pending", "queued")):
        items = queue.get(key, [])
        if not isinstance(items, list):
            raise ValueError("Unexpected queue items")
        if any(isinstance(item, list) and len(item) > 1 and item[1] == prompt_id for item in items):
            result["status"] = label
            break
    return result


def generate(client, graph, output_root, *, wait_seconds=600, poll_seconds=2):
    """Submit exactly once; errors and timeouts never submit a replacement job."""
    if not 1 <= wait_seconds <= 1800:
        raise ValueError("wait_seconds must be 1..1800")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / f"{stamp}-{uuid.uuid4().hex[:12]}"
    run_dir.mkdir()
    write_json(run_dir / "workflow.api.json", graph)
    print(f"Run folder: {run_dir}", flush=True)
    print("Submitting once. If the response is lost, do not submit again blindly.", flush=True)
    result = client.request("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    if not isinstance(result, dict) or result.get("error") or result.get("node_errors"):
        raise RuntimeError("ComfyUI rejected the workflow; inspect its server log")
    prompt_id = result.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 128:
        raise RuntimeError("No valid prompt_id; acceptance is uncertain")
    write_json(run_dir / "job.json", {"prompt_id": prompt_id, "submitted_at_utc": datetime.now(timezone.utc).isoformat()})
    print(f"prompt_id: {prompt_id}", flush=True)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        history = client.request("/history/" + quote(prompt_id, safe=""), timeout=min(30, remaining))
        job = history.get(prompt_id) if isinstance(history, dict) else None
        if job:
            status = job.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI generation failed; inspect its server log")
            if status.get("completed") is True:
                if status.get("status_str") != "success":
                    raise RuntimeError("ComfyUI did not report success")
                images = job.get("outputs", {}).get("7", {}).get("images", [])
                if len(images) != 1 or images[0].get("type") != "output":
                    raise RuntimeError("Expected exactly one saved output image")
                image_info = images[0]
                # The remote filename is a query value, never a local filesystem path.
                query = urlencode({key: image_info.get(key, "") for key in ("filename", "subfolder", "type")})
                image_data = client.request("/view?" + query, binary=True)
                size = graph["4"]["inputs"]
                check_png(image_data, (size["width"], size["height"]))
                image_path = run_dir / "image.png"
                partial_path = run_dir / "image.png.part"
                with partial_path.open("xb") as stream:
                    stream.write(image_data)
                partial_path.rename(image_path)
                write_json(run_dir / "result.json", {
                    "status": "saved", "prompt_id": prompt_id, "image": "image.png",
                    "sha256": hashlib.sha256(image_data).hexdigest(),
                    "bytes": len(image_data), "width": size["width"], "height": size["height"],
                    "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "instance_destroyed": False,
                })
                return image_path
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
    raise TimeoutError("Result wait expired. The remote job and GPU may still be running")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "status", "history", "generate"))
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--prompt")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument("--wait-seconds", type=int, default=600)
    parser.add_argument("--job-file", type=Path)
    args = parser.parse_args(argv)
    try:
        client = Client(args.port)
        if args.action == "status":
            print(json.dumps(wait_ready(client, wait_seconds=args.wait_seconds), ensure_ascii=False, indent=2))
            return 0
        if args.action == "history":
            if args.job_file is None:
                raise ValueError("history requires --job-file pointing to the saved job.json")
            print(json.dumps(inspect_job(client, args.job_file), ensure_ascii=False, indent=2))
            return 0
        graph = workflow(args.prompt)
        if args.action == "plan":
            print(json.dumps({"mode": "offline-plan", "network_requests": 0,
                              "model": graph["1"]["inputs"]["ckpt_name"],
                              "image": graph["4"]["inputs"],
                              "prompt": graph["2"]["inputs"]["text"],
                              "base_url": client.base}, ensure_ascii=False, indent=2))
            return 0
        image_path = generate(client, graph, args.output_dir, wait_seconds=args.wait_seconds)
        print(f"Saved: {image_path}")
        print("Open the local PNG, then Destroy this instance in Vast.ai and verify its removal.")
        return 0
    except (OSError, ValueError, RuntimeError, HTTPError, URLError, TimeoutError) as exc:
        print(f"Stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("No generation resubmission or GPU cleanup. Check remote history before retrying; Destroy when finished.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted locally. The GPU may still run. Recover images if needed, then Destroy in Vast.ai.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
