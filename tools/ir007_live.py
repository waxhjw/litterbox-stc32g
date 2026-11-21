"""IR007实时双通道监视：每轮交替查询状态(按键/运行)与三路ADC，带毫秒时间戳。

只读：不发探测命令、不启停电机，仅用于把用户的现场操作与板上状态对齐。
"""
import argparse
from datetime import datetime
import re
import sys
import time
import serial
from project import CONFIG, load_json, ports

STATUS = re.compile(rb'IR007 (RUN|STOP) KEYS=([01]{3}) PROBE=([0-6]) RST=([0-9A-F]{4}) REQ=([01]) ARRAY=SAMPLE\r?\n')
ADC = re.compile(rb'IR007 ADC=([0-9A-F]{4}),([0-9A-F]{4}),([0-9A-F]{4})\r?\nLIVE=([01])\r?\n')


def ask(link, command, pattern, timeout=0.5):
    link.reset_input_buffer()
    link.write(command)
    end = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < end:
        data.extend(link.read(max(1, min(255, link.in_waiting))))
        match = pattern.search(data)
        if match:
            return match
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=40.0)
    parser.add_argument('--period', type=float, default=0.25)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    port = ports(load_json(CONFIG))
    link = serial.Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=1)
    link.dtr = False
    link.rts = False
    link.port = port
    previous = None
    with link:
        if ask(link, b'?', STATUS) is None:
            print('FAIL: 未确认IR007身份，未开始监视', flush=True)
            raise SystemExit(1)
        start = time.monotonic()
        print(f'PORT={port} 监视{args.seconds:.0f}秒（只读）', flush=True)
        n = 0
        while time.monotonic() - start < args.seconds:
            stamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            status = ask(link, b'?', STATUS)
            adc = ask(link, b'a', ADC)
            if status is None or adc is None:
                print(f'{stamp}  <无完整应答>', flush=True)
                time.sleep(args.period)
                continue
            run = status[1].decode()
            keys = status[2].decode()
            req = status[5].decode()
            probe_live = status[3].decode()
            values = [int(adc[i], 16) for i in (1, 2, 3)]
            delta = '---'
            if previous is not None:
                deltas = [None if v == 65535 or p == 65535 else v - p for v, p in zip(values, previous)]
                if any(d is not None and abs(d) >= 30 for d in deltas):
                    delta = 'ADC变化 ' + ','.join('--' if d is None else f'{d:+d}' for d in deltas)
            previous = values
            n += 1
            line = f'{stamp} {run} KEY={keys} REQ={req} PROBE={probe_live} ADC={values[0]},{values[1]},{values[2]}'
            if delta != '---':
                line += '  ' + delta
            print(line, flush=True)
            time.sleep(max(0.0, args.period - 0.02))
        print(f'共{n}轮，监视结束', flush=True)


if __name__ == '__main__':
    main()
