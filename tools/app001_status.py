"""读取合版台架状态，同时记录电机引脚、传感器状态和控制节拍。"""
import argparse
from datetime import datetime
import re
import time

import serial
from project import CONFIG, ROOT, load_json, ports, save_json
from diagnostic import APP_PROFILES, DRUM_PROFILES


APP_FIELDS = b"".join(
        f" {field}=[0-9A-F]{{{width}}}".encode("ascii")
        for field, width in zip("NHDRETXQVIUWOY", (2, 4, 4, 4, 4, 4, 4, 1, 1, 4, 1, 1, 1, 4))
)
LOCAL = re.compile(rb"IRC [SR] K=[01]{3} R=[0-9A-F]{4} Q=[01] C=[0-9A-F] B=[0-7] D=[01]")
HALL = re.compile(rb"H[0-3]")
GUARDS = re.compile(rb"IRX R=[01] A=[0-8] S=[0-2] T=[0-9A-F]{4}")
BEAMS = re.compile(rb"IRC P=(?:[0-9A-F]{4},){2}[0-9A-F]{4} M=[0-4]{3} B=[0-7]")
SINGLE_FRAME = re.compile(
    rb"IRS W=[0-9A-F]{4} V=[0-9A-F]{4} Q=[01] N=[0-9A-F]{4} H=[0-9A-F]{4} E=[0-9A-F]{4} F=[0-9A-F]{4} L=[01](?: C=[0-9A-F]{4})?"
)
OPTICAL_MODES = ((b"j", "array"), (b"c", "combined"))
PERIOD_MODES = ((b"c", "10ms-before"), (b"u", "20ms"), (b"v", "40ms"), (b"c", "10ms-after"))
PHASE_FRAME = re.compile(rb"IRP S=[0-4](?: [0-9A-F]{12}){9}")


def query(link, command, pattern):
    link.reset_input_buffer()
    link.write(command)
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        line = link.read_until(b"\n", size=160).strip()
        if pattern.fullmatch(line):
            return line.decode("ascii")
    raise RuntimeError(f"未收到 {command!r} 对应的台架状态")


def arm_trial(link, app_pattern):
    query(link, b"w", app_pattern)  # 回包型号匹配才允许发送台架准备命令。
    query(link, b"g", LOCAL)
    armed = query(link, b"w", app_pattern)
    if " M=1 " not in armed:
        raise RuntimeError(f"台架准备未生效：{armed}")
    print("ARMED: waiting for one new App start", flush=True)


def optical_check(link, app_pattern, path, report, seconds, single_trace=False, modes=OPTICAL_MODES):
    """电机已拔下时固定摆位，依次对照指定的发射模式。"""
    initial = query(link, b"w", app_pattern)
    if not all(field in initial for field in (" O=0 ", " J=0 ", " M=0 ")):
        raise RuntimeError(f"主板未待机：{initial}")
    try:
        for command, mode in modes:
            query(link, b"k", LOCAL)
            response = query(link, command, LOCAL)
            if " C=1 " not in response:
                raise RuntimeError(f"{mode} 发射未开启：{response}")
            started = time.monotonic()
            time.sleep(0.2)
            while time.monotonic() - started < seconds:
                guards = query(link, b"d", GUARDS)
                peaks = query(link, b"a", BEAMS)
                app = query(link, b"w", app_pattern)
                if " O=0 " not in app or " M=0 " not in app:
                    raise RuntimeError(f"采样期间出现了运行状态：{app}")
                sample = dict(mode=mode, elapsed=round(time.monotonic()-started, 3), guards=guards, peaks=peaks)
                if single_trace and mode != "array":
                    sample["single"] = query(link, b"z", SINGLE_FRAME)
                print(mode, guards, peaks, sample.get("single", ""), flush=True)
                report["samples"].append(sample)
                save_json(path, report)
                time.sleep(0.25)
    finally:
        stopped = query(link, b"k", LOCAL)
        print("OPTICAL OFF:", stopped, flush=True)
        if " C=0 " not in stopped:
            raise RuntimeError(f"未确认关闭发射：{stopped}")


