"""主板断开、DAP U_TX与U_RX已短接时，观察静默和逐字节收发。"""
import sys
import time
import serial
from project import ROOT, CONFIG, load_json, ports, save_json

sys.stdout.reconfigure(encoding='utf-8')
port = ports(load_json(CONFIG))
report = {'port':port, 'target_connected':False, 'tests':[]}
for baud in (2400,115200):
    with serial.Serial(port, baudrate=baud, bytesize=8, parity='N', stopbits=1,
                       timeout=0.5,write_timeout=2) as link:
        time.sleep(0.5)
        link.reset_input_buffer()
        quiet = link.read(512)
        print('8N1',baud,'QUIET:',quiet.hex(' ') or '(empty)',flush=True)
        rows=[]
        for value in (0x55,0xAA,0x00,0xFF,0x46,0xB9):
            link.reset_input_buffer()
            link.write(bytes([value]))
            link.flush()
            got=link.read(16)
            row={'tx':f'{value:02x}','rx':got.hex(' '),'pass':got==bytes([value])}
            rows.append(row)
            print('TX:',row['tx'],'RX:',row['rx'] or '(empty)','PASS:',row['pass'],flush=True)
        report['tests'].append({'baud':baud,'mode':'8N1','host_settings':link.get_settings(),
                                'quiet_hex':quiet.hex(' '),'rows':rows})
save_json(ROOT/'build/UART-loopback-detail-20261110.json',report)
raise SystemExit(0 if all(row['pass'] for test in report['tests'] for row in test['rows']) else 1)
