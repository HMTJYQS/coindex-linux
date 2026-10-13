"""JSON RPC over the existing remote Codex app-server proxy, without a new engine."""
import base64
import hashlib
import json
import os
import select
import shlex
import struct
import subprocess
import time
from connections import normalize_remote, ssh_command

LOCATOR = """import os,pathlib,shutil,json
home=pathlib.Path.home()
settings=json.loads(__SETTINGS__)
if settings.get('codex_home'): os.environ['CODEX_HOME']=str(pathlib.Path(settings['codex_home']).expanduser())
candidates=[shutil.which('codex'),str(home/'.local/bin/codex'),str(home/'.codex/bin/codex'),'/usr/local/bin/codex','/usr/bin/codex']+[str(p) for p in sorted((home/'.nvm/versions/node').glob('*/bin/codex'),reverse=True)]
if settings.get('codex_cli'): candidates=[str(pathlib.Path(settings['codex_cli']).expanduser())]
path=next((p for p in candidates if p and os.path.isfile(p) and os.access(p,os.X_OK)),None)
if not path: raise SystemExit('Codex CLI not found')
os.execv(path,[path,'app-server','proxy'])
"""


class RemoteRPC:
    def __init__(self, host, process_factory=subprocess.Popen, profile=None):
        self.profile=normalize_remote(profile or {'id':host})
        self.host=host
        self.process_factory=process_factory
        self.process=None
        self.buffer=bytearray()
        self.sequence=0
        self.events=[]
        self.requests={}
        self.on_attention=None
        self.thread_id=None

    def connect(self):
        locator=LOCATOR.replace('__SETTINGS__',repr(json.dumps(self.profile)))
        command=ssh_command(self.profile)+[shlex.quote(self.profile['python'] or 'python3')+' -c '+shlex.quote(locator)]
        self.process=self.process_factory(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        nonce=base64.b64encode(os.urandom(16)).decode()
        request=('GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+nonce+'\r\nSec-WebSocket-Version: 13\r\n\r\n').encode()
        self.write(request)
        deadline=time.monotonic()+12
        while b'\r\n\r\n' not in self.buffer:
            self.fill(deadline)
            if len(self.buffer)>16384: raise ValueError('Codex 连接响应异常')
        head,rest=self.buffer.split(b'\r\n\r\n',1);self.buffer=bytearray(rest)
        headers={}
        lines=head.decode('ascii').split('\r\n')
        for line in lines[1:]:
            if ':' in line:
                k,v=line.split(':',1);headers[k.lower()]=v.strip()
        expected=base64.b64encode(hashlib.sha1((nonce+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if not lines[0].startswith('HTTP/1.1 101 ') or headers.get('sec-websocket-accept')!=expected:
            raise ValueError('Codex 共享对话服务未就绪')
        self.call('initialize',{'clientInfo':{'name':'codex_todo','title':'coindex','version':'1.7.0'},'capabilities':{'experimentalApi':True,'requestAttestation':False}})
        self.send({'method':'initialized','params':{}})
        return self

    def write(self, data):
        self.process.stdin.write(data);self.process.stdin.flush()

    def fill(self, deadline):
        timeout=max(0,deadline-time.monotonic())
        if not select.select([self.process.stdout],[],[],timeout)[0]: raise TimeoutError('Codex 响应超时')
        data=os.read(self.process.stdout.fileno(),65536)
        if not data: raise ConnectionError('Codex 对话连接已关闭')
        self.buffer.extend(data)

    def exact(self, count, deadline):
        while len(self.buffer)<count:self.fill(deadline)
        result=bytes(self.buffer[:count]);del self.buffer[:count];return result

    def frame(self, data, opcode=1):
        size=len(data);head=bytearray([0x80|opcode])
        if size<126:head.append(0x80|size)
        elif size<65536:head.extend(struct.pack('!BH',0x80|126,size))
        else:head.extend(struct.pack('!BQ',0x80|127,size))
        mask=os.urandom(4);head.extend(mask)
        self.write(bytes(head)+bytes(value^mask[i%4] for i,value in enumerate(data)))

    def send(self, value):self.frame(json.dumps(value,ensure_ascii=False).encode())

    def observe(self, message):
        method=message.get('method')
        if method=='serverRequest/resolved':
            self.requests.pop(str((message.get('params') or {}).get('requestId')),None)
        elif method and 'id' in message:
            params=message.get('params') or {}
            if self.thread_id and params.get('threadId') not in (None,self.thread_id):return
            self.requests[str(message['id'])]=params
        else:return
        if self.on_attention:
            self.on_attention('原对话等待授权或回答，请打开 Codex 处理' if self.requests else '')

    def read(self, timeout=15):
        deadline=time.monotonic()+timeout
        chunks=bytearray();started=False
        while True:
            first,second=self.exact(2,deadline)
            final=bool(first&0x80);opcode=first&0x0f;size=second&0x7f
            if first&0x70 or second&0x80:raise ValueError('Codex 帧格式错误')
            if size==126:size=struct.unpack('!H',self.exact(2,deadline))[0]
            elif size==127:size=struct.unpack('!Q',self.exact(8,deadline))[0]
            if size+len(chunks)>32*1024*1024:raise ValueError('Codex 响应过大')
            data=self.exact(size,deadline)
            if opcode==8:raise ConnectionError('Codex 对话连接已关闭')
            if opcode==9:self.frame(data,10);continue
            if opcode==10:continue
            if opcode in (1,2):
                if started:raise ValueError('Codex 分片格式错误')
                started=True
            elif opcode!=0 or not started:raise ValueError('Codex 帧类型错误')
            chunks.extend(data)
            if final:return json.loads(chunks)

    def call(self, method, params, timeout=15):
        self.sequence+=1;request_id=self.sequence
        self.send({'id':request_id,'method':method,'params':params})
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            message=self.read(max(0.01,deadline-time.monotonic()))
            self.observe(message)
            if message.get('id')==request_id and 'method' not in message:
                if 'error' in message:raise RuntimeError(message['error'].get('message','Codex 拒绝了请求'))
                return message.get('result')
            if message.get('method')=='turn/completed':self.events.append(message)
        raise TimeoutError('Codex 响应超时')

    def follow(self, thread_id, turn_id):
        def completed(message):
            params=message.get('params') or {}
            return message.get('method')=='turn/completed' and params.get('threadId')==thread_id and (params.get('turn') or {}).get('id')==turn_id
        if any(completed(e) for e in self.events):return
        # Keep the requesting connection alive for approvals/desktop observation.
        # All requests are left for the user's normal Codex approval UI.
        while True:
            try: message=self.read(timeout=30)
            except TimeoutError:continue
            self.observe(message)
            if completed(message):
                if self.on_attention:self.on_attention('')
                return

    def close(self):
        if self.process:
            try:self.process.stdin.close()
            except OSError:pass
            self.process.terminate()
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=1)
            self.process.stdout.close()
            self.process=None
