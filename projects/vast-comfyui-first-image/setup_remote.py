"""Prepare one dedicated Linux container. Default is a network-free plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

SOURCE = Path(__file__).resolve().parent
INSTALL = Path("/workspace/vast-first-image")
COMFY_COMMIT = "c9ea36b9d2140c89b2ef84f93f428df474e72ba5"
COMFY_REPO = "https://github.com/Comfy-Org/ComfyUI.git"
CONSTRAINTS = "torch==2.9.1\ntorchvision==0.24.1\ntorchaudio==2.9.1\ntransformers==5.21.0\nsafetensors==0.8.0\n"


def model_spec():
    model = json.loads((SOURCE / "model.json").read_text(encoding="utf-8"))
    model["url"] = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{model['filename']}"
    return model


def commands(root=INSTALL):
    comfy = root / "ComfyUI"
    python = root / ".venv/bin/python"
    host_python = sys.executable if sys.platform == "linux" else "python"
    return [
        ["git", "init", comfy.as_posix()],
        ["git", "-C", comfy.as_posix(), "fetch", "--depth", "1", COMFY_REPO, COMFY_COMMIT],
        ["git", "-C", comfy.as_posix(), "checkout", "--detach", "FETCH_HEAD"],
        [host_python, "-m", "venv", "--system-site-packages", (root / ".venv").as_posix()],
        [python.as_posix(), "-m", "pip", "install", "-c", (root / "constraints.txt").as_posix(), "-r", (comfy / "requirements.txt").as_posix()],
    ]


def download_model(spec, target, *, opener=urlopen):
    """Keep an incomplete download under .part; promote only after size and SHA match."""
    partial = target.with_suffix(target.suffix + ".part")
    if target.exists() or partial.exists():
        raise FileExistsError("Model or partial file exists; inspect it before starting again")
    count = 0
    digest = hashlib.sha256()
    deadline = time.monotonic() + 900
    with opener(spec["url"], timeout=30) as response, partial.open("xb") as output:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Model download exceeded 15 minutes")
            data = response.read(1024 * 1024)
            if not data:
                break
            count += len(data)
            if count > spec["size_bytes"]:
                raise ValueError("Model is larger than the recorded file")
            digest.update(data)
            output.write(data)
    if count != spec["size_bytes"] or digest.hexdigest() != spec["sha256"]:
        raise ValueError("Model size/SHA-256 mismatch; the .part file was not installed")
    partial.rename(target)


def install():
    if sys.platform != "linux":
        raise RuntimeError("Run --install only inside the dedicated Linux GPU container")
    if INSTALL.exists():
        raise FileExistsError("Installation already exists (possibly incomplete); no overwrite")
    if not shutil.which("git"):
        raise RuntimeError("git is missing; see the README prerequisite step")
    if shutil.disk_usage(INSTALL.parent).free < 30 * 1024**3:
        raise RuntimeError("At least 30 GiB of free disk space is required by this installer")
    subprocess.run([sys.executable, "-c", "import torch; assert torch.__version__.split('+')[0]=='2.9.1'; assert torch.cuda.is_available()"], check=True, timeout=60)
    INSTALL.mkdir()
    (INSTALL / "constraints.txt").write_text(CONSTRAINTS, encoding="utf-8")
    for command in commands():
        subprocess.run(command, check=True, timeout=900)
    spec = model_spec()
    target = INSTALL / "ComfyUI/models/checkpoints" / spec["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    download_model(spec, target)
    print("Installation complete. Start ComfyUI with the README command.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.install:
            install()
        else:
            print(json.dumps({"mode": "offline-plan", "comfy_commit": COMFY_COMMIT,
                              "commands": commands(), "model": model_spec(),
                              "downloads_models": False, "rents_gpu": False}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Setup stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("The GPU remains rented. Inspect the error; Destroy in Vast.ai if ending the session.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Setup interrupted. The GPU remains rented; Destroy in Vast.ai when finished.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
