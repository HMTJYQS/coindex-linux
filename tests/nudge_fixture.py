"""Isolated desktop broker for protocol and native UI checks; never real conversations."""
import json
import os
import pathlib
import socket
import struct
import threading
import time


class DesktopBroker:
    def __init__(self, folder, phase="idle", fail_write=False):
        self.path = pathlib.Path(folder)/"ipc"/"ipc.sock"
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.path)); os.chmod(self.path, 0o600)
        self.server.listen(8); self.server.settimeout(0.2)
        self.phase, self.fail_write = phase, fail_write
        self.messages, self.clients = [], []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True); self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try: client, _ = self.server.accept()
            except socket.timeout: continue
            except OSError: break
            self.clients.append(client)
            threading.Thread(target=self.handle, args=(client,), daemon=True).start()

    def handle(self, client):
        def exact(count):
            data = bytearray()
            while len(data)<count:
                chunk = client.recv(count-len(data))
                if not chunk: raise EOFError()
                data.extend(chunk)
            return data
        def send(value):
            data = json.dumps(value).encode(); frame = struct.pack('<I',len(data))+data
            # Exercise framing across multiple reads.
            client.sendall(frame[:3]); client.sendall(frame[3:])
        try:
            while True:
                value = json.loads(exact(struct.unpack('<I',exact(4))[0])); self.messages.append(value)
                method, p = value.get('method'), value.get('params') or {}
                if value['type']=='broadcast':
                    if p.get('following'):
                        base={'type':'broadcast','method':'thread-stream-state-changed','version':11,'sourceClientId':'owner','params':{'hostId':'local','conversationId':p['conversationId'],'change':{'type':'snapshot','conversationState':{'threadRuntimeStatus':{'type':self.phase}}}}}
                        wrong=dict(base,sourceClientId='another-owner');send(wrong);send(base)
                    continue
                response={'type':'response','requestId':value['requestId'],'resultType':'success','handledByClientId':'client' if method=='initialize' else 'owner'}
                if method.startswith('thread-follower-'):
                    if self.fail_write: client.close(); return
                    response['result']={'result':{'turnId':'running-turn'} if method.endswith('steer-turn') else {'turn':{'id':'new-turn'}}}
                # An unrelated response cannot confirm the submitted request.
                send(dict(response,requestId='unrelated'));send(response)
        except (EOFError, OSError): pass
        finally:
            client.close()

    def close(self):
        self.stop.set();self.server.close()
        for c in self.clients:
            try:c.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            c.close()
        self.thread.join(timeout=1)


if __name__ == '__main__':
    import signal, sys
    broker=DesktopBroker(sys.argv[1])
    print('ready',flush=True)
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
    try:
        while True:
            time.sleep(0.1)
            pathlib.Path(sys.argv[2]).write_text(json.dumps(broker.messages,ensure_ascii=False))
    finally:broker.close()
