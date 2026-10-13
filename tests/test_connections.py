import json
import os
import pathlib
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/"backend"))
from connections import codex_path, local_check, normalize_remote, remote_check, ssh_aliases, ssh_command
from service import collect_host
from store import Store
from remote_rpc import RemoteRPC
from nudge import dispatch, DesktopIPC
from nudge_fixture import DesktopBroker
from test_backend import conversation, entry
from test_nudge import TARGET
from analyzer import command, generate_json


class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_new_install_has_only_local_source_and_requires_setup(self):
        snap = self.store.snapshot()
        self.assertEqual(snap["settings"]["enabled_hosts"], ["mac"])
        self.assertEqual(snap["settings"]["remote_hosts"], [])
        self.assertEqual([h["id"] for h in snap["hosts"]], ["mac"])
        self.assertFalse(snap["settings"]["connection_setup_complete"])

    def test_legacy_machine_inventory_migrates_without_changing_work_or_enablement(self):
        conv = conversation("lab-old:" + str(uuid.uuid4()))
        self.store.ingest(dict(host="lab-old", root="/old", files={}, conversations=[conv], total_files=1, remaining_files=0))
        self.store.reconcile([entry(conv["id"])], [conv])
        before = {name: self.store.db.execute("SELECT * FROM " + name).fetchall() for name in ("tasks", "conversations", "nudges")}
        self.store.put_meta("settings", {"automatic": False, "enabled_hosts": ["mac"], "interval_seconds": 300})
        self.store.db.close(); self.store = Store(self.tmp.name)
        settings = self.store.settings()
        self.assertEqual(settings["remote_hosts"][0]["id"], "lab-old")
        self.assertEqual(settings["enabled_hosts"], ["mac"])
        self.assertFalse(settings["automatic"])
        self.assertEqual(settings["interval_seconds"], 300)
        self.assertTrue(settings["connection_setup_complete"])
        for name, records in before.items():
            self.assertEqual([tuple(r) for r in records], [tuple(r) for r in self.store.db.execute("SELECT * FROM " + name)])

    def test_any_configured_alias_can_collect_analyze_and_nudge(self):
        self.store.save_settings({"remote_hosts": [{"id": "research-east", "name": "研究服务器"}], "enabled_hosts": ["research-east"]})
        conv = conversation("research-east:" + str(uuid.uuid4()))
        self.store.ingest(dict(host="research-east", root="/custom", files={}, conversations=[conv], total_files=1, remaining_files=0))
        self.assertEqual(self.store.eligible()[0]["host"], "research-east")
        self.store.reconcile([entry(conv["id"])], [conv])
        task = self.store.snapshot()["tasks"][0]
        self.assertEqual(self.store.nudge_target(task["id"])["host"], "research-east")
        self.assertEqual(self.store.snapshot()["hosts"][-1]["name"], "研究服务器")

    def test_remove_and_readd_preserves_history_and_never_recreates_default_machines(self):
        self.store.save_settings({"remote_hosts": [{"id": "my-server"}], "enabled_hosts": ["my-server"]})
        conv = conversation("my-server:" + str(uuid.uuid4()))
        self.store.ingest(dict(host="my-server", root="/custom", files={}, conversations=[conv], total_files=1, remaining_files=0))
        self.store.reconcile([entry(conv["id"])], [conv])
        task_id = self.store.snapshot()["tasks"][0]["id"]
        self.store.save_settings({"remote_hosts": [], "enabled_hosts": ["mac"]})
        self.store.db.close(); self.store = Store(self.tmp.name)
        self.assertEqual(self.store.settings()["remote_hosts"], [])
        self.assertEqual([h["id"] for h in self.store.snapshot()["hosts"]], ["mac"])
        self.assertEqual(self.store.snapshot()["tasks"][0]["id"], task_id)
        with self.assertRaises(ValueError): self.store.nudge_target(task_id)
        self.store.save_settings({"remote_hosts": [{"id": "my-server"}], "enabled_hosts": ["my-server"]})
        self.assertEqual(self.store.nudge_target(task_id)["id"], task_id)

    def test_changed_root_clears_cursor_only_for_that_source(self):
        self.store.save_settings({"remote_hosts": [{"id": "lab"}], "enabled_hosts": ["mac", "lab"]})
        self.store.db.executemany("INSERT INTO files VALUES(?,?,?)", [("mac", "/a", "[1,2]"), ("lab", "/b", "[1,2]")]); self.store.db.commit()
        self.store.save_settings({"remote_hosts": [{"id": "lab", "codex_home": "/different"}]})
        self.assertEqual(self.store.known("lab"), {})
        self.assertEqual(self.store.known("mac"), {"/a": [1,2]})
        self.store.save_settings({"codex_home": "/local-different"})
        self.assertEqual(self.store.known("mac"), {})

    def test_invalid_or_duplicate_hosts_are_rejected_atomically(self):
        before = self.store.settings()
        for values in ({"remote_hosts": [{"id": "-oProxyCommand=bad"}]},
                       {"remote_hosts": [{"id": "lab"}, {"id": "lab"}]},
                       {"enabled_hosts": ["unknown"]}, {"analysis_model": "invalid\nmodel"}):
            with self.assertRaises(ValueError): self.store.save_settings(values)
            self.assertEqual(self.store.settings(), before)


