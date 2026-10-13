import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from analyzer import analyze, rewrite_task_copy
from test_backend import conversation, entry, task


def fake_process(response, inspect=None):
    class Process:
        returncode = 0
        def __init__(self, args, **kwargs):
            self.answer = pathlib.Path(args[args.index("--output-last-message") + 1])
            if inspect:
                inspect(json.loads(pathlib.Path(args[args.index("--output-schema") + 1]).read_text()))
        def communicate(self, prompt, timeout=None):
            self.answer.write_text(json.dumps(response))
            return "", ""
    return Process


class AnalyzerTests(unittest.TestCase):
    def test_displayed_evidence_always_comes_from_selected_source_message(self):
        conv = conversation()
        response = {"conversations": [entry(tasks=[dict(task(), evidence="模型的改写，原文没有这句话", evidence_index=1)])]}
        with patch("analyzer.subprocess.Popen", fake_process(response)):
            entries = analyze([conv], {})
        self.assertEqual(entries[0]["tasks"][0]["evidence"], conv["messages"][1]["text"])

    def test_batch_schema_requires_all_requested_ids(self):
        conv = conversation()
        inspected = []
        response = {"conversations": [entry(tasks=[dict(task(), evidence_index=1)])]}
        with patch("analyzer.subprocess.Popen", fake_process(response, inspected.append)):
            analyze([conv], {})
        array = inspected[0]["properties"]["conversations"]
        self.assertEqual(array["minItems"], 1)
        self.assertEqual(array["maxItems"], 1)
        self.assertEqual(array["items"]["properties"]["id"]["enum"], [conv["id"]])

    def test_partial_batch_is_rejected_before_persistence(self):
        conv = conversation()
        with patch("analyzer.subprocess.Popen", fake_process({"conversations": []})):
            with self.assertRaisesRegex(ValueError, "范围不完整"):
                analyze([conv], {})

    def test_fabricated_message_reference_is_rejected(self):
        response = {"conversations": [entry(tasks=[dict(task(), evidence_index=999)])]}
        with patch("analyzer.subprocess.Popen", fake_process(response)):
            with self.assertRaisesRegex(ValueError, "消息不存在"):
                analyze([conversation()], {})

    def test_unknown_task_cannot_be_marked_resolved(self):
        response = {"conversations": [entry(resolved=["not-a-real-task"], tasks=[])]}
        with patch("analyzer.subprocess.Popen", fake_process(response)):
            with self.assertRaisesRegex(ValueError, "未知待办"):
                analyze([conversation()], {})

    def test_new_work_message_is_attached_to_task_instance(self):
        conv = conversation()
        conv["messages"] += [dict(role="user",text="再次提交模型",at=100)]
        response = {"conversations": [entry(tasks=[dict(task(), evidence_index=1, work_index=2)])]}
        with patch("analyzer.subprocess.Popen", fake_process(response)):
            entries = analyze([conv], {})
        item = entries[0]["tasks"][0]
        self.assertEqual(item["_work_at"], 100)
        self.assertTrue(item["_work_token"])

    def test_running_progress_is_supported_and_cannot_become_a_resume_reminder(self):
        conv=dict(conversation(active=True),execution_state='running')
        response={'conversations':[entry(tasks=[dict(task(kind='continue'),evidence_index=1)])]}
        with patch('analyzer.generate_json',return_value=response) as generate:
            result=analyze([conv],{})
        self.assertIn('"execution_state": "running"',generate.call_args.args[0])
        self.assertEqual(result[0]['tasks'][0]['kind'],'running')

    def test_idle_execution_cannot_keep_running_status(self):
        conv=dict(conversation(active=True),execution_state='idle')
        response={'conversations':[dict(entry(tasks=[dict(task(kind='running'),evidence_index=1)]),state='running')]}
        with patch('analyzer.generate_json',return_value=response):
            result=analyze([conv],{})
        self.assertEqual(result[0]['tasks'][0]['kind'],'continue')
        self.assertEqual(result[0]['state'],'unfinished')

    def test_copy_requires_a_short_stop_point_and_first_next_action(self):
        original = dict(task(), id="copy-example", conversation=conversation())
        rewritten = dict(id="copy-example",title="验收模型发布",detail="发布新模型",progress="已提交；停在验证结果",next_action="核对本次模型验证指标")
        with patch("analyzer.subprocess.Popen", fake_process({"tasks":[rewritten]})):
            entries = rewrite_task_copy([original])
        self.assertEqual(entries[0]["title"], rewritten["title"])
        self.assertEqual(entries[0]["progress"], original["progress"])
        self.assertEqual(entries[0]["next_action"], original["next_action"])
        with patch("analyzer.subprocess.Popen", fake_process({"tasks":[dict(rewritten,progress="长"*55)]})):
            with self.assertRaisesRegex(ValueError, "文案过长"):
                rewrite_task_copy([original])


if __name__ == "__main__":
    unittest.main()
