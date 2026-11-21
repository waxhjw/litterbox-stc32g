"""先确认指定IR版本；受控测试或选择已实测极性，无串口电机启动命令。"""
import argparse
from datetime import datetime
import re
import time
import serial
from project import ROOT, CONFIG, load_json, ports, save_json

def status_pattern(profile):
    return re.compile(profile.encode()+rb' (STOP|RUN) KEYS=([01]{3}) TX=([0-5]) RAW=([01]) RST=([0-9A-F]{4})\r?\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status','off','test38','link-low','link-high','watch','stop'])
    parser.add_argument('--profile', choices=['IR002','IR003','IR004','IR005'], default='IR003')
    args = parser.parse_args()
    port = ports(load_json(CONFIG))
    link = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
    link.dtr = False
    link.rts = False
    link.port = port
    events = []
    report = {'version': args.profile, 'action': args.action, 'port': port,
              'module_passed': False, 'motor_motion_verified': False, 'events': events}
    path = ROOT/'build'/(args.profile+'-'+args.action+'-'+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.json')

    def receive(seconds, phase):
        end = time.monotonic()+seconds
        data = bytearray()
        while time.monotonic() < end:
            chunk = link.read(1024)
            if chunk:
                data.extend(chunk)
                print(chunk.decode('ascii', errors='replace'), end='', flush=True)
        events.append({'time': datetime.now().astimezone().isoformat(), 'phase': phase,
                       'response': data.decode('ascii', errors='replace')})
        return bytes(data)

    identified = False
    try:
        with link:
            link.write(b'?')
            identity = receive(2, 'identify')
            match = status_pattern(args.profile).search(identity)
            if match is None:
                raise RuntimeError('未确认'+args.profile+'身份；未发送控制命令')
            identified = True
            report['runtime_rstcfg'] = match[5].decode()
            # IR004/IR005遮挡暂停时STOP但REQ仍为1；不能在这时用独立测试重置红外模式。
            manual_off = args.profile not in ('IR004','IR005') or re.search(rb'REQ=0 BEAM=', identity) is not None
            if args.action == 'test38':
                if not manual_off or match[1] != b'STOP' or (int(match[5], 16) & 0x43) != 0x41:
                    raise RuntimeError('未确认软件STOP及运行期低压复位配置，不开始发射')
                try:
                    print('阶段：发射关闭基线2秒', flush=True)
                    link.write(b'0')
                    receive(2, 'tx_off_baseline')
                    print('阶段：38kHz短脉冲10秒；观察正对和遮挡的变化', flush=True)
                    link.write(b'8')
                    active = receive(10.5, 'tx_38khz_bursts')
                    if b'TX=2' not in active:
                        raise RuntimeError('未确认固件进入38kHz模式，结果未知')
                finally:
                    link.write(b'0')
                    receive(2, 'tx_off_after_test')
            elif args.action == 'off':
                link.write(b'0')
                receive(1, 'tx_off')
            elif args.action == 'stop':
                link.write(b'!')
                response=receive(1, 'stop_motor_and_ir')
                stopped=status_pattern(args.profile).search(response)
                if stopped is None or stopped[1]!=b'STOP' or stopped[3]!=b'0':
                    raise RuntimeError('未确认停止和发射关闭状态')
            elif args.action == 'watch':
                # 仅查询，不重置模式、按键意图或10秒倒计时。
                for _ in range(60):
                    link.write(b'?')
                    receive(1, 'watch')
            elif args.action in ('link-low','link-high'):
                if args.profile not in ('IR003','IR004','IR005') or not manual_off or match[1]!=b'STOP' or (int(match[5],16)&0x43)!=0x41:
                    raise RuntimeError('未确认联动版本已手动停止及运行期复位配置，不更改模式')
                # l/h只选择接收脉冲极性，绝不设置用户电机运行请求。
                command=b'l' if args.action=='link-low' else b'h'
                link.write(command)
                response=receive(2, args.action)
                enabled=status_pattern(args.profile).search(response)
                # IR004/IR005关机时只记住下次开机极性，TX仍0；长按启动后查询实际TX4/5。
                expected=b'0' if args.profile in ('IR004','IR005') else b'4' if command==b'l' else b'5'
                if enabled is None or enabled[3]!=expected:
                    raise RuntimeError('未确认选择的光路联动模式')
            report['result'] = 'captured_not_hardware_acceptance'
    except (RuntimeError, serial.SerialException) as exc:
        report['result'] = 'failed'
        report['error'] = str(exc)
        print('FAIL:', exc, flush=True)
    finally:
        report['identified'] = identified
        save_json(path, report)
        print('REPORT:', path, flush=True)
    if report['result'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
