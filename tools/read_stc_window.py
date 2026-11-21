"""只读STC-ISP控件文字，不发送按键、不改变焦点。"""
import ctypes
from ctypes import wintypes
import json
import sys
from pathlib import Path

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SendMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
user32.EnumWindows.argtypes = [callback,wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND,callback,wintypes.LPARAM]

def title(handle):
    buf = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(handle,buf,len(buf))
    return buf.value

roots=[]
@callback
def top(handle, param):
    name=title(handle)
    if name.startswith('STC') and 'V6.97C' in name:
        roots.append((handle,name))
    return True
user32.EnumWindows(top,0)
results=[]
for root,name in roots:
    controls=[]
    @callback
    def child(handle,param):
        buf=ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle,buf,len(buf))
        kind=buf.value
        if 'edit' in kind.lower() or 'static' in kind.lower():
            size=min(30000,user32.SendMessageW(handle,0x000E,0,0))
            if size>0:
                text=ctypes.create_unicode_buffer(size+1)
                user32.SendMessageW(handle,0x000D,len(text),ctypes.addressof(text))
                controls.append({'hwnd':handle,'class':kind,'text':text.value})
        return True
    user32.EnumChildWindows(root,child,0)
    results.append({'hwnd':root,'title':name,'controls':controls})
output=Path(__file__).resolve().parents[1]/'build/STC-ISP-ui-latest.json'
output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
print(json.dumps([{'hwnd':r['hwnd'],'title':r['title'],
                  'logs':[c for c in r['controls'] if 'edit' in c['class'].lower() and len(c['text'])>80]}
                 for r in results],ensure_ascii=False,indent=2))
