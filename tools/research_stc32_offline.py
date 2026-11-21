"""对照本机厂商手册及当前依赖，离线摘录匹配章节；不连接主板。"""
from pathlib import Path
import fitz

root=Path(__file__).resolve().parents[1]
doc=fitz.open(root/'docs/reference/stc32g-cn.pdf')
out=root/'build/stc32-research-20261110'
out.mkdir(exist_ok=True)
selected=[]
for index, page in enumerate(doc):
    text=page.get_text()
    categories=[]
    if ('P3.2/P3.3' in text or 'P3.2和P3.3' in text) and ('下载' in text) and ('冷启动' in text or '硬件选项' in text):
        categories.append('download_entry')
    if 'EAXFR' in text and ('使能寄存器' in text or 'sfr ' in text or 'BAH' in text or 'BAh' in text):
        categories.append('eaxfr_register')
    if categories:
        selected.append({'page':index+1,'categories':categories})
        (out/('page-'+str(index+1)+'.txt')).write_text(text,encoding='utf-8')
print(selected)
