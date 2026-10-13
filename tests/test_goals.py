import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'backend'))
from analyzer import analyze
from collector import collect
from store import Store
from test_backend import conversation,entry,task

THREAD='00000000-0000-4000-8000-000000000001'


class GoalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.conv=conversation('mac:'+THREAD);self.ingest()
        self.apply(task('train-goal',kind='running'))
        self.original=self.store.snapshot()['tasks'][0]
    def tearDown(self):self.store.db.close();self.tmp.cleanup()
    def ingest(self,states=None):
        self.store.ingest(dict(host='mac',files={},conversations=[self.conv],total_files=1,remaining_files=0,root='/tmp',archive_states=states or {}))
    def apply(self,item,resolved=None):
        self.store.reconcile([entry(self.conv['id'],[item],resolved)],[self.conv])
    def progress(self,text):
        self.conv['messages'].append(dict(role='assistant',text=text,at=max(m['at'] for m in self.conv['messages'])+1))
        self.conv.update(fingerprint=str(uuid.uuid4()),updated_at=self.conv['updated_at']+1);self.ingest()
        return len(self.conv['messages'])-1
    def update(self,kind='review',key='different-action',artifact='new-artifact'):
        index=self.progress('新一阶段已完成，剩余工作尚未闭环。')
        return dict(task(key,kind,artifact),related_task_ids=[self.original['id']],evidence_index=index,
                    evidence=self.conv['messages'][index]['text'],work_index=0,progress='已进入下一阶段；尚未闭环',next_action='推进最先未完成的步骤')
    def test_same_goal_keeps_identity_across_actions_phases_and_artifacts(self):
        self.store.act('snooze',self.original['id'],60)
        for kind in ('wait','continue','decision','review'):
            self.apply(self.update(kind))
            rows=self.store.snapshot()['tasks'];self.assertEqual(len(rows),1)
            row=rows[0];self.assertEqual(row['id'],self.original['id']);self.assertEqual(row['created_at'],self.original['created_at'])
            self.assertEqual(row['kind'],kind);self.assertEqual(row['progress'],'已进入下一阶段；尚未闭环')
            self.assertGreater(row['snoozed_until'],time.time());self.assertEqual(row['goal_key'],'train-goal')
    def test_intermediate_completion_cannot_retire_same_live_goal(self):
        self.apply(self.update(),resolved=['train-goal'])
        self.assertEqual([(r['id'],r['status']) for r in self.store.snapshot()['tasks']],[(self.original['id'],'open')])
    def test_distinct_user_goal_may_have_its_own_active_task(self):
        index=self.progress('用户另一个目标的独立产物已提交。')
        self.conv['messages'][index]['role']='user';self.ingest()
        self.apply(dict(task('separate-goal',artifact='other-artifact'),evidence='独立产物已提交',work_index=index,evidence_index=index))
        self.assertEqual(len(self.store.snapshot()['tasks']),2)
        self.assertEqual({r['goal_key'] for r in self.store.snapshot()['tasks']},{'train-goal','separate-goal'})
    def test_no_active_goal_and_new_progress_create_new_identity_even_same_phase_artifact_and_anchor(self):
        for _ in range(3):
            previous=next(r for r in self.store.snapshot()['tasks'] if r['status']=='open')
            self.store.act('complete',previous['id'])
            index=self.progress('训练目标又有新的进展，仍需核对。')
            item=dict(task('train-goal',kind='running'),related_task_ids=[previous['id']],work_index=0,evidence_index=index,evidence='又有新的进展')
            self.apply(item);current=next(r for r in self.store.snapshot()['tasks'] if r['status']=='open')
            self.assertNotEqual(current['id'],previous['id']);self.assertEqual(current['goal_key'],'train-goal')
            self.apply(item);self.assertEqual(sum(r['status']=='open' for r in self.store.snapshot()['tasks']),1)
        self.assertEqual(len(self.store.snapshot()['tasks']),4)
    def test_completed_without_new_progress_does_not_reappear_under_new_wording(self):
        self.store.act('complete',self.original['id'])
        self.apply(dict(task('new-wording',kind='review'),related_task_ids=[self.original['id']]))
        self.assertEqual(self.store.snapshot()['tasks'][0]['status'],'done');self.assertEqual(len(self.store.snapshot()['tasks']),1)
    def test_completion_during_analysis_keeps_old_boundary_and_creates_only_for_new_progress(self):
        item=self.update()
        self.store.act('complete',self.original['id'])
        self.apply(item)
        self.assertEqual(len(self.store.snapshot()['tasks']),2)
        self.assertEqual(sum(r['status']=='open' for r in self.store.snapshot()['tasks']),1)
    def test_resolved_goal_needs_new_evidence_and_keeps_completed_identity(self):
        self.store.reconcile([entry(self.conv['id'],[],['train-goal'])],[self.conv])
        self.apply(dict(task('train-goal',kind='running'),related_task_ids=[self.original['id']]))
        self.assertEqual(len(self.store.snapshot()['tasks']),1)
        self.assertEqual(self.store.snapshot()['tasks'][0]['status'],'resolved')
        self.apply(self.update());self.assertEqual(len(self.store.snapshot()['tasks']),2)
        self.assertEqual(next(r['status'] for r in self.store.snapshot()['tasks'] if r['id']==self.original['id']),'resolved')
    def test_merge_legacy_steps_preserves_original_snooze_nudge_and_alias(self):
        self.apply(task('legacy-next-step',kind='continue'))
        duplicate=next(r for r in self.store.snapshot()['tasks'] if r['id']!=self.original['id'])
        self.store.act('snooze',duplicate['id'],120)
        action=str(uuid.uuid4());self.store.queue_nudge(duplicate['id'],action);self.store.finish_nudge(action,'sent')
        item=self.update();item['related_task_ids'].append(duplicate['id']);self.apply(item)
        rows=self.store.snapshot()['tasks'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],self.original['id']);self.assertGreater(rows[0]['snoozed_until'],time.time()+7000)
        self.assertEqual(self.store.nudge(action)['task_id'],self.original['id'])
        self.assertFalse(self.store.queue_nudge(duplicate['id'],action)[1])
        self.assertEqual(self.store.nudge_target(duplicate['id'])['id'],self.original['id'])
        self.store.act('complete',duplicate['id']);self.assertEqual(self.store.snapshot()['tasks'][0]['status'],'done')
        self.assertEqual(self.store.db.execute('SELECT status FROM tasks WHERE id=?',(duplicate['id'],)).fetchone()[0],'merged')
    def test_reopening_old_history_cannot_add_a_second_live_goal(self):
        self.store.act('complete',self.original['id']);self.apply(self.update())
        self.store.act('reopen',self.original['id'])
        self.assertEqual(sum(r['status']=='open' for r in self.store.snapshot()['tasks']),1)
        self.assertEqual(next(r['status'] for r in self.store.snapshot()['tasks'] if r['id']==self.original['id']),'done')
    def test_archive_while_model_runs_blocks_reconcile_and_nudge(self):
        item=self.update();self.ingest({THREAD:True});self.apply(item)
        self.assertEqual(self.store.snapshot()['tasks'],[]);self.assertEqual(self.store.eligible(),[])
        with self.assertRaisesRegex(ValueError,'归档'):self.store.nudge_target(self.original['id'])
        self.assertEqual(self.store.db.execute('SELECT progress FROM tasks WHERE id=?',(self.original['id'],)).fetchone()[0],self.original['progress'])
    def test_unarchive_restores_same_active_identity_but_manual_close_stays_closed(self):
        self.ingest({THREAD:True});self.ingest({THREAD:False})
        self.assertEqual(self.store.snapshot()['tasks'][0]['id'],self.original['id'])
        self.ingest({THREAD:True});self.store.act('close_conversation',self.conv['id']);self.ingest({THREAD:False})
        self.assertEqual(self.store.eligible(),[])
        self.assertEqual(self.store.snapshot()['tasks'][0]['status'],'conversation_closed')
    def test_policy_migration_revisits_only_open_non_archived_goals_once(self):
        self.store.put_meta('task_policy_version',1);self.store.db.close();self.store=Store(self.tmp.name)
        self.assertEqual(len(self.store.eligible()),1)
        self.apply(task('train-goal',kind='running'));self.assertEqual(self.store.eligible(),[])
        self.store.db.close();self.store=Store(self.tmp.name);self.assertEqual(self.store.eligible(),[])


