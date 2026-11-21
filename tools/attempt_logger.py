"""保存原始下载输出，避免Windows PowerShell将stderr当作脚本异常。"""
from datetime import datetime
from pathlib import Path
import codecs
import os
import subprocess
import sys
import time
from diagnostic import APP_PROFILES

root = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
profile = 'ISP_TEST001'
if '--profile' in sys.argv:
    index = sys.argv.index('--profile')
    if index + 1 < len(sys.argv):
        profile = sys.argv[index + 1]
if profile not in ('ISP_TEST001', 'WIFI001', 'WIFI002', 'MOTOR001', 'MOTOR002', 'MOTOR003', 'IR002', 'IR003', 'IR004', 'IR005', 'IR006', 'IR007', 'IR008', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017') + APP_PROFILES:
    raise SystemExit('Unknown diagnostic profile')
prefix = 'ISP_TEST001-3v3-20261110-' if profile == 'ISP_TEST001' else profile+'-'
log = root/'build'/(prefix+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.log')
env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
def run_download(output):
    child = subprocess.Popen([sys.executable, '-u', str(root/'tools/diagnostic.py'), 'flash'] + sys.argv[1:],
                             cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # 立即转发已收到的数据，包括没有换行的等待提示。
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    tail = b''
    while True:
        data = child.stdout.read1(4096)
        if not data:
            break
        tail = (tail + data)[-2048:]
        output.write(data)
        output.flush()
        text = decoder.decode(data)
        if text:
            print(text, end='', flush=True)
    return child.wait(), tail


print('LOG:', log, flush=True)
with log.open('wb') as output:
    code, tail = run_download(output)
    if profile in ('IR014', 'IR015', 'IR016', 'IR017', 'WIFI001', 'WIFI002') + APP_PROFILES and code == 1 and b'ClearCommError failed' in tail:
        from project import CONFIG, load_json
        from serial.tools.list_ports import comports

        state_path = root/'build'/f'{profile}-last-attempt.json'
        state = load_json(state_path) if state_path.exists() else {}
        if state.get('stage') == 'connect' and state.get('completed') == []:
            config = load_json(CONFIG)
            # 仅在擦除前且同一 COM 号重新出现时重开一次。
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                adapters = [p.device for p in comports()
                            if (p.vid, p.pid) == (config['usb_vid'], config['usb_pid'])]
                if adapters == [state['port']]:
                    note = '\nREOPEN: same CH340 returned; retrying before erase\n'
                    output.write(note.encode('utf-8'))
                    output.flush()
                    print(note, end='', flush=True)
                    code, _ = run_download(output)
                    break
                time.sleep(0.5)
print('\nEXIT:', code, flush=True)
raise SystemExit(code)
