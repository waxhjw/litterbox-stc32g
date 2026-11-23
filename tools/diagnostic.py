"""ISP_TEST001专用入口；build/check不打开串口。"""
import argparse
from pathlib import Path
import sys
import tempfile
import time
from project import ROOT, CONFIG, load_json, save_json, resolve, digest, command, tool_env, inspect_hex, ports, require_verified_option_writer

VERSION = 'LB_ISP_TEST001'
SOURCE = ROOT/'diagnostics/ISP_TEST001/main.c'
OUTPUT = ROOT/'output'/VERSION
IMAGE = OUTPUT/(VERSION+'.hex')
MANIFEST = OUTPUT/'manifest.json'
EXTRA_SOURCES = []
TRIM_KHZ = None
WAIT_SECONDS = 60
DRUM_PROFILES = ('DRUM001', 'DRUM002', 'DRUM003', 'DRUM004', 'DRUM005', 'DRUM006', 'DRUM007', 'DRUM008', 'DRUM009', 'DRUM010', 'DRUM011', 'DRUM012', 'DRUM013')
APP_PROFILES = ('APP001', 'APP002', 'APP003', 'APP004', 'APP005') + DRUM_PROFILES
APP_VERSIONS = tuple('LB_'+profile for profile in APP_PROFILES)


