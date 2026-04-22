"""HX711 24-bit load-cell ADC driver (bit-banged GPIO) for MicroPython."""

import time
import machine


_GAIN_PULSES = {128: 1, 64: 3, 32: 2}


class HX711:
    def __init__(self, dout_pin, sck_pin, gain=128, ready_timeout_ms=200):
        if gain not in _GAIN_PULSES:
            raise ValueError("gain must be 128, 64, or 32")
        self.dout = machine.Pin(dout_pin, machine.Pin.IN)
        self.sck = machine.Pin(sck_pin, machine.Pin.OUT)
        self.sck.value(0)
        self.gain = gain
        self._gain_pulses = _GAIN_PULSES[self.gain]
        self.ready_timeout_ms = ready_timeout_ms
        self.offset = 0

    def _read_raw(self):
        # Wait for "data ready" (DOUT low).
        deadline = time.ticks_add(time.ticks_ms(), self.ready_timeout_ms)
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

        # Extra pulses set the gain for the NEXT reading.
        for _ in range(self._gain_pulses):
            self.sck.value(1)
            time.sleep_us(1)
            self.sck.value(0)
            time.sleep_us(1)

        if raw & 0x800000:
            raw -= 0x1000000
        return raw

    def set_gain(self, gain):
        if gain not in _GAIN_PULSES:
            raise ValueError("gain must be 128, 64, or 32")
        self.gain = gain
        self._gain_pulses = _GAIN_PULSES[gain]
        # Prime the new gain for next conversion cycle.
        self._read_raw()

    def tare(self, samples=10):
        readings = []
        for _ in range(samples):
            r = self._read_raw()
            if r is not None:
                readings.append(r)
        if readings:
            self.offset = sum(readings) // len(readings)

    def read_raw(self):
        return self._read_raw()

    def get_value(self):
        raw = self._read_raw()
        if raw is None:
            return None
        return raw - self.offset
