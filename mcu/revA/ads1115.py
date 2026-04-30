"""ADS1x15 helpers used by thermistor and pH sensor classes."""

import time
from machine import I2C, Pin

_REG_CONVERSION = 0x00
_REG_CONFIG = 0x01
_MUX_SINGLE = (0x4000, 0x5000, 0x6000, 0x7000)
_OS_START = 0x8000
_MODE_SINGLE = 0x0100
_PGA_2V048 = 0x0400
_DR_16SPS = 0x0020


class ADS1x15Bus:
    """Single-shot single-ended reads from ADS111x-like parts."""

    def __init__(self, i2c_id=1, sda=6, scl=7, freq=400000):
        self.i2c = I2C(i2c_id, sda=Pin(sda), scl=Pin(scl), freq=freq)

    def scan(self):
        return self.i2c.scan()

    def _write_reg(self, addr, reg, value):
        self.i2c.writeto(addr, bytes([reg, (value >> 8) & 0xFF, value & 0xFF]))

    def _read_reg(self, addr, reg):
        self.i2c.writeto(addr, bytes([reg]))
        data = self.i2c.readfrom(addr, 2)
        return (data[0] << 8) | data[1]

    def read_raw_single(self, addr, channel=0, timeout_ms=200):
        if channel < 0 or channel > 3:
            raise ValueError("channel must be 0-3")
        config = _OS_START | _MUX_SINGLE[channel] | _PGA_2V048 | _MODE_SINGLE | _DR_16SPS
        self._write_reg(addr, _REG_CONFIG, config)
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while True:
            reg = self._read_reg(addr, _REG_CONFIG)
            if reg & _OS_START:
                break
            if time.ticks_diff(time.ticks_ms(), deadline) > 0:
                raise OSError("ads timeout")
            time.sleep_ms(5)

        raw = self._read_reg(addr, _REG_CONVERSION)
        if raw & 0x8000:
            raw -= 0x10000
        return raw

    @staticmethod
    def raw_to_mv(raw):
        return int(raw * 0.0625)  # 62.5uV / LSB at +/-2.048V