def phase_check(link, app_pattern, path, report):
    """每次采三路在三个相位的分布，固件同时负责关闭发射。"""
    initial = query(link, b"w", app_pattern)
    if not all(field in initial for field in (" O=0 ", " J=0 ", " M=0 ")):
        raise RuntimeError(f"主板未待机：{initial}")
    report["initial"] = initial
    totals = [
        dict(gate_ticks=gate, channel=channel, count=0, light=0, low=None, high=None)
        for gate in (60, 42, 24) for channel in (1, 2, 3)
    ]
    report["totals"] = totals
    try:
        # 精确到一拍的采样可能错过窗口。每次有固件超时，跨多轮累积各组数据。
        for run in range(1, 19):
            query(link, b"k", LOCAL)
            response = query(link, b"e", LOCAL)
            if " C=1 " not in response or not response.startswith("IRC S "):
                raise RuntimeError(f"定相位采样未启动：{response}")
            time.sleep(1.70)
            deadline = time.monotonic() + 1.1
            while True:
                raw = query(link, b"y", PHASE_FRAME)
                _, state_field, *values = raw.split()
                if state_field != "S=1" or time.monotonic() >= deadline:
                    break
                time.sleep(0.18)
            cells = []
            for i, value in enumerate(values):
                count, light, low, high = (int(value[a:b], 16) for a, b in ((0, 2), (2, 4), (4, 8), (8, 12)))
                if not 0 <= light <= count <= 16 or (count and not 0 <= low <= high <= 4095):
                    raise RuntimeError(f"采样回包数值越界：{raw}")
                cells.append(dict(gate_ticks=(60, 42, 24)[i//3], channel=i%3+1,
                                  count=count, light=light, low=low if count else None,
                                  high=high if count else None))
                total = totals[i]
                if count:
                    total["low"] = min(total["low"], low) if total["count"] else low
                    total["high"] = max(total["high"], high) if total["count"] else high
                    total["count"] += count
                    total["light"] += light
            report["samples"].append(dict(run=run, state=state_field, raw=raw, cells=cells))
            save_json(path, report)
            print(f"SCAN {run} {raw}", flush=True)
            if state_field not in ("S=2", "S=3") or (state_field == "S=2" and any(c["count"] != 16 for c in cells)):
                raise RuntimeError("固件采样状态不符，已记录收到的样本")
            automatic = query(link, b"?", LOCAL)
            if " C=0 " not in automatic or " Q=0 " not in automatic or not automatic.startswith("IRC S "):
                raise RuntimeError(f"采样结束后发射未自动关闭：{automatic}")
            if run>=3 and all(c["count"]>=16 for c in totals):
                return
        raise RuntimeError("已达采样轮数上限，保存了已收到的样本")
    finally:
        stopped = query(link, b"k", LOCAL)
        report["stop"] = stopped
        save_json(path, report)
        print("OPTICAL OFF:", stopped, flush=True)
        if " C=0 " not in stopped or not stopped.startswith("IRC S "):
            raise RuntimeError(f"未确认关闭发射及输出：{stopped}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "watch", "radar-high", "stop", "arm-watch", "optical-check", "period-check", "phase-check"))
    parser.add_argument("--profile", choices=APP_PROFILES, default="APP001")
    parser.add_argument("--seconds", type=int, choices=range(1, 301), default=60, metavar="1..300")
    args = parser.parse_args()
    combined_guards = args.profile in DRUM_PROFILES[DRUM_PROFILES.index("DRUM005"):]
    bench_profile = args.profile == "DRUM004" or combined_guards
    if args.action == "arm-watch" and not bench_profile:
        parser.error("arm-watch only supports the unloaded bench profiles")
    if args.action == "optical-check" and args.profile not in DRUM_PROFILES[DRUM_PROFILES.index("DRUM007"):]:
        parser.error("optical-check requires DRUM007 or later")
    if args.action == "period-check" and args.profile not in DRUM_PROFILES[DRUM_PROFILES.index("DRUM010"):]:
        parser.error("period-check requires DRUM010 or later")
    if args.action == "phase-check" and args.profile not in DRUM_PROFILES[DRUM_PROFILES.index("DRUM012"):]:
        parser.error("phase-check requires DRUM012 or later")
    config = load_json(CONFIG)
    port = ports(config)
    suffix = rb" S=[023]" if args.profile in ("APP003", "APP004", "APP005") + DRUM_PROFILES else b""
    if args.profile in ("APP004", "APP005") + DRUM_PROFILES:
        suffix += rb" L=[01]"
    if args.profile == "DRUM001":
        suffix += rb" J=[0-3] F=[0-7] A=[01] G=[0-3] Z=[0-9A-F]{4}"
    elif args.profile in DRUM_PROFILES:
        suffix += rb" J=[0-3] F=[0-8] A=[01] G=[0-3] Z=[0-9A-F]{4} B=[01] P=[0-3F]"
    if bench_profile:
        suffix += rb" M=[0-4] C=[0-6] K=[0-4]"
    app_pattern = re.compile(args.profile.encode("ascii") + APP_FIELDS + suffix)
    path = ROOT / "build" / f"{args.profile}-{args.action}-{datetime.now():%Y%m%d-%H%M%S%f}.json"
    report = {"port": port, "action": args.action, "samples": []}
    link = serial.Serial(port=None, baudrate=config["baud"], timeout=0.15, write_timeout=0.2)
    link.dtr = False
    link.rts = False
    link.port = port

    with link:
        started = time.monotonic()
        print("REPORT:", path, flush=True)
        if args.action == "phase-check":
            phase_check(link, app_pattern, path, report)
            return
        if args.action in ("optical-check", "period-check"):
            modes = PERIOD_MODES if args.action == "period-check" else OPTICAL_MODES
            optical_check(link, app_pattern, path, report, args.seconds,
                          single_trace=args.profile in DRUM_PROFILES[DRUM_PROFILES.index("DRUM009"):], modes=modes)
            return
        command = {"radar-high": b"H", "stop": b"!"}.get(args.action, b"?")
        if args.action == "radar-high":
            query(link, b"w", app_pattern)
        armed_watch = args.action == "arm-watch"
        if armed_watch:
            arm_trial(link, app_pattern)
        previous = None
        while True:
            local = query(link, command, LOCAL)
            hall = query(link, b"h", HALL)
            line = query(link, b"w", app_pattern)
            protection = query(link, b"d", GUARDS) if combined_guards else ""
            fields = {item[0]: int(item[2:], 16) for item in line.split()[1:]}
            elapsed = round(time.monotonic() - started, 3)
            sample = {"s": elapsed, "app": fields, "local": local, "hall": hall}
            if protection:
                sample["protection"] = protection
            report["samples"].append(sample)
            # 恢复计时递减仍写进文件，终端只打印保护状态切换。
            state = ({k: v for k, v in fields.items() if k != "Y"}, local, hall, protection.split(" T=")[0])
            if state != previous:
                print(f"{elapsed:8.3f}s {line} {local} {hall} {protection}".rstrip(), flush=True)
                previous = state
            save_json(path, report)
            if elapsed >= args.seconds:
                if armed_watch and fields["M"] != 0:
                    query(link, b"!", LOCAL)
                    print("STOPPED: bench watch time elapsed", flush=True)
                break
            if armed_watch and fields["M"] == 0:
                # 只有尚未收到启动请求的准备超时才重进等待。完成、取消和保护停机不重开。
                if fields["C"] != 6:
                    break
                arm_trial(link, app_pattern)
            if args.action not in ("watch", "arm-watch"):
                break
            time.sleep(0.25)


if __name__ == "__main__":
    main()