class SSHConnectionTests(unittest.TestCase):
    def test_explicit_machine_uses_separate_arguments_and_strict_host_check(self):
        entry = normalize_remote({"id": "lab-east", "hostname": "192.0.2.10", "user": "developer", "port": 2222,
                                  "identity_file": "/tmp/a key $(touch bad)"})
        args = ssh_command(entry)
        self.assertIn("HostName=192.0.2.10", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        self.assertEqual(args[args.index("-i")+1], "/tmp/a key $(touch bad)")
        self.assertEqual(args[-1], "lab-east")
        interactive = ssh_command(entry, interactive=True)
        self.assertIn("StrictHostKeyChecking=ask", interactive)
        self.assertNotIn("BatchMode=yes", interactive)
        self.assertEqual(shlex.split(shlex.join(interactive)), interactive)

    def test_rejects_option_injection_control_characters_and_invalid_ports(self):
        for value in ({"id": "-F"}, {"id": "a;touch"}, {"id": "a\n"}, {"id": "mac"},
                      {"id": "a", "hostname": "x -oProxyCommand=bad"}, {"id": "a", "user": "-root"},
                      {"id": "a", "port": "not-a-port"}, {"id": "a", "port": 65536},
                      {"id": "a", "python": "python3\nexec bad"}):
            with self.subTest(value=value), self.assertRaises(ValueError): normalize_remote(value)

    def test_discovers_included_concrete_aliases_with_quotes_and_cycles(self):
        with tempfile.TemporaryDirectory() as folder:
            config = pathlib.Path(folder)/"config"; other = pathlib.Path(folder)/"extra"
            config.write_text('Host alpha beta *.example !blocked\nInclude "' + str(other) + '"\nHost=gamma\n')
            other.write_text('Host "delta"\nInclude "' + str(config) + '"\n')
            self.assertEqual(ssh_aliases(config), ["alpha", "beta", "delta", "gamma"])

    def test_remote_probe_checks_real_custom_directory_without_reading_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); (root/"sessions").mkdir()
            (root/"auth.json").write_text("DO NOT READ")
            real_run = subprocess.run
            def run(args, **kwargs):
                self.assertIn("StrictHostKeyChecking=yes", args)
                return real_run([sys.executable] + shlex.split(args[-1])[1:], **kwargs)
            with patch("connections.subprocess.run", side_effect=run):
                result = remote_check({"id": "different-host", "codex_home": folder})
            self.assertTrue(result["ok"])
            self.assertEqual(result["root"], str(pathlib.Path(folder).resolve()))
            self.assertNotIn("DO NOT READ", json.dumps(result))

    def test_remote_failure_preserves_fingerprint_check_and_shows_setup_guidance(self):
        failed = subprocess.CompletedProcess([], 255, "", "Host key verification failed.")
        with patch("connections.subprocess.run", return_value=failed):
            result = remote_check({"id": "new-host"})
        self.assertFalse(result["ok"])
        self.assertIn("主机指纹", result["detail"])

    def test_collector_transports_arbitrary_profile_and_root_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); (root/"sessions").mkdir()
            rollout = root/"sessions"/"rollout.jsonl"
            records = [{"type":"session_meta","payload":{"id":str(uuid.uuid4()),"source":"vscode","cwd":"/workspace"}},
                       {"type":"response_item","payload":{"type":"message","role":"user","content":[{"text":"实现应用"}]}}]
            rollout.write_text("\n".join(json.dumps(r) for r in records))
            before = rollout.read_bytes()
            real_run = subprocess.run
            def run(args, **kwargs):
                self.assertIn("HostName=192.0.2.20", args)
                return real_run([sys.executable] + shlex.split(args[-1])[1:], **kwargs)
            with patch("service.subprocess.run", side_effect=run):
                result = collect_host("custom-lab", {}, {"remote_hosts": [{"id": "custom-lab", "hostname": "192.0.2.20", "codex_home": folder}]})
            self.assertEqual(result["conversations"][0]["host"], "custom-lab")
            self.assertEqual(result["root"], str(pathlib.Path(folder).resolve()))
            self.assertEqual(rollout.read_bytes(), before)

    def test_remote_proxy_passes_custom_home_cli_and_host_without_a_whitelist(self):
        commands = []
        class Stop(Exception): pass
        def factory(args, **kwargs): commands.append(args); raise Stop()
        remote = RemoteRPC("lab-other", process_factory=factory, profile={"id":"lab-other", "codex_home":"/data/codex", "codex_cli":"/opt/custom codex", "python":"/opt/python 3"})
        with self.assertRaises(Stop): remote.connect()
        code = shlex.split(commands[0][-1])[-1]
        compile(code, "remote-locator", "exec")
        self.assertIn("/data/codex", code); self.assertIn("/opt/custom codex", code)
        self.assertEqual(shlex.split(commands[0][-1])[0], "/opt/python 3")
        self.assertIn("lab-other", commands[0])


