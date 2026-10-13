"""WebSocket app-server stand-in over pipes, with no machine or model connection."""
import base64, hashlib, json, struct, sys
source, sink = sys.stdin.buffer, sys.stdout.buffer
header = bytearray()
while not header.endswith(b'\r\n\r\n'):header.extend(source.read(1))
nonce = next(line.split(':',1)[1].strip() for line in header.decode().split('\r\n') if line.lower().startswith('sec-websocket-key:'))
accept = base64.b64encode(hashlib.sha1((nonce+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
sink.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n').encode());sink.flush()
def frame(data,opcode=1,final=True):
    size=len(data)
    head=bytes([(0x80 if final else 0)|opcode])
    head+=bytes([size]) if size<126 else struct.pack('!BH',126,size) if size<65536 else struct.pack('!BQ',127,size)
    sink.write(head+data);sink.flush()
def send(value,fragment=False):
    data=json.dumps(value).encode()
    if fragment:
        frame(data[:4],final=False);frame(b'ping',9);frame(data[4:],0)
    else:frame(data)
while True:
    first=source.read(2)
    if not first:break
    opcode=first[0]&15; size=first[1]&127
    assert first[1]&128, 'client must mask frames'
    if size==126:size=struct.unpack('!H',source.read(2))[0]
    elif size==127:size=struct.unpack('!Q',source.read(8))[0]
    mask=source.read(4);data=source.read(size)
    data=bytes(v^mask[i%4] for i,v in enumerate(data))
    if opcode==10:continue
    request=json.loads(data);method=request.get('method')
    if 'id' not in request:continue
    if method=='echo':result=request['params']
    elif method=='turn/start':
        send({'id':'approval-1','method':'item/commandExecution/requestApproval','params':{'threadId':'fixture','turnId':'turn'}})
        result={'turn':{'id':'turn'}}
    else:result={}
    send({'id':request['id'],'result':result},fragment=True)
    if method=='turn/start':
        send({'method':'serverRequest/resolved','params':{'requestId':'approval-1'}})
        send({'method':'turn/completed','params':{'threadId':'another','turn':{'id':'turn'}}})
        send({'method':'turn/completed','params':{'threadId':'fixture','turn':{'id':'turn'}}})
