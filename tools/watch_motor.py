"""MOTOR003专项按键验证：每200ms查询状态，不发送启动或复位命令。"""
from datetime import datetime
import sys
import time
import serial
from project import ROOT, CONFIG, load_json, ports, save_json
sys.stdout.reconfigure(encoding='utf-8')
port = ports(load_json(CONFIG))
link = serial.Serial(port=None, baudrate=115200, timeout=0.08, write_timeout=1)
link.dtr = False
link.rts = False
link.port = port
events = []
buffer = bytearray()
previous = None
start = time.monotonic()
print('WATCH:',port,'60 seconds; status queries only; keep motor disconnected',flush=True)
with link:
    while time.monotonic() - start < 60:
        link.write(b'?')
        buffer.extend(link.read(512))
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer = bytearray(rest)
            text = line.strip().decode('ascii', errors='replace')
            if text.startswith('MOTOR003 ') and text != previous:
                row = {'elapsed_ms':round((time.monotonic()-start)*1000),'status':text}
                events.append(row)
                print(row,flush=True)
                previous = text
        time.sleep(0.12)
path = ROOT/'build'/('MOTOR003-keys-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
save_json(path,{'port':port,'events':events,'query_only':True,
                'motor_physically_disconnected':'user confirmed before download'})
print('REPORT:',path,flush=True)
