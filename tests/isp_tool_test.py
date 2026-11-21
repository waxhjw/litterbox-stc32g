"""验证真实历史报文，以及项目烧录入口在串口连接之前拦截。"""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import diagnostic
import project
from audit_isp_options import audit


class IspToolTest(unittest.TestCase):
    def test_ir006_approved_sampling_profile_uses_no_options(self):
        import stcgal.frontend
        original=stcgal.frontend.StcGal
        cfg={'model':'STC32G8K64','baud':115200,'handshake_baud':2400}
        def offline_cli():
            self.assertIn(str(diagnostic.IMAGE),sys.argv)
            self.assertNotIn('-t',sys.argv)
            return 0
        with patch('diagnostic.check',return_value='OFFLINE'), \
             patch('diagnostic.save_json') as saved, \
             patch('stcgal.frontend.cli',side_effect=offline_cli):
            diagnostic.select_profile('IR006')
            with self.assertRaises(SystemExit) as result:
                diagnostic.flash(cfg)
            self.assertEqual(result.exception.code,0)
            self.assertEqual(saved.call_args.args[1]['option_policy'],'no_option_write')
            self.assertIsNone(saved.call_args.args[1]['trim_khz'])
        self.assertIs(stcgal.frontend.StcGal,original)

    def test_real_packet_replay(self):
        report = audit()
        self.assertTrue(report['installed_builder_matches_recorded_write'])
        self.assertTrue(report['status_before_first_flash']['reported_low_voltage_reset'])
        self.assertFalse(report['status_before_second_flash']['reported_low_voltage_reset'])
        self.assertEqual([x['offset'] for x in report['changed_status_bytes']], [8, 11, 12, 14])

    def test_all_project_writers_block_before_port_enumeration(self):
        with patch('project.ports', side_effect=AssertionError('不得枚举或打开串口')), \
             patch('diagnostic.ports', side_effect=AssertionError('不得枚举或打开串口')):
            for profile in ('ISP_TEST001', 'MOTOR001', 'MOTOR002', 'MOTOR003'):
                diagnostic.select_profile(profile)
                with self.subTest(profile=profile), self.assertRaisesRegex(RuntimeError, '暂停烧录'):
                    diagnostic.flash({})
            with self.assertRaisesRegex(RuntimeError, '暂停烧录'):
                project.flash({})


if __name__ == '__main__':
    unittest.main()
