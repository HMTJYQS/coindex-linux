import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
from analyzer import COPY_VERSION
from collector import clean_user, parse_rollout
from store import Store
from test_backend import conversation, entry, task


class GoalTitleLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.conv = conversation()
        self.ingest()
        self.goal = dict(task('upload-speed'), title='降低图片上传等待时间', detail='比较两组上传方案的响应时间')
        self.apply(self.goal)
        self.original = self.store.snapshot()['tasks'][0]

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def ingest(self, states=None):
        self.store.ingest(dict(host='mac', files={}, conversations=[self.conv], total_files=1,
                               remaining_files=0, root='/tmp', archive_states=states or {}))

    def apply(self, item):
        self.store.reconcile([entry(tasks=[item])], [self.conv])

    def advance(self):
        self.conv['messages'].append(dict(role='assistant', text='实验训练已完成；指标尚未核对。', at=3))
        self.conv.update(fingerprint='v2', updated_at=self.conv['updated_at'] + 1)
        self.ingest()
        return dict(self.goal, title='核对 D2 训练指标', detail='读取评测日志', kind='review',
                    related_task_ids=[self.original['id']], evidence='实验训练已完成', evidence_index=2,
                    progress='训练已完成；指标尚未核对', next_action='对比上传延迟和失败率')

    def test_stage_change_keeps_goal_title_and_updates_progress(self):
        self.apply(self.advance())
        row = self.store.snapshot()['tasks'][0]
        self.assertEqual(row['id'], self.original['id'])
        self.assertEqual(row['title'], self.goal['title'])
        self.assertEqual(row['detail'], self.goal['detail'])
        self.assertEqual(row['progress'], '训练已完成；指标尚未核对')
        self.assertEqual(row['next_action'], '对比上传延迟和失败率')

    def test_new_occurrence_of_same_goal_reuses_goal_title_without_reopening_history(self):
        self.store.act('complete', self.original['id'])
        self.apply(self.advance())
        rows = self.store.snapshot()['tasks']
        live = next(r for r in rows if r['status'] == 'open')
        self.assertNotEqual(live['id'], self.original['id'])
        self.assertEqual(live['title'], self.goal['title'])
        self.assertEqual(next(r for r in rows if r['id'] == self.original['id'])['status'], 'done')

    def test_legacy_stage_title_can_be_upgraded_once_during_normal_analysis(self):
        with self.store.db:
            self.store.db.execute('UPDATE tasks SET title=?,copy_version=? WHERE id=?',
                                  ('等待实验训练结果', COPY_VERSION - 1, self.original['id']))
        self.apply(dict(self.advance(), title=self.goal['title'], detail=self.goal['detail']))
        self.assertEqual(self.store.snapshot()['tasks'][0]['title'], self.goal['title'])
        self.assertEqual(self.store.snapshot()['tasks'][0]['copy_version'], COPY_VERSION)

    def test_title_migration_keeps_stage_identity_acknowledgement_and_reminder(self):
        self.store.act('snooze', self.original['id'], 60)
        with self.store.db:
            self.store.db.execute('UPDATE tasks SET copy_version=? WHERE id=?', (COPY_VERSION - 1, self.original['id']))
        originals = self.store.copy_pending()
        result = dict(id=self.original['id'], title='改善图片上传响应时间', detail=self.goal['detail'],
                      progress=originals[0]['progress'], next_action=originals[0]['next_action'])
        before = dict(self.store.db.execute('SELECT * FROM tasks WHERE id=?', (self.original['id'],)).fetchone())
        self.assertEqual(self.store.apply_copy([result], originals), 1)
        after = dict(self.store.db.execute('SELECT * FROM tasks WHERE id=?', (self.original['id'],)).fetchone())
        for k in before:
            if k not in ('title', 'detail', 'copy_version'):
                self.assertEqual(after[k], before[k], k)
        self.assertEqual(self.store.apply_copy([dict(result, title='旧的阶段措辞')], originals), 0)
        self.assertEqual(self.store.copy_pending(), [])
        self.apply(self.advance())
        self.assertEqual(self.store.snapshot()['tasks'][0]['title'], result['title'])

    def test_migration_cannot_touch_manual_completed_or_archived_tasks(self):
        manual = self.store.save_manual('用户自己的标题')
        with self.store.db:
            self.store.db.execute('UPDATE tasks SET copy_version=?', (COPY_VERSION - 1,))
        self.assertEqual([t['id'] for t in self.store.copy_pending()], [self.original['id']])
        originals = self.store.copy_pending()
        result = dict(id=self.original['id'], title=self.goal['title'], detail=self.goal['detail'],
                      progress=originals[0]['progress'], next_action=originals[0]['next_action'])
        self.store.act('complete', self.original['id'])
        self.assertEqual(self.store.apply_copy([result], originals), 0)
        self.assertEqual(self.store.copy_pending(), [])
        self.store.act('reopen', self.original['id'])
        self.ingest({self.conv['thread_id']: True})
        self.assertEqual(self.store.copy_pending(), [])
        self.assertEqual(self.store.apply_copy([result], originals), 0)
        self.assertEqual(next(t['title'] for t in self.store.snapshot()['tasks'] if t['id'] == manual), '用户自己的标题')


class GoalContextTests(unittest.TestCase):
    def test_injected_setup_is_removed_but_following_real_request_is_kept(self):
        setup = ('<recommended_plugins>插件清单</recommended_plugins>\n# AGENTS.md instructions\n'
                 '<INSTRUCTIONS>仓库规范，不是工作目标。</INSTRUCTIONS>\n'
                 '<environment_context>环境信息</environment_context>')
        self.assertEqual(clean_user(setup), '')
        self.assertEqual(clean_user(setup + '\n降低图片上传等待时间'), '降低图片上传等待时间')
        self.assertEqual(clean_user('请修改 AGENTS.md instructions 中的测试命令'), '请修改 AGENTS.md instructions 中的测试命令')

    def test_long_conversation_keeps_real_initial_goal_instead_of_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            p = pathlib.Path(folder) / 'rollout.jsonl'
            rows = [{'type': 'session_meta', 'payload': {'id': 'goal-context'}}]
            messages = ['# AGENTS.md instructions\n<INSTRUCTIONS>规范</INSTRUCTIONS>',
                        '降低图片上传等待时间'] + ['等待第 %d 次实验结果' % n for n in range(24)]
            for n, text in enumerate(messages):
                rows.append({'timestamp': '2026-10-10T01:00:%02dZ' % n, 'type': 'response_item',
                             'payload': {'type': 'message', 'role': 'user', 'content': [{'text': text}]}})
            p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
            c = parse_rollout(p, 'mac')
            self.assertEqual(c['messages'][0]['text'], '降低图片上传等待时间')
            self.assertFalse(any('INSTRUCTIONS' in m['text'] for m in c['messages']))
            self.assertIn('等待第 23 次实验结果', [m['text'] for m in c['messages']])


if __name__ == '__main__':
    unittest.main()
