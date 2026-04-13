# HX711 24-bit load-cell ADC for Klipper (bit-banged on the printer MCU)
#
# Protocol: DOUT + PD_SCK (not I2C/SPI/UART). See datasheet for timing.
#
# Seeed Studio XIAO RP2040 — example (D0/D1, no UART conflict if unused):
#
#   [mcu xiao]
#   serial: /dev/serial/by-id/usb-Klipper_rp2040_...
#
#   [hx711 loadcell1]
#   dout_pin: xiao:^gpio26
#   sck_pin: xiao:gpio27
#   gain: 128
#   report_time: 0.5
#   # offset: <raw at no load>
#   # scale: <raw_delta per gram>
#
# If the XIAO is your *only* MCU, drop the xiao: prefix:
#   dout_pin: ^gpio26
#   sck_pin: gpio27
#
# Klipper RP2040 pins use the SoC name: gpio0 … gpio29 (see wiki pin map:
# D4/D5 = I2C gpio6/gpio7, D0/D1 = gpio26/gpio27, etc.)
#
#   [gcode_macro READ_LOADCELL]
#   gcode:
#     {action_respond_info("HX711 raw: %s" % (printer["hx711 loadcell1"].raw,))}
#
# Copy into Klipper's klippy/extras/, then: sudo service klipper restart
#
# Copyright (C) 2025  — custom extra; GPLv3 per Klipper ecosystem
import logging
from .bus import MCU_bus_digital_out

GAIN_EXTRA_PULSES = {128: 1, 64: 3, 32: 2}


class HX711:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.reactor = self.printer.get_reactor()
        self.gain = config.getint('gain', 128, minval=32, maxval=128)
        if self.gain not in GAIN_EXTRA_PULSES:
            raise config.error("hx711: gain must be 32, 64, or 128")
        self.gain_pulses = GAIN_EXTRA_PULSES[self.gain]
        self.report_time = config.getfloat('report_time', 1.0, minval=0.1, maxval=30.0)
        self.read_timeout = config.getfloat('read_timeout', 0.5, minval=0.05, maxval=5.0)
        self.bit_delay = config.getfloat('bit_delay', 0.0002, minval=0.00005, maxval=0.01)
        self.offset = config.getint('offset', 0)
        self.scale = config.getfloat('scale', 0., minval=0.)

        ppins = self.printer.lookup_object('pins')
        self.dout = ppins.setup_pin('endstop', config.get('dout_pin'))
        mcu = self.dout.get_mcu()
        sck_desc = config.get('sck_pin')
        sp = ppins.lookup_pin(sck_desc, can_invert=True)
        if sp['chip'] is not mcu:
            raise config.error("hx711: dout_pin and sck_pin must be on the same mcu")
        self.sck = MCU_bus_digital_out(mcu, sck_desc)

        self.last_raw = 0
        self.last_weight_g = None
        self.error_count = 0

        self.printer.add_object("hx711 " + self.name, self)
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        self.reactor.register_timer(self._poll, self.reactor.NOW)

    def _print_time(self):
        return self.dout.get_mcu().estimated_print_time(self.reactor.monotonic())

    def _pause_bit(self):
        self.reactor.pause(self.reactor.monotonic() + self.bit_delay)

    def _read_raw(self, eventtime):
        """Read one 24-bit signed sample; returns None on timeout."""
        mcu = self.dout.get_mcu()
        deadline = eventtime + self.read_timeout

        while self.dout.query_endstop(self._print_time()):
            self._pause_bit()
            if self.reactor.monotonic() > deadline:
                return None

        raw = 0
        for _ in range(24):
            self.sck.update_digital_out(1)
            self._pause_bit()
            bit = self.dout.query_endstop(self._print_time())
            raw = (raw << 1) | int(bit)
            self.sck.update_digital_out(0)
            self._pause_bit()

        for _ in range(self.gain_pulses):
            self.sck.update_digital_out(1)
            self._pause_bit()
            self.sck.update_digital_out(0)
            self._pause_bit()

        if raw & 0x800000:
            raw -= 0x1000000
        return raw

    def _poll(self, eventtime):
        raw = self._read_raw(eventtime)
        if raw is None:
            self.error_count += 1
            logging.warning("HX711 %s: read timeout", self.name)
        else:
            self.last_raw = raw
            if self.scale > 0.:
                self.last_weight_g = (raw - self.offset) / self.scale
            else:
                self.last_weight_g = None
        return eventtime + self.report_time

    def get_status(self, eventtime):
        st = {
            'raw': self.last_raw,
            'gain': self.gain,
            'errors': self.error_count,
        }
        if self.last_weight_g is not None:
            st['weight_g'] = round(self.last_weight_g, 3)
        return st


def load_config_prefix(config):
    return HX711(config)