class LocalConnectionTests(unittest.TestCase):
    def test_custom_application_and_cli_override_fail_explicitly_without_silent_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CODEX_TODO_CODEX": ""}):
            app = pathlib.Path(folder)/"Renamed.app"; cli = app/"Contents/Resources/codex"
            cli.parent.mkdir(parents=True); cli.write_text("#!/bin/sh\n"); cli.chmod(0o700)
            self.assertEqual(codex_path({"codex_app":str(app)}), str(cli.resolve()))
            with self.assertRaisesRegex(RuntimeError, "重新选择"): codex_path({"codex_cli":str(app/"missing")})

    def test_model_and_effort_use_profile_but_keep_read_only_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            cli = pathlib.Path(folder)/"codex"; cli.write_text("#!/bin/sh\n"); cli.chmod(0o700)
            args = command("schema", "answer", {"codex_cli":str(cli), "analysis_model":"gpt-6.1-sol", "analysis_effort":"high"})
            self.assertEqual(args[0], str(cli.resolve()))
            self.assertEqual(args[args.index("-m")+1], "gpt-6.1-sol")
            self.assertIn('model_reasoning_effort="high"', args)
            self.assertEqual(args[args.index("-s")+1], "read-only")
            self.assertIn("--ephemeral", args)

    def test_analysis_process_receives_selected_home_and_drops_active_identity(self):
        captured = {}
        class Child:
            returncode = 0
            def communicate(self, prompt, timeout): return "", ""
        def start(args, **kwargs):
            captured.update(kwargs)
            pathlib.Path(args[args.index("--output-last-message")+1]).write_text('{"ok":true}')
            return Child()
        with patch("analyzer.codex_path", return_value="/fake/codex"), patch("analyzer.subprocess.Popen", side_effect=start), patch.dict(os.environ, {"CODEX_THREAD_ID":"active"}):
            self.assertEqual(generate_json("prompt", {}, settings={"codex_home":"/tmp/custom-codex"}), {"ok":True})
        self.assertEqual(captured["env"]["CODEX_HOME"], str(pathlib.Path("/tmp/custom-codex").resolve()))
        self.assertNotIn("CODEX_THREAD_ID", captured["env"])

    def test_local_probe_distinguishes_collection_login_and_desktop(self):
        with tempfile.TemporaryDirectory() as folder:
            (pathlib.Path(folder)/"sessions").mkdir()
            def run(args, **kwargs):
                self.assertEqual(kwargs["env"]["CODEX_HOME"], str(pathlib.Path(folder).resolve()))
                if args[-1] == "--version": return subprocess.CompletedProcess(args, 0, "codex-cli test", "")
                if args[-1] == "--help": return subprocess.CompletedProcess(args, 0, "--ignore-user-config --ignore-rules --ephemeral --output-schema", "")
                return subprocess.CompletedProcess(args, 1, "", "secret output must never leave this check")
            with patch("connections.codex_path", return_value="/fake/codex"), patch("connections.subprocess.run", side_effect=run):
                result = local_check({"codex_home":folder})
            self.assertTrue(result["sessions_ready"]); self.assertFalse(result["login_ready"]); self.assertFalse(result["ok"])
            self.assertNotIn("secret output", json.dumps(result))

    def test_selected_codex_home_is_used_for_desktop_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            broker = DesktopBroker(folder)
            try:
                result = dispatch(TARGET, str(uuid.uuid4()), settings={"codex_home":folder})
                self.assertEqual(result["delivery"], "started")
            finally: broker.close()

    def test_connection_check_does_not_block_snapshot_polling(self):
        service = pathlib.Path(__file__).resolve().parents[1]/"backend/service.py"
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); (root/"codex/sessions").mkdir(parents=True)
            cli = root/"cli"
            cli.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then sleep 1; echo "codex-cli fake"; elif [ "$1" = "exec" ]; then echo "--ignore-user-config --ignore-rules --ephemeral --output-schema"; else exit 0; fi\n'); cli.chmod(0o700)
            store = Store(root/"data"); store.save_settings({"codex_home":str(root/"codex"),"codex_cli":str(cli)})
            store.put_meta("off_duty_until", time.time()+3600); store.db.close()
            proc = subprocess.Popen([sys.executable,str(service),"--data-dir",str(root/"data"),"serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                proc.stdin.write('{"id":1,"method":"check_connection"}\n{"id":2,"method":"snapshot"}\n'); proc.stdin.flush()
                self.assertEqual(json.loads(proc.stdout.readline())["id"], 2)
                result = json.loads(proc.stdout.readline())
                self.assertEqual(result["id"], 1); self.assertTrue(result["result"]["ok"])
            finally:
                proc.stdin.close(); proc.wait(timeout=5); proc.stdout.close(); proc.stderr.close()
