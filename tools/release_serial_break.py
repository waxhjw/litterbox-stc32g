"""结束辅助试验后恢复串口空闲状态；不发送字节、不复位、不擦写。"""
import serial
from serial import win32
from project import CONFIG, load_json, ports

link=serial.Serial(port=None, baudrate=115200, timeout=0.1)
link.dtr=False
link.rts=False
link.port=ports(load_json(CONFIG))
with link:
    if not win32.ClearCommBreak(link._port_handle):
        raise RuntimeError('Windows拒绝清除串口BREAK')
print('PASS: Windows ClearCommBreak返回成功；已关闭端口，未发送字节。')
