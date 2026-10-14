#!/usr/bin/env python3
"""User-level Linux install/upgrade/uninstall with explicit file ownership."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

APP_ID = "org.coindex.desktop.linux"
MANIFEST = "install-manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def absolute(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def require_safe_prefix(prefix: Path):
    dangerous = {Path("/"), Path.home(), Path.home() / ".local", Path.home() / ".local/share"}
    if prefix in dangerous or len(prefix.parts) < 3 or prefix.is_symlink():
        raise ValueError("Choose an application-specific, non-symlink install prefix")


def read_manifest(prefix: Path) -> dict | None:
    if not prefix.exists():
        return None
    manifest_path = prefix / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Existing prefix is not a managed coindex-linux installation")
    result = json.loads(manifest_path.read_text(encoding="utf-8"))
    if result.get("app_id") != APP_ID or result.get("prefix") != str(prefix):
        raise ValueError("Install manifest does not belong to this coindex-linux prefix")
    return result


def generated_paths(args) -> dict[str, Path]:
    return {
        "launcher": absolute(args.bin_dir) / "coindex-linux",
        "desktop": absolute(args.desktop_dir) / "coindex-linux.desktop",
        "icon": absolute(args.icon_dir) / "coindex-linux.png",
    }


def owned_file(path: Path, manifest: dict | None) -> bool:
    if path.is_symlink() or not path.is_file() or not manifest:
        return False
    return manifest.get("files", {}).get(str(path)) == digest(path)


def ensure_outputs_free(paths: dict[str, Path], previous: dict | None):
    for path in paths.values():
        if path.exists() or path.is_symlink():
            if not owned_file(path, previous):
                raise ValueError("Refusing to overwrite a file not owned by this installation: " + str(path))


def pip_options(args) -> list[str]:
    options = []
    if args.offline:
        options.append("--no-index")
    for folder in args.find_links:
        options += ["--find-links", str(absolute(folder))]
    return options


def create_environment(stage: Path, args):
    interpreter = absolute(args.python) if "/" in args.python else Path(shutil.which(args.python) or args.python)
    subprocess.run([str(interpreter), "-c", "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ is required'"], check=True)
    venv = stage / "venv"
    # Ubuntu can provide venv without ensurepip. Bootstrap pip separately in that case.
    result = subprocess.run([str(interpreter), "-m", "venv", str(venv)], capture_output=True, text=True)
    if result.returncode:
        if venv.exists():
            shutil.rmtree(venv)
        subprocess.run([str(interpreter), "-m", "venv", "--without-pip", str(venv)], check=True)
        python = venv / "bin/python"
        site = subprocess.check_output([str(python), "-c",
                                       "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
        bootstrap = str(absolute(args.pip_wheel)) if args.pip_wheel else "pip"
        subprocess.run([str(interpreter), "-m", "pip", "install", "--disable-pip-version-check", "--timeout", "90", "--retries", "5",
                        "--no-deps", "--target", site, *pip_options(args), bootstrap], check=True)
    python = venv / "bin/python"
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--timeout", "90", "--retries", "5",
                    *pip_options(args), str(absolute(args.wheel))], check=True)
    # This check does not open the desktop, connect SSH, call a model, or send a nudge.
    subprocess.run([str(python), "-c",
                    "from coindex_linux.resources import backend_script,resource_path,demo_snapshot; "
                    "assert backend_script().is_file(); "
                    "assert resource_path('Brand/AppIcon.png').is_file(); "
                    "assert resource_path('CustomPets/coindex-cat/spritesheet.png').is_file(); "
                    "assert demo_snapshot()['tasks']; "
                    "from PySide6 import QtCore,QtGui,QtWidgets; "
                    "import importlib.util; assert importlib.util.find_spec('coindex_linux.app')"], check=True)


def replace_atomic(path: Path, data: bytes, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".coindex-linux-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def launcher_bytes(prefix: Path, launcher: Path) -> bytes:
    python = prefix / "venv/bin/python"
    return ("#!/bin/sh\nexport COINDEX_LINUX_LAUNCHER=" + shlex.quote(str(launcher)) +
            "\nexec " + shlex.quote(str(python)) + " -m coindex_linux.app \"$@\"\n").encode()


def desktop_quote(path: Path) -> str:
    # The Desktop Entry specification reserves these characters in quoted Exec args.
    value = str(path).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    if any(character in value for character in "\r\n"):
        raise ValueError("Desktop paths cannot contain line breaks")
    return '"' + value + '"'


def desktop_bytes(paths: dict[str, Path]) -> bytes:
    if any(character in str(paths["icon"]) for character in "\r\n"):
        raise ValueError("Icon path cannot contain line breaks")
    return ("[Desktop Entry]\nType=Application\nName=coindex Linux\n"
            "Comment=Follow up your Codex conversations\n"
            "Exec=" + desktop_quote(paths["launcher"]) + "\n"
            "Icon=" + str(paths["icon"]) + "\nTerminal=false\n"
            "Categories=Office;Utility;\nStartupWMClass=coindex-linux\n").encode()


def install(args):
    prefix = absolute(args.prefix)
    require_safe_prefix(prefix)
    wheel = absolute(args.wheel)
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError("Provide a built coindex-linux wheel")
    previous = read_manifest(prefix)
    paths = generated_paths(args)
    ensure_outputs_free(paths, previous)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + prefix.name + "-staging-", dir=prefix.parent))
    backup = prefix.with_name("." + prefix.name + "-backup-" + uuid.uuid4().hex)
    prior_files = {path: path.read_bytes() if path.is_file() else None for path in paths.values()}
    prior_modes = {path: path.stat().st_mode & 0o777 for path in paths.values() if path.is_file()}
    moved_old = moved_new = committed = False
    try:
        create_environment(stage, args)
        python = stage / "venv/bin/python"
        icon = subprocess.check_output([str(python), "-c",
                                       "from coindex_linux.resources import resource_path; print(resource_path('Brand/AppIcon.png'))"], text=True).strip()
        content = {
            paths["launcher"]: launcher_bytes(prefix, paths["launcher"]),
            paths["desktop"]: desktop_bytes(paths),
            paths["icon"]: Path(icon).read_bytes(),
        }
        # venv's Python relocates; rewrite its console-script shebangs to the final prefix.
        for script in (stage / "venv/bin").iterdir():
            if script.is_file() and not script.is_symlink():
                data = script.read_bytes()
                if data.startswith(b"#!") or script.name.startswith("activate"):
                    script.write_bytes(data.replace(str(stage).encode(), str(prefix).encode()))
        manifest = {"app_id": APP_ID, "format": 1, "prefix": str(prefix),
                    "wheel_sha256": digest(wheel),
                    "files": {str(path): hashlib.sha256(data).hexdigest() for path, data in content.items()}}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Verify ownership again after preparation, before replacing anything.
        ensure_outputs_free(paths, previous)
        if previous:
            os.replace(prefix, backup)
            moved_old = True
        os.replace(stage, prefix)
        moved_new = True
        for path, data in content.items():
            replace_atomic(path, data, 0o755 if path == paths["launcher"] else 0o644)
        committed = True
        # Remove obsolete custom-location entries only after the new install is committed.
        if previous:
            for name, checksum in previous.get("files", {}).items():
                old = Path(name)
                if old not in content and old.is_file() and not old.is_symlink() and digest(old) == checksum:
                    try:
                        old.unlink()
                    except OSError:
                        print("Preserved obsolete entry that could not be removed: " + str(old))
        if moved_old:
            try:
                shutil.rmtree(backup)
            except OSError:
                print("Preserved old application backup: " + str(backup))
        print("Installed coindex-linux: " + str(paths["launcher"]))
        print("Run with --demo to preview without real model requests.")
    except BaseException:
        if not committed:
            if moved_new:
                shutil.rmtree(prefix)
            if moved_old:
                os.replace(backup, prefix)
            if moved_new:
                for path, data in prior_files.items():
                    if data is None:
                        if path.is_file() and not path.is_symlink():
                            path.unlink()
                    else:
                        replace_atomic(path, data, prior_modes[path])
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def uninstall(args):
    prefix = absolute(args.prefix)
    require_safe_prefix(prefix)
    manifest = read_manifest(prefix)
    if manifest is None:
        print("coindex-linux is not installed at this prefix.")
        return
    for name, checksum in manifest.get("files", {}).items():
        path = Path(name)
        if path.is_file() and not path.is_symlink() and digest(path) == checksum:
            path.unlink()
        elif path.exists() or path.is_symlink():
            print("Preserved modified or unowned file: " + str(path))
    autostart = absolute(args.config_dir) / "autostart/coindex-linux.desktop"
    if autostart.is_file() and not autostart.is_symlink():
        lines = autostart.read_text(encoding="utf-8").splitlines()
        launchers = [Path(name) for name in manifest.get("files", {})
                     if Path(name).name == "coindex-linux"]
        matching_exec = any("Exec=" + desktop_quote(launcher) in lines for launcher in launchers)
        if "X-Coindex-Linux=true" in lines and matching_exec:
            autostart.unlink()
    # Only the exact, manifest-owned application prefix is removed. Task data is elsewhere.
    shutil.rmtree(prefix)
    print("Uninstalled coindex-linux; task data and preferences were preserved.")


def main():
    def xdg_directory(name, fallback):
        value = os.environ.get(name, "")
        return Path(value) if value and Path(value).is_absolute() else fallback

    data = xdg_directory("XDG_DATA_HOME", Path.home() / ".local/share")
    config = xdg_directory("XDG_CONFIG_HOME", Path.home() / ".config")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "uninstall"))
    parser.add_argument("wheel", nargs="?")
    parser.add_argument("--prefix", default=str(data / "coindex-linux/app"))
    parser.add_argument("--bin-dir", default=str(Path.home() / ".local/bin"))
    parser.add_argument("--desktop-dir", default=str(data / "applications"))
    parser.add_argument("--icon-dir", default=str(data / "icons/hicolor/256x256/apps"))
    parser.add_argument("--config-dir", default=str(config), help="Configuration root for owned autostart cleanup")
    parser.add_argument("--python", default="python3")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--find-links", action="append", default=[])
    parser.add_argument("--pip-wheel", help="Optional local pip wheel for systems without ensurepip")
    args = parser.parse_args()
    if args.operation == "install" and not args.wheel:
        parser.error("install requires a wheel path")
    try:
        (install if args.operation == "install" else uninstall)(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "coindex-linux: " + str(error) + "\n")


if __name__ == "__main__":
    main()
