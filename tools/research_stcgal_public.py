"""只读取公开上游API，保存协议资料索引；不连接账号、不操作硬件。"""
import json
from urllib.request import Request, urlopen
from project import ROOT, save_json

targets={
    'protocol_docs':'https://api.github.com/repos/grigorig/stcgal/contents/doc/reverse-engineering',
    'stc32_issues':'https://api.github.com/search/issues?q=repo%3Agrigorig%2Fstcgal%20STC32',
    'stc32_changes':'https://api.github.com/repos/grigorig/stcgal/commits?path=stcgal/protocols.py&per_page=100',
}
report={}
for name,url in targets.items():
    try:
        request=Request(url,headers={'User-Agent':'STC32-readonly-research','Accept':'application/vnd.github+json'})
        with urlopen(request,timeout=20) as response:
            data=json.load(response)
        if name=='protocol_docs':
            report[name]=[{'name':x['name'],'url':x.get('download_url')} for x in data]
        elif name=='stc32_issues':
            report[name]={'count':data['total_count'],'items':[{'title':x['title'],'url':x['html_url'],'body':x.get('body')}
                                                               for x in data.get('items',[])]}
        else:
            report[name]=[{'sha':x['sha'],'url':x['html_url'],'message':x['commit']['message']}
                          for x in data if any(t in x['commit']['message'].lower() for t in ('stc32','option','stc8'))]
        print(name,json.dumps(report[name],ensure_ascii=False))
    except Exception as exc:
        report[name]={'error':str(exc)}
        print(name,str(exc))
save_json(ROOT/'build/stc32-research-20261110/upstream-index.json',report)
