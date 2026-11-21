"""运行tasks.json中的真实入口；仅适用于尚未导入产品的ENV001阶段。"""
from pathlib import Path
import json
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT/'config/project.json').read_text(encoding='utf-8'))
if any(cfg['product'].values()):
    raise SystemExit('已有产品配置，禁止以环境测试方式执行下载任务。')
tasks = json.loads((ROOT/'.vscode/tasks.json').read_text(encoding='utf-8'))['tasks']
records = []
for task in tasks:
    if 'command' not in task:
        continue
    if '${workspaceFolder}/tools/task.ps1' not in task['args']:
        # 独立诊断下载入口可能真正写板，不能作为ENV001自检运行。
        continue
    argv = [task['command']] + [arg.replace('${workspaceFolder}', str(ROOT)) for arg in task['args']]
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = result.stdout.decode('utf-8', errors='replace')
    action = task['args'][-1]
    expected = 0 if action in ('doctor','validate') else 1
    if result.returncode != expected:
        print(output)
        raise SystemExit('任务退出码不符合预期：'+task['label'])
    if expected == 0 and 'PASS:' not in output:
        raise SystemExit('缺少通过信息：'+task['label'])
    if expected == 1 and 'config/project.json' not in output:
        raise SystemExit('任务未在缺少产品配置阶段拒绝：'+task['label'])
    (ROOT/'build'/('task-'+action+'.log')).write_text(output, encoding='utf-8')
    records.append({'task': task['label'], 'action': action, 'exit_code': result.returncode,
                    'expected_exit_code': expected, 'pass': True})
    print('PASS:', task['label'], 'exit=', result.returncode)
report = {'phase': 'ENV001', 'serial_opened': False, 'target_connected': False,
          'tasks': records, 'vscode_ui': 'pending'}
(ROOT/'build/entrypoint-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
