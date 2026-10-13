import datetime
import json
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'backend'))
from store import Store
from schedule import finish_workday
from service import sync
from test_backend import conversation,entry

SERVICE=pathlib.Path(__file__).resolve().parents[1]/'backend/service.py'


class WorkdayProtocolTests(unittest.TestCase):
    def test_direct_sync_cannot_collect_or_analyze_while_off_duty(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);settings=store.settings();finish_workday(store)
            store.db.close()
            with patch('service.collect_host') as collect,patch('service.analyze') as analyze:
                self.assertFalse(sync(folder,force=True)['accepted'])
                collect.assert_not_called();analyze.assert_not_called()
            store=Store(folder)
            self.assertEqual(store.settings(),settings);self.assertTrue(store.meta('off_duty_until')>time.time())
            store.db.close()

    def test_stdio_blocks_manual_forced_and_automatic_updates_and_persists_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);data=root/'state'
            store=Store(data);store.save_settings({'workdays_only':False,'work_hours_enabled':True,'work_start_minutes':600,'work_end_minutes':1380,'enabled_hosts':['mac']})
            manual=store.save_manual('保留手动待办');original=store.snapshot()['tasks'];store.db.close()
            env=dict(os.environ,CODEX_HOME=str(root/'empty-codex'))
            requests=[{'id':1,'method':'finish_workday'},{'id':2,'method':'sync'},
                      {'id':3,'method':'sync','force':True},{'id':4,'method':'sync','automatic':True},{'id':5,'method':'snapshot'}]
            result=subprocess.run([sys.executable,str(SERVICE),'--data-dir',str(data),'serve'],input='\n'.join(json.dumps(x) for x in requests)+'\n',env=env,text=True,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            output=[json.loads(x)['result'] for x in result.stdout.splitlines()]
            self.assertTrue(output[0]['schedule']['off_duty'])
            for item in output[1:4]:self.assertFalse(item['accepted'])
            self.assertEqual(output[-1]['tasks'],original)
            self.assertTrue(output[-1]['settings']['automatic'])
            until=output[-1]['schedule']['off_duty_until']
            result=subprocess.run([sys.executable,str(SERVICE),'--data-dir',str(data),'serve'],input=json.dumps({'id':1,'method':'snapshot'})+'\n'+json.dumps({'id':2,'method':'resume_workday'})+'\n',env=env,text=True,capture_output=True,timeout=10)
            output=[json.loads(x)['result'] for x in result.stdout.splitlines()]
            self.assertEqual(output[0]['schedule']['off_duty_until'],until)
            self.assertFalse(output[1]['schedule']['off_duty'])
            self.assertTrue(output[1]['settings']['automatic'])

    def test_off_duty_stops_owned_model_child_and_preserves_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);data=root/'state';source=root/'codex/sessions';source.mkdir(parents=True)
            stamp=datetime.datetime.fromtimestamp(time.time()-120,datetime.timezone.utc).isoformat()
            lines=[dict(type='session_meta',timestamp=stamp,payload=dict(id='workday-stop',source='vscode',cwd='/work')),
                   dict(type='response_item',timestamp=stamp,payload=dict(type='message',role='user',content=[dict(text='发布模型')]))]
            (source/'rollout.jsonl').write_text('\n'.join(json.dumps(x) for x in lines)+'\n')
            pid_file=root/'model-pid';stub=root/'fake-codex'
            stub.write_text('#!'+sys.executable+'\nimport os,pathlib,signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\npathlib.Path(os.environ["TEST_MODEL_PID"]).write_text(str(os.getpid()))\ntime.sleep(60)\n');stub.chmod(0o700)
            store=Store(data);store.save_settings({'workdays_only':False,'enabled_hosts':['mac']})
            conv=conversation();store.ingest(dict(host='mac',files={},conversations=[conv],total_files=1,remaining_files=0,root='/tmp'));store.reconcile([entry()],[conv])
            original=store.snapshot()['tasks'];store.db.close()
            env=dict(os.environ,CODEX_HOME=str(root/'codex'),CODEX_TODO_CODEX=str(stub),TEST_MODEL_PID=str(pid_file))
            process=subprocess.Popen([sys.executable,str(SERVICE),'--data-dir',str(data),'serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
            def rpc(method):
                process.stdin.write(json.dumps({'id':1,'method':method})+'\n');process.stdin.flush()
                self.assertTrue(select.select([process.stdout],[],[],4)[0]);response=json.loads(process.stdout.readline());self.assertNotIn('error',response);return response['result']
            try:
                self.assertTrue(rpc('sync')['accepted'])
                deadline=time.monotonic()+8
                while not pid_file.exists() and time.monotonic()<deadline:time.sleep(0.05)
                self.assertTrue(pid_file.exists());pid=int(pid_file.read_text())
                result=rpc('finish_workday')
                self.assertFalse(result['sync']['running']);self.assertTrue(result['schedule']['off_duty'])
                self.assertTrue(result['settings']['automatic']);self.assertEqual(result['tasks'],original)
                deadline=time.monotonic()+3
                alive=True
                while time.monotonic()<deadline:
                    try:os.kill(pid,0)
                    except ProcessLookupError:alive=False;break
                    time.sleep(0.05)
                self.assertFalse(alive,'model child outlived finish_workday')
                self.assertFalse(rpc('sync')['accepted'])
            finally:
                process.stdin.close();process.wait(timeout=8);process.stdout.close();process.stderr.close()


if __name__=='__main__':unittest.main()