class GoalAnalyzerTests(unittest.TestCase):
    def test_model_matches_by_existing_id_and_keeps_goal_key_despite_action_name_drift(self):
        conv=conversation();old=dict(id='original',key='stable-goal',goal_key='stable-goal',status='open',created_at=1)
        item=dict(task('new-phase-name'),related_task_ids=['original'],evidence_index=1)
        with patch('analyzer.generate_json',return_value={'conversations':[entry(tasks=[item])]}) as generate:
            result=analyze([conv],{conv['id']:[old]})
        self.assertEqual(result[0]['tasks'][0]['key'],'stable-goal')
        self.assertIn('"id": "original"',generate.call_args.args[0])
    def test_forged_other_conversation_id_and_split_goal_are_rejected(self):
        conv=conversation();old=dict(id='original',key='stable-goal',status='open')
        for items in ([dict(task(),related_task_ids=['other-thread-task'],evidence_index=1)],
                      [dict(task('phase-a'),related_task_ids=['original'],evidence_index=1),dict(task('phase-b'),related_task_ids=['original'],evidence_index=1)]):
            with patch('analyzer.generate_json',return_value={'conversations':[entry(tasks=items)]}):
                with self.assertRaises(ValueError):analyze([conv],{conv['id']:[old]})


class ArchiveCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);(self.root/'sessions').mkdir();(self.root/'archived_sessions').mkdir()
        self.path=self.root/'sessions'/('rollout-'+THREAD+'.jsonl')
        self.path.write_text(json.dumps({'type':'session_meta','payload':{'id':THREAD,'source':'vscode'}})+'\n'+json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'验证模型'}]}})+'\n')
        self.db=sqlite3.connect(str(self.root/'state_5.sqlite'));self.db.execute('CREATE TABLE threads(id TEXT,title TEXT,archived INTEGER)');self.db.execute('INSERT INTO threads VALUES(?,?,0)',(THREAD,'测试对话'));self.db.commit()
    def tearDown(self):
        if self.db:self.db.close()
        self.tmp.cleanup()
    def test_archive_flag_is_seen_without_content_change_and_skips_rollout_analysis(self):
        first=collect({'root':str(self.root)})
        self.db.execute('UPDATE threads SET archived=1');self.db.commit()
        with patch('collector.parse_rollout') as parse:
            second=collect({'root':str(self.root),'known':first['files']});parse.assert_not_called()
        self.assertTrue(second['archive_states'][THREAD]);self.assertEqual(second['conversations'],[])
    def test_moved_archive_is_excluded_even_outside_history_range_or_without_database(self):
        self.db.close();self.db=None;(self.root/'state_5.sqlite').unlink()
        self.path.rename(self.root/'archived_sessions'/self.path.name)
        old=time.time()-90*86400;os.utime(self.root/'archived_sessions'/self.path.name,(old,old))
        second=collect({'root':str(self.root),'days':7})
        self.assertTrue(second['archive_states'][THREAD]);self.assertEqual(second['total_files'],0);self.assertEqual(second['conversations'],[])
        self.db=sqlite3.connect(':memory:')
    def test_unarchive_status_is_reported_even_when_file_is_unchanged(self):
        first=collect({'root':str(self.root)})
        self.db.execute('UPDATE threads SET archived=1');self.db.commit();collect({'root':str(self.root),'known':first['files']})
        self.db.execute('UPDATE threads SET archived=0');self.db.commit()
        result=collect({'root':str(self.root),'known':first['files']})
        self.assertFalse(result['archive_states'][THREAD]);self.assertEqual(result['conversations'],[])


if __name__=='__main__':unittest.main()
