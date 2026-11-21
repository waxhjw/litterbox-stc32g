"""读取独立 Wi-Fi 台架。配网命令单独执行，状态记录仅包含协议计数。"""
import argparse
from datetime import datetime
import re
import time

import serial
from project import CONFIG, ROOT, load_json, ports, save_json


NETWORK = {0: "EZ", 1: "AP", 2: "未连路由器", 3: "路由器已连", 4: "云端已连", 6: "EZ/AP"}
STATUS_FIELDS = {"WIFI001": "BNHPMSAQDETO", "WIFI002": "BNHPMSAQDETOIUVKRX"}


def query(link, command, profile):
    link.reset_input_buffer()
    link.write(command)
    line = link.read_until(b"\n", size=128).strip()
    pattern = profile.encode("ascii") + b"".join(
        f" {field}=[0-9A-F]{{2}}".encode("ascii") for field in STATUS_FIELDS[profile]
    )
    if not re.fullmatch(pattern, line):
        raise RuntimeError(f"未收到完整 {profile} 状态，请检查板内版本及串口")
    status = {item[0]: int(item[2:], 16) for item in line.decode("ascii").split()[1:]}
    if status["O"] != 0:
        raise RuntimeError("台架电机输出异常")
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("status", "watch", "pair", "baud"))
    ap.add_argument("--profile", choices=STATUS_FIELDS, default="WIFI001")
    ap.add_argument("--seconds", type=int, default=60)
    args = ap.parse_args()
    config = load_json(CONFIG)
    port = ports(config)
    path = ROOT / "build" / f"{args.profile}-{args.action}-{datetime.now():%Y%m%d-%H%M%S%f}.json"
    report = {"port": port, "action": args.action, "samples": []}
    link = serial.Serial(port=None, baudrate=config["baud"], timeout=0.4, write_timeout=0.2)
    link.dtr = False
    link.rts = False
    link.port = port

    def capture(status):
        report["samples"].append(status)
        print(args.profile, status, NETWORK.get(status["N"], "未知"), flush=True)
        save_json(path, report)

    with link:
        print("REPORT:", path, flush=True)
        status = query(link, b"?", args.profile)
        capture(status)
        if args.action == "pair":
            if status["A"] or status["H"] == 0 or not (status["P"] and status["M"] or status["S"]):
                raise SystemExit("串口尚未就绪或本次上电已提交配网")
            capture(query(link, b"p", args.profile))
        elif args.action == "baud":
            if status["H"]:
                raise SystemExit("已有有效心跳，当前波特率保持")
            capture(query(link, b"b", args.profile))
        elif args.action == "watch":
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                time.sleep(0.9)
                state = query(link, b"?", args.profile)
                if state != status:
                    record = {"at": datetime.now().isoformat(timespec="seconds"), **state}
                    capture(record)
                status = state


if __name__ == "__main__":
    main()
