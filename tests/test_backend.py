import json
import datetime
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from collector import collect, parse_rollout, redact
from store import Store
from analyzer import command


def conversation(cid="mac:example", updated=None, active=False):
    return dict(id=cid, host=cid.split(":")[0], thread_id=cid.split(":")[1], title="发布模型",
                cwd="/workspace", path="/rollout.jsonl", messages=[dict(role="user", text="发布模型", at=1),
                dict(role="assistant", text="已提交 MR !123；结果尚待校对。", at=2)], fingerprint="v1", updated_at=updated or time.time()-600,
                active=active, last_event_at=0, truncated=False, malformed_lines=0)


def task(key="review-release", kind="review", artifact="MR !123"):
    return dict(key=key, related_task_ids=[], kind=kind, title="校对 MR 的模型结果", detail="需要检查部署效果", evidence="已提交 MR !123", next_action="打开 MR，检查测试结果。",
                progress="MR 已提交；结果尚未校对", work_index=0,
                priority=2, confidence=0.95, artifact=artifact, suggested_after_minutes=0)


def entry(cid="mac:example", tasks=None, resolved=None):
    return dict(id=cid, state="submitted", summary="已提交，待校对", tasks=tasks if tasks is not None else [task()], resolved_keys=resolved or [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.conv = conversation()
        self.ingest(self.conv)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def ingest(self, conv):
        self.store.ingest(dict(host=conv["host"], files={}, conversations=[conv], total_files=1, remaining_files=0, root="/tmp"))

    def test_new_submission_creates_review_and_unchanged_refresh_does_not_duplicate(self):
        self.store.reconcile([entry()], [self.conv])
        self.store.reconcile([entry()], [self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 1)
        self.assertEqual(self.store.eligible(), [])

    def test_manual_completion_survives_new_analysis(self):
        self.store.reconcile([entry()], [self.conv])
        self.store.act("complete", self.store.snapshot()["tasks"][0]["id"])
        self.conv["fingerprint"] = "v2"
        self.ingest(self.conv)
        # Even model wording/key drift cannot recreate a completed review of the same artifact.
        self.store.reconcile([entry(tasks=[task("new-wording")])], [self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 1)
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "done")

    def test_manual_close_during_model_call_is_respected_and_reversible(self):
        self.store.reconcile([entry()], [self.conv])
        self.store.act("close_conversation", self.conv["id"])
        self.store.reconcile([entry(tasks=[task("another-key")])], [self.conv])
        self.assertEqual(self.store.eligible(), [])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 1)
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "conversation_closed")
        self.store.act("reopen_conversation", self.conv["id"])
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "open")
        self.assertEqual(len(self.store.eligible()), 1)

    def test_stale_model_response_cannot_overwrite_newer_conversation(self):
        newer = dict(self.conv, fingerprint="v2", updated_at=time.time())
        self.ingest(newer)
        self.store.reconcile([entry()], [self.conv])
        self.assertEqual(self.store.snapshot()["tasks"], [])

    def test_older_rollout_fragment_cannot_overwrite_newer_turn(self):
        newer = dict(self.conv, fingerprint="v2", updated_at=time.time())
        self.ingest(newer)
        self.ingest(self.conv)
        self.assertEqual(self.store.db.execute("SELECT fingerprint FROM conversations").fetchone()[0], "v2")

    def test_running_task_is_eligible_without_waiting_for_idle_threshold(self):
        recent = dict(self.conv, active=True, updated_at=time.time()-120)
        self.ingest(recent)
        self.assertEqual(self.store.eligible()[0]['execution_state'], 'running')
        recent["updated_at"] = time.time()-700
        with self.store.db:
            self.store.db.execute("DELETE FROM conversations")
        self.ingest(recent)
        self.assertEqual(len(self.store.eligible()), 1)
        self.assertEqual(self.store.eligible()[0]['execution_state'], 'idle')

    def test_open_running_task_gets_one_idle_transition_without_new_content(self):
        now=time.time()
        self.conv.update(active=True,updated_at=now-30)
        self.ingest(self.conv)
        batch=self.store.eligible()
        self.store.reconcile([dict(entry(tasks=[task(kind='running')]),state='running')],batch)
        original=self.store.snapshot()['tasks'][0]['id']
        self.assertEqual(self.store.eligible(),[])
        with patch('store.time.time',return_value=now+600):
            batch=self.store.eligible()
            self.assertEqual(batch[0]['execution_state'],'idle')
            self.store.reconcile([entry(tasks=[task(kind='continue')])],batch)
            self.assertEqual(self.store.eligible(),[])
        result=self.store.snapshot()['tasks'][0]
        self.assertEqual(result['id'],original)
        self.assertEqual(result['kind'],'continue')

    def test_completed_running_task_does_not_reappear_when_it_becomes_idle(self):
        now=time.time()
        self.conv.update(active=True,updated_at=now-30)
        self.ingest(self.conv)
        self.store.reconcile([dict(entry(tasks=[task(kind='running')]),state='running')],self.store.eligible())
        self.store.act('complete',self.store.snapshot()['tasks'][0]['id'])
        with patch('store.time.time',return_value=now+600):
            self.assertEqual(self.store.eligible(),[])
        self.assertEqual(self.store.snapshot()['tasks'][0]['status'],'done')

    def test_running_submission_moves_to_wait_without_duplicate(self):
        self.conv.update(active=True,updated_at=time.time()-30)
        self.ingest(self.conv)
        self.store.reconcile([dict(entry(tasks=[task(kind='running')]),state='running')],self.store.eligible())
        tid=self.store.snapshot()['tasks'][0]['id']
        self.conv.update(fingerprint='submitted',updated_at=time.time())
        self.ingest(self.conv)
        self.store.reconcile([dict(entry(tasks=[task(kind='wait')]),state='waiting')],self.store.eligible())
        self.assertEqual(len(self.store.snapshot()['tasks']),1)
        self.assertEqual(self.store.snapshot()['tasks'][0]['id'],tid)
        self.assertEqual(self.store.snapshot()['tasks'][0]['kind'],'wait')

    def test_truncated_or_uncertain_update_preserves_previous_open_task(self):
        self.store.reconcile([entry()], [self.conv])
        self.conv.update(fingerprint="v2", truncated=True)
        self.ingest(self.conv)
        self.store.reconcile([dict(entry(tasks=[]), state="uncertain")], [self.conv])
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "open")

    def test_explicit_resolution_and_new_submission_transition(self):
        self.store.reconcile([entry()], [self.conv])
        self.store.reconcile([entry(tasks=[], resolved=["review-release"])], [self.conv])
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "resolved")
        self.conv['messages'].append(dict(role='assistant',text='已提交 MR !124；新的结果待校对。',at=3))
        self.conv.update(fingerprint='next-mr',updated_at=self.conv['updated_at']+1)
        self.ingest(self.conv)
        self.store.reconcile([entry(tasks=[dict(task("review-next", artifact="MR !124"),evidence='已提交 MR !124',work_index=2,evidence_index=2)])], [self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 2)
        self.assertEqual(sum(t["status"] == "open" for t in self.store.snapshot()["tasks"]), 1)

    def test_wait_to_review_reuses_identity_and_snooze(self):
        self.store.reconcile([entry(tasks=[task(kind="wait")])], [self.conv])
        tid = self.store.snapshot()["tasks"][0]["id"]
        self.store.act("snooze", tid, 60)
        self.store.reconcile([entry()], [self.conv])
        updated = self.store.snapshot()["tasks"][0]
        self.assertEqual(updated["id"], tid)
        self.assertEqual(updated["kind"], "review")
        self.assertGreater(updated["snoozed_until"], time.time())

    def test_history_range_limits_backlog_without_deleting_existing_tasks(self):
        self.store.reconcile([entry()], [self.conv])
        self.store.save_settings({"history_days": 7})
        self.conv.update(updated_at=time.time()-10*86400, fingerprint="v2")
        with self.store.db:
            self.store.db.execute("DELETE FROM conversations")
        self.ingest(self.conv)
        self.assertEqual(self.store.eligible(), [])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 1)

    def test_new_work_after_completion_creates_another_task_in_same_thread(self):
        self.store.reconcile([entry()], [self.conv])
        first = self.store.snapshot()["tasks"][0]["id"]
        with patch("store.time.time", return_value=100):
            self.store.act("complete", first)
        self.conv["messages"] += [dict(role="user",text="增加正文搜索，再更新同一个 MR",at=101),
                                  dict(role="assistant",text="已再次更新 MR !123，待核对新输入。",at=102)]
        self.conv.update(fingerprint="v2", updated_at=self.conv["updated_at"]+1)
        self.ingest(self.conv)
        followup = dict(task(), evidence="已再次更新 MR !123", work_index=2)
        self.store.reconcile([entry(tasks=[followup])], [self.conv])
        rows = self.store.snapshot()["tasks"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(r for r in rows if r["id"] == first)["status"], "done")
        second = next(r for r in rows if r["status"] == "open")
        self.assertNotEqual(first, second["id"])
        self.store.reconcile([entry(tasks=[followup])], [self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 2)
        # Re-reading the second occurrence after completing it also stays completed.
        with patch("store.time.time", return_value=103):
            self.store.act("complete", second["id"])
        self.store.reconcile([entry(tasks=[followup])], [self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]), 2)
        self.assertTrue(all(r["status"] == "done" for r in self.store.snapshot()["tasks"]))

    def test_copy_upgrade_preserves_identity_and_does_not_reopen_completed_task(self):
        self.store.reconcile([entry()], [self.conv])
        row = self.store.snapshot()["tasks"][0]
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET copy_version=0,progress='' WHERE id=?", (row["id"],))
        pending = self.store.copy_pending()
        rewritten = dict(id=row["id"],title="验收全文检索 MR",detail="为文档搜索增加全文检索",progress="MR 已提交；停在结果校对",next_action="核对本次 MR 的验证结果")
        self.store.apply_copy([rewritten], pending)
        updated = self.store.snapshot()["tasks"][0]
        self.assertEqual(updated["id"], row["id"])
        self.assertEqual(updated["progress"], rewritten["progress"])
        self.assertEqual(updated["updated_at"], row["updated_at"])
        self.assertEqual(self.store.copy_pending(), [])
        self.store.act("complete", row["id"])
        self.store.apply_copy([dict(rewritten,title="错误的新标题")], pending)
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "done")
        self.assertEqual(self.store.snapshot()["tasks"][0]["title"], rewritten["title"])

    def test_new_submission_reported_after_completion_can_create_another_review(self):
        self.store.reconcile([entry()], [self.conv])
        first = self.store.snapshot()["tasks"][0]["id"]
        with patch("store.time.time",return_value=100):
            self.store.act("complete",first)
        self.conv["messages"].append(dict(role="assistant",text="新一轮实验已提交；需检查新的指标。",at=101))
        self.conv.update(fingerprint="v2",updated_at=self.conv["updated_at"]+1)
        self.ingest(self.conv)
        followup = dict(task(),evidence="新一轮实验已提交",work_index=2)
        self.store.reconcile([entry(tasks=[followup])],[self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]),2)
        self.assertEqual(sum(t["status"]=="open" for t in self.store.snapshot()["tasks"]),1)

    def test_same_work_is_not_reopened_even_when_source_clock_is_ahead(self):
        self.store.reconcile([entry()],[self.conv])
        first=self.store.snapshot()["tasks"][0]["id"]
        with patch("store.time.time",return_value=0.5):
            self.store.act("complete",first)
        self.store.reconcile([entry()],[self.conv])
        self.assertEqual(len(self.store.snapshot()["tasks"]),1)
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"],"done")

    def test_copy_upgrade_ignores_conversation_changed_during_rewrite(self):
        self.store.reconcile([entry()], [self.conv])
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET copy_version=0")
        pending = self.store.copy_pending()
        self.conv.update(fingerprint="v2",updated_at=self.conv["updated_at"]+1)
        self.ingest(self.conv)
        rewritten = dict(id=pending[0]["id"],title="旧结果",detail="旧目标",progress="旧进度",next_action="旧动作")
        self.store.apply_copy([rewritten], pending)
        self.assertNotEqual(self.store.snapshot()["tasks"][0]["title"], "旧结果")

    def test_submission_before_completing_stale_list_creates_wait_task(self):
        self.store.reconcile([entry(tasks=[task('experiment',kind='continue',artifact='')])],[self.conv])
        first=self.store.snapshot()['tasks'][0]['id']
        self.conv['messages'].append(dict(role='assistant',text='D1-D3 已提交；任务 t-123 正在排队。',at=95))
        self.conv.update(fingerprint='v2',updated_at=self.conv['updated_at']+1)
        self.ingest(self.conv)
        with patch('store.time.time',return_value=100): self.store.act('complete',first)
        followup=dict(task('experiment',kind='wait',artifact='t-123'),evidence='D1-D3 已提交',work_index=2,evidence_index=2)
        self.store.reconcile([entry(tasks=[followup])],[self.conv])
        rows=self.store.snapshot()['tasks']
        self.assertEqual(len(rows),2)
        self.assertEqual(next(t for t in rows if t['id']==first)['status'],'done')
        self.assertEqual([(t['kind'],t['artifact']) for t in rows if t['status']=='open'],[('wait','t-123')])
        self.assertEqual(self.store.snapshot()['conversations'][0]['closed'],0)
        self.store.reconcile([entry(tasks=[followup])],[self.conv])
        self.assertEqual(len(self.store.snapshot()['tasks']),2)

    def test_followup_stages_can_share_original_work_anchor_without_id_collision(self):
        self.store.reconcile([entry(tasks=[task('experiment',kind='continue',artifact='')])],[self.conv])
        first=self.store.snapshot()['tasks'][0]['id']
        with patch('store.time.time',return_value=100): self.store.act('complete',first)
        self.conv['messages'].append(dict(role='assistant',text='实验已提交任务 t-123；等待结果。',at=95))
        self.conv.update(fingerprint='v2',updated_at=self.conv['updated_at']+1)
        self.ingest(self.conv)
        waiting=dict(task('experiment',kind='wait',artifact='t-123'),evidence='实验已提交',work_index=0,evidence_index=2)
        self.store.reconcile([entry(tasks=[waiting])],[self.conv])
        second=next(t['id'] for t in self.store.snapshot()['tasks'] if t['status']=='open')
        self.conv['messages'].append(dict(role='assistant',text='任务 t-123 已完成；评测指标尚未核对。',at=105))
        self.conv.update(fingerprint='v3',updated_at=self.conv['updated_at']+1)
        self.ingest(self.conv)
        with patch('store.time.time',return_value=110): self.store.act('complete',second)
        review=dict(waiting,kind='review',evidence='任务 t-123 已完成',evidence_index=3)
        self.store.reconcile([entry(tasks=[review])],[self.conv])
        rows=self.store.snapshot()['tasks']
        self.assertEqual(len(rows),3)
        self.assertEqual(len({t['id'] for t in rows}),3)
        self.assertEqual([(t['kind'],t['status']) for t in rows if t['status']=='open'],[('review','open')])
        third=next(t['id'] for t in rows if t['status']=='open')
        with patch('store.time.time',return_value=120): self.store.act('complete',third)
        self.store.reconcile([entry(tasks=[review])],[self.conv])
        self.assertEqual(len(self.store.snapshot()['tasks']),3)
        self.assertFalse(any(t['status']=='open' for t in self.store.snapshot()['tasks']))

    def test_completion_without_new_content_does_not_schedule_reanalysis(self):
        self.store.reconcile([entry()],[self.conv])
        self.assertEqual(self.store.eligible(),[])
        self.store.act('complete',self.store.snapshot()['tasks'][0]['id'])
        self.assertEqual(self.store.eligible(),[])
        self.assertEqual(self.store.snapshot()['conversations'][0]['closed'],0)
        self.store.reconcile([entry()],[self.conv])
        self.assertEqual(len(self.store.snapshot()['tasks']),1)
        self.assertEqual(self.store.snapshot()['tasks'][0]['status'],'done')

    def test_manual_tasks_are_independent_of_conversations_and_model_updates(self):
        tid=self.store.save_manual('准备周会材料','整理本周实验结论',1)
        item=next(t for t in self.store.snapshot()['tasks'] if t['id']==tid)
        self.assertEqual(item['host'],'manual')
        self.assertEqual(item['conversation_id'],'')
        self.assertEqual(item['thread_id'],'')
        self.assertEqual(len(self.store.snapshot()['conversations']),1)
        self.store.reconcile([entry()],[self.conv])
        self.store.act('complete',tid)
        self.store.save_manual('更新周会材料','补充结论',2,tid)
        updated=next(t for t in self.store.snapshot()['tasks'] if t['id']==tid)
        self.assertEqual(updated['status'],'done')
        self.assertEqual(updated['detail'],'补充结论')
        self.store.act('reopen',tid)
        self.store.act('snooze',tid,60)
        self.assertGreater(next(t for t in self.store.snapshot()['tasks'] if t['id']==tid)['snoozed_until'],time.time())
        self.store.act('dismiss',tid)
        self.assertEqual(next(t for t in self.store.snapshot()['tasks'] if t['id']==tid)['status'],'dismissed')
        with self.assertRaisesRegex(ValueError,'只能编辑'):
            self.store.save_manual('错误','',2,next(t['id'] for t in self.store.snapshot()['tasks'] if t['kind']=='review'))

    def test_unchanged_completed_conversation_is_not_sent_to_model_on_sync(self):
        from service import sync
        self.store.save_settings({'enabled_hosts':['mac'],'workdays_only':False})
        self.store.reconcile([entry()],[self.conv])
        self.store.act('complete',self.store.snapshot()['tasks'][0]['id'])
        collected=dict(host='mac',files={},conversations=[self.conv],total_files=1,remaining_files=0,root='/tmp')
        with patch('service.collect_host',return_value=collected),patch('service.analyze') as model:
            result=sync(self.tmp.name)
            model.assert_not_called()
            self.assertEqual(result['analyzed'],0)
        self.conv['messages'].append(dict(role='assistant',text='新的实验已提交；等待任务结果。',at=time.time()-60))
        self.conv.update(fingerprint='v2',updated_at=time.time()-60)
        waiting=dict(task(kind='wait',artifact='t-new'),evidence='新的实验已提交',work_index=2)
        with patch('service.collect_host',return_value=collected),patch('service.analyze',return_value=[entry(tasks=[waiting])]) as model:
            result=sync(self.tmp.name)
            model.assert_called_once()
            self.assertEqual(result['analyzed'],1)
        self.assertEqual(sum(t['status']=='open' and t['kind']=='wait' for t in self.store.snapshot()['tasks']),1)

    def test_legacy_completion_does_not_acknowledge_newer_submission(self):
        with patch('store.time.time',return_value=90):
            self.store.reconcile([entry(tasks=[task('experiment',kind='continue',artifact='')])],[self.conv])
        first=self.store.snapshot()['tasks'][0]['id']
        self.conv['messages'].append(dict(role='assistant',text='实验已提交；等待任务 t-123 结果。',at=95))
        self.conv.update(fingerprint='v2',updated_at=self.conv['updated_at']+1)
        self.ingest(self.conv)
        with patch('store.time.time',return_value=100): self.store.act('complete',first)
        with self.store.db: self.store.db.execute('ALTER TABLE tasks DROP COLUMN observed_at')
        self.store.db.close()
        self.store=Store(self.tmp.name)
        self.assertEqual(self.store.existing([self.conv['id']])[self.conv['id']][0]['observed_at'],90)
        waiting=dict(task('experiment',kind='wait',artifact='t-123'),evidence='实验已提交',work_index=2,evidence_index=2)
        self.store.reconcile([entry(tasks=[waiting])],[self.conv])
        self.assertEqual(len(self.store.snapshot()['tasks']),2)
        self.assertEqual(sum(t['status']=='open' for t in self.store.snapshot()['tasks']),1)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "sessions").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def rollout(self, name="test", source="vscode", big=False):
        p = self.root / "sessions" / (name+".jsonl")
        events = [dict(type="session_meta", payload=dict(id=name, cwd="/work", source=source)),
                  dict(type="event_msg", payload=dict(type="task_started")),
                  dict(type="response_item", payload=dict(type="message",role="developer",content=[dict(text="Secret system instructions")])),
                  dict(type="response_item", payload=dict(type="message",role="user",content=[dict(text="<environment_context>noise</environment_context>\n发布模型")])),
                  dict(type="response_item", payload=dict(type="message",role="assistant",content=[dict(text="已提交，password=private-value")])),
                  dict(type="event_msg", payload=dict(type="task_complete"))]
        if big:
            events.insert(4, dict(type="response_item",payload=dict(type="reasoning",encrypted_content="x"*250000)))
        p.write_text("\n".join(json.dumps(d) for d in events)+"\n")
        return p

    def test_extracts_only_conversation_and_redacts_credentials(self):
        c = parse_rollout(self.rollout(), "mac")
        content = json.dumps(c, ensure_ascii=False)
        self.assertNotIn("Secret system", content)
        self.assertNotIn("private-value", content)
        self.assertNotIn("environment_context", content)
        self.assertIn("发布模型", content)
        self.assertFalse(c["active"])

    def test_guardian_children_are_not_tasks(self):
        self.assertIsNone(parse_rollout(self.rollout(source={"subagent":{"other":"guardian"}}), "mac"))

    def test_incremental_scan_and_backfill(self):
        self.rollout("one")
        self.rollout("two")
        first = collect(dict(root=str(self.root), host="mac", limit=1))
        self.assertEqual(first["remaining_files"], 1)
        second = collect(dict(root=str(self.root), host="mac", known=first["files"], limit=1))
        self.assertEqual(second["remaining_files"], 0)
        third = collect(dict(root=str(self.root), host="mac", known=dict(first["files"], **second["files"])))
        self.assertEqual(third["conversations"], [])

    def test_new_conversation_is_discovered_after_previous_scan(self):
        self.rollout('existing')
        previous=collect(dict(root=str(self.root),host='build-server'))
        self.rollout('new-thread')
        current=collect(dict(root=str(self.root),host='build-server',known=previous['files']))
        self.assertEqual([c['thread_id'] for c in current['conversations']],['new-thread'])
        self.assertEqual(current['remaining_files'],0)

    def test_recent_tool_activity_counts_as_execution_activity(self):
        p=self.rollout()
        lines=[json.loads(line) for line in p.read_text().splitlines()]
        for row in lines: row['timestamp']='2026-10-09T07:00:00Z'
        lines.pop()  # Keep the turn open while a long-running tool reports progress.
        lines.append(dict(type='response_item',timestamp='2026-10-09T07:15:00Z',payload=dict(type='function_call_output',output='构建仍在进行')))
        p.write_text('\n'.join(json.dumps(row) for row in lines)+'\n')
        result=parse_rollout(p,'research-server')
        self.assertTrue(result['active'])
        self.assertEqual(result['updated_at'],datetime.datetime(2026,10,9,7,15,tzinfo=datetime.timezone.utc).timestamp())

    def test_large_boundary_and_partial_line_are_tolerated(self):
        p = self.rollout(big=True)
        with p.open("a") as f: f.write('{"partial":')
        c = parse_rollout(p, "mac")
        self.assertFalse(c["active"])
        self.assertGreaterEqual(c["malformed_lines"], 1)

    def test_secret_patterns(self):
        value = redact("Authorization: Bearer abc123 password='pw' sk-"+"s"*30+" https://user:pass@example.com")
        self.assertNotIn("abc123", value)
        self.assertNotIn("'pw'", value)
        self.assertNotIn("user:pass", value)


