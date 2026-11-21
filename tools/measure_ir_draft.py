"""仅编译/链接IR006开发源码以检查容量；不生成HEX或冻结交付物，不连接串口。"""
from pathlib import Path
import tempfile
from project import ROOT,CONFIG,load_json,resolve,tool_env,command

cfg=load_json(CONFIG)
source=ROOT/'diagnostics/IR006/array_main.c'
draft=Path(tempfile.mkdtemp(prefix='draft-IR006-',dir=ROOT/'build'))
print('DRAFT_ONLY:',draft,flush=True)
compiler=resolve(cfg['toolchain'])/'BIN'
command([compiler/'C251.EXE',source,'SMALL','MODSRC','INCDIR('+str(source.parent)+')',
         'OBJECT(main.obj)','PRINT(main.lst)','CODE','OPTIMIZE(9,SIZE)','ROM(SMALL)'],draft,tool_env(cfg),keil=True)
command([compiler/'L251.EXE','main.obj','TO','DRAFT_NOT_FOR_FLASH','PRINT(draft.map)'],draft,tool_env(cfg),keil=True)
print('PASS: draft capacity check only; no HEX generated')
