import json
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'backend'))
from store import Store
from nudge import DesktopIPC, NudgeError, dispatch, dispatch_remote, run_nudge
from nudge_fixture import DesktopBroker
from remote_rpc import RemoteRPC
from test_backend import conversation, entry, task

THREAD='00000000-0000-4000-8000-000000000001'
TARGET=dict(host='mac',thread_id=THREAD,title='核对训练结果',progress='训练已提交',next_action='检查已有任务结果',artifact='train-123')


class NudgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.conv=conversation('mac:'+THREAD)
        self.store.ingest(dict(host='mac',files={},conversations=[self.conv],total_files=1,remaining_files=0,root='/tmp'))
        self.store.reconcile([entry(self.conv['id'])],[self.conv])
        self.task=self.store.snapshot()['tasks'][0]
        self.action=str(uuid.uuid4())
    def tearDown(self):self.store.db.close();self.tmp.cleanup()
    def queue(self,**kw):return self.store.queue_nudge(self.task['id'],self.action,**kw)
    def test_repeated_request_and_conversation_double_click_send_once(self):
        record,created=self.queue();self.assertTrue(created)
        self.assertEqual(self.queue(),(record,False))
        self.store.reconcile([entry(self.conv['id'],tasks=[task('second')])],[self.conv])
        second=next(t for t in self.store.snapshot()['tasks'] if t['id']!=self.task['id'])
        self.assertEqual(self.store.queue_nudge(second['id'],str(uuid.uuid4())),(record,False))
    def test_nudge_never_completes_task_or_changes_schedule(self):
        original=self.store.snapshot()['tasks'];settings=self.store.settings()
        self.queue();self.store.finish_nudge(self.action,'sending');self.store.finish_nudge(self.action,'sent',result={'turn_id':'turn'})
        self.assertEqual(self.store.snapshot()['tasks'],original)
        self.assertEqual(self.store.settings(),settings)
        self.assertEqual(self.store.snapshot()['nudges'][0]['status'],'sent')
    def test_sent_cooldown_and_acknowledged_status_not_overwritten(self):
        self.queue();self.store.finish_nudge(self.action,'sent')
        self.store.finish_nudge(self.action,'unknown',error='disconnect')
        record,new=self.store.queue_nudge(self.task['id'],str(uuid.uuid4()))
        self.assertFalse(new);self.assertEqual(record['status'],'sent')
        with patch('store.time.time',return_value=time.time()+31):
            self.assertTrue(self.store.queue_nudge(self.task['id'],str(uuid.uuid4()))[1])
    def test_unknown_requires_explicit_checked_retry(self):
        self.queue();self.store.finish_nudge(self.action,'unknown',error='unconfirmed')
        with self.assertRaisesRegex(ValueError,'核对'):self.store.queue_nudge(self.task['id'],str(uuid.uuid4()))
        self.assertTrue(self.store.queue_nudge(self.task['id'],str(uuid.uuid4()),retry_unknown=True)[1])
        self.assertEqual(self.store.nudge(self.action)['status'],'checked')
    def test_failure_can_retry_and_restart_does_not_resend(self):
        self.queue();self.store.finish_nudge(self.action,'failed')
        new=str(uuid.uuid4());self.store.queue_nudge(self.task['id'],new)
        self.store.recover_nudges();self.assertEqual(self.store.nudge(new)['status'],'unknown')
        self.assertEqual(self.store.nudge(self.action)['status'],'failed')
    def test_manual_done_closed_and_invalid_targets_rejected(self):
        manual=self.store.save_manual('买书')
        with self.assertRaisesRegex(ValueError,'没有关联'):self.store.queue_nudge(manual,str(uuid.uuid4()))
        self.store.act('complete',self.task['id'])
        with self.assertRaisesRegex(ValueError,'已结束'):self.queue()
        self.store.act('reopen',self.task['id']);self.store.act('close_conversation',self.conv['id'])
        with self.assertRaisesRegex(ValueError,'已结束'):self.queue()
        self.assertEqual(self.store.snapshot()['nudges'],[])
    def test_completion_before_worker_starts_prevents_dispatch(self):
        self.queue();self.store.act('complete',self.task['id'])
        with patch('nudge.dispatch') as send:run_nudge(self.tmp.name,self.action);send.assert_not_called()
        self.assertEqual(self.store.nudge(self.action)['status'],'failed')
    def test_worker_records_ack_and_unknown_without_retry(self):
        self.queue()
        with patch('nudge.dispatch',side_effect=NudgeError('断开',uncertain=True)) as send:
            run_nudge(self.tmp.name,self.action);run_nudge(self.tmp.name,self.action)
            self.assertEqual(send.call_count,1)
        self.assertEqual(self.store.nudge(self.action)['status'],'unknown')


class DesktopNudgeTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()
    def send(self,phase='idle',fail=False):
        broker=DesktopBroker(self.tmp.name,phase,fail)
        try:
            result=dispatch(TARGET,str(uuid.uuid4()),ipc_factory=lambda:DesktopIPC(broker.path))
            return result,broker.messages
        finally:broker.close()
    def test_idle_uses_owner_and_retains_all_thread_settings(self):
        result,messages=self.send();self.assertEqual(result['delivery'],'started')
        write=next(m for m in messages if m.get('method')=='thread-follower-start-turn')
        self.assertEqual(write['targetClientId'],'owner');self.assertEqual(write['version'],2)
        self.assertEqual(write['params']['turnStart']['context'],{'inheritThreadSettings':True})
        self.assertEqual(set(write['params']['turnStart']['request']),{'threadId','input','clientUserMessageId'})
        prompt=write['params']['turnStart']['request']['input'][0]['text']
        self.assertIn(TARGET['artifact'],prompt);self.assertIn('进度可能已经变化',prompt)
    def test_running_steers_once_and_does_not_start_another_turn(self):
        result,messages=self.send('active');self.assertEqual(result['delivery'],'steered')
        writes=[m for m in messages if m.get('method','').startswith('thread-follower-')]
        self.assertEqual(len(writes),1);self.assertEqual(writes[0]['method'],'thread-follower-steer-turn')
    def test_disconnect_after_write_is_unknown_and_not_resent(self):
        with self.assertRaises(NudgeError) as error:self.send(fail=True)
        self.assertTrue(error.exception.uncertain)
    def test_unverified_runtime_does_not_send(self):
        with self.assertRaises(NudgeError) as error:self.send('notLoaded')
        self.assertFalse(error.exception.uncertain)
    def test_missing_owner_opens_same_identity_only(self):
        fake=type('Fake',(),{})();fake.connect=lambda:fake;fake.close=lambda:None
        fake.owner=iter([None,'owner']).__next__
        fake.state=lambda *a:{'threadRuntimeStatus':{'type':'idle'}}
        fake.request=lambda *a,**kw:{'resultType':'success','result':{'result':{'turn':{'id':'new-turn'}}}}
        calls=[]
        with patch('nudge.time.sleep'):
            # Iterator method takes no arguments, unlike real discovery.
            owner=fake.owner;fake.owner=lambda *a:owner()
            dispatch(TARGET,str(uuid.uuid4()),ipc_factory=lambda:fake,open_thread=lambda *a:calls.append(a))
        self.assertEqual(calls,[(THREAD,'local')])
    def test_unsafe_socket_and_invalid_identity_never_sent(self):
        broker=DesktopBroker(self.tmp.name)
        try:
            os.chmod(broker.path,0o666)
            with self.assertRaisesRegex(NudgeError,'权限'):DesktopIPC(broker.path).connect()
            with self.assertRaisesRegex(NudgeError,'来源'):dispatch(dict(TARGET,thread_id=';rm -rf'),str(uuid.uuid4()))
        finally:broker.close()


class FakeRemote:
    def __init__(self,phase='idle',fail=None):self.phase=phase;self.fail=fail;self.calls=[];self.closed=False;self.followed=False
    def connect(self):return self
    def call(self,method,params):
        self.calls.append((method,params))
        if method==self.fail:raise TimeoutError()
        if method=='thread/read':return {'thread':{'status':{'type':self.phase}}}
        if method=='thread/turns/list':return {'data':[{'id':'running-turn','status':'inProgress'}]}
        if method=='turn/steer':return {'turnId':'running-turn'}
        if method=='turn/start':return {'turn':{'id':'new-turn'}}
        return {}
    def follow(self,*a):self.followed=True
    def close(self):self.closed=True


