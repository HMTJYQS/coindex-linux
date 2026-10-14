"""Linux desktop boundaries, without real Codex data, credentials or requests."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
import platforms
from connections import codex_path, remote_check, ssh_command
from nudge import open_desktop_thread as nudge_open_thread
from store import Store

THREAD = "12345678-1234-1234-1234-123456789abc"


class DataLocationTests(unittest.TestCase):
    def test_linux_uses_xdg_or_home_and_ignores_relative_xdg(self):
        with patch("platforms.sys.platform", "linux"), patch("pathlib.Path.home", return_value=pathlib.Path("/workspace/example")):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(platforms.default_data_dir(), pathlib.Path("/workspace/example/.local/share/coindex"))
            with patch.dict(os.environ, {"XDG_DATA_HOME": "/data space"}, clear=True):
                self.assertEqual(platforms.default_data_dir(), pathlib.Path("/data space/coindex"))
            with patch.dict(os.environ, {"XDG_DATA_HOME": "relative"}, clear=True):
                self.assertEqual(platforms.default_data_dir(), pathlib.Path("/workspace/example/.local/share/coindex"))

    def test_explicit_environment_overrides_xdg_and_mac_retains_legacy_directory(self):
        with patch("pathlib.Path.home", return_value=pathlib.Path("/workspace/example")):
            with patch.dict(os.environ, {"CODEX_TODO_DATA_DIR": "/chosen", "XDG_DATA_HOME": "/xdg"}, clear=True):
                self.assertEqual(platforms.default_data_dir(), pathlib.Path("/chosen"))
            with patch("platforms.sys.platform", "darwin"), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(platforms.default_data_dir(), pathlib.Path("/workspace/example/Library/Application Support/CodexTodo"))

    def test_service_explicit_argument_overrides_environment(self):
        service = pathlib.Path(__file__).resolve().parents[1] / "backend/service.py"
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env = dict(os.environ, HOME=str(root), CODEX_HOME=str(root / "codex"),
                       CODEX_TODO_DATA_DIR=str(root / "environment"), XDG_DATA_HOME=str(root / "xdg"))
            result = subprocess.run([sys.executable, str(service), "--data-dir", str(root / "argument"), "snapshot"],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["settings"]["enabled_hosts"], ["mac"])
            self.assertTrue((root / "argument/todos.sqlite").is_file())
            self.assertFalse((root / "environment").exists())
            self.assertFalse((root / "xdg").exists())

    def test_store_label_changes_without_migrating_local_identity(self):
        with tempfile.TemporaryDirectory() as directory, patch("platforms.sys.platform", "linux"):
            store = Store(directory)
            try:
                snapshot = store.snapshot()
                self.assertEqual(snapshot["hosts"][0]["id"], "mac")
                self.assertEqual(snapshot["hosts"][0]["name"], "本机")
                self.assertEqual(snapshot["settings"]["enabled_hosts"], ["mac"])
                with patch("platforms.sys.platform", "darwin"):
                    self.assertEqual(store.snapshot()["hosts"][0]["name"], "这台 Mac")
            finally:
                store.db.close()


class DesktopOpenTests(unittest.TestCase):
    def test_thread_url_retains_remote_identity_and_quotes_components(self):
        url = platforms.desktop_thread_url("a/b?c", "remote-ssh-discovered:lab & west")
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "codex")
        self.assertEqual(parsed.path, "/a%2Fb%3Fc")
        self.assertEqual(parse_qs(parsed.query), {"hostId": ["remote-ssh-discovered:lab & west"]})

    def test_linux_uses_xdg_open_and_never_cli_discovery(self):
        with patch("platforms.sys.platform", "linux"), patch("platforms.shutil.which", return_value="/usr/bin/xdg-open") as discover, patch("platforms.subprocess.run") as run:
            platforms.open_desktop_thread(THREAD, "local")
        discover.assert_called_once_with("xdg-open")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/xdg-open", platforms.desktop_thread_url(THREAD, "local")])
        self.assertTrue(run.call_args.kwargs["start_new_session"])

    def test_missing_opener_and_failed_protocol_report_actionable_error(self):
        with patch("platforms.sys.platform", "linux"), patch("platforms.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "xdg-utils"):
                platforms.open_desktop_thread(THREAD, "local")
        with patch("platforms.sys.platform", "linux"), patch("platforms.shutil.which", return_value="/usr/bin/xdg-open"), patch("platforms.subprocess.run", side_effect=subprocess.CalledProcessError(4, ["xdg-open"])):
            with self.assertRaisesRegex(RuntimeError, "codex://"):
                platforms.open_desktop_thread(THREAD, "local")

    def test_explicit_gui_is_passed_as_one_argument_and_can_keep_running(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = pathlib.Path(directory) / "Codex Desktop"
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o700)
            child = Mock()
            child.wait.side_effect = subprocess.TimeoutExpired([str(executable)], 0.5)
            with patch("platforms.sys.platform", "linux"), patch("platforms.subprocess.Popen", return_value=child) as start, patch("platforms.shutil.which") as discover:
                platforms.open_desktop_thread(THREAD, "local", str(executable))
            self.assertEqual(start.call_args.args[0], [str(executable.resolve()), platforms.desktop_thread_url(THREAD, "local")])
            self.assertTrue(start.call_args.kwargs["start_new_session"])
            discover.assert_not_called()
            child.terminate.assert_not_called()

    def test_explicit_gui_missing_or_immediate_failure_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = pathlib.Path(directory) / "Codex Desktop"
            with patch("platforms.sys.platform", "linux"), patch("platforms.subprocess.Popen") as start:
                with self.assertRaisesRegex(RuntimeError, "无法执行"):
                    platforms.open_desktop_thread(THREAD, "local", str(executable))
                start.assert_not_called()
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o700)
            with patch("platforms.sys.platform", "linux"), patch("platforms.subprocess.Popen", return_value=Mock(wait=Mock(return_value=1))):
                with self.assertRaisesRegex(RuntimeError, "启动失败"):
                    platforms.open_desktop_thread(THREAD, "local", str(executable))

    def test_mac_open_and_nudge_wrapper_keep_existing_contract(self):
        with patch("platforms.sys.platform", "darwin"), patch("platforms.subprocess.run") as run:
            platforms.open_desktop_thread(THREAD, "local", "/Applications/Codex.app")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/open", "-a", "/Applications/Codex.app", platforms.desktop_thread_url(THREAD, "local")])
        with patch("platforms.open_desktop_thread") as opener:
            nudge_open_thread(THREAD, "local", "/gui")
        opener.assert_called_once_with(THREAD, "local", "/gui")


class LinuxDiscoveryTests(unittest.TestCase):
    def test_gui_file_does_not_replace_cli_and_explicit_cli_takes_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            gui, cli = root / "desktop", root / "cli"
            for executable in (gui, cli):
                executable.write_text("#!/bin/sh\n")
                executable.chmod(0o700)
            with patch("connections.sys.platform", "linux"), patch.dict(os.environ, {}, clear=True), patch("connections.shutil.which", return_value=str(cli)):
                self.assertEqual(codex_path({"codex_app": str(gui)}), str(cli))
                self.assertEqual(codex_path({"codex_app": str(gui), "codex_cli": str(cli)}), str(cli.resolve()))

    def test_gui_on_path_is_not_mistaken_for_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            gui = root / ".local/bin/codex"
            gui.parent.mkdir(parents=True)
            gui.write_text("#!/bin/sh\n")
            gui.chmod(0o700)
            with patch("connections.sys.platform", "linux"), patch("pathlib.Path.home", return_value=root), patch.dict(os.environ, {}, clear=True), patch("connections.shutil.which", return_value=str(gui)):
                with self.assertRaisesRegex(RuntimeError, "找不到 Codex CLI"):
                    codex_path({"codex_app": str(gui)})

    def test_ssh_discovery_preserves_arguments_and_missing_dependency_is_reported(self):
        with patch("connections.shutil.which", return_value="/custom/bin/ssh"):
            command = ssh_command({"id": "lab", "identity_file": "/keys/key with spaces"})
        self.assertEqual(command[0], "/custom/bin/ssh")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("/keys/key with spaces", command)
        self.assertEqual(command[-1], "lab")
        with patch("connections.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "OpenSSH"):
                ssh_command({"id": "lab"})
            result = remote_check({"id": "lab"})
        self.assertFalse(result["ok"])
        self.assertIn("OpenSSH", result["detail"])


if __name__ == "__main__":
    unittest.main()
