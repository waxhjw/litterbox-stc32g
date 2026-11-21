"""猫砂盆环境入口。doctor/validate/flash-check均不打开串口。"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/project.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def resolve(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def tool_env(cfg):
    k = resolve(cfg['toolchain'])
    return dict(os.environ, C251INC=str(k/'INC'), C251LIB=str(k/'LIB'))


def command(argv, cwd, env=None, keil=False, encoding='mbcs'):
    print('RUN:', subprocess.list2cmdline([str(x) for x in argv]), flush=True)
    result = subprocess.run([str(x) for x in argv], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = result.stdout.decode(encoding, errors='replace')
    print(output, flush=True)
    # Keil退出码1表示警告；转换器可能以0退出却在文字中报告错误，必须双重核验。
    allowed = (0, 1) if keil else (0,)
    if result.returncode not in allowed or '*** ERROR' in output or 'FATAL-ERROR' in output:
        raise RuntimeError('工具失败，退出码 {}'.format(result.returncode))
    return output


def ports(cfg):
    from serial.tools.list_ports import comports
    available = list(comports())
    found = [p for p in available if p.vid == cfg['usb_vid'] and p.pid == cfg['usb_pid']]
    adapter = cfg.get('serial_adapter', 'USB-TTL')
    for p in found:
        print(adapter + '串口:', p.device, p.description, p.hwid)
    # 列举设备不会打开串口，更不会切换DTR/RTS。
    if len(found) != 1:
        visible = ', '.join('{} {}'.format(p.device, p.hwid) for p in available) or '无'
        raise RuntimeError('需要唯一一只{}串口（VID={:04X}/PID={:04X}），当前数量：{}。已枚举：{}'.format(
            adapter, cfg['usb_vid'], cfg['usb_pid'], len(found), visible))
    return found[0].device


def inspect_hex(path):
    from stcgal.ihex import IHex
    raw = path.read_bytes()
    base = 0
    data = {}
    eof = False
    linear = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        if eof:
            raise ValueError('HEX结束标记后存在额外记录')
        text = line.strip()
        if not text.startswith(b':'):
            raise ValueError('HEX记录格式错误')
        record = bytes.fromhex(text[1:].decode('ascii'))
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) % 256:
            raise ValueError('HEX长度或校验和错误')
        size, kind = record[0], record[3]
        addr = int.from_bytes(record[1:3], 'big')
        payload = record[4:-1]
        if kind == 4 and size == 2 and addr == 0:
            linear = True
            base = int.from_bytes(payload, 'big') << 16
        elif kind == 0:
            if addr + size > 0x10000:
                raise ValueError('HEX记录跨64KB边界')
            for offset, value in enumerate(payload):
                absolute = base + addr + offset
                if absolute < 0xFF0000 or absolute > 0xFFFFFF or absolute in data:
                    raise ValueError('HEX地址越界或重复，不属于本型号64KB程序区')
                data[absolute] = value
        elif kind == 1 and size == 0 and addr == 0:
            eof = True
        elif kind == 5 and size == 4 and addr == 0:
            pass
        else:
            raise ValueError('不支持的HEX记录')
    if not eof or not linear or 0xFF0000 not in data:
        raise ValueError('需要含复位地址及结束记录的HEX-386固件')
    parsed = IHex.read(raw.splitlines())
    if parsed.get_mode() != 32 or len(parsed.extract_data()) > 65536:
        raise ValueError('实际stcgal解析结果与64KB MCS251格式不兼容')
    return {'bytes': len(data), 'start': hex(min(data)), 'end': hex(max(data)), 'sha256': digest(path)}


def doctor(cfg):
    k = resolve(cfg['toolchain'])
    for name in ('C251.EXE', 'L251.EXE', 'OH251.EXE', 'A251.EXE'):
        p = k/'BIN'/name
        if not p.is_file():
            raise FileNotFoundError(p)
        print('OK:', name, p)
    from stcgal.models import MCUModelDatabase
    if not any(m.name == cfg['model'] and m.mcs251 for m in MCUModelDatabase.models):
        raise RuntimeError('已安装stcgal未包含目标型号')
    print('stcgal:', importlib.metadata.version('stcgal'), '型号:', cfg['model'])
    command([sys.executable, '-m', 'stcgal', '-h'], ROOT)
    port = ports(cfg)
    print('PASS: 工具和串口枚举正常；未打开串口，未连接目标。')
    report = {'model': cfg['model'], 'port': port, 'adapter': cfg.get('serial_adapter', 'USB-TTL'),
              'usb_vid': cfg['usb_vid'], 'usb_pid': cfg['usb_pid'], 'serial_opened': False,
              'target_connected': False, 'stcgal': importlib.metadata.version('stcgal'),
              'compiler_license': 'evaluation-2KB',
              'tools': {n: digest(k/'BIN'/n) for n in ('C251.EXE','L251.EXE','OH251.EXE')}}
    save_json(ROOT/'build/environment.json', report)


def validate(cfg):
    import tempfile
    k = resolve(cfg['toolchain'])
    build = ROOT/'build/validation'
    build.mkdir(parents=True, exist_ok=True)
    env = tool_env(cfg)
    commands = [
        [k/'BIN/C251.EXE', ROOT/'validation/main.c', 'SMALL', 'MODSRC',
         'OBJECT(main.obj)', 'PRINT(main.lst)'],
        [k/'BIN/L251.EXE', 'main.obj', 'TO', 'environment-only', 'PRINT(environment-only.map)'],
        [k/'BIN/OH251.EXE', 'environment-only', 'HEXFILE(environment-only.hex)', 'H386'],
    ]
    # 每次新建构建目录，失败不会残留看似最新的验证产物。
    with tempfile.TemporaryDirectory(prefix='c251-', dir=str(build)) as temp:
        temp = Path(temp)
        logs = [command(c, temp, env, keil=True) for c in commands]
        image = temp/'environment-only.hex'
        info = inspect_hex(image)
        for name in ('main.obj','main.lst','environment-only','environment-only.map','environment-only.hex'):
            (build/name).write_bytes((temp/name).read_bytes())
        (build/'build.log').write_text('\n'.join(logs), encoding='utf-8')
    save_json(build/'manifest.json', dict(info, kind='environment-validation',
              flashable=False, source_sha256=digest(ROOT/'validation/main.c'),
              hardware_tested=False, compiler_license='evaluation-2KB'))
    print('PASS: 编译、链接、HEX-386及实际stcgal解析通过。仅离线验证，禁止烧录。')


def product_config(cfg):
    product = cfg['product']
    if not all(product.get(key) for key in ('keil_project','target','hex')):
        raise RuntimeError('尚未导入原厂完整源码：请在config/project.json配置产品工程、目标和HEX路径。当前仅环境验证可构建。')
    return product


def build_product(cfg):
    p = product_config(cfg)
    project = resolve(p['keil_project'])
    image = resolve(p['hex'])
    if not project.is_file():
        raise FileNotFoundError(project)
    log = ROOT/'build/product-build.log'
    log.parent.mkdir(exist_ok=True)
    before = image.stat().st_mtime_ns if image.exists() else None
    command([resolve(cfg['uv4']), '-r', project, '-t', p['target'], '-o', log],
            project.parent, tool_env(cfg), keil=True)
    if not log.is_file():
        raise RuntimeError('Keil没有生成构建日志')
    text = log.read_bytes().decode('mbcs', errors='replace')
    print(text)
    import re
    if not re.search(r'0 Error\(s\)', text) or '*** ERROR' in text:
        raise RuntimeError('产品构建日志未确认0个错误')
    if not image.is_file() or image.stat().st_mtime_ns == before:
        raise RuntimeError('构建没有生成新的HEX，拒绝使用旧产物')
    info = inspect_hex(image)
    save_json(ROOT/'build/product-manifest.json', dict(info, kind='product', model=cfg['model'],
              hex=str(image.resolve()), project_sha256=digest(project), hardware_tested=False))
    print('PASS: 产品构建完成；硬件待验证。')


def flash_check(cfg):
    # 所有校验都在连接串口前完成，禁止把validation产物当作产品固件。
    p = product_config(cfg)
    manifest = load_json(ROOT/'build/product-manifest.json')
    image = resolve(p['hex']).resolve()
    if ROOT/'build/validation' in image.parents or ROOT/'validation' in image.parents:
        raise RuntimeError('环境验证产物禁止烧录')
    if manifest.get('kind') != 'product' or manifest.get('model') != cfg['model']:
        raise RuntimeError('产品构建清单的用途或型号不匹配')
    if str(image) != manifest.get('hex') or digest(image) != manifest.get('sha256'):
        raise RuntimeError('产品HEX路径或校验值与最近构建不匹配')
    if digest(resolve(p['keil_project'])) != manifest.get('project_sha256'):
        raise RuntimeError('产品工程配置已改变，需要重新构建')
    info = inspect_hex(image)
    port = ports(cfg)
    print('PASS: 离线烧录检查通过；未打开串口。', image, info['sha256'])
    return image, port


def flash(cfg):
    require_verified_option_writer()
    image, port = flash_check(cfg)
    print('准备串口ISP下载：请按已确认接线供电条件操作；必要时手动断电再上电。', flush=True)
    from stcgal import frontend
    from stcgal.protocols import StcProtocolException
    original = frontend.StcGal

    class CheckedGal(original):
        def program_mcu(self):
            # 实际型号在握手后检查；不匹配时在擦除前拒绝。
            if self.protocol.model.name != cfg['model']:
                raise StcProtocolException('目标型号不匹配，拒绝擦除/写入')
            super().program_mcu()

    frontend.StcGal = CheckedGal
    sys.argv = ['stcgal', '-P', 'auto', '-p', port, '-b', str(cfg['baud']),
                '-l', str(cfg['handshake_baud']), str(image)]
    # 不使用自动复位、擦除专用参数或自定义时钟参数。
    raise SystemExit(frontend.cli())


def require_verified_option_writer():
    """已有真实报文显示选项变化；布局核实并修复前在打开串口之前停止。"""
    raise RuntimeError('暂停烧录：STC32G硬件选项保持尚未验证；历史下载前后配置字节已变化。'
                       '未打开串口、未擦写。可继续构建、离线检查、查询应用状态；详见docs/MOTOR003.md。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['doctor','validate','build','flash-check','flash'])
    args = parser.parse_args()
    cfg = load_json(CONFIG)
    {'doctor': doctor, 'validate': validate, 'build': build_product,
     'flash-check': flash_check, 'flash': flash}[args.action](cfg)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print('FAIL:', exc, file=sys.stderr)
        sys.exit(1)
