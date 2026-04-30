"""Load cell facade around HX711."""


class LoadCellSensor:
    def __init__(self, hx711, scale_counts_per_gram=1.0):
        self._hx = hx711
        self._scale = float(scale_counts_per_gram)
        self._tare_raw = 0

    def read_raw(self):
        raw = self._hx.read_raw()
        if raw is None:
            raise TimeoutError("HX711")
        return raw

    def tare(self):
        self._tare_raw = self.read_raw()
        return self._tare_raw

    def set_gain(self, gain):
        self._hx.set_gain(gain)

    def get_cfg(self):
        return self._hx.gain, self._tare_raw

    def read(self):
        raw = self.read_raw()
        grams = (raw - self._tare_raw) / self._scale
        return raw, grams
