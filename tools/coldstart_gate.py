"""已撤回的辅助试验源码，仅保留追溯；诊断入口不导入此文件。

SetCommBreak属性赋值不等于实测TX或目标电源；不以此认定回供电。
"""
from datetime import datetime
from pathlib import Path
import time
from project import ROOT, load_json, save_json


class ColdStartGate:
    def __init__(self, state, evidence):
        self.state, self.evidence = state, evidence
        self.directory = ROOT/'build'/('IR003-coldstart-'+datetime.now().strftime('%Y%m%d-%H%M%S%f'))
        self.directory.mkdir()
        self.off_file = self.directory/'board-off-confirmed.json'
        self.on_file = self.directory/'12v-on-confirmed.json'
        self.used = False
        state['coldstart_gate'] = {'directory': str(self.directory),
                                  'off_file': str(self.off_file), 'on_file': str(self.on_file),
                                  'supply_voltage_measured': False}

    def publish(self, stage):
        self.state['stage'] = stage
        save_json(self.evidence, self.state)
        print('STAGE:', stage, flush=True)

    def wait_confirmation(self, path, key, timeout=240):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if path.exists() and load_json(path).get(key) is True:
                return
            time.sleep(0.1)
        raise RuntimeError('等待用户供电确认超时，未进入擦写')

    def before_first_sync(self, protocol):
        if self.used:
            return
        self.used = True
        protocol.ser.break_condition = True
        self.state['coldstart_gate']['break_asserted_by_driver'] = True
        self.publish('tx_low_waiting_board_off')
        try:
            self.wait_confirmation(self.off_file, 'board_12v_off')
            # 用户确认断电后仍保留5秒低TX；这不是对芯片电源的表测。
            time.sleep(5)
        finally:
            protocol.ser.break_condition = False
        self.state['coldstart_gate']['break_released'] = True
        self.publish('identify_after_tx_low')

    def before_program(self, protocol):
        self.state['coldstart_gate']['identified_model'] = protocol.model.name
        self.publish('identified_waiting_12v_confirmation')
        self.wait_confirmation(self.on_file, 'board_12v_on')
        self.state['coldstart_gate']['user_confirmed_12v_on'] = True
        self.publish('power_confirmed_preflight')
