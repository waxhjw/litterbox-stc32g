"""仅在DAP与主板完全断开、U_TX与U_RX短接时运行。"""
import json
import sys
import time
from pathlib import Path
import serial
from datetime import datetime
from project import ROOT, CONFIG, load_json, ports, save_json

sys.stdout.reconfigure(encoding='utf-8')
port = ports(load_json(CONFIG))
pattern = bytes([0x00,0xFF,0x7F,0x80,0x46,0xB9,0x6A,0x55,0xAA,0xFE,0x16])
report = {'test':'DAP U_TX to U_RX external loopback','port':port,'baud':2400,
          'target_connected':False,'results':[]}
for parity, label in [(serial.PARITY_NONE,'8N1'),(serial.PARITY_EVEN,'8E1')]:
    with serial.Serial(port, baudrate=2400, bytesize=8, parity=parity,
                       stopbits=1, timeout=2, write_timeout=2) as link:
        time.sleep(0.2)
        link.reset_input_buffer()
        link.write(pattern)
        link.flush()
        received = link.read(len(pattern))
        passed = received == pattern
        item = {'mode':label,'sent':pattern.hex(' '),'received':received.hex(' '),
                'pass':passed,'missing_bytes':len(pattern)-len(received)}
        report['results'].append(item)
        print(label,'PASS' if passed else 'FAIL','TX:',item['sent'],'RX:',item['received'],flush=True)
report_path = ROOT/'build'/('UART-loopback-'+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.json')
save_json(report_path,report)
print('REPORT:',report_path)
print('说明：同一UART回环通过不单独证明引脚上的校验位波形正确，也不证明目标ISP可下载。')
raise SystemExit(0 if all(row['pass'] for row in report['results']) else 1)
