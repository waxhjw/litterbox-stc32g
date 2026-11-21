"""对真实协议解析/探测前提做边界回放，不连接串口。"""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from array_probe import probe_byte,probe_permitted,parse_adc

def state(run=b'STOP',probe=b'0',rst=b'0051',request=b'0',version=b'IR006'):
    return version+b' '+run+b' KEYS=111 PROBE='+probe+b' RST='+rst+b' REQ='+request+b' ARRAY=SAMPLE\r\n'

class ToolTest(unittest.TestCase):
    def test_maps_six_explicit_probe_commands(self):
        self.assertEqual([probe_byte(c,l) for l in ('low','high') for c in (1,2,3)],
                         [bytes([x]) for x in b'ABCDEF'])
    def test_rejects_running_active_unknown_identity_and_reset(self):
        self.assertTrue(probe_permitted(state()))
        for response in (state(run=b'RUN'),state(request=b'1'),state(probe=b'1'),
                         state(rst=b'0000'),state(version=b'IR005'),b''):
            self.assertFalse(probe_permitted(response))
    def test_adc_timeout_and_live_are_preserved(self):
        result=parse_adc(b'IR006 ADC=0000,0FFF,FFFF\r\nLIVE=0\r\n')
        self.assertEqual(result['raw_adc14_0_1'],[0,4095,65535])
        self.assertEqual(result['adc_timeout_channels'],[3])
        self.assertFalse(result['probe_live'])
        self.assertTrue(parse_adc(b'IR006 ADC=0123,0456,0789\r\nLIVE=1\r\n')['probe_live'])
    def test_missing_and_out_of_range_fail(self):
        for response in (b'',b'IR006 REJECT\r\n',b'IR006 ADC=1000,0000,0000\r\nLIVE=1\r\n'):
            with self.assertRaises(RuntimeError): parse_adc(response)

if __name__=='__main__': unittest.main()
