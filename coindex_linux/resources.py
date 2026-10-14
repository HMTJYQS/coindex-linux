"""Resolve public assets in a source checkout and an installed wheel."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile


_PACKAGE = pathlib.Path(__file__).resolve().parent
_SOURCE = _PACKAGE.parent


def backend_script() -> pathlib.Path:
    """Locate the stdio service without importing its executable module."""
    spec = importlib.util.find_spec("backend")
    if spec is None or spec.origin is None:
        raise FileNotFoundError("The coindex backend is not installed")
    path = pathlib.Path(spec.origin).parent / "service.py"
    if not path.is_file():
        raise FileNotFoundError("The coindex backend service is missing")
    return path


def resource_path(relative: str) -> pathlib.Path:
    """Return a public asset relative to the upstream Resources directory."""
    name = pathlib.PurePosixPath(relative)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError("Resource paths must stay inside Resources")
    packaged = _PACKAGE / "resources" / pathlib.Path(*name.parts)
    source = _SOURCE / "Resources" / pathlib.Path(*name.parts)
    for candidate in (packaged, source):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Missing coindex resource: " + relative)


def demo_snapshot() -> dict:
    """Load the generated, fictional demo; never scan real conversations."""
    try:
        return json.loads(resource_path("demo.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        generator = _SOURCE / "scripts" / "create-demo.py"
        if not generator.is_file():
            raise
        with tempfile.TemporaryDirectory(prefix="coindex-demo-") as temporary:
            output = pathlib.Path(temporary) / "demo.json"
            subprocess.run([sys.executable, str(generator), str(output)], check=True)
            return json.loads(output.read_text(encoding="utf-8"))
