"""IR007 发射脚巡游：三路发射脚同步拉低/拉高，配合手机摄像头判断哪根长条是发射条及其极性。

只驱动 CN7 的 P0.4/P5.2/P5.3（IR007 原设计就是探测这三路），不动电机。
每 2 秒切换一次：低 -> 高 -> 低 -> 高……共 6 轮 24 秒。
同时打印三路 ADC，若某根是接收条被反向驱动，ADC 会跟着摆动。
"""
import re
import sys
import time

import serial

from project import CONFIG, load_json, ports

STATUS = re.compile(rb'IR007 (RUN|STOP) KEYS=([01]{3}) PROBE=([0-6]) RST=([0-9A-F]{4}) REQ=([01]) ARRAY=SAMPLE\r?\n')
ADC = re.compile(rb'IR007 ADC=([0-9A-F]{4}),([0-9A-F]{4}),([0-9A-F]{4})\r?\nLIVE=([01])\r?\n')


def ask(link, command, pattern, timeout=0.4):
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


def read_adc(link):
    match = ask(link, b'a', ADC)
    if not match:
        return None
    return tuple(int(match.group(i), 16) for i in (1, 2, 3))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    port = ports(load_json(CONFIG))
    link = serial.Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=1)
    link.dtr = False
    link.rts = False
    link.port = port
    link.open()
    try:
        print('端口 {} 已打开，开始发射巡游'.format(port), flush=True)
        low_cmds = b'ABC'
        high_cmds = b'DEF'
        for round_index in range(6):
            # 三路一起拉低：若 CN7 上挂的是发射条且低有效，红外管此刻点亮
            for ch in low_cmds:
                link.write(bytes([ch]))
                time.sleep(0.03)
            link.read_all()
            level = '低'
            print('--- 第{}轮：三路拉低（此刻应亮） ---'.format(round_index + 1), flush=True)
            mark = time.monotonic()
            while time.monotonic() - mark < 2.0:
                adc = read_adc(link)
                if adc:
                    print('  [{}] 低 ADC={:4d},{:4d},{:4d}'.format(
                        time.strftime('%H:%M:%S'), adc[0], adc[1], adc[2]), flush=True)
                time.sleep(0.3)
            # 三路一起拉高
            for ch in high_cmds:
                link.write(bytes([ch]))
                time.sleep(0.03)
            link.read_all()
            print('--- 第{}轮：三路拉高（此刻应灭） ---'.format(round_index + 1), flush=True)
            mark = time.monotonic()
            while time.monotonic() - mark < 2.0:
                adc = read_adc(link)
                if adc:
                    print('  [{}] 高 ADC={:4d},{:4d},{:4d}'.format(
                        time.strftime('%H:%M:%S'), adc[0], adc[1], adc[2]), flush=True)
                time.sleep(0.3)
        # 收尾：释放三路
        link.write(b'0')
        time.sleep(0.1)
        print('巡游结束，已释放发射脚', flush=True)
    finally:
        link.close()


if __name__ == '__main__':
    main()
