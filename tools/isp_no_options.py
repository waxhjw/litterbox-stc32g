"""IR002限定下载：参照厂商STC32G手册10.3，不发送硬件选项写命令。"""
import time

import serial
from stcgal.protocols import StcFramingException


def require_application_silent(port, baud):
    """正常应用有应答时停止，避免用 ISP 同步字节喂给仍在运行的应用。"""
    with serial.Serial(port=None, baudrate=baud, timeout=0.18, write_timeout=0.2) as closed:
        closed.dtr = False
        closed.rts = False
        closed.port = port
        closed.open()
        for _ in range(3):
            closed.write(b'?')
            if closed.read(1):
                raise RuntimeError('应用串口仍有应答，暂不发送 ISP 同步；请在主板 12V 断开时启动下载。')


def handshake_skip_leading_bytes(protocol, handshake, each_response=False):
    """限时跳过握手包头前的少量字节，保持 stcgal 的校验和及命令验证。"""
    read_packet = protocol.read_packet

    def read_response():
        if not each_response:
            protocol.read_packet = read_packet
        old_timeout = protocol.ser.timeout
        deadline = time.monotonic() + 1.5
        try:
            for _ in range(12):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                protocol.ser.timeout = remaining
                try:
                    return read_packet()
                except StcFramingException as exc:
                    if str(exc) != 'incorrect frame start':
                        raise
            raise StcFramingException('handshake response could not synchronize')
        finally:
            protocol.ser.timeout = old_timeout

    protocol.read_packet = read_response
    try:
        return handshake()
    finally:
        protocol.read_packet = read_packet


def program_without_options(gal, original_program, on_skip):
    p = gal.protocol
    if p.model.name != 'STC32G8K64' or not p.model.mcs251:
        raise RuntimeError('不写选项流程仅核对了STC32G8K64')
    if gal.opts.option or gal.opts.eeprom_image or gal.opts.trim or gal.opts.erase:
        raise RuntimeError('本流程禁止修改硬件选项、EEPROM或非易失时钟参数')
    # 不写选项就不保存新的时钟校准；应用只接受原有约11.0592MHz的板。
    if abs(p.mcu_clock_hz / 11059200 - 1) > 0.005:
        raise RuntimeError('原有时钟与IR002要求偏差超过0.5%，在擦除前停止')
    write_packet, options = p.write_packet, p.program_options

    def guarded_write(data, *args, **kwargs):
        if data and data[0] == 0x04:
            raise RuntimeError('不写选项流程禁止0x04硬件选项命令')
        return write_packet(data, *args, **kwargs)

    p.write_packet = guarded_write
    p.program_options = on_skip
    try:
        return original_program()
    finally:
        p.write_packet, p.program_options = write_packet, options
