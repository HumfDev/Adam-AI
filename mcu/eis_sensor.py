"""AD5933 EIS sweep support with paging for large payloads."""

import time

_REG_CONTROL_H = 0x80
_REG_START_FREQ = 0x82
_REG_FREQ_INC = 0x85
_REG_NUM_INC = 0x88
_REG_SETTLE = 0x8A
_REG_STATUS = 0x8F
_REG_REAL = 0x94
_REG_IMAG = 0x96

_CTRL_POWER_DOWN = 0xA0
_CTRL_STANDBY = 0xB0
_CTRL_INIT_START = 0x10
_CTRL_START_SWEEP = 0x20
_CTRL_INC_FREQ = 0x30

_VRANGE_BITS = {1: 0b00, 2: 0b11, 3: 0b10, 4: 0b01}
_GAIN_BIT = {1: 1, 5: 0}


class EISSensor:
    def __init__(self, i2c, addr=0x0D, present=False, mclk_hz=16776000, page_points=50):
        self._i2c = i2c
        self._addr = addr
        self.present = present
        self._mclk_hz = int(mclk_hz)
        self._busy = False
        self._page_points = page_points
        self.start_hz = 1000
        self.stop_hz = 200000
        self.steps = 100
        self.vrange = 1
        self.gain = 1
        self._last_points = None
        self._pages = None

    def _write(self, reg, data):
        self._i2c.writeto(self._addr, bytes([reg]) + data)

    def _read(self, reg, length=1):
        self._i2c.writeto(self._addr, bytes([reg]))
        return self._i2c.readfrom(self._addr, length)

    @staticmethod
    def _to_i16(msb, lsb):
        raw = (msb << 8) | lsb
        if raw & 0x8000:
            raw -= 0x10000
        return raw

    def _set_control_mode(self, mode_upper_nibble):
        ctrl = mode_upper_nibble
        ctrl |= (_VRANGE_BITS[self.vrange] << 1)
        ctrl |= _GAIN_BIT[self.gain]
        self._write(_REG_CONTROL_H, bytes([ctrl, 0x00]))

    def _write_u24(self, reg, value):
        value &= 0xFFFFFF
        self._write(reg, bytes([(value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF]))

    def _write_u16(self, reg, value):
        value &= 0xFFFF
        self._write(reg, bytes([(value >> 8) & 0xFF, value & 0xFF]))

    def _freq_code(self, hz):
        return int(round((float(hz) / (self._mclk_hz / 4.0)) * (1 << 27)))

    def set_start(self, hz):
        hz = int(hz)
        if hz < 1:
            raise ValueError("start must be >= 1 Hz")
        self.start_hz = hz

    def set_stop(self, hz):
        hz = int(hz)
        if hz < 1:
            raise ValueError("stop must be >= 1 Hz")
        self.stop_hz = hz

    def set_steps(self, steps):
        steps = int(steps)
        if steps < 1 or steps > 511:
            raise ValueError("max 511 steps")
        self.steps = steps

    def set_vrange(self, vrange):
        vrange = int(vrange)
        if vrange not in _VRANGE_BITS:
            raise ValueError("vrange must be 1-4")
        self.vrange = vrange

    def set_gain(self, gain):
        gain = int(gain)
        if gain not in _GAIN_BIT:
            raise ValueError("gain must be 1 or 5")
        self.gain = gain

    def get_cfg(self):
        return self.start_hz, self.stop_hz, self.steps, self.vrange, self.gain

    def _format_payload(self, points):
        chunk = []
        for f_hz, real, imag in points:
            chunk.append("{},{},{}".format(int(f_hz), int(real), int(imag)))
        return ";".join(chunk)

    def format_points(self, points):
        return self._format_payload(points)

    def _paginate(self, points):
        pages = []
        for i in range(0, len(points), self._page_points):
            pages.append(points[i : i + self._page_points])
        self._pages = pages

    def get_last(self):
        return self._last_points

    def get_page(self, page_idx):
        if self._pages is None:
            raise ValueError("no paged data")
        if page_idx < 0 or page_idx >= len(self._pages):
            raise ValueError("page out of range")
        return self._pages[page_idx], len(self._pages)

    def run(self):
        if self._busy:
            raise RuntimeError("busy")
        if not self.present:
            raise TimeoutError("AD5933")

        self._busy = True
        try:
            inc_hz = (self.stop_hz - self.start_hz) / float(self.steps)
            if inc_hz < 0:
                raise ValueError("stop must be >= start")

            self._set_control_mode(_CTRL_POWER_DOWN)
            self._set_control_mode(_CTRL_STANDBY)

            self._write_u24(_REG_START_FREQ, self._freq_code(self.start_hz))
            self._write_u24(_REG_FREQ_INC, self._freq_code(inc_hz))
            self._write_u16(_REG_NUM_INC, self.steps)
            self._write_u16(_REG_SETTLE, 10)

            self._set_control_mode(_CTRL_INIT_START)
            time.sleep_ms(2)
            self._set_control_mode(_CTRL_START_SWEEP)

            points = []
            current_freq = float(self.start_hz)
            deadline = time.ticks_add(time.ticks_ms(), 30000)

            while True:
                if time.ticks_diff(time.ticks_ms(), deadline) > 0:
                    raise TimeoutError("AD5933")
                status = self._read(_REG_STATUS, 1)[0]
                data_valid = status & 0x02
                sweep_done = status & 0x04

                if data_valid:
                    real = self._read(_REG_REAL, 2)
                    imag = self._read(_REG_IMAG, 2)
                    real_i = self._to_i16(real[0], real[1])
                    imag_i = self._to_i16(imag[0], imag[1])
                    points.append((int(round(current_freq)), real_i, imag_i))
                    current_freq += inc_hz
                    if sweep_done:
                        break
                    self._set_control_mode(_CTRL_INC_FREQ)
                elif sweep_done:
                    break
                else:
                    time.sleep_ms(2)

            self._set_control_mode(_CTRL_STANDBY)
            self._last_points = points
            payload = self._format_payload(points)
            if len(payload) > 1800:
                self._paginate(points)
                return "READY", len(points), len(self._pages)
            self._pages = None
            return "DATA", len(points), payload
        finally:
            self._busy = False