class RemoteNudgeTests(unittest.TestCase):
    def send(self,rpc,accepted=None):return dispatch_remote(dict(TARGET,host='build-server'),str(uuid.uuid4()),rpc_factory=lambda _:rpc,accepted=accepted)
    def test_idle_turn_inherits_settings_without_overrides(self):
        rpc=FakeRemote();self.assertEqual(self.send(rpc)['delivery'],'started')
        self.assertEqual(rpc.calls[0],('thread/resume',{'threadId':THREAD,'excludeTurns':True}))
        start=rpc.calls[-1];self.assertEqual(start[0],'turn/start')
        self.assertEqual(set(start[1]),{'threadId','input','clientUserMessageId'});self.assertTrue(rpc.closed)
    def test_active_turn_uses_exact_current_turn(self):
        rpc=FakeRemote('active');self.assertEqual(self.send(rpc)['delivery'],'steered')
        self.assertEqual(rpc.calls[-1][1]['expectedTurnId'],'running-turn')
        self.assertNotIn('turn/start',[m for m,p in rpc.calls])
    def test_preflight_failure_is_retryable_but_write_timeout_unknown(self):
        for method,uncertain in [('thread/read',False),('turn/start',True)]:
            rpc=FakeRemote(fail=method)
            with self.assertRaises(NudgeError) as error:self.send(rpc)
            self.assertEqual(error.exception.uncertain,uncertain);self.assertTrue(rpc.closed)
    def test_acknowledge_before_follow_and_disconnect_keeps_sent(self):
        rpc=FakeRemote();accepted=[]
        def follow(*_):
            self.assertEqual(len(accepted),1);raise ConnectionError()
        rpc.follow=follow
        self.assertEqual(self.send(rpc,accepted.append)['delivery'],'started');self.assertTrue(rpc.closed)


class RemoteTransportTests(unittest.TestCase):
    def rpc(self):
        fixture=pathlib.Path(__file__).with_name('proxy_fixture.py')
        def process_factory(command,**kw):
            self.assertEqual(command[0],'/usr/bin/ssh')
            self.assertIn('StrictHostKeyChecking=yes',command)
            self.assertIn('app-server',command[-1]);self.assertIn('proxy',command[-1])
            return subprocess.Popen([sys.executable,str(fixture)],**kw)
        return RemoteRPC('build-server',process_factory)
    def test_handshake_masked_frames_fragmentation_ping_and_large_messages(self):
        rpc=self.rpc()
        try:
            rpc.connect()
            for size in (8,1000,100000):
                value={'text':'中文内容'+('x'*size)}
                self.assertEqual(rpc.call('echo',value),value)
        finally:rpc.close()
    def test_pending_requests_are_visible_but_never_auto_approved(self):
        rpc=self.rpc();attention=[];rpc.on_attention=attention.append
        try:
            rpc.connect();result=rpc.call('turn/start',{'threadId':'fixture'})
            self.assertEqual(result['turn']['id'],'turn')
            self.assertIn('等待授权',attention[0])
            rpc.follow('fixture','turn')
            self.assertEqual(attention[-1],'');self.assertEqual(rpc.requests,{})
        finally:rpc.close()


class NudgeServiceTests(unittest.TestCase):
    setUp=NudgeStoreTests.setUp
    tearDown=NudgeStoreTests.tearDown
    def test_stdio_nudge_ack_and_double_click_with_isolated_broker(self):
        self.store.save_settings({'automatic':False,'workdays_only':False})
        broker=DesktopBroker(self.tmp.name)
        env=dict(os.environ,CODEX_HOME=self.tmp.name)
        service=pathlib.Path(__file__).resolve().parents[1]/'backend/service.py'
        process=subprocess.Popen([sys.executable,str(service),'--data-dir',self.tmp.name,'serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True)
        def rpc(value):
            process.stdin.write(json.dumps(dict(value,id=1))+'\n');process.stdin.flush()
            self.assertTrue(select.select([process.stdout],[],[],5)[0]);return json.loads(process.stdout.readline())
        try:
            first=rpc({'method':'nudge','entity_id':self.task['id'],'action_id':self.action})
            self.assertNotIn('error',first)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                snapshot=rpc({'method':'snapshot'})['result']
                if snapshot['nudges'][0]['status']=='sent':break
                time.sleep(0.05)
            self.assertEqual(snapshot['nudges'][0]['status'],'sent')
            again=rpc({'method':'nudge','entity_id':self.task['id'],'action_id':str(uuid.uuid4())})['result']
            self.assertEqual(len(again['nudges']),1)
            writes=[m for m in broker.messages if m.get('method')=='thread-follower-start-turn']
            self.assertEqual(len(writes),1)
        finally:
            process.stdin.close();process.wait(timeout=5);process.stdout.close();process.stderr.close();broker.close()


if __name__=='__main__':unittest.main()
