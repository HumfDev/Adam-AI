import machine
import time
from machine import I2C, Pin

# --- ADS1115 (I2C) — class is loaded but not used until you swap main() (see file bottom) ---
_REG_CONVERSION = 0x00
_REG_CONFIG = 0x01
_MUX = [0x4000, 0x5000, 0x6000, 0x7000]
_PGA = 0x0200
_MODE_ONE = 0x0100
_DR_128SPS = 0x0080
_OS_START = 0x8000


class ADS1115Sensor:
    def __init__(self, i2c_id=1, sda=6, scl=7, i2c_addr=0x48):
        self.i2c = I2C(i2c_id, sda=Pin(sda), scl=Pin(scl), freq=400_000)
        self.addr = i2c_addr

    def _write_reg(self, reg, value):
        self.i2c.writeto(self.addr, bytes([reg, value >> 8, value & 0xFF]))

    def _read_reg(self, reg):
        self.i2c.writeto(self.addr, bytes([reg]))
        data = self.i2c.readfrom(self.addr, 2)
        return (data[0] << 8) | data[1]

    def read(self, channel):
        """Return voltage on channel 0-3 in volts."""
        if channel not in range(4):
            raise ValueError("channel must be 0-3")
        config = _OS_START | _MUX[channel] | _PGA | _MODE_ONE | _DR_128SPS
        self._write_reg(_REG_CONFIG, config)
        time.sleep_ms(10)
        raw = self._read_reg(_REG_CONVERSION)
        if raw & 0x8000:
            raw -= 0x10000
        # ±4.096V range → 0.125 mV per LSB (per original ads1115_sensor.py)
        return raw * 0.0001


# --- HX711 (bit-bang GPIO) ---
class HX711:
    def __init__(self, dout_pin, sck_pin, gain=128):
        self.dout = machine.Pin(dout_pin, machine.Pin.IN)
        self.sck = machine.Pin(sck_pin, machine.Pin.OUT)
        self.sck.value(0)
        self._gain_pulses = {128: 1, 64: 3, 32: 2}[gain]
        self.offset = 0

    def _read_raw(self):
        deadline = time.ticks_add(time.ticks_ms(), 500)
        while self.dout.value():
            if time.ticks_diff(time.ticks_ms(), deadline) > 0:
                return None

        raw = 0
        for _ in range(24):
            self.sck.value(1)
            time.sleep_us(1)
            raw = (raw << 1) | self.dout.value()
            self.sck.value(0)
            time.sleep_us(1)

        for _ in range(self._gain_pulses):
            self.sck.value(1)
            time.sleep_us(1)
            self.sck.value(0)
            time.sleep_us(1)

        if raw & 0x800000:
            raw -= 0x1000000
        return raw

    def tare(self, samples=10):
        readings = [self._read_raw() for _ in range(samples)]
        readings = [r for r in readings if r is not None]
        if readings:
            self.offset = sum(readings) // len(readings)

    def get_value(self):
        raw = self._read_raw()
        if raw is None:
            return None
        return raw - self.offset

def main():

    # --- Sensors ---
    hx = HX711(dout_pin=8, sck_pin=7, gain=128)
    ads = ADS1115Sensor(i2c_id=1, sda=6, scl=7, i2c_addr=0x48)

    print("Taring HX711...")
    hx.tare(samples=10)
    print("Tare done. Offset:", hx.offset)

    # --- timing control ---
    last_hx = time.ticks_ms()
    last_ads = time.ticks_ms()

    hx_interval = 200
    ads_interval = 200

    while True:
        now = time.ticks_ms()

        # ---------------- HX711 ----------------
        if time.ticks_diff(now, last_hx) >= hx_interval:
            val = hx.get_value()
            if val is None:
                print("HX TIMEOUT")
            else:
                print("Load:", val)
            last_hx = now

        # ---------------- ADS1115 ----------------
        if time.ticks_diff(now, last_ads) >= ads_interval:
            v0 = ads.read(0)  # A0
            v1 = ads.read(1)  # A1

            print("A0 V:", v0, " | A1 V:", v1)

            last_ads = now

        time.sleep_ms(5)
main()