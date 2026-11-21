"""IR006/IR007原始采样工具；默认不驱动发射脚，不自动启动电机。"""
import argparse
from datetime import datetime
import re
import sys
import time
import serial
from project import ROOT,CONFIG,load_json,ports,save_json

IDENTITY=None
ADC=None
REJECT=b''

def build_patterns(version):
    """按固件身份编译应答模式；IR007仅替换身份字符串，协议不变。"""
    global IDENTITY, ADC, REJECT
    IDENTITY=re.compile(version.encode() + rb' (RUN|STOP) KEYS=([01]{3}) PROBE=([0-6]) RST=([0-9A-F]{4}) REQ=([01]) ARRAY=SAMPLE\r?\n')
    ADC=re.compile(version.encode() + rb' ADC=([0-9A-F]{4}),([0-9A-F]{4}),([0-9A-F]{4})\r?\nLIVE=([01])\r?\n')
    REJECT=version.encode() + b' REJECT\r\n'

def probe_byte(channel,level):
    if channel not in (1,2,3) or level not in ('low','high'):
        raise ValueError('探测通道或电平无效')
    return bytes([ord('A')+channel-1+(3 if level=='high' else 0)])

def probe_permitted(identity):
    match=IDENTITY.search(identity)
    return bool(match and match[1]==b'STOP' and match[3]==b'0' and match[5]==b'0'
                and (int(match[4],16)&0x43)==0x41)

def parse_adc(response):
    match=ADC.search(response)
    if match is None:
        raise RuntimeError('没有完整ADC应答；未把空结果解释为模块故障')
    values=[int(match[i],16) for i in (1,2,3)]
    if any(v>4095 and v!=65535 for v in values):
        raise RuntimeError('ADC应答超出12位结果/FFFF超时标记范围')
    return {'raw_adc14_0_1':values,'probe_live':match[4]==b'1',
            'adc_timeout_channels':[i+1 for i,v in enumerate(values) if v==65535]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['status','sample','probe','stop'])
    parser.add_argument('--channel',type=int,choices=[1,2,3],default=1)
    parser.add_argument('--level',choices=['low','high'],default='high')
    parser.add_argument('--count',type=int,choices=range(1,1001),default=100,metavar='1..1000')
    parser.add_argument('--version',choices=['IR006','IR007'],default='IR006')
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    build_patterns(args.version)
    report={'version':args.version,'action':args.action,'events':[],
            'hardware_acceptance':False,'optical_response_verified':False,'motor_motion_verified':False}
    path=ROOT/'build'/(args.version+'-'+args.action+'-'+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.json')
    def capture(link,command,pattern,phase):
        link.write(command)
        end=time.monotonic()+2
        data=bytearray()
        while time.monotonic()<end:
            # 已到达的字节立即读取，避免固定256字节读取把前后采样拉开100ms。
            data.extend(link.read(max(1,min(256,link.in_waiting))))
            if pattern.search(data) or REJECT in data: break
        entry={'time':datetime.now().astimezone().isoformat(),'phase':phase,
               'tx_hex':command.hex(),'response':data.decode('ascii',errors='replace')}
        report['events'].append(entry)
        print(entry['response'],end='',flush=True)
        return bytes(data),entry
    try:
        port=ports(load_json(CONFIG)); report['port']=port
        link=serial.Serial(port=None,baudrate=115200,timeout=0.1,write_timeout=1)
        link.dtr=False; link.rts=False; link.port=port
        with link:
            identity,_=capture(link,b'?',IDENTITY,'identify')
            if IDENTITY.search(identity) is None:
                raise RuntimeError('未确认'+args.version+'独立采样版本，未发送探测或停止命令')
            if args.action=='stop':
                response,_=capture(link,b'!',IDENTITY,'stop')
                match=IDENTITY.search(response)
                if match is None or match[1]!=b'STOP' or match[3]!=b'0' or match[5]!=b'0':
                    raise RuntimeError('未确认软件停止/取消探测')
            elif args.action in ('sample','probe'):
                if args.action=='probe' and not probe_permitted(identity):
                    raise RuntimeError('未确认手动停止、探测空闲及运行期低压复位配置，不驱动GPIO')
                command=probe_byte(args.channel,args.level) if args.action=='probe' else b'a'
                for _ in range(args.count):
                    baseline=None
                    if args.action=='probe':
                        before,event=capture(link,b'a',ADC,'before_probe')
                        baseline=parse_adc(before)
                        event.update(baseline)
                    response,event=capture(link,command,ADC,args.action)
                    if REJECT in response:
                        raise RuntimeError('固件拒绝探测，可能仍在冷却或用户已开机；停止发送')
                    event.update(parse_adc(response))
                    if baseline is not None:
                        event['delta_from_before']=[None if a==65535 or b==65535 else a-b
                                                   for a,b in zip(event['raw_adc14_0_1'],baseline['raw_adc14_0_1'])]
                        time.sleep(0.01)  # 正常5ms探测应已释放，再读一次三路输入。
                        after,after_event=capture(link,b'a',ADC,'after_probe')
                        after_event.update(parse_adc(after))
                    # MCU自身有100ms冷却，这里再留200ms，不依赖主机才能限时退出。
                    time.sleep(0.2)
            report['result']='captured_not_hardware_acceptance'
    except (RuntimeError,ValueError,OSError,serial.SerialException) as exc:
        report['result']='failed'; report['error']=str(exc); print('FAIL:',exc,flush=True)
    finally:
        save_json(path,report); print('REPORT:',path,flush=True)
    if report['result']=='failed': raise SystemExit(1)

if __name__=='__main__': main()
