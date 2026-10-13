import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
from store import Store
from test_backend import conversation, entry, task

SERVICE = pathlib.Path(__file__).resolve().parents[1] / 'backend/service.py'


class CustomTitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.conv = conversation()
        self.store.ingest(dict(host='mac', files={}, conversations=[self.conv], total_files=1, remaining_files=0, root='/tmp'))
        self.store.reconcile([entry()], [self.conv])
        self.original = self.store.snapshot()['tasks'][0]

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def row(self, tid=None):
        return dict(self.store.db.execute('SELECT * FROM tasks WHERE id=?', (tid or self.original['id'],)).fetchone())

    def advance(self, key='review-release'):
        self.conv['messages'].append(dict(role='assistant', text='训练已结束；最新结果尚未核对。', at=3))
        self.conv.update(fingerprint='v2', updated_at=self.conv['updated_at'] + 1)
        self.store.ingest(dict(host='mac', files={}, conversations=[self.conv], total_files=1, remaining_files=0, root='/tmp'))
        return dict(task(key), evidence='训练已结束', evidence_index=2,
                    progress='训练已结束；尚未核对最新结果', next_action='核对最新结果的性能指标')

    def test_edit_only_changes_title_metadata_and_survives_restart(self):
        self.store.act('snooze', self.original['id'], 60)
        before = self.row()
        self.assertEqual(self.store.rename_task(self.original['id'], '  为文档搜索增加全文检索  '), self.original['id'])
        after = self.row()
        for k in before:
            if k not in ('title', 'title_override', 'title_edited_at', 'updated_at'):
                self.assertEqual(before[k], after[k], k)
        self.assertEqual(after['title'], '为文档搜索增加全文检索')
        self.assertEqual(after['title_override'], after['title'])
        self.assertGreater(after['title_edited_at'], 0)
        self.assertEqual(self.store.eligible(), [])
        self.store.db.close()
        self.store = Store(self.tmp.name)
        self.assertEqual(self.row(), after)

    def test_in_flight_analysis_updates_stage_without_overwriting_custom_title(self):
        response = self.advance()
        title = '自定义目标' + '甲' * 80
        self.store.rename_task(self.original['id'], title)
        self.store.reconcile([entry(tasks=[response])], [self.conv])
        row = self.row()
        self.assertEqual(row['title'], title)
        self.assertEqual(row['progress'], response['progress'])
        self.assertEqual(row['next_action'], response['next_action'])
        self.assertTrue(self.store.existing([self.conv['id']])[self.conv['id']][0]['title_is_manual'])

    def test_future_copy_policy_and_analysis_cannot_overwrite_fixed_title(self):
        self.store.rename_task(self.original['id'], '我希望长期看到的目标')
        with patch('store.COPY_VERSION', 4):
            originals = self.store.copy_pending()
            item = dict(id=self.original['id'], title='新的自动总结', detail='更新背景',
                        progress=originals[0]['progress'], next_action=originals[0]['next_action'])
            self.assertEqual(self.store.apply_copy([item], originals), 1)
            self.assertEqual(self.row()['title'], '我希望长期看到的目标')
            self.store.reconcile([entry(tasks=[self.advance()])], [self.conv])
            self.assertEqual(self.row()['title'], '我希望长期看到的目标')

    def test_title_edit_while_copy_request_is_in_flight_rejects_old_copy(self):
        with self.store.db:
            self.store.db.execute('UPDATE tasks SET copy_version=2')
        originals = self.store.copy_pending()
        item = dict(id=self.original['id'], title='旧自动标题', detail='旧背景',
                    progress=originals[0]['progress'], next_action=originals[0]['next_action'])
        self.store.rename_task(self.original['id'], '新手动标题')
        self.assertEqual(self.store.apply_copy([item], originals), 0)
        self.assertEqual(self.row()['title'], '新手动标题')
        self.assertEqual(self.store.apply_copy([item], self.store.copy_pending()), 1)
        self.assertEqual(self.row()['title'], '新手动标题')

    def test_merging_keeps_latest_manual_title_and_stale_card_edits_survivor(self):
        self.store.reconcile([entry(tasks=[task('legacy-phase')])], [self.conv])
        duplicate = next(t for t in self.store.snapshot()['tasks'] if t['id'] != self.original['id'])
        with patch('store.time.time', return_value=100):
            self.store.rename_task(self.original['id'], '较早手动标题')
        with patch('store.time.time', return_value=200):
            self.store.rename_task(duplicate['id'], '最近手动标题')
        item = dict(self.advance(), related_task_ids=[self.original['id'], duplicate['id']])
        self.store.reconcile([entry(tasks=[item])], [self.conv])
        self.assertEqual(self.row()['title'], '最近手动标题')
        self.assertEqual(self.store.rename_task(duplicate['id'], '合并后从旧卡片改名'), self.original['id'])
        self.assertEqual(self.row()['title'], '合并后从旧卡片改名')
        self.assertEqual(self.row(duplicate['id'])['status'], 'merged')

    def test_same_goal_new_occurrence_inherits_title_different_goal_does_not(self):
        self.store.rename_task(self.original['id'], '保留我的整体目标')
        self.store.act('complete', self.original['id'])
        response = dict(self.advance(), related_task_ids=[self.original['id']])
        self.store.reconcile([entry(tasks=[response])], [self.conv])
        live = next(t for t in self.store.snapshot()['tasks'] if t['status'] == 'open')
        self.assertNotEqual(live['id'], self.original['id'])
        self.assertEqual(live['title'], '保留我的整体目标')
        self.assertEqual(live['title_override'], live['title'])
        self.assertEqual(self.row()['status'], 'done')
        other = dict(response, key='separate-goal', related_task_ids=[], title='另一个独立目标')
        self.store.reconcile([entry(tasks=[other])], [self.conv])
        other = next(t for t in self.store.snapshot()['tasks'] if t['goal_key'] == 'separate-goal')
        self.assertEqual(other['title'], '另一个独立目标')
        self.assertEqual(other['title_override'], '')

    def test_invalid_edits_and_missing_task_preserve_original(self):
        before = self.row()
        for title in ('', '  ', '甲' * 101, '第一行\n第二行', None, 42):
            with self.assertRaisesRegex(ValueError, '单行标题'):
                self.store.rename_task(self.original['id'], title)
            self.assertEqual(self.row(), before)
        with self.assertRaisesRegex(ValueError, '不存在'):
            self.store.rename_task('missing', '有效标题')
        self.assertEqual(self.row(), before)
        self.store.rename_task(self.original['id'], '甲' * 100)
        self.assertEqual(len(self.row()['title']), 100)

    def test_manual_and_completed_task_edit_keeps_note_priority_and_acknowledgement(self):
        manual = self.store.save_manual('原手动标题', '保留备注', 1)
        self.store.rename_task(manual, '新手动标题')
        row = self.row(manual)
        self.assertEqual((row['title'], row['detail'], row['priority']), ('新手动标题', '保留备注', 1))
        self.assertEqual(row['title_override'], '')
        self.store.act('complete', self.original['id'])
        before = self.row()
        self.store.rename_task(self.original['id'], '完成记录的标题')
        after = self.row()
        self.assertEqual(after['status'], 'done')
        self.assertEqual(after['completed_at'], before['completed_at'])
        self.assertEqual(after['observed_at'], before['observed_at'])


