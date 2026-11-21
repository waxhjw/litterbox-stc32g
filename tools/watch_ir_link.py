"""记录 IR013 台架状态。watch 只查询状态并保存状态变化。"""
import argparse
from datetime import datetime
import re
import sys
import time

import serial
from capture_ir_array_fixture import RADAR_STATUS, STATUS
from project import CONFIG, ROOT, load_json, ports, save_json

LINK_STATUS = re.compile(STATUS.pattern.replace(b"IR9", b"IRA", 1))
INTERLOCK_STATUS = re.compile(STATUS.pattern.replace(b"IR9", b"IRB", 1))
HALL_STATUS = re.compile(rb"H([0-3])")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "watch", "stop"))
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--profile", choices=("IR9", "IR013", "IR014", "IR015", "IR016", "IR017"), default="IR013")
    parser.add_argument("--hall", action="store_true")
    parser.add_argument("--with-hall", action="store_true", help="在运行监听中交替查询霍尔")
    parser.add_argument("--radar-active", choices=("high", "low"), help="仅在安全待机时为 IR017 设置实测触发电平")
    args = parser.parse_args()
    if args.hall and (args.profile not in ("IR014", "IR015", "IR016", "IR017") or args.action == "stop"):
        parser.error("--hall 仅用于 IR014 至 IR017 状态查询和监听")
    if args.with_hall and (args.hall or args.profile not in ("IR016", "IR017") or args.action != "watch"):
        parser.error("--with-hall 仅用于 IR016 和 IR017 运行状态监听")
    if args.radar_active is not None and (args.profile != "IR017" or args.action != "status" or args.hall):
        parser.error("--radar-active 仅用于 IR017 状态查询")
    sys.stdout.reconfigure(encoding="utf-8")
    config = load_json(CONFIG)
    port = ports(config)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    suffix = "motor-hall-watch" if args.with_hall else f"hall-{args.action}" if args.hall else args.action
    path = ROOT / "build" / f"{args.profile}-{suffix}-{stamp}.json"
    motor_pattern = {"IR9": STATUS, "IR016": INTERLOCK_STATUS, "IR017": RADAR_STATUS}.get(args.profile, LINK_STATUS)
    pattern = HALL_STATUS if args.hall else motor_pattern
    report = {"port": port, "action": args.action, "events": []}
    command = b"h" if args.hall else b"!" if args.action == "stop" else b"?"
    duration = args.seconds if args.action == "watch" else 1
    link = serial.Serial(port=None, baudrate=config["baud"], timeout=0.07, write_timeout=0.2)
    link.dtr = False
    link.rts = False
    link.port = port
    pending = bytearray()
    previous = None
    previous_hall = None
    last_response = None
    result = False
    try:
        with link:
            if args.radar_active is not None:
                link.reset_input_buffer()
                link.write(b"?")
                state = motor_pattern.fullmatch(link.read_until(b"\n", size=128).strip())
                if state is None or state[1] != b"S" or state[2] != b"111" or state[4] != b"0":
                    raise SystemExit("请先确认 IR017 待机且按键松开")
                command = b"H" if args.radar_active == "high" else b"L"
                report["radar_active_requested"] = args.radar_active
            start = time.monotonic()
            print("WATCH:", args.action, port, "REPORT:", path, flush=True)
            while time.monotonic() - start < duration:
                link.write(command)
                time.sleep(0.07)
                pending.extend(link.read(link.in_waiting or 1))
                while b"\n" in pending:
                    raw, _, pending = pending.partition(b"\n")
                    line = bytes(raw.strip())
                    elapsed_ms = round((time.monotonic() - start) * 1000)
                    if args.action == "watch" and line == b"BOOT":
                        event = {"elapsed_ms": elapsed_ms, "status": "BOOT"}
                        report["events"].append(event)
                        print(event, flush=True)
                        previous = None
                        previous_hall = None
                        save_json(path, report)
                        continue
                    if args.with_hall:
                        hall = HALL_STATUS.fullmatch(line)
                        if hall is not None:
                            if line != previous_hall:
                                bits = int(hall[1])
                                event = {"elapsed_ms": elapsed_ms, "status": line.decode("ascii"),
                                         "hlr1": bits >> 1, "hlr2": bits & 1}
                                report["events"].append(event)
                                print(event, flush=True)
                                save_json(path, report)
                                previous_hall = line
                            continue
                    match = pattern.fullmatch(line)
                    if match is None:
                        continue
                    gap = None if last_response is None else elapsed_ms - last_response
                    last_response = elapsed_ms
                    if line != previous or (args.action == "watch" and gap is not None and gap >= 500):
                        event = {"elapsed_ms": elapsed_ms, "status": line.decode("ascii")}
                        if gap is not None and gap >= 500:
                            event["response_gap_ms"] = gap
                        if args.hall:
                            bits = int(match[1])
                            event.update(hlr1=bits >> 1, hlr2=bits & 1)
                        elif args.profile == "IR017":
                            event["radar_raw"] = int(match[7])
                        report["events"].append(event)
                        print(event, flush=True)
                        previous = line
                        save_json(path, report)
                    result = args.action != "stop" or (
                        match[1] == b"S" and match[4] == match[5] == b"0"
                    )
                    if result and args.action != "watch":
                        break
                if result and args.action != "watch":
                    break
                if args.with_hall:
                    # 等上一条应答处理完再切换查询，避免 MCU 发送时漏收紧跟的命令。
                    command = b"h" if command == b"?" else b"?"
                time.sleep(0.08)
    finally:
        report["match"] = result
        report["last_response_elapsed_ms"] = last_response
        save_json(path, report)
    if not result:
        raise SystemExit(f"没有观察到要求的 {args.profile} 状态，请核对报告和板内版本")


if __name__ == "__main__":
    main()
