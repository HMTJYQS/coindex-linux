"""Ownership and rollback checks; the packaged Qt smoke test is run separately."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("linux_installer", ROOT / "scripts/linux-install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class LinuxInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="coindex-install-test-")
        self.base = Path(self.temporary.name)
        self.wheel = self.base / "coindex_linux-test.whl"
        self.wheel.write_bytes(b"test wheel")
        self.args = argparse.Namespace(
            prefix=str(self.base / "app"), wheel=str(self.wheel),
            bin_dir=str(self.base / "bin"), desktop_dir=str(self.base / "desktop"),
            icon_dir=str(self.base / "icons"), config_dir=str(self.base / "config"),
            python="python3", offline=True,
            find_links=[], pip_wheel=None,
        )
        self.icon = self.base / "public-icon.png"
        self.icon.write_bytes(b"public icon")

    def tearDown(self):
        self.temporary.cleanup()

    def fake_environment(self, stage, args):
        bin_path = stage / "venv/bin"
        bin_path.mkdir(parents=True)
        (bin_path / "python").symlink_to(Path(sys.executable))
        (bin_path / "coindex-linux").write_text("#!" + str(bin_path / "python") + "\n")

    def run_install(self):
        with mock.patch.object(installer, "create_environment", side_effect=self.fake_environment), \
             mock.patch.object(installer.subprocess, "check_output", return_value=str(self.icon) + "\n"):
            installer.install(self.args)

    def test_normalized_prefix_cannot_bypass_safety_check(self):
        prefix = installer.absolute(Path.home() / "application-child/..")
        self.assertEqual(prefix, Path.home())
        with self.assertRaisesRegex(ValueError, "application-specific"):
            installer.require_safe_prefix(prefix)

    def test_unowned_launcher_is_preserved(self):
        launcher = Path(self.args.bin_dir) / "coindex-linux"
        launcher.parent.mkdir()
        launcher.write_text("user program")
        with mock.patch.object(installer, "create_environment") as prepare:
            with self.assertRaisesRegex(ValueError, "not owned"):
                installer.install(self.args)
        prepare.assert_not_called()
        self.assertEqual(launcher.read_text(), "user program")
        self.assertFalse(Path(self.args.prefix).exists())

    def test_failed_upgrade_preserves_existing_install(self):
        self.run_install()
        prefix = Path(self.args.prefix)
        manifest = (prefix / installer.MANIFEST).read_bytes()
        launcher = installer.generated_paths(self.args)["launcher"]
        original = launcher.read_bytes()
        with mock.patch.object(installer, "create_environment", side_effect=RuntimeError("prepare failed")):
            with self.assertRaisesRegex(RuntimeError, "prepare failed"):
                installer.install(self.args)
        self.assertEqual((prefix / installer.MANIFEST).read_bytes(), manifest)
        self.assertEqual(launcher.read_bytes(), original)
        self.assertEqual(list(self.base.glob(".app-staging-*")), [])

    def test_upgrade_and_uninstall_preserve_data(self):
        data = self.base / "task-data"
        data.mkdir()
        database = data / "tasks.sqlite"
        database.write_bytes(b"keep task data")
        self.run_install()
        self.run_install()
        prefix = Path(self.args.prefix)
        entry = (prefix / "venv/bin/coindex-linux").read_text()
        self.assertTrue(entry.startswith("#!" + str(prefix)))
        self.assertNotIn("staging-", entry)
        installer.uninstall(self.args)
        self.assertFalse(prefix.exists())
        self.assertEqual(database.read_bytes(), b"keep task data")
        self.assertFalse(installer.generated_paths(self.args)["launcher"].exists())

    def test_uninstall_preserves_modified_launcher(self):
        self.run_install()
        launcher = installer.generated_paths(self.args)["launcher"]
        launcher.write_text("changed by user")
        installer.uninstall(self.args)
        self.assertEqual(launcher.read_text(), "changed by user")

    def test_uninstall_removes_only_own_autostart(self):
        self.run_install()
        autostart = Path(self.args.config_dir) / "autostart/coindex-linux.desktop"
        autostart.parent.mkdir(parents=True)
        launcher = installer.generated_paths(self.args)["launcher"]
        autostart.write_text("[Desktop Entry]\nX-Coindex-Linux=true\nExec=" +
                             installer.desktop_quote(launcher) + "\n")
        installer.uninstall(self.args)
        self.assertFalse(autostart.exists())
        self.run_install()
        autostart.write_text('[Desktop Entry]\nX-Coindex-Linux=true\nExec="/opt/example/another-app"\n')
        installer.uninstall(self.args)
        self.assertTrue(autostart.exists())

    def test_failed_new_prefix_switch_restores_existing_app(self):
        self.run_install()
        prefix = Path(self.args.prefix)
        manifest = (prefix / installer.MANIFEST).read_bytes()
        original_replace = installer.os.replace

        def fail_stage_switch(source, destination):
            if Path(source).name.startswith(".app-staging-") and Path(destination) == prefix:
                raise OSError("new prefix switch failed")
            return original_replace(source, destination)

        with mock.patch.object(installer, "create_environment", side_effect=self.fake_environment), \
             mock.patch.object(installer.subprocess, "check_output", return_value=str(self.icon) + "\n"), \
             mock.patch.object(installer.os, "replace", side_effect=fail_stage_switch):
            with self.assertRaisesRegex(OSError, "new prefix switch failed"):
                installer.install(self.args)
        self.assertEqual((prefix / installer.MANIFEST).read_bytes(), manifest)
        self.assertTrue(installer.generated_paths(self.args)["launcher"].is_file())
        self.assertEqual(list(self.base.glob(".app-backup-*")), [])

    def test_commit_failure_rolls_back_app_and_launcher(self):
        self.run_install()
        prefix = Path(self.args.prefix)
        manifest = (prefix / installer.MANIFEST).read_bytes()
        launcher = installer.generated_paths(self.args)["launcher"]
        original = launcher.read_bytes()
        replace = installer.replace_atomic
        calls = []

        def fail_desktop_once(path, content, mode=0o644):
            calls.append(path)
            if path.name.endswith(".desktop") and calls.count(path) == 1:
                raise OSError("desktop write failed")
            replace(path, content, mode)

        with mock.patch.object(installer, "create_environment", side_effect=self.fake_environment), \
             mock.patch.object(installer.subprocess, "check_output", return_value=str(self.icon) + "\n"), \
             mock.patch.object(installer, "replace_atomic", side_effect=fail_desktop_once):
            with self.assertRaisesRegex(OSError, "desktop write failed"):
                installer.install(self.args)
        self.assertEqual((prefix / installer.MANIFEST).read_bytes(), manifest)
        self.assertEqual(launcher.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
