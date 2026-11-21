"""IR010 现场探针：按顺序发单字节命令，把每条的回复行原样打出来。

IR010 命令：
  ?  状态   IR9 S|R K=xxx R=xxxx Q=x C=x B=x
  a  光束   IR9 P=xxxx,xxxx,xxxx M=xyz B=x   （本窗口三路峰值 / 连续未收到光窗口数 / 遮挡位图）
  c  开 38.13kHz 三路同步载波（会清空判定历史并回一次 status）
  k  关载波（钉低三路并释放，回一次 status）
  !  全停（电机 + 载波）

用法：
  python tools/ir010_probe.py --port COM9 --actions "?,c,a,a,a"
  python tools/ir010_probe.py --port COM9 --actions a --repeat 20 --delay 0.15

峰值判读：≈0390 附近=暗态(1.19V)，≥0700(2000)=通光，0FFF=近满量程，FFFF=ADC超时。
B 位图 bit0/bit1/bit2 分别对应 REV1/REV2/REV3，1=连续 4 窗未收到光（遮挡）。
"""
import argparse
import sys
import time

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='COM9')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--actions', default='?,c,a,a,a,a')
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--delay', type=float, default=0.25)
    args = ap.parse_args()

    with serial.Serial(args.port, args.baud, timeout=1.0) as port:
        port.reset_input_buffer()
        time.sleep(0.05)
        # 探头可能停在半行，先握手一次把缓冲对齐。
        port.write(b'?')
        port.read_until(b'\n')

        for _ in range(args.repeat):
            for cmd in args.actions.replace(' ', ''):
                port.write(cmd.encode())
                line = port.read_until(b'\n')
                text = line.decode('ascii', 'replace').strip()
                print(f'{cmd} -> {text}' if text else f'{cmd} -> (无回复)')
                sys.stdout.flush()
                time.sleep(args.delay)


if __name__ == '__main__':
    main()
