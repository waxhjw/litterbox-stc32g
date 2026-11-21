"""IR003/IR004/IR005离线交付绑定检查；不打开串口。"""
import argparse
import re
from project import ROOT, digest, load_json, save_json, inspect_hex

parser=argparse.ArgumentParser()
parser.add_argument('--profile',choices=['IR003','IR004','IR005'],default='IR005')
profile=parser.parse_args().profile
image=ROOT/'output'/('LB_'+profile)/('LB_'+profile+'.hex')
manifest=load_json(image.parent/'manifest.json')
tasks=load_json(ROOT/'.vscode/tasks.json')['tasks']
selected=[t for t in tasks if (' '+profile+':') in t['label']]
assert len(selected)==9
actions=[]
for task in selected:
    args=task['args']
    script='${workspaceFolder}/tools/'+('ir004.ps1' if profile=='IR004' else 'ir005.ps1' if profile=='IR005' else 'ir.ps1')
    assert task['command']=='shnote' and script in args
    actions.append(args[args.index('-Action')+1])
assert set(actions)=={'build','check','flash','status','test38','off','link-low','watch','stop'}
info=inspect_hex(image)
assert info['sha256']==manifest['sha256']
assert digest(ROOT/'diagnostics'/profile/'main.c')==manifest['source_sha256']
for name, sha in manifest['extra_sources'].items():
    assert digest(ROOT/'diagnostics'/profile/name)==sha==digest(image.parent/name)
assert digest(ROOT/'diagnostics/MOTOR003/motor_control.h')==digest(ROOT/'diagnostics'/profile/'motor_control.h')
assert digest(ROOT/'diagnostics/IR003/ir_control.h')==digest(ROOT/'diagnostics'/profile/'ir_control.h')
if profile in ('IR004','IR005'):
    assert manifest['compiler_options']==['OPTIMIZE(9,SIZE)','ROM(SMALL)']
    mapping=(image.parent/('LB_'+profile+'.map')).read_text(errors='replace')
    segments=re.findall(r'^([0-9A-F]+)H\s+([0-9A-F]+)H\s+[0-9A-F]+H[^\n]*\sCODE\s+(.+)$',mapping,re.M)
    assert len(segments)>10
    assert all(0xFF0000<=int(start,16)<=int(end,16)<0xFF0800 for start,end,name in segments)
report={'version':profile,'image':str(image),'sha256':info['sha256'],
        'task_actions':actions,'motor_control_inherited_byte_for_byte':True,
        'serial_opened':False,'hardware_acceptance':'not_claimed'}
save_json(ROOT/'build'/(profile+'-delivery-check.json'),report)
print('PASS: UTF-8任务、'+profile+'冻结源码/HEX与原按键/红外采样继承核对通过；未打开串口。')

