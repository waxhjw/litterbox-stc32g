"""实际stcgal HEX解析/下载流程/分块实现，传输层离线应答；不证明硬件通过。"""
import argparse
from pathlib import Path
import re
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from project import ROOT
from stcgal.frontend import StcGal
from stcgal.protocols import Stc8dProtocol, StcFramingException
from stcgal.models import MCUModelDatabase
from isp_no_options import handshake_skip_leading_bytes, program_without_options


class NoOptionsTest(unittest.TestCase):
    def replay_image(self, profile, expected_blocks):
        p = Stc8dProtocol('OFFLINE', 2400, 115200, 0)
        p.model = next(m for m in MCUModelDatabase.models if m.name == 'STC32G8K64')
        p.bsl_version = 0x74
        p.mcu_clock_hz = 11057000
        p.ser = SimpleNamespace(close=lambda: None)
        sent = []
        p.write_packet = lambda data, *args, **kwargs: sent.append(bytes(data))
        def response():
            cmd = sent[-1][0]
            if cmd == 3: return bytes.fromhex('03f854ca24072770')
            if cmd in (2, 0x22): return b'\x02\x54'
            if cmd == 7: return b'\x07\x54'
            raise AssertionError('未知离线应答命令')
        p.read_packet = response
        p.handshake = Mock()  # 校准/串口握手不在本次离线证明范围。
        p.progress_cb = lambda *args: None
        skipped = Mock()
        with (ROOT/'output'/('LB_'+profile)/('LB_'+profile+'.hex')).open('rb') as image:
            opts = argparse.Namespace(option=None, eeprom_image=None, trim=0, erase=False, code_image=image)
            gal = object.__new__(StcGal)
            gal.protocol, gal.opts = p, opts
            program_without_options(gal, gal.program_mcu, skipped)
        commands = [data[0] for data in sent]
        self.assertNotIn(4, commands)
        self.assertEqual(commands[0], 3)
        self.assertEqual(commands[1], 0x22)
        self.assertEqual(commands[-2:], [7, 0xff])
        self.assertEqual(sum(cmd in (2, 0x22) for cmd in commands), expected_blocks)
        skipped.assert_called_once()
        p.handshake.assert_called_once()

    def test_ir002_installed_programming_flow(self):
        self.replay_image('IR002', 32)

    def test_ir003_installed_programming_flow(self):
        self.replay_image('IR003', 40)

    def test_ir004_installed_programming_flow(self):
        self.replay_image('IR004', 40)

    def test_ir006_image_flow_offline_only(self):
        # 实际前端把1601字节解析镜像按512字节补齐到2048，再以64字节分块。
        self.replay_image('IR006', 32)

    def test_ir013_image_flow_offline_only(self):
        self.replay_image('IR013', 40)

    def test_ir014_image_flow_offline_only(self):
        self.replay_image('IR014', 40)

    def test_ir015_image_flow_offline_only(self):
        self.replay_image('IR015', 40)

    def test_ir016_image_flow_offline_only(self):
        self.replay_image('IR016', 40)

    def test_ir017_radar_image(self):
        self.replay_image('IR017', 40)

    def test_wifi001_network_bench_image(self):
        self.replay_image('WIFI001', 16)

    def test_wifi002_app_bench_image(self):
        self.replay_image('WIFI002', 24)

    def test_app001_integrated_bench_image(self):
        self.replay_image('APP001', 144)

    def test_app002_integrated_bench_image(self):
        self.replay_image('APP002', 144)

    def test_app003_state_report_bench_image(self):
        self.replay_image('APP003', 152)

    def test_app004_split_report_bench_image(self):
        self.replay_image('APP004', 152)

    def test_app005_manual_ack_bench_image(self):
        self.replay_image('APP005', 152)

    def test_drum001_candidate_image(self):
        self.replay_image('DRUM001', 216)

    def test_drum002_bin_interlock_candidate_image(self):
        self.replay_image('DRUM002', 224)

    def test_drum003_either_hall_candidate_image(self):
        self.replay_image('DRUM003', 224)

    def test_drum004_unloaded_exercise_image(self):
        self.replay_image('DRUM004', 248)

    def test_drum005_combined_interlock_image(self):
        self.replay_image('DRUM005', 264)

    def test_drum006_array_counter_image(self):
        self.replay_image('DRUM006', 272)

    def test_drum007_optical_timing_image(self):
        self.replay_image('DRUM007', 264)

    def test_drum008_pause_resume_image(self):
        self.replay_image('DRUM008', 264)

    def test_drum009_single_trace_image(self):
        self.replay_image('DRUM009', 272)

    def test_drum010_single_period_image(self):
        self.replay_image('DRUM010', 280)

    def test_drum011_adc_window_image(self):
        self.replay_image('DRUM011', 280)

    def test_drum012_phase_scan_image(self):
        self.replay_image('DRUM012', 304)

    def test_drum013_single_window_stop_image(self):
        self.replay_image('DRUM013', 304)

    def test_app_only_initialization_writes_timer0_reload(self):
        for profile in ('APP002', 'APP003', 'APP004', 'APP005', 'DRUM001', 'DRUM002', 'DRUM003', 'DRUM004', 'DRUM005', 'DRUM006', 'DRUM007', 'DRUM008', 'DRUM009', 'DRUM010', 'DRUM011', 'DRUM012', 'DRUM013'):
            with self.subTest(profile=profile):
                listing = (ROOT/'output'/('LB_'+profile)/'listing.asm').read_text(encoding='utf-8')
                # CLR/SETB 0x8C 使用位寻址，指的是 TCON.TR0。
                th0 = re.findall(r'^.*\bMOV[^\n]*\b0x8[cC](?=,|[ \t]|$).*$', listing, flags=re.MULTILINE)
                self.assertEqual(len(th0), 1, th0)
                self.assertRegex(th0[0], r'\bMOV 0x8[Cc], #0xFF\b')

    def test_wifi001_second_handshake_response_resynchronizes(self):
        reader = Mock(side_effect=[b'\x00', StcFramingException('incorrect frame start'), b'\x0c'])
        protocol = SimpleNamespace(ser=SimpleNamespace(timeout=15), read_packet=reader)
        packets = handshake_skip_leading_bytes(
            protocol, lambda: (protocol.read_packet(), protocol.read_packet()), each_response=True
        )
        self.assertEqual(packets, (b'\x00', b'\x0c'))
        self.assertIs(protocol.read_packet, reader)
        self.assertEqual(protocol.ser.timeout, 15)

    def test_ir014_first_handshake_response_resynchronizes(self):
        p = SimpleNamespace(ser=SimpleNamespace(timeout=15))
        reader = Mock(side_effect=[StcFramingException('incorrect frame start'), b'\x00', b'\x01'])
        p.read_packet = reader
        packets = handshake_skip_leading_bytes(p, lambda: (p.read_packet(), p.read_packet()))
        self.assertEqual(packets, (b'\x00', b'\x01'))
        self.assertIs(p.read_packet, reader)
        self.assertEqual(p.ser.timeout, 15)

    def test_ir014_bad_checksum_still_aborts(self):
        p = SimpleNamespace(ser=SimpleNamespace(timeout=15))
        reader = Mock(side_effect=StcFramingException('incorrect checksum'))
        p.read_packet = reader
        with self.assertRaisesRegex(StcFramingException, 'incorrect checksum'):
            handshake_skip_leading_bytes(p, lambda: p.read_packet())
        reader.assert_called_once()
        self.assertEqual(p.ser.timeout, 15)

    def test_clock_mismatch_fails_before_original_program(self):
        p = SimpleNamespace(model=SimpleNamespace(name='STC32G8K64', mcs251=True), mcu_clock_hz=24000000)
        gal = SimpleNamespace(protocol=p, opts=SimpleNamespace(option=None, eeprom_image=None, trim=0, erase=False))
        original = Mock()
        with self.assertRaisesRegex(RuntimeError, '擦除前'):
            program_without_options(gal, original, Mock())
        original.assert_not_called()


if __name__ == '__main__':
    unittest.main()