class CustomTitleProtocolTests(unittest.TestCase):
    def test_stdio_edit_persists_during_off_duty_without_starting_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            store.save_settings({'automatic': False, 'enabled_hosts': [], 'workdays_only': False})
            conv = conversation()
            store.ingest(dict(host='mac', files={}, conversations=[conv], total_files=1, remaining_files=0, root='/tmp'))
            store.reconcile([entry()], [conv])
            tid = store.snapshot()['tasks'][0]['id']
            store.db.close()
            requests = [{'id':1, 'method':'finish_workday'},
                        {'id':2, 'method':'rename_task', 'entity_id':tid, 'title':'我的整项目标'},
                        {'id':3, 'method':'snapshot'}]
            result = subprocess.run([sys.executable, str(SERVICE), '--data-dir', folder, 'serve'],
                                    input='\n'.join(json.dumps(r) for r in requests) + '\n',
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            responses = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertTrue(all('error' not in r for r in responses), responses)
            saved = responses[1]['result']
            self.assertEqual(saved['task_id'], tid)
            self.assertEqual(saved['snapshot']['tasks'][0]['title_override'], '我的整项目标')
            self.assertTrue(responses[2]['result']['schedule']['off_duty'])
            self.assertFalse(responses[2]['result']['sync']['running'])
            store = Store(folder)
            self.assertEqual(store.snapshot()['tasks'][0]['title'], '我的整项目标')
            store.db.close()


if __name__ == '__main__':
    unittest.main()
