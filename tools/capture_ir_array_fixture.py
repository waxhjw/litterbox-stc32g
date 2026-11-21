"""IR9 系列台架采集。先确认停机，再短时开启载波，完整保存每次读数及关断应答。"""
import argparse
from datetime import datetime
import re
import sys
import time

import serial
from project import CONFIG, ROOT, load_json, ports, save_json

STATUS = re.compile(rb"IR9 ([SR]) K=([01]{3}) R=([0-9A-F]{4}) Q=([01]) C=([01]) B=([0-7])")
BEAM = re.compile(rb"IR9 P=([0-9A-F]{4}),([0-9A-F]{4}),([0-9A-F]{4}) M=([0-9A-F]{3}) B=([0-7])")
RADAR_STATUS = re.compile(STATUS.pattern.replace(b"IR9", b"IRC", 1) + rb" D=([01])")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=["as-connected", "clear", "blocked-1", "blocked-2", "blocked-3", "clear-again"])
    parser.add_argument("--profile", choices=["IR9", "IR013", "IR014", "IR015", "IR016", "IR017"], default="IR9")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    stamp = datetime.now().astimezone()
    path = ROOT / "build" / f"{args.profile}-fixture-{args.fixture}-{stamp.strftime('%Y%m%d-%H%M%S%f')}.json"
    status_pattern, beam_pattern = STATUS, BEAM
    if args.profile != "IR9":
        prefix = {"IR016": b"IRB", "IR017": b"IRC"}.get(args.profile, b"IRA")
        status_pattern = RADAR_STATUS if args.profile == "IR017" else re.compile(STATUS.pattern.replace(b"IR9", prefix, 1))
        beam_pattern = re.compile(BEAM.pattern.replace(b"IR9", prefix, 1))
    report = {"setup": args.fixture, "started": stamp.isoformat(), "frames": [],
              "samples": [], "carrier_confirmed_off": False}

    def request(link, command, pattern):
        link.write(command)
        deadline = time.monotonic() + 0.35
        pending = bytearray()
        while time.monotonic() < deadline:
            pending.extend(link.read_until(b"\n", size=128))
            if not pending.endswith(b"\n") and len(pending) < 128:
                continue
            raw = bytes(pending)
            pending.clear()
            report["frames"].append({"command": command.decode(), "rx": raw.decode("ascii", "replace").strip()})
            save_json(path, report)
            match = pattern.fullmatch(raw.strip())
            if match is not None:
                return match
        raise RuntimeError(f"命令 {command.decode()} 未收到完整应答")

    try:
        report["port"] = ports(load_json(CONFIG))
        link = serial.Serial(port=None, baudrate=115200, timeout=0.06, write_timeout=0.2)
        link.dtr = False
        link.rts = False
        link.port = report["port"]
        with link:
            state = request(link, b"?", status_pattern)
            if state[1] != b"S" or state[4] != b"0" or state[5] != b"0" or (int(state[3], 16) & 0x43) != 0x41:
                raise RuntimeError("台架采集要求停止、无运行请求、载波关闭且低压复位配置正常")
            try:
                state = request(link, b"c", status_pattern)
                if state[1] != b"S" or state[4] != b"0" or state[5] != b"1":
                    raise RuntimeError("未确认载波已开启且电机保持停止")
                time.sleep(0.18)
                for _ in range(18):
                    reading = request(link, b"a", beam_pattern)
                    report["samples"].append({
                        "peaks": [int(reading[i], 16) for i in (1, 2, 3)],
                        "miss": [int(chr(v), 16) for v in reading[4]],
                        "blocked": int(reading[5], 16),
                    })
                    time.sleep(0.095)
            finally:
                state = request(link, b"k", status_pattern)
                report["carrier_confirmed_off"] = state[5] == b"0"
                if not report["carrier_confirmed_off"]:
                    raise RuntimeError("载波关闭未收到确认")
            report["result"] = "captured"
    except (OSError, RuntimeError) as exc:
        report["result"] = "failed"
        report["error"] = str(exc)
    finally:
        save_json(path, report)
        samples = report["samples"]
        print("REPORT:", path)
        print("RESULT:", report["result"], "carrier_off:", report["carrier_confirmed_off"])
        if samples:
            print("PEAK_RANGES:", [(min(s["peaks"][i] for s in samples), max(s["peaks"][i] for s in samples)) for i in range(3)])
            print("BLOCKED_COUNTS:", {m: sum(s["blocked"] == m for s in samples) for m in range(8)})
        if report["result"] == "failed":
            print(report["error"])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
