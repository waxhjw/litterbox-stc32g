"""IR006/IR007临时诊断绑定检查；不打开串口。"""
import re
import sys
from project import ROOT,load_json,digest,inspect_hex,save_json

version=sys.argv[1] if len(sys.argv)>1 else 'IR006'
assert version in ('IR006','IR007'), '未知诊断版本'
directory=ROOT/('output/LB_'+version)
manifest=load_json(directory/'manifest.json')
assert digest(ROOT/('diagnostics/'+version+'/array_main.c'))==manifest['source_sha256']==digest(directory/'main.c')
info=inspect_hex(directory/(version.replace('IR','LB_IR')+'.hex'))
assert info['sha256']==manifest['sha256']
for name,sha in manifest['extra_sources'].items():
    assert digest(ROOT/('diagnostics/'+version)/name)==sha==digest(directory/name)
# 核心头文件继承：motor_control/guard逐字节来自IR005基线（经IR006原样传递）。
for name in ('motor_control.h','motor_ir_guard.h'):
    assert digest(ROOT/('diagnostics/'+version)/name)==digest(ROOT/'diagnostics/IR005'/name)
if version=='IR007':
    # IR007只改array_main.c；三个配套头文件必须与IR006逐字节一致。
    for name in ('motor_control.h','motor_ir_guard.h','array_probe_state.h'):
        assert digest(ROOT/'diagnostics/IR007'/name)==digest(ROOT/'diagnostics/IR006'/name)
tasks=[t for t in load_json(ROOT/'.vscode/tasks.json')['tasks'] if ' '+version+':' in t['label']]
assert len(tasks)==12
assert all(t['command']=='shnote' and ('${workspaceFolder}/tools/'+version.lower()+'.ps1') in t['args'] for t in tasks)
actions=[t['args'][t['args'].index('-Action')+1] for t in tasks]
assert set(actions)=={'build','check','flash','status','sample','probe','stop'}
assert actions.count('probe')==6
pairs={(t['args'][t['args'].index('-Channel')+1],t['args'][t['args'].index('-Level')+1])
       for t in tasks if 'probe' in t['args']}
assert pairs=={(str(c),level) for c in (1,2,3) for level in ('low','high')}
mapping=(directory/(version.replace('IR','LB_IR')+'.map')).read_text(errors='replace')
segments=re.findall(r'^([0-9A-F]+)H\s+([0-9A-F]+)H\s+[0-9A-F]+H[^\n]*\sCODE\s+(.+)$',mapping,re.M)
assert len(segments)>10 and all(0xFF0000<=int(a,16)<=int(b,16)<0xFF0800 for a,b,_ in segments)
assert 'temporarily inactive' in manifest['diagnostic_scope']
report={'version':version,'sha256':info['sha256'],'image':str(directory/(version.replace('IR','LB_IR')+'.hex')),
        'task_count':len(tasks),'motor_and_guard_inherited_byte_for_byte':True,
        'single_ir_link':'temporarily_inactive_user_approved_20261111',
        'serial_opened':False,'hardware_acceptance':False}
if version=='IR007':
    report['change_vs_IR006']='internal 4k pull-ups on P0.6/P1.0/P1.1 only; array_main.c otherwise unchanged'
save_json(ROOT/'build'/(version+'-delivery-check.json'),report)
print('PASS: '+version+' source/image/tasks/core inheritance and temporary diagnostic scope; no serial opened')
