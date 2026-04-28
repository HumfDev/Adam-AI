"""Serial ASCII command event loop for the MicroPython MCU controller."""

import gc
import select
import sys
import time

from ads1115 import ADS1x15Bus
from commands import CommandProcessor
from eis_sensor import EISSensor
from heat_pad import HeatPad
from hx711 import HX711
from load_cell import LoadCellSensor
from ph_sensor import PHSensor
from thermistor import ThermistorSensor

STATUS_HP0 = 1 << 0
STATUS_HP1 = 1 << 1
STATUS_TH0 = 1 << 2
STATUS_TH1 = 1 << 3
STATUS_LOAD = 1 << 4
STATUS_PH = 1 << 5
STATUS_EIS = 1 << 6


class Runtime:
    def __init__(self):
        self.status_bits = 0
        self.processor = CommandProcessor(self.get_status)

    def get_status(self):
        return self.status_bits

    def _mark_ready(self, bit):
        self.status_bits |= bit

    def boot(self):
        ads_bus = ADS1x15Bus(i2c_id=1, sda=6, scl=7, freq=400000)
        scan = []
        try:
            scan = ads_bus.scan()
        except Exception:
            pass

        has_48 = 0x48 in scan
        has_49 = 0x49 in scan
        has_ad5933 = 0x0D in scan

        self.processor.hp0 = HeatPad(pin=28, frequency_hz=1000)
        self.processor.hp1 = HeatPad(pin=29, frequency_hz=1000)
        self._mark_ready(STATUS_HP0 | STATUS_HP1)

        t0_addr = 0x48 if has_48 else None
        t1_addr = 0x49 if has_49 else (0x48 if has_48 else None)
        t1_channel = 0 if has_49 else 1

        self.processor.temp0 = ThermistorSensor(
            adc_pin=26,
            ads_bus=ads_bus if t0_addr is not None else None,
            ads_addr=t0_addr,
            ads_channel=0,
        )
        self.processor.temp1 = ThermistorSensor(
            adc_pin=27,
            ads_bus=ads_bus if t1_addr is not None else None,
            ads_addr=t1_addr,
            ads_channel=t1_channel,
        )
        self._mark_ready(STATUS_TH0 | STATUS_TH1)

        hx = HX711(dout_pin=4, sck_pin=2, gain=128, ready_timeout_ms=200)
        self.processor.load_cell = LoadCellSensor(hx711=hx, scale_counts_per_gram=1000.0)
        self._mark_ready(STATUS_LOAD)

        ph_addr_irox = 0x48 if has_48 else None
        ph_addr_agcl = 0x49 if has_49 else None
        self.processor.ph = PHSensor(
            ads_bus=ads_bus if (has_48 or has_49) else None,
            addr_irox=ph_addr_irox,
            addr_agcl=ph_addr_agcl,
            fallback_irox_pin=26,
            fallback_agcl_pin=27,
            cal_path="ph_cal.json",
        )
        self._mark_ready(STATUS_PH)

        self.processor.eis = EISSensor(
            i2c=ads_bus.i2c,
            addr=0x0D,
            present=has_ad5933,
            mclk_hz=16776000,
            page_points=50,
        )
        if has_ad5933:
            self._mark_ready(STATUS_EIS)


def run_loop(processor):
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)
    buffer = ""
    gc_ticks = 0

    while True:
        events = poller.poll(5)
        if events:
            chunk = sys.stdin.read(1)
            if chunk:
                buffer += chunk
                if chunk == "\n":
                    response = processor.handle(buffer)
                    sys.stdout.write(response + "\n")
                    # sys.stdout.flush()  # doesn't exist in MicroPython
                    buffer = ""
        gc_ticks += 1
        if gc_ticks >= 200:
            gc.collect()
            gc_ticks = 0
        time.sleep_ms(1)


def main():
    runtime = Runtime()
    runtime.boot()
    run_loop(runtime.processor)


main()
