"""回放已有真实下载报文；只读本地文件，禁止打开串口。"""
import contextlib
import io
import re
import struct
from pathlib import Path
from project import ROOT, digest, save_json


def packets(path, direction):
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    pattern = re.escape(direction) + r' Packet data: ((?:[0-9A-F]{2} ?)+)'
    for match in re.finditer(pattern, text):
        frame = bytes.fromhex(match.group(1))
        # 先核验帧完整性，不能把截断日志当成芯片原始状态。
        if frame[:2] != b'\x46\xb9' or frame[-1:] != b'\x16':
            raise ValueError('帧头或帧尾错误')
        if len(frame) != int.from_bytes(frame[3:5], 'big') + 2:
            raise ValueError('帧长度不匹配')
        if sum(frame[2:-3]) & 0xffff != int.from_bytes(frame[-3:-1], 'big'):
            raise ValueError('帧校验和不匹配')
        yield frame, frame[5:-3]


def audit():
    from stcgal.protocols import Stc8dProtocol
    import stcgal.protocols
    import stcgal.options
    import serial
    from unittest.mock import patch

    before_log = ROOT/'build/MOTOR002-20261110-110103320023.log'
    after_log = ROOT/'build/MOTOR003-20261110-112038267110.log'
    report = {'kind': 'offline_real_packet_replay', 'serial_opened': False,
              'sources': {str(p.relative_to(ROOT)): digest(p) for p in (before_log, after_log)},
              'implementation': {str(Path(m.__file__).relative_to(ROOT)): digest(m.__file__)
                                 for m in (stcgal.protocols, stcgal.options)}}
    # 若今后依赖内部行为改变，测试应直接失败，不允许离线回放误开真实端口。
    with patch.object(serial, 'Serial', side_effect=AssertionError('离线审查禁止打开串口')):
        statuses = []
        for path in (before_log, after_log):
            frame, payload = next((f, p) for f, p in packets(path, '<-') if p[0] == 0x50)
            protocol = Stc8dProtocol('OFFLINE', 2400, 115200, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                protocol.initialize_options(payload)
            statuses.append({'frame_hex': frame.hex(), 'payload_hex': payload.hex(),
                             'msr_hex': bytes(protocol.options.get_msr()).hex(),
                             'decoder': type(protocol.options).__name__,
                             'stc32_field_semantics_verified': False,
                             'reported_low_voltage_reset': protocol.options.get_lvrs(),
                             'reported_low_voltage_threshold': protocol.options.get_low_voltage(),
                             'reported_bsl_pin_detect': protocol.options.get_pindetect()})
        _, option_payload = next((f, p) for f, p in packets(before_log, '->')
                                 if p[:5] == b'\x04\x00\x00\x5a\xa5')
        written = option_payload[5:]
        protocol = Stc8dProtocol('OFFLINE', 2400, 115200, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            protocol.initialize_options(bytes.fromhex(statuses[0]['payload_hex']))
        protocol.trim_frequency = struct.unpack('>I', written[24:28])[0]
        protocol.trim_value = written[28:30]
        protocol.trim_divider = written[30]
        rebuilt = protocol.build_options()
        if rebuilt != written:
            raise RuntimeError('本机选项构造与真实历史发包不一致，停止推断')
    before, after = (bytes.fromhex(s['payload_hex']) for s in statuses)
    report.update(status_before_first_flash=statuses[0], status_before_second_flash=statuses[1],
                  changed_status_bytes=[{'offset': i, 'before': f'{a:02X}', 'after': f'{b:02X}'}
                                        for i, (a, b) in enumerate(zip(before, after)) if a != b],
                  first_flash_option_data_hex=written.hex(),
                  installed_builder_matches_recorded_write=True,
                  decoder_status_offsets=[9,10,11,15,16],
                  interpretation_limits=['STC32复用Stc8Option，未独立核对全部选项字段语义',
                                         'P3.2/P3.3下载条件存在于厂商手册，但本板该设置是否改变仍未知',
                                         '选项写入是先前擦写后的阶段，无法据当前connect失败证明本次无选项写路径有错或已通过'],
                  conclusion='原始配置字节变化已确认；LVR及下载脚检测只是通用解析器报告，真实STC32字段语义和本次连接失败根因仍待验证。')
    return report


if __name__ == '__main__':
    report = audit()
    path = ROOT/'evidence/isp-options-20261110/offline-audit.json'
    save_json(path, report)
    print('PASS: 真实报文校验及本机选项构造回放一致；未打开串口。')
    print(path)
    print('状态变化:', report['changed_status_bytes'])
    print(report['conclusion'])
