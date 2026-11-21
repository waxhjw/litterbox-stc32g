"""被动串口采集：只接收，不发送命令，不调用ISP或复位。"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import serial
from project import ROOT, CONFIG, load_json, ports, save_json

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
parser=argparse.ArgumentParser()
parser.add_argument('--seconds',type=float,default=20)
args=parser.parse_args()
if not 1 <= args.seconds <= 60:
    raise SystemExit('采集时长必须为1至60秒')
stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
folder=ROOT/'evidence'/('uart-rx-'+stamp)
port=ports(load_json(CONFIG))
folder.mkdir(parents=True,exist_ok=False)

class ReceiveOnlySerial(serial.Serial):
    def write(self,*args,**kwargs):
        raise RuntimeError('被动采集禁止发送串口数据')

link=ReceiveOnlySerial(port=None,baudrate=115200,bytesize=8,parity='N',
                      stopbits=1,timeout=0.2)
link.dtr=False
link.rts=False
link.port=port
received=bytearray()
chunks=[]
start=time.monotonic()
print('CAPTURE:',port,'115200 8N1',args.seconds,'seconds; TX disabled',flush=True)
with link:
    while time.monotonic()-start < args.seconds:
        data=link.read(min(8192,max(1,link.in_waiting)))
        if data:
            chunks.append({'elapsed_ms':round((time.monotonic()-start)*1000),
                           'offset':len(received),'length':len(data)})
            received.extend(data)
        if len(received)>8*1024*1024:
            raise RuntimeError('超出本次被动采集大小上限')
raw=bytes(received)
try:
    decoded=raw.decode('utf-8')
    encoding='utf-8'
except UnicodeDecodeError:
    decoded=raw.decode('gb18030',errors='replace')
    encoding='gb18030 with replacement'
suspect=re.compile(r'(?i)(?:password|passwd|\bpwd\b|\bpsk\b|token|secret|auth[_ -]?key|local[_ -]?key|\bssid\b)\s*[:=]')
redactions=0
lines=[]
for line in decoded.splitlines():
    if suspect.search(line):
        redactions+=1
        lines.append('[redacted: possible credential line]')
    else:
        lines.append(line)
text='\n'.join(lines)
(folder/'received.txt').write_text(text,encoding='utf-8')
if redactions==0:
    (folder/'received.bin').write_bytes(raw)
save_json(folder/'capture.json',{'port':port,'settings':'115200 8N1',
          'requested_seconds':args.seconds,'received_bytes':len(raw),'transmitted_bytes':0,
          'target_reset_requested':False,'encoding':encoding,'redacted_lines':redactions,
          'raw_saved':redactions==0,'raw_sha256':hashlib.sha256(raw).hexdigest(),
          'adapter':load_json(CONFIG).get('serial_adapter', 'USB-TTL'),
          'supply':'not measured by software; confirm externally powered board and adapter VCC disconnected',
          'chunks':chunks})
print('SAVED:',folder,'RX_BYTES:',len(raw),'REDACTED_LINES:',redactions)
print('LOG_PREVIEW:')
print(text[:9000])
