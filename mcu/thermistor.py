"""Reusable thermistor reader with ADS fallback to onboard ADC."""

import math
from machine import ADC, Pin


class ThermistorSensor:
    """Reads one thermistor channel and converts to Celsius."""

    def __init__(
        self,
        adc_pin,
        ads_bus=None,
        ads_addr=None,
        ads_channel=0,
        beta=3950.0,
        r0=10000.0,
        t0_c=25.0,
        fixed_resistor=10000.0,
        vref_mv=3300,
    ):
        self._fallback_adc = ADC(Pin(adc_pin))
        self._ads_bus = ads_bus
        self._ads_addr = ads_addr
        self._ads_channel = ads_channel
        self._beta = float(beta)
        self._r0 = float(r0)
        self._t0_k = float(t0_c) + 273.15
        self._fixed_resistor = float(fixed_resistor)
        self._vref_mv = int(vref_mv)

    def _read_mv(self):
        if self._ads_bus is not None and self._ads_addr is not None:
            raw = self._ads_bus.read_raw_single(self._ads_addr, self._ads_channel)
            return self._ads_bus.raw_to_mv(raw)
        raw_u16 = self._fallback_adc.read_u16()
        return int((raw_u16 * self._vref_mv) / 65535)

    def _mv_to_celsius(self, raw_mv):
        if raw_mv <= 0 or raw_mv >= self._vref_mv:
            raise ValueError("thermistor voltage out of range")
        v = float(raw_mv) / self._vref_mv
        r_therm = self._fixed_resistor * (v / (1.0 - v))
        inv_t = (1.0 / self._t0_k) + (math.log(r_therm / self._r0) / self._beta)
        return (1.0 / inv_t) - 273.15

    def read(self):
        raw_mv = self._read_mv()
        celsius = self._mv_to_celsius(raw_mv)
        return raw_mv, celsius
