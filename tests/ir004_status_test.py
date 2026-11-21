"""执行真实ir_status入口，串口与时间为离线替身；不打开硬件。"""
import contextlib
import io
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import ir_status


def frame(version='IR004',request=0,mode=0,rst='0051',running=False):
    state='RUN' if running else 'STOP'
    return (f'{version} {state} KEYS=111 TX={mode} RAW=0 RST={rst}\r\n'
            f'REQ={request} BEAM=0 ARM=0 WAIT=0000\r\n').encode()


class SerialReplay:
    def __init__(self,identity):
        self.identity=identity
        self.rx=b''
        self.writes=[]

    def __enter__(self): return self
    def __exit__(self,*args): pass
    def write(self,data):
        self.writes.append(data)
        self.rx+=self.identity if data==b'?' else frame(mode=2 if data==b'8' else 0)
    def read(self,count):
        data,self.rx=self.rx[:count],self.rx[count:]
        return data


class StatusTest(unittest.TestCase):
    def run_action(self,action,identity):
        serial=SerialReplay(identity)
        ticks=itertools.count(step=0.25)
        with patch.object(sys,'argv',['ir_status.py',action,'--profile','IR004']), \
             patch.object(ir_status,'ports',return_value='OFFLINE'), \
             patch.object(ir_status.serial,'Serial',return_value=serial), \
             patch.object(ir_status.time,'monotonic',side_effect=lambda:next(ticks)), \
             patch.object(ir_status,'save_json') as save, \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                ir_status.main()
                code=0
            except SystemExit as exc:
                code=exc.code
        return code,serial.writes,save.call_args.args[1]

    def test_paused_session_cannot_be_mistaken_for_manual_off(self):
        for action in ('test38','link-low','link-high'):
            with self.subTest(action=action):
                code,writes,report=self.run_action(action,frame(request=1,mode=4))
                self.assertEqual(code,1)
                self.assertEqual(writes,[b'?'])

    def test_polarity_choice_does_not_start_ir_or_motor(self):
        for action,command in (('link-low',b'l'),('link-high',b'h')):
            code,writes,report=self.run_action(action,frame())
            self.assertEqual(code,0)
            self.assertEqual(writes,[b'?',command])
            self.assertIn('TX=0',report['events'][-1]['response'])

    def test_bounded_test_restores_off(self):
        code,writes,report=self.run_action('test38',frame())
        self.assertEqual(code,0)
        self.assertEqual(writes,[b'?',b'0',b'8',b'0'])
        self.assertEqual(report['events'][-1]['phase'],'tx_off_after_test')

    def test_other_identity_and_wrong_reset_do_not_start_test(self):
        for identity in (frame(version='IR003'),frame(rst='0000')):
            code,writes,report=self.run_action('test38',identity)
            self.assertEqual(code,1)
            self.assertEqual(writes,[b'?'])

    def test_stop_ack_and_status_identity(self):
        code,writes,report=self.run_action('stop',frame(request=1,mode=4,running=True))
        self.assertEqual(code,0)
        self.assertEqual(writes,[b'?',b'!'])
        self.assertIn('REQ=0',report['events'][-1]['response'])
        code,writes,report=self.run_action('status',frame())
        self.assertEqual(code,0)
        self.assertTrue(report['identified'])
        self.assertEqual(writes,[b'?'])


if __name__=='__main__': unittest.main()