class ProtocolTests(unittest.TestCase):
    def test_manual_task_rpc_persists_without_conversation_and_automatic_gate_is_enforced(self):
        service=pathlib.Path(__file__).resolve().parents[1]/'backend/service.py'
        with tempfile.TemporaryDirectory() as folder:
            requests=[dict(id=1,method='settings',values=dict(automatic=False,workdays_only=False)),
                      dict(id=2,method='save_manual',title='准备周会材料',detail='整理实验结论',priority=1),
                      dict(id=3,method='sync',automatic=True),dict(id=4,method='snapshot')]
            result=subprocess.run([sys.executable,str(service),'--data-dir',folder,'serve'],input='\n'.join(json.dumps(r) for r in requests)+'\n',capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            outputs=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertFalse(outputs[2]['result']['accepted'])
            snapshot=outputs[3]['result']
            self.assertEqual(snapshot['conversations'],[])
            self.assertEqual(snapshot['tasks'][0]['id'],outputs[1]['result']['task_id'])
            self.assertEqual(snapshot['tasks'][0]['kind'],'manual')
            self.assertFalse(snapshot['schedule']['due'])
            self.assertFalse(snapshot['sync']['running'])

    def test_stdio_rpc_persists_settings_and_no_network_listener(self):
        service = pathlib.Path(__file__).resolve().parents[1] / "backend/service.py"
        with tempfile.TemporaryDirectory() as folder:
            requests = [dict(id=1,method="settings",values=dict(automatic=False,workdays_only=False)),dict(id=2,method="snapshot")]
            result = subprocess.run([sys.executable,str(service),"--data-dir",folder,"serve"],input="\n".join(json.dumps(r) for r in requests)+"\n",capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = [json.loads(l) for l in result.stdout.splitlines()]
            self.assertFalse(outputs[1]["result"]["settings"]["automatic"])
            self.assertEqual(outputs[1]["result"]["model"], "gpt-6-luna")

    def test_model_and_effort_fixed_and_tool_features_disabled(self):
        args = command("schema", "answer")
        self.assertEqual(args[args.index("-m")+1], "gpt-6-luna")
        self.assertIn('model_reasoning_effort="max"', args)
        self.assertIn("--ignore-user-config", args)
        self.assertIn("--ephemeral", args)
        for flag in ("shell_tool", "apps", "plugins", "multi_agent"):
            self.assertIn(flag, args)

    def test_quitting_service_stops_in_flight_model_process(self):
        service = pathlib.Path(__file__).resolve().parents[1] / "backend/service.py"
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            source = root / "codex/sessions"
            source.mkdir(parents=True)
            stamp = datetime.datetime.fromtimestamp(time.time()-120, datetime.timezone.utc).isoformat()
            lines = [dict(type="session_meta",payload=dict(id="quit-check",source="vscode",cwd="/work")),
                     dict(type="response_item",payload=dict(type="message",role="user",content=[dict(text="发布模型")]))]
            for item in lines: item["timestamp"] = stamp
            (source / "rollout.jsonl").write_text("\n".join(json.dumps(x) for x in lines)+"\n")
            stub = root / "fake-codex"
            pid_file = root / "model-pid"
            stub.write_text("#!"+sys.executable+"\nimport os,pathlib,time\npathlib.Path(os.environ['TEST_MODEL_PID']).write_text(str(os.getpid()))\ntime.sleep(60)\n")
            stub.chmod(0o700)
            data = root / "state"
            store = Store(data)
            store.save_settings({"enabled_hosts": ["mac"],"workdays_only":False})
            store.db.close()
            env = dict(os.environ, CODEX_HOME=str(root / "codex"), CODEX_TODO_CODEX=str(stub), TEST_MODEL_PID=str(pid_file))
            proc = subprocess.Popen([sys.executable,str(service),"--data-dir",str(data),"serve"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
            try:
                proc.stdin.write(json.dumps(dict(id=1,method="sync"))+"\n")
                proc.stdin.flush()
                self.assertTrue(json.loads(proc.stdout.readline())["result"]["accepted"])
                deadline = time.time()+8
                while not pid_file.exists() and time.time()<deadline:
                    time.sleep(0.05)
                self.assertTrue(pid_file.exists(), "fake model was not invoked")
                pid = int(pid_file.read_text())
                proc.stdin.close()
                proc.wait(timeout=8)
                deadline = time.time()+3
                alive = True
                while time.time()<deadline:
                    try: os.kill(pid, 0)
                    except ProcessLookupError:
                        alive = False
                        break
                    time.sleep(0.05)
                self.assertFalse(alive, "model process outlived the app service")
            finally:
                if proc.poll() is None: proc.terminate(); proc.wait(timeout=8)
                proc.stdout.close()
                proc.stderr.close()

    def test_cancel_stops_model_children_preserves_tasks_and_allows_manual_restart(self):
        service = pathlib.Path(__file__).resolve().parents[1] / "backend/service.py"
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            source = root / "codex/sessions"
            source.mkdir(parents=True)
            stamp = datetime.datetime.fromtimestamp(time.time()-120, datetime.timezone.utc).isoformat()
            lines = [dict(type="session_meta",payload=dict(id="cancel-check",source="vscode",cwd="/work")),
                     dict(type="response_item",payload=dict(type="message",role="user",content=[dict(text="发布新的模型")]))]
            for item in lines: item["timestamp"] = stamp
            (source / "rollout.jsonl").write_text("\n".join(json.dumps(x) for x in lines)+"\n")
            stub = root / "fake-codex"
            pid_file = root / "model-pid"
            # A child that ignores SIGTERM exercises cleanup after its worker has exited.
            stub.write_text("#!"+sys.executable+"\nimport os,pathlib,signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\npathlib.Path(os.environ['TEST_MODEL_PID']).write_text(str(os.getpid()))\ntime.sleep(60)\n")
            stub.chmod(0o700)
            data = root / "state"
            store = Store(data)
            store.save_settings({"enabled_hosts": ["mac"],"workdays_only":False})
            existing = conversation()
            store.ingest(dict(host="mac",files={},conversations=[existing],total_files=1,remaining_files=0,root="/tmp"))
            store.reconcile([entry()], [existing])
            original = store.snapshot()["tasks"]
            store.db.close()
            env = dict(os.environ,CODEX_HOME=str(root / "codex"),CODEX_TODO_CODEX=str(stub),TEST_MODEL_PID=str(pid_file))
            proc = subprocess.Popen([sys.executable,str(service),"--data-dir",str(data),"serve"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)

            def rpc(identifier, method):
                proc.stdin.write(json.dumps(dict(id=identifier,method=method))+"\n")
                proc.stdin.flush()
                self.assertTrue(select.select([proc.stdout],[],[],3)[0], "service did not respond while updating")
                result = json.loads(proc.stdout.readline())
                self.assertEqual(result["id"], identifier)
                self.assertNotIn("error", result)
                return result["result"]

            try:
                for run in range(2):
                    self.assertTrue(rpc(run*3+1,"sync")["accepted"])
                    deadline = time.monotonic()+8
                    while not pid_file.exists() and time.monotonic()<deadline: time.sleep(0.05)
                    self.assertTrue(pid_file.exists(), "fake model was not invoked")
                    pid = int(pid_file.read_text())
                    started = time.monotonic()
                    result = rpc(run*3+2,"cancel_sync")
                    self.assertLess(time.monotonic()-started, 2)
                    self.assertFalse(result["sync"]["running"])
                    self.assertTrue(result["sync"]["cancelled"])
                    self.assertFalse(result["settings"]["automatic"])
                    self.assertEqual(result["tasks"], original)
                    deadline = time.monotonic()+3
                    alive = True
                    while time.monotonic()<deadline:
                        try: os.kill(pid,0)
                        except ProcessLookupError:
                            alive = False
                            break
                        time.sleep(0.05)
                    self.assertFalse(alive, "cancel left its model child running")
                    self.assertFalse(rpc(run*3+3,"snapshot")["sync"]["running"])
                    pid_file.unlink()
                proc.stdin.close()
                proc.wait(timeout=8)
            finally:
                if proc.poll() is None: proc.terminate(); proc.wait(timeout=8)
                if not proc.stdin.closed: proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
