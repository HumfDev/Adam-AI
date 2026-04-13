# ADS1115 as a Klipper "temperature" sensor (value is really ADS voltage in volts).
#
# This module uses Adafruit Blinka on the Linux host (Raspberry Pi, etc.):
#   pip install adafruit-blinka adafruit-circuitpython-ads1x15
# The ADS1115 must be on the **host SBC I2C bus** (e.g. Pi GPIO2/GPIO3), not
# on a remote Klipper MCU. To read an ADS1115 wired only to a Seeed XIAO RP2040,
# you would need a different approach (MCU-side I2C driver), not this file as-is.
#
# XIAO RP2040 I2C pin reference (for other firmware or a future MCU driver):
#   SDA = D4 = gpio6,  SCL = D5 = gpio7  (3.3 V only)
#
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

REPORT_TIME = 1.0


class ADS1115Sensor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.temperature = 0.
        self._callback = None
        self.min_temp = self.max_temp = 0.
        self.channel = config.getint('channel', 0, minval=0, maxval=3)

        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.ads = ADS.ADS1115(self.i2c)
        # ADS1115 channels: 0=A0, 1=A1, 2=A2, 3=A3
        self.chan = AnalogIn(self.ads, self.channel)

        self.printer.add_object("ads1115_sensor " + self.name, self)
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _handle_connect(self):
        reactor = self.printer.get_reactor()
        self.sample_timer = reactor.register_timer(self._update, reactor.monotonic() + 1.)

    def _update(self, eventtime):
        try:
            self.temperature = self.chan.voltage
            if self._callback:
                self._callback(eventtime, self.temperature)
        except Exception:
            pass
        return eventtime + REPORT_TIME

    def setup_minmax(self, min_temp, max_temp):
        self.min_temp = min_temp
        self.max_temp = max_temp

    def setup_callback(self, cb):
        self._callback = cb

    def get_report_time_delta(self):
        return REPORT_TIME

    def get_temp(self, eventtime):
        return self.temperature, 0.

    def get_status(self, eventtime):
        return {
            'temperature': self.temperature,
            'voltage': self.temperature,
            'channel': self.channel,
        }


def load_config(config):
    pheaters = config.get_printer().load_object(config, "heaters")
    pheaters.add_sensor_factory("ADS1115", ADS1115Sensor)


def load_config_prefix(config):
    pheaters = config.get_printer().load_object(config, "heaters")
    pheaters.add_sensor_factory("ADS1115", ADS1115Sensor)
