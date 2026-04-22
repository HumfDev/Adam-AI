"""pH sensor abstraction with persisted slope/offset calibration."""

import json
from machine import ADC, Pin


class PHSensor:
    def __init__(
        self,
        ads_bus=None,
        addr_irox=None,
        addr_agcl=None,
        fallback_irox_pin=26,
        fallback_agcl_pin=27,
        cal_path="ph_cal.json",
    ):
        self._ads_bus = ads_bus
        self._addr_irox = addr_irox
        self._addr_agcl = addr_agcl
        self._adc_irox = ADC(Pin(fallback_irox_pin))
        self._adc_agcl = ADC(Pin(fallback_agcl_pin))
        self._cal_path = cal_path
        self.slope_mv_per_ph = -59.16
        self.offset_mv = 0.0
        self._load_calibration()

    def _load_calibration(self):
        try:
            with open(self._cal_path, "r") as fp:
                data = json.loads(fp.read())
            self.slope_mv_per_ph = float(data.get("slope_mv_per_ph", self.slope_mv_per_ph))
            self.offset_mv = float(data.get("offset_mv", self.offset_mv))
        except Exception:
            pass

    def _save_calibration(self):
        data = {
            "slope_mv_per_ph": self.slope_mv_per_ph,
            "offset_mv": self.offset_mv,
        }
        with open(self._cal_path, "w") as fp:
            fp.write(json.dumps(data))

    @staticmethod
    def _u16_to_mv(raw_u16):
        return int((raw_u16 * 3300) / 65535)

    def _read_mv(self):
        if self._ads_bus is not None and self._addr_irox is not None:
            irox_raw = self._ads_bus.read_raw_single(self._addr_irox, 0)
            irox_mv = self._ads_bus.raw_to_mv(irox_raw)
            if self._addr_agcl is None:
                agcl_raw = self._ads_bus.read_raw_single(self._addr_irox, 1)
                agcl_mv = self._ads_bus.raw_to_mv(agcl_raw)
            else:
                agcl_raw = self._ads_bus.read_raw_single(self._addr_agcl, 0)
                agcl_mv = self._ads_bus.raw_to_mv(agcl_raw)
            return irox_raw, agcl_raw, irox_mv, agcl_mv

        irox_u16 = self._adc_irox.read_u16()
        agcl_u16 = self._adc_agcl.read_u16()
        return irox_u16, agcl_u16, self._u16_to_mv(irox_u16), self._u16_to_mv(agcl_u16)

    def read_raw_counts(self):
        irox_counts, agcl_counts, _, _ = self._read_mv()
        return irox_counts, agcl_counts

    def read(self):
        _, _, irox_mv, agcl_mv = self._read_mv()
        diff_mv = irox_mv - agcl_mv
        p_h = (diff_mv - self.offset_mv) / self.slope_mv_per_ph
        return irox_mv, agcl_mv, diff_mv, p_h

    def set_calibration(self, slope_mv_per_ph, offset_mv):
        self.slope_mv_per_ph = float(slope_mv_per_ph)
        self.offset_mv = float(offset_mv)
        self._save_calibration()
