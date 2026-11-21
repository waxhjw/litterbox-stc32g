"""汇总本轮三路短探测，保持原始报告不变，不以差值自动宣布光电通过。"""
from pathlib import Path
import json
import statistics
import sys
root=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
rows=[]
for path in sorted((root/'build').glob('IR006-probe-20261111-101*.json')):
    data=json.loads(path.read_text(encoding='utf-8'))
    active=[event for event in data['events'] if event.get('phase')=='probe']
    if not active: continue
    rows.append({'file':path.name,'tx_hex':sorted({event['tx_hex'] for event in active}),
                 'samples':len(active),'live_samples':sum(event['probe_live'] for event in active),
                 'median_delta_from_before':[statistics.median([event['delta_from_before'][i] for event in active
                                                               if event['delta_from_before'][i] is not None])
                                             for i in range(3)],
                 'active_raw_ranges':[[min(event['raw_adc14_0_1'][i] for event in active),
                                       max(event['raw_adc14_0_1'][i] for event in active)] for i in range(3)]})
assert len(rows)==6, '本轮应有六个独立通道/电平报告，不能混用不完整结果'
report={'source':'actual IR006 UART capture','optical_acceptance':False,'reports':rows}
output=root/'build/IR006-probe-summary-20261111-1012.json'
output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
print('REPORT:',output)