def select_profile(profile):
    """固定名单选择诊断用途，旧ISP_TEST001入口默认行为保留。"""
    global VERSION, SOURCE, OUTPUT, IMAGE, MANIFEST, EXTRA_SOURCES, TRIM_KHZ
    if profile in APP_PROFILES:
        VERSION = 'LB_' + profile
        SOURCE = ROOT/('src' if profile in DRUM_PROFILES else 'diagnostics')/profile/'array_main.c'
        OUTPUT = ROOT/'output'/VERSION
        IMAGE = OUTPUT/(VERSION+'.hex')
        MANIFEST = OUTPUT/'manifest.json'
        EXTRA_SOURCES = sorted(SOURCE.parent.glob('*.h'))
        TRIM_KHZ = 11059.2
        return
    if profile in ('ISP_TEST001', 'APP001', 'WIFI001', 'WIFI002', 'MOTOR001', 'MOTOR002', 'MOTOR003', 'IR001', 'IR002', 'IR003', 'IR004', 'IR005', 'IR006', 'IR007', 'IR008', 'IR009', 'IR010', 'IR011', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017'):
        VERSION = 'LB_' + profile
        SOURCE = ROOT/'diagnostics'/profile/'main.c'
        if profile in ('IR006', 'IR007', 'IR008', 'IR009', 'IR010', 'IR011', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017'):
            SOURCE = ROOT/'diagnostics'/profile/'array_main.c'
        OUTPUT = ROOT/'output'/VERSION
        IMAGE = OUTPUT/(VERSION+'.hex')
        MANIFEST = OUTPUT/'manifest.json'
        if profile in ('WIFI001', 'WIFI002'):
            EXTRA_SOURCES = [SOURCE.parent/'tuya_link.h']
        else:
            EXTRA_SOURCES = [] if profile == 'ISP_TEST001' else [SOURCE.parent/'motor_control.h']
        if profile in ('IR001', 'IR002', 'IR003', 'IR004', 'IR005'):
            EXTRA_SOURCES.append(SOURCE.parent/'ir_control.h')
        if profile in ('IR003', 'IR004', 'IR005', 'IR006', 'IR007', 'IR008', 'IR009', 'IR010', 'IR011', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017'):
            EXTRA_SOURCES.append(SOURCE.parent/'motor_ir_guard.h')
        if profile in ('IR006', 'IR007', 'IR008'):
            EXTRA_SOURCES.append(SOURCE.parent/'array_probe_state.h')
        if profile in ('IR008', 'IR009', 'IR010', 'IR011', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017'):
            EXTRA_SOURCES.append(SOURCE.parent/'ir_carrier_state.h')
        if profile in ('IR009', 'IR010', 'IR011', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017'):
            EXTRA_SOURCES.append(SOURCE.parent/'ir_beam_state.h')
        TRIM_KHZ = None if profile == 'ISP_TEST001' else 11059.2
    else:
        raise ValueError('未知诊断版本')


def build(cfg):
    if VERSION in APP_VERSIONS:
        return build_app001(cfg)
    k = resolve(cfg['toolchain'])
    compiler_options = ['OPTIMIZE(9,SIZE)'] if VERSION in ('LB_IR003', 'LB_IR004', 'LB_IR005', 'LB_IR006', 'LB_IR007', 'LB_IR008', 'LB_IR009', 'LB_IR010', 'LB_IR011', 'LB_IR012', 'LB_IR013', 'LB_IR014', 'LB_IR015', 'LB_IR016', 'LB_IR017', 'LB_WIFI001', 'LB_WIFI002', 'LB_APP001') else []
    if VERSION in ('LB_IR004', 'LB_IR005', 'LB_IR006', 'LB_IR007', 'LB_IR008', 'LB_IR009', 'LB_IR010', 'LB_IR011', 'LB_IR012', 'LB_IR013', 'LB_IR014', 'LB_IR015', 'LB_IR016', 'LB_IR017', 'LB_WIFI001', 'LB_WIFI002', 'LB_APP001'):
        # 厂商ROM(SMALL)使用同一2KB页内的ACALL/AJMP；链接器仍检查真实地址与许可大小。
        compiler_options.append('ROM(SMALL)')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isp001-', dir=str(ROOT/'build')) as temp:
        temp = Path(temp)
        logs = [command(cmd, temp, tool_env(cfg), keil=True) for cmd in (
            [k/'BIN/C251.EXE', SOURCE, 'SMALL', 'MODSRC', 'INCDIR('+str(SOURCE.parent)+')', 'OBJECT(main.obj)', 'PRINT(main.lst)']+compiler_options,
            [k/'BIN/L251.EXE', 'main.obj', 'TO', VERSION, 'PRINT('+VERSION+'.map)'],
            [k/'BIN/OH251.EXE', VERSION, 'HEXFILE('+VERSION+'.hex)', 'H386'],
        )]
        # 只接受已知评估许可证提示；截断/指针等语义警告不作为可交付产物。
        import re
        warnings = re.findall(r'\*\*\* WARNING (\w+)', '\n'.join(logs))
        if any(code != 'C500' for code in warnings):
            raise RuntimeError('存在非许可编译警告，未更新冻结产物：'+','.join(warnings))
        info = inspect_hex(temp/(VERSION+'.hex'))
        if MANIFEST.exists() and load_json(MANIFEST)['sha256'] != info['sha256']:
            raise RuntimeError(VERSION+'已有不同产物，需递增诊断版本，不能覆盖冻结文件')
        for name in ('main.obj','main.lst',VERSION,VERSION+'.map',VERSION+'.hex'):
            (OUTPUT/name).write_bytes((temp/name).read_bytes())
        (OUTPUT/'main.c').write_bytes(SOURCE.read_bytes())
        for extra in EXTRA_SOURCES:
            (OUTPUT/extra.name).write_bytes(extra.read_bytes())
        (OUTPUT/'build.log').write_text('\n'.join(logs), encoding='utf-8')
    save_json(MANIFEST, dict(info, version=VERSION, kind='diagnostic', model=cfg['model'],
              source_sha256=digest(SOURCE), tool_sha256=digest(Path(__file__)),
              hardware_tested=False,
              purpose=('App DP5 pause bench; motor outputs forced low' if VERSION=='LB_WIFI002' else
                       'WBR3 communication and pairing bench; motor outputs forced low' if VERSION=='LB_WIFI001' else
                       'radar-triggered stop with three-beam and Hall interlocks' if VERSION=='LB_IR017' else
                       'three-beam motor interlock with read-only Hall diagnostics' if VERSION in ('LB_IR014', 'LB_IR015', 'LB_IR016') else
                       'three-beam motor interlock bench test' if VERSION=='LB_IR013' else 'serial ISP download test only'),
              original_functions_inherited=False, rollback_firmware_available=False,
              compiler_license='official C251 evaluation 2KB', compiler_options=compiler_options, trim_khz=TRIM_KHZ,
              extra_sources={p.name:digest(p) for p in EXTRA_SOURCES},
              diagnostic_scope=('WBR3 UART3, Wi-Fi handshake, and validated DP5 pause state; local motion disabled'
                                if VERSION=='LB_WIFI002' else
                                'WBR3 UART3, Wi-Fi handshake, explicit pairing, and passive DP counters; local motion disabled'
                                if VERSION=='LB_WIFI001' else
                                'three-beam motor interlock; old single IR link temporarily inactive; motor-only bench test explicitly enabled'
                                if VERSION in ('LB_IR013', 'LB_IR014', 'LB_IR015', 'LB_IR016', 'LB_IR017') else
                                'array raw ADC and bounded pin probes; old single IR link temporarily inactive; motor key and stop retained'
                                if VERSION in ('LB_IR006', 'LB_IR007', 'LB_IR008', 'LB_IR009', 'LB_IR010', 'LB_IR011', 'LB_IR012') else 'existing diagnostic'),
              purpose_detail=('independent App bench; WIFI001 for network and IR017 for local-control rollback'
                              if VERSION=='LB_WIFI002' else
                              'independent Wi-Fi bench approved; IR017 remains the local-control rollback'
                              if VERSION=='LB_WIFI001' else
                              'IR016 plus raw P4.7 radar diagnostics and a configurable stop interlock; IRC status'
                              if VERSION=='LB_IR017' else
                              'IR015 plus hall-low precondition for initial motor output; IRB status'
                              if VERSION=='LB_IR016' else
                              'IR014 Hall diagnostics with silent handling of undocumented serial bytes'
                              if VERSION=='LB_IR015' else
                              'IR013 plus high-impedance HLR1/HLR2 and read-only h command; existing IRA status and motor behaviour retained'
                              if VERSION=='LB_IR014' else
                              'IR012 plus automatic carrier and three-beam stop/resume interlock; snapshot samples and diagnostics; ID IRA'
                              if VERSION=='LB_IR013' else
                              'IR011 plus cross-window contamination guard: sampling rounds cut 4->2 and start gate 45->55 ticks so a batch fits inside the 1ms burst; window sequence number gen aborts a batch the moment the window flips, so leftover rounds never land in the next window peak; close() snapshots peak into last[] and the report prints the snapshot instead of the live accumulator'
                              if VERSION=='LB_IR012' else
                              'IR010 plus whole-window sampling gate: only start sampling at burst_ticks>=45 so a window is used only if a full 4-round peak fits inside it; half-window peaks are discarded instead of counted as blocked'
                              if VERSION=='LB_IR011' else
                              'IR009 plus motor tick restored to 100us base (8 half-ticks, IR008 wrongly used 8200 = 10.8s per tick); window-synchronised peak sampling with 4-window confirmation per channel; reports blocked mask only, no IR stop decisions'
                              if VERSION=='LB_IR010' else
                              'three channel raw ADC14/0/1 with 38.13kHz carrier on P0.4/P5.2/P5.3, 1ms burst per 10ms window, window-synchronised peak sampling with 4-window confirmation per channel; reports blocked mask only, no IR stop decisions'
                              if VERSION=='LB_IR009' else
                              'three channel raw ADC14/0/1 with 38.13kHz software carrier on P0.4/P5.2/P5.3; 1ms burst per 10ms window; sync and rotate modes; no uncalibrated IR stop decisions'
                              if VERSION=='LB_IR008' else
                              'three channel raw ADC14/0/1; 5ms pin probes with 100ms cooldown; long-press motor retained; no uncalibrated IR stop decisions'
                              if VERSION=='LB_IR006' else
                              'IR006 sampling plus internal 4k pull-ups on P0.6/P1.0/P1.1; probing suspected open-collector receivers; no IR stop decisions'
                              if VERSION=='LB_IR007' else
                              '3s key starts motor and IR with default high-pulse link; arm on first valid beam; block pauses and clear 10s resumes; manual off stops both'
                              if VERSION == 'LB_IR005' else
                              '3s key starts motor and IR; arm on first valid beam; block pauses and clear 10s resumes; manual off stops both'
                              if VERSION == 'LB_IR004' else
                              'beam interruption inhibits motor; clear for 10s permits requested run; raw IR and bounded tests retained'
                              if VERSION == 'LB_IR003' else
                              'raw IR input and bounded 36/38/40kHz burst test; inherits MOTOR003; startup TX off'
                              if VERSION.startswith('LB_IR') else
                              ('any single key' if VERSION == 'LB_MOTOR003' else 'CLEAN') +
                              ' hold 3s toggles continuous motor; startup stopped; no original protections'
                              if TRIM_KHZ else 'no GPIO download test')))
    print('PASS:', VERSION, '诊断固件编译通过，不是产品程序。')
    print(IMAGE, info)


def build_app001(cfg):
    from stcgal.ihex import IHex

    sys.stdout.reconfigure(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='stcide-', dir=str(ROOT/'build')) as name:
        directory = Path(name)
        raw = directory/'stcide.hex'
        log = command(['node', ROOT/'tools/stcide_compile.mjs', SOURCE.parent, raw], ROOT, encoding='utf-8')
        candidate = directory/(VERSION+'.hex')
        records = raw.read_bytes().splitlines()
        if not records or any(line[7:9] not in (b'00', b'01') for line in records):
            raise RuntimeError('厂商 HEX 需要从 16 位偏移转换到 STC32G 程序区')
        # STC IDE 的 0000H 复位偏移对应 STC32G8K64 的 FF0000H。
        candidate.write_bytes(b':0200000400FFFB\n' + b'\n'.join(records) + b'\n')
        info = inspect_hex(candidate)
        identity = (VERSION[3:] + ' N=').encode('ascii')
        if identity not in IHex.read(candidate.read_bytes().splitlines()).extract_data():
            raise RuntimeError('目标镜像串口身份与构建版本不一致')
        if MANIFEST.exists() and load_json(MANIFEST)['sha256'] != info['sha256']:
            raise RuntimeError(VERSION+'已有不同的冻结镜像')
        OUTPUT.mkdir(parents=True, exist_ok=True)
        IMAGE.write_bytes(candidate.read_bytes())
        (OUTPUT/'main.c').write_bytes(SOURCE.read_bytes())
        for header in EXTRA_SOURCES:
            (OUTPUT/header.name).write_bytes(header.read_bytes())
        (OUTPUT/'listing.asm').write_bytes(raw.with_suffix('.hex.asm').read_bytes())
        (OUTPUT/'build.log').write_text(log, encoding='utf-8')
    save_json(MANIFEST, dict(info, version=VERSION, kind='diagnostic', model=cfg['model'],
              source_sha256=digest(SOURCE), tool_sha256=digest(Path(__file__)),
              compiler_cache_sha256=digest(ROOT/'.tools/stc-ide/manifest.json'),
              extra_sources={header.name:digest(header) for header in EXTRA_SOURCES},
              trim_khz=TRIM_KHZ, hardware_tested=False,
              purpose=('Unloaded two-round motor exercise; physical drum position remains unknown'
                       if VERSION in ('LB_DRUM004', 'LB_DRUM005', 'LB_DRUM006', 'LB_DRUM007', 'LB_DRUM008', 'LB_DRUM009', 'LB_DRUM010', 'LB_DRUM011', 'LB_DRUM012', 'LB_DRUM013') else
                       'APP004-based drum cycle, bench only before commissioning'
                       if VERSION[3:] in DRUM_PROFILES else
                       'IR017 + WIFI002 manual-clean request through the shared motor interlock')))
    print('PASS:', IMAGE, info)


def check(cfg):
    manifest = load_json(MANIFEST)
    if manifest['version'] != VERSION or manifest['kind'] != 'diagnostic' or manifest['model'] != cfg['model']:
        raise RuntimeError('诊断清单用途、版本或型号不匹配')
    if digest(SOURCE) != manifest['source_sha256'] or digest(OUTPUT/'main.c') != manifest['source_sha256']:
        raise RuntimeError('诊断源码已变更，需递增版本重新构建')
    for extra in EXTRA_SOURCES:
        expected = manifest.get('extra_sources', {}).get(extra.name)
        if digest(extra) != expected or digest(OUTPUT/extra.name) != expected:
            raise RuntimeError('诊断配套源码与冻结清单不一致')
    if manifest.get('trim_khz') != TRIM_KHZ:
        raise RuntimeError('诊断时钟与构建清单不一致')
    info = inspect_hex(IMAGE)
    if info['sha256'] != manifest['sha256']:
        raise RuntimeError('诊断HEX与构建清单不匹配')
    port = ports(cfg)
    print('PASS: 诊断文件、HEX-386和端口枚举通过；未打开串口。')
    print('IMAGE:', IMAGE, 'SHA256:', info['sha256'], flush=True)
    return port


def preflight(cfg):
    port = check(cfg)
    if VERSION in ('LB_IR015', 'LB_IR016', 'LB_IR017', 'LB_WIFI001', 'LB_WIFI002') + APP_VERSIONS:
        from isp_no_options import require_application_silent
        require_application_silent(port, cfg['baud'])
        print('预检未收到应用应答。等待主板冷启动。', flush=True)
    return port


def flash(cfg, write=True, debug=False, transfer_baud=None):
    # 2026-11-11用户明确同意IR006临时采样范围，沿用已核对的无0x04路径。
    preserve_options = VERSION in ('LB_IR002', 'LB_IR003', 'LB_IR004', 'LB_IR005', 'LB_IR006', 'LB_IR007', 'LB_IR008', 'LB_IR009', 'LB_IR010', 'LB_IR011', 'LB_IR012', 'LB_IR013', 'LB_IR014', 'LB_IR015', 'LB_IR016', 'LB_IR017', 'LB_WIFI001', 'LB_WIFI002') + APP_VERSIONS
    if write and not preserve_options:
        require_verified_option_writer()
    port = preflight(cfg) if write else check(cfg)
    transfer_baud = transfer_baud or cfg['baud']
    from stcgal import frontend
    original_gal_class = frontend.StcGal
    original_argv = sys.argv[:]
    from stcgal.protocols import StcProtocolException
    # 下载日志分阶段保留。工具写入应答通过不等于独立读回或启动验收。
    state = {'version': VERSION, 'image_sha256': digest(IMAGE), 'port': port,
             'stage': 'connect', 'completed': [], 'independent_readback': 'not_available',
             'startup': 'not_tested', 'functional_regression': 'not_applicable_diagnostic'}
    state['mode'] = 'flash' if write else 'identify_only'
    state['transfer_baud'] = transfer_baud
    prefix = VERSION[3:]
    evidence = ROOT/'build'/(prefix+('-last-attempt.json' if write else '-probe.json'))
    state['trim_khz'] = TRIM_KHZ if write and not preserve_options else None
    state['option_policy'] = 'no_option_write' if preserve_options else 'blocked_pending_option_writer'

    def wrap(protocol, method, stage):
        original = getattr(protocol, method)
        def traced(*args, **kwargs):
            state['stage'] = stage
            save_json(evidence, state)
            print('STAGE:', stage, flush=True)
            try:
                result = original(*args, **kwargs)
            except Exception as exc:
                state['failed_stage'] = stage
                state['error'] = str(exc)
                save_json(evidence, state)
                raise
            state['completed'].append(stage)
            save_json(evidence, state)
            return result
        setattr(protocol, method, traced)

    class CheckedGal(frontend.StcGal):
        def initialize_protocol(self, opts):
            super().initialize_protocol(opts)
            protocol = self.protocol
            original_initialize = protocol.initialize
            def recorded_initialize(*args, **kwargs):
                result = original_initialize(*args, **kwargs)
                # 保存完整身份包，不能只保存第三方工具对选项的解释。
                state['status_packet_hex'] = protocol.status_packet.hex()
                state['model'] = protocol.model.name
                if protocol.options is not None:
                    state['options_msr_hex'] = bytes(protocol.options.get_msr()).hex()
                    state['options_decoder'] = type(protocol.options).__name__
                    state['stc32_option_semantics_verified'] = False
                save_json(evidence, state)
                return result
            protocol.initialize = recorded_initialize
            original_connect = protocol.connect
            def bounded_connect(*args, **kwargs):
                deadline = time.monotonic() + WAIT_SECONDS
                original_pulse = protocol.pulse
                def bounded_pulse(character=b'\x7f', timeout=0):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise StcProtocolException('等待主控超过{}秒，停止本次连接；未进入擦除阶段'.format(WAIT_SECONDS))
                    # stcgal的pulse默认会无限等待，必须把剩余时间传入底层。
                    return original_pulse(character, timeout=min(timeout or remaining, remaining))
                protocol.pulse = bounded_pulse
                try:
                    return original_connect(*args, **kwargs)
                finally:
                    protocol.pulse = original_pulse
            protocol.connect = bounded_connect

        def initialize_protocol_checked_model(self):
            if self.protocol.model.name != cfg['model']:
                raise StcProtocolException('实际型号不匹配，停止试验')

        def run(self):
            result = super().run()
            if result == 0 and not write:
                self.initialize_protocol_checked_model()
                state['completed'].append('identify:'+self.protocol.model.name)
            return result

        def program_mcu(self):
            if self.protocol.model.name != cfg['model']:
                raise StcProtocolException('实际型号不匹配，拒绝擦除/写入')
            state['completed'].append('identify:'+self.protocol.model.name)
            if VERSION in ('LB_IR014', 'LB_IR015', 'LB_IR016', 'LB_IR017', 'LB_WIFI001', 'LB_WIFI002') + APP_VERSIONS:
                from functools import partial
                from isp_no_options import handshake_skip_leading_bytes
                self.protocol.handshake = partial(
                    handshake_skip_leading_bytes, self.protocol, self.protocol.handshake,
                    each_response=VERSION in ('LB_WIFI001', 'LB_WIFI002') + APP_VERSIONS,
                )
            for method, stage in [('handshake','handshake'),('erase_flash','erase'),
                                  ('program_flash','write_ack'),('program_options','options'),
                                  ('disconnect','disconnect')]:
                wrap(self.protocol, method, stage)
            if preserve_options:
                from isp_no_options import program_without_options
                def skipped_options():
                    state['hardware_options_write'] = 'skipped_no_0x04_command'
                    state['nonvolatile_original_options_restored'] = False
                    save_json(evidence, state)
                    print('OPTIONS: skipped; no hardware-option write command', flush=True)
                program_without_options(self, super().program_mcu, skipped_options)
            else:
                super().program_mcu()
    frontend.StcGal = CheckedGal
    # IR014 已实际识别为 STC32G8K64/stc8d，直接按偶校验进入，避免在识别后切换串口校验。
    protocol_name = 'stc8d' if VERSION in ('LB_IR014', 'LB_IR015', 'LB_IR016', 'LB_IR017', 'LB_WIFI001', 'LB_WIFI002') + APP_VERSIONS else 'auto'
    sys.argv = ['stcgal','-P',protocol_name,'-p',port,'-b',str(transfer_baud),
                '-l',str(cfg['handshake_baud'])]
    if write:
        if TRIM_KHZ is not None and not preserve_options:
            sys.argv.extend(['-t', str(TRIM_KHZ)])
        sys.argv.append(str(IMAGE))
    if debug:
        sys.argv.append('-D')
    print('等待目标冷启动，最多{}秒。模式：'.format(WAIT_SECONDS)+('下载诊断固件' if write else '只识别，不擦除不写入'), flush=True)
    save_json(evidence, state)
    try:
        result = frontend.cli()
        state['exit_code'] = result
        state['result'] = 'tool_flow_completed' if result == 0 else 'failed'
        save_json(evidence, state)
        raise SystemExit(result)
    except KeyboardInterrupt:
        state['result'] = 'interrupted'
        save_json(evidence, state)
        raise SystemExit(2)
    except Exception as exc:
        state['result'] = 'failed'
        state['failed_stage'] = state.get('failed_stage', state['stage'])
        state['error'] = str(exc)
        save_json(evidence, state)
        raise
    finally:
        frontend.StcGal = original_gal_class
        sys.argv = original_argv


def probe(cfg, debug=False):
    return flash(cfg, write=False, debug=debug)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['build','check','preflight','probe','flash'])
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--profile', choices=('ISP_TEST001','WIFI001','WIFI002','MOTOR001','MOTOR002','MOTOR003','IR001','IR002','IR003','IR004','IR005','IR006','IR007','IR008','IR009','IR010', 'IR011', 'IR012', 'IR013', 'IR014', 'IR015', 'IR016', 'IR017') + APP_PROFILES, default='ISP_TEST001')
    parser.add_argument('--wait-seconds', type=int, choices=range(10,301), default=60, metavar='10..300')
    parser.add_argument('--transfer-baud', type=int, choices=(38400, 57600, 115200))
    args = parser.parse_args()
    select_profile(args.profile)
    WAIT_SECONDS = args.wait_seconds
    action = args.action
    try:
        if action == 'flash':
            flash(load_json(CONFIG), debug=args.debug, transfer_baud=args.transfer_baud)
        elif action == 'probe':
            probe(load_json(CONFIG), debug=args.debug)
        else:
            {'build':build,'check':check,'preflight':preflight}[action](load_json(CONFIG))
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print('FAIL:', exc, file=sys.stderr)
        raise SystemExit(1)
