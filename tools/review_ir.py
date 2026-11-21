"""离线核对本轮红外接口；不打开串口、不改固件。"""
import json
import sys
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    manual = fitz.open(ROOT/'docs/reference/stc32g-cn.pdf')
    for argument in sys.argv[1:]:
        number = int(argument)
        page = manual[number-1]
        print('MANUAL PAGE', number, page.get_text())
        (ROOT/'build'/('manual-page-'+str(number)+'.txt')).write_text(page.get_text(), encoding='utf-8')
        page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(str(ROOT/'build'/('manual-page-'+str(number)+'.png')))
    raise SystemExit(0)
doc = fitz.open(ROOT/'docs/reference/2-猫砂盆控制原理图.pdf')
for i, page in enumerate(doc):
    text = page.get_text()
    if any(word in text for word in ('NEC', '红外', 'T+', '38K')):
        print('SCHEMATIC PAGE', i+1, text)
cam = json.loads((ROOT/'build/cam-review/connectivity.json').read_text())
components = cam['components']
for name, pads in components.items():
    if name in ('CN4', 'CN8', 'Q10'):
        print('COMPONENT', name, pads)
print('MCU_PINS', {p: cam['mcu_pins'][p] for p in ('8', '11')})
for target in ('CN4', 'CN8', 'Q10'):
    nets = {tuple(n) for pad in components[target].values() for n in pad['net'] if '17' not in pad['mcu_pins']}
    for name, pads in components.items():
        if name.startswith('R') and any(nets.intersection(map(tuple, p['net'])) for p in pads.values()):
            print('SERIES', target, name, pads)
placement = fitz.open(ROOT/'docs/reference/贴片图-LQ-WiFi_红外20260921更新贴片图.pdf')
sys.path.insert(0, str(ROOT/'.tools/bom-python'))
import xlrd
bom = xlrd.open_workbook(str(ROOT/'docs/reference/更新-WIFI款主板-红外猫砂盆-BOM表261017.xls'))
for sheet in bom.sheets():
    for row in sheet.get_rows():
        values = [str(c.value) for c in row]
        if any(target in ' '.join(values) for target in ('Q10', 'R41', 'R42', 'R43', 'CN4', 'CN8')):
            print('BOM', sheet.name, values)
manual = fitz.open(ROOT/'docs/reference/stc32g-cn.pdf')
index = []
for i in range(len(manual)):
    text = manual[i].get_text()
    if ('LQFP48' in text or 'LQFP-48' in text) and 'P1.4' in text:
        print('MCU PINOUT PAGE', i+1)
    if 'PWMA' in text and ('寄存器' in text or '38' in text or 'PWM4' in text):
        index.append('PAGE '+str(i+1)+'\n'+text)
(ROOT/'build/ir-pwm-manual.txt').write_text('\n'.join(index), encoding='utf-8')
for number in list(range(565, 580)) + [1041, 1043, 1063, 1066, 1071]:
    (ROOT/'build'/('manual-page-'+str(number)+'.txt')).write_text(manual[number-1].get_text(), encoding='utf-8')
