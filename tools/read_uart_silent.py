"""仅USB连接、DAP全部针脚空置时读取；不发送任何串口数据。"""
import sys
import time
import serial
from project import ROOT, CONFIG, load_json, ports, save_json

sys.stdout.reconfigure(encoding='utf-8')
port = ports(load_json(CONFIG))
with serial.Serial(port, baudrate=115200, bytesize=8, parity='N', stopbits=1,
                   timeout=3) as link:
    time.sleep(0.2)
    link.reset_input_buffer()
    received = link.read(4096)
raw = ROOT/'build/UART-usb-only-20261110.bin'
raw.write_bytes(received)
report = {'mode':'115200 8N1','port':port,'transmitted_bytes':0,
          'received_bytes':len(received),'duration_seconds':3,
          'requested_setup':'USB only; all probe pin headers disconnected',
          'contains_initial_ok':b'initial ok' in received,
          'contains_wifi_state':b'wifi_state' in received,
          'raw_file':str(raw)}
save_json(ROOT/'build/UART-usb-only-20261110.json',report)
print('USB-only silent receive: TX=0 bytes, RX='+str(len(received))+' bytes')
print('Known program log signatures:',report['contains_initial_ok'],report['contains_wifi_state'])
