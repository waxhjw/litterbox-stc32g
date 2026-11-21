"""只适用于已写入MOTOR003的板：查询状态或停止，无串口启动命令。"""
import argparse
from datetime import datetime
import sys
import time
import serial
from project import ROOT, CONFIG, load_json, ports, save_json
sys.stdout.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['status','stop'])
args = parser.parse_args()
port = ports(load_json(CONFIG))
link = serial.Serial(port=None, baudrate=115200, timeout=0.15, write_timeout=1)
link.dtr = False
link.rts = False
link.port = port
responses = bytearray()
with link:
    # 先查询本轮测试固件标识，确认后停止命令才发送；不会通过串口启动电机。
    link.write(b'?')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        responses.extend(link.read(512))
        if b'MOTOR003 ' in responses and b'\n' in responses:
            break
    identified = b'MOTOR003 ' in responses
    if identified and args.action == 'stop':
        link.write(b'!')
        responses.extend(link.read(512))
        time.sleep(0.1)
        link.write(b'?')
        responses.extend(link.read(512))
text = responses.decode('ascii', errors='replace')
report = {'port':port, 'action':args.action, 'identified':identified,
          'response':text, 'motor_motion_verified':False}
path = ROOT/'build'/('MOTOR003-'+args.action+'-'+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.json')
save_json(path,report)
print(text, flush=True)
print('REPORT:',path)
if not identified:
    raise SystemExit('FAIL: 未收到MOTOR003身份，状态未知；未发送停止命令。')
if args.action == 'stop' and b'MOTOR003 STOP ' not in responses:
    raise SystemExit('FAIL: 未确认固件报告停止；物理状态待核对。')
print('PASS: 已收到固件状态；日志不能代替电机实际观察。')
