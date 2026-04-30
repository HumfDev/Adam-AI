"""
SensorBoard v0 firmware -- XIAO RP2040.

Implements the AGENT.md command API over USB serial (sys.stdin / sys.stdout),
mapped onto the actual board pin layout.

Pin map (actual hardware):
    GPIO0   ADC_RDY (ADS1115 ALERT/RDY -- not used; we poll OS bit)
    GPIO1   HP0 PWM       -- 200 mA heat pad, AO3400A gate
    GPIO2   HP1 PWM       -- 400 mA heat pad, AO3400A gate
    GPIO3   HX711 DT      (DOUT)
    GPIO4   HX711 SCK     (PD_SCK)
    GPIO6   I2C1 SDA      (ADS1115 + AD5933)
    GPIO7   I2C1 SCL      (ADS1115 + AD5933)
    GPIO26  pH_0 ADC      (DISCONNECTED -- routed via ADS1115)
    GPIO27  pH_1 ADC      (DISCONNECTED -- routed via ADS1115)
    GPIO28  thermistor_0  (NTC voltage divider, RP2040 ADC2)
    GPIO29  thermistor_1  (NTC voltage divider, RP2040 ADC3)

I2C bus 1 devices:
    0x0D  AD5933   (impedance / EIS)
    0x48  ADS1115  (pH:  AIN0 = IrOx, AIN1 = Ag/AgCl)

Transport: USB serial (REPL). Frames are '\\n'-terminated ASCII.
"""

import sys
import time
import math
import select
from machine import I2C, Pin, PWM, ADC


VERSION = "1.0.0"


# =============================================================================
# ADS1115 -- 16-bit I2C ADC (used for pH electrode op-amp outputs)
# =============================================================================
_REG_CONVERSION = 0x00
_REG_CONFIG     = 0x01

_MUX_AIN0 = 0x4000
_MUX_AIN1 = 0x5000
_MUX_AIN2 = 0x6000
_MUX_AIN3 = 0x7000
_MUX = [_MUX_AIN0, _MUX_AIN1, _MUX_AIN2, _MUX_AIN3]

# AGENT.md asks for +/- 2.048 V FSR on the pH path.
_PGA_2_048V   = 0x0400
_MODE_SINGLE  = 0x0100
_DR_16SPS     = 0x0000   # slowest data rate -> best noise rejection on pH
_OS_START     = 0x8000
_COMP_DISABLE = 0x0003


class ADS1115Sensor:
    """Single-ended ADS1115 reader. Bus is shared with AD5933."""

    LSB_VOLTS_2V048 = 2.048 / 32768.0    # 62.5 uV per LSB

    def __init__(self, i2c, addr=0x48):
        self.i2c = i2c
        self.addr = addr
        self.present = addr in i2c.scan()

    def read(self, channel, timeout_ms=200):
        """Single-ended read. Returns (raw_counts, volts) or raises OSError."""
        if channel not in (0, 1, 2, 3):
            raise ValueError("channel must be 0..3")
        if not self.present:
            raise OSError("ADS1115 not present")

        config = (_OS_START | _MUX[channel] | _PGA_2_048V
                  | _MODE_SINGLE | _DR_16SPS | _COMP_DISABLE)
        self.i2c.writeto(self.addr,
                         bytes([_REG_CONFIG, (config >> 8) & 0xFF, config & 0xFF]))

        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while True:
            self.i2c.writeto(self.addr, bytes([_REG_CONFIG]))
            d = self.i2c.readfrom(self.addr, 2)
            if (d[0] << 8 | d[1]) & _OS_START:
                break
            if time.ticks_diff(time.ticks_ms(), deadline) > 0:
                raise OSError("ADS1115 conversion timeout (ch {})".format(channel))
            time.sleep_ms(5)

        self.i2c.writeto(self.addr, bytes([_REG_CONVERSION]))
        d = self.i2c.readfrom(self.addr, 2)
        raw = (d[0] << 8) | d[1]
        if raw & 0x8000:
            raw -= 0x10000
        return raw, raw * self.LSB_VOLTS_2V048


# =============================================================================
# Thermistor -- 10K NTC + 10K fixed pullup, RP2040 internal ADC
# =============================================================================
class Thermistor:
    """10K NTC, 10K fixed resistor.

    Wiring assumed:  3V3 --- R_FIXED --- ADC_PIN --- NTC --- GND
    so V_adc = 3.3 * R_ntc / (R_FIXED + R_ntc).

    If the schematic actually has the NTC on the high side, flip the
    formula in read_resistance() to:
        R_ntc = R_FIXED * (V_REF - V) / V
    """

    ADC_REF_V = 3.3
    ADC_FULL  = 65535

    def __init__(self, pin_num, r_fixed=10_000.0,
                 r0=10_000.0, t0_c=25.0, beta=3950.0):
        self.adc = ADC(Pin(pin_num))
        self.r_fixed = r_fixed
        self.r0 = r0
        self.t0_k = t0_c + 273.15
        self.beta = beta

    def read_voltage(self):
        return self.adc.read_u16() * self.ADC_REF_V / self.ADC_FULL

    def read_resistance(self):
        v = self.read_voltage()
        if v <= 0.001 or v >= self.ADC_REF_V - 0.001:
            return None
        return self.r_fixed * v / (self.ADC_REF_V - v)

    def read_celsius(self):
        r = self.read_resistance()
        if r is None or r <= 0:
            return None
        inv_t = 1.0 / self.t0_k + math.log(r / self.r0) / self.beta
        return 1.0 / inv_t - 273.15

    def read_mv_and_celsius(self):
        v = self.read_voltage()
        c = self.read_celsius()
        return int(v * 1000), c


# =============================================================================
# HeatPad -- PWM on AO3400A gate
# =============================================================================
class HeatPad:
    def __init__(self, pin_num, freq_hz=1000):
        self.pwm = PWM(Pin(pin_num))
        self.pwm.freq(freq_hz)
        self.pwm.duty_u16(0)
        self._duty_pct = 0

    def set_duty_pct(self, pct):
        if pct < 0:
            pct = 0
        elif pct > 100:
            pct = 100
        self._duty_pct = int(pct)
        self.pwm.duty_u16(int(self._duty_pct * 65535 // 100))

    def get_duty_pct(self):
        return self._duty_pct

    def off(self):
        self.set_duty_pct(0)


# =============================================================================
# HX711 -- 24-bit load cell ADC, bit-bang
# =============================================================================
class HX711:
    GAIN_PULSES = {128: 1, 64: 3, 32: 2}

    def __init__(self, dout_pin, sck_pin, gain=128):
        self.dout = Pin(dout_pin, Pin.IN)
        self.sck  = Pin(sck_pin, Pin.OUT)
        self.sck.value(0)
        self.gain = gain
        self.offset = 0
        self.scale = 1.0   # raw counts per gram -- user calibrates externally

    def _gain_pulse_count(self):
        return self.GAIN_PULSES[self.gain]

    def read_raw(self, timeout_ms=200):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
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

        for _ in range(self._gain_pulse_count()):
            self.sck.value(1)
            time.sleep_us(1)
            self.sck.value(0)
            time.sleep_us(1)

        if raw & 0x800000:
            raw -= 0x1000000
        return raw

    def tare(self, samples=10):
        readings = []
        for _ in range(samples):
            r = self.read_raw()
            if r is not None:
                readings.append(r)
        if not readings:
            return False
        self.offset = sum(readings) // len(readings)
        return True

    def get_value(self):
        raw = self.read_raw()
        if raw is None:
            return None, None
        offset_corrected = raw - self.offset
        grams = offset_corrected / self.scale if self.scale else 0.0
        return raw, grams

    def set_gain(self, gain):
        if gain not in self.GAIN_PULSES:
            raise ValueError("gain must be 128, 64, or 32")
        self.gain = gain
        # New gain takes effect on next conversion -- issue a throwaway read.
        self.read_raw()


# =============================================================================
# AD5933 -- impedance converter
# =============================================================================
class AD5933:
    I2C_ADDR = 0x0D

    REG_CONTROL_HI    = 0x80
    REG_CONTROL_LO    = 0x81
    REG_START_FREQ_HI = 0x82
    REG_FREQ_INC_HI   = 0x85
    REG_NUM_INC_HI    = 0x88
    REG_NUM_INC_LO    = 0x89
    REG_SETTLING_HI   = 0x8A
    REG_SETTLING_LO   = 0x8B
    REG_STATUS        = 0x8F
    REG_REAL_HI       = 0x94
    REG_IMAG_HI       = 0x96

    CMD_INIT_START_FREQ = 0x10
    CMD_START_SWEEP     = 0x20
    CMD_INCREMENT_FREQ  = 0x30
    CMD_POWER_DOWN      = 0xA0
    CMD_STANDBY         = 0xB0

    # AGENT.md API mapping: 1->2Vpp, 2->1Vpp, 3->400mVpp, 4->200mVpp.
    VRANGE_BITS = {
        1: 0x00,   # 2.0  V p-p
        2: 0x06,   # 1.0  V p-p
        3: 0x04,   # 400 mV p-p
        4: 0x02,   # 200 mV p-p
    }

    PGA_X1 = 0x01
    PGA_X5 = 0x00

    BIT_RESET    = 0x10
    CLK_INTERNAL = 0x00

    STATUS_VALID_DATA = 0x02
    STATUS_SWEEP_DONE = 0x04

    CMD_BLOCK_READ   = 0xA1
    CMD_ADDR_POINTER = 0xB0

    INTERNAL_MCLK_HZ = 16_776_000

    def __init__(self, i2c, addr=I2C_ADDR):
        self.i2c = i2c
        self.addr = addr
        self.mclk = self.INTERNAL_MCLK_HZ
        self._upper_cfg = self.VRANGE_BITS[1] | self.PGA_X1
        self._lower_cfg = self.CLK_INTERNAL
        self.present = addr in i2c.scan()
        if self.present:
            self.reset()

    def _write_reg(self, reg, value):
        self.i2c.writeto(self.addr, bytes([reg, value & 0xFF]))

    def _read_reg(self, reg):
        self.i2c.writeto(self.addr, bytes([self.CMD_ADDR_POINTER, reg]))
        return self.i2c.readfrom(self.addr, 1)[0]

    def _block_read(self, reg, n):
        self.i2c.writeto(self.addr, bytes([self.CMD_ADDR_POINTER, reg]))
        self.i2c.writeto(self.addr, bytes([self.CMD_BLOCK_READ, n]))
        return self.i2c.readfrom(self.addr, n)

    def _write_control_hi(self, command_nibble):
        self._write_reg(self.REG_CONTROL_HI,
                        (command_nibble & 0xF0) | (self._upper_cfg & 0x07))

    def _write_control_lo(self, extra_bits=0):
        self._write_reg(self.REG_CONTROL_LO,
                        (self._lower_cfg & 0x08) | (extra_bits & 0x10))

    def reset(self):
        self._write_control_lo(self.BIT_RESET)
        time.sleep_ms(1)
        self._write_control_lo(0)
        self._write_control_hi(self.CMD_STANDBY)

    def configure(self, vrange_api, gain_api):
        if vrange_api not in self.VRANGE_BITS:
            raise ValueError("vrange must be 1..4")
        if gain_api not in (1, 5):
            raise ValueError("gain must be 1 or 5")
        self._upper_cfg = (self.VRANGE_BITS[vrange_api]
                           | (self.PGA_X1 if gain_api == 1 else self.PGA_X5))

    def _freq_to_code(self, freq_hz):
        code = int((freq_hz / (self.mclk / 4.0)) * (1 << 27))
        if code < 0 or code > 0xFFFFFF:
            raise ValueError("Frequency {} Hz out of DDS range".format(freq_hz))
        return code

    def _set_24bit_reg(self, reg_hi, code):
        self._write_reg(reg_hi,     (code >> 16) & 0xFF)
        self._write_reg(reg_hi + 1, (code >>  8) & 0xFF)
        self._write_reg(reg_hi + 2,  code        & 0xFF)

    def _set_settling(self, cycles):
        if cycles < 0 or cycles > 511:
            raise ValueError("settling 0..511")
        self._write_reg(self.REG_SETTLING_HI, (cycles >> 8) & 0x01)
        self._write_reg(self.REG_SETTLING_LO,  cycles       & 0xFF)

    def _read_signed_16(self, reg_hi):
        d = self._block_read(reg_hi, 2)
        v = (d[0] << 8) | d[1]
        if v & 0x8000:
            v -= 0x10000
        return v

    def sweep(self, start_hz, stop_hz, steps, settling_cycles=15,
              point_timeout_ms=500):
        """Yields (freq, real, imag) for each of (steps + 1) points."""
        if not self.present:
            raise OSError("AD5933 not present")
        if steps < 1 or steps > 511:
            raise ValueError("steps 1..511")

        num_points = steps + 1
        step_hz = (stop_hz - start_hz) / steps if steps > 0 else 0

        self._write_control_hi(self.CMD_STANDBY)
        self._set_24bit_reg(self.REG_START_FREQ_HI, self._freq_to_code(start_hz))
        self._set_24bit_reg(self.REG_FREQ_INC_HI,
                            self._freq_to_code(step_hz) if step_hz > 0 else 0)
        self._write_reg(self.REG_NUM_INC_HI, (steps >> 8) & 0x01)
        self._write_reg(self.REG_NUM_INC_LO,  steps       & 0xFF)
        self._set_settling(settling_cycles)
        self._write_control_hi(self.CMD_INIT_START_FREQ)
        time.sleep_ms(10)
        self._write_control_hi(self.CMD_START_SWEEP)

        freq = start_hz
        for i in range(num_points):
            t0 = time.ticks_ms()
            while not (self._read_reg(self.REG_STATUS) & self.STATUS_VALID_DATA):
                if time.ticks_diff(time.ticks_ms(), t0) > point_timeout_ms:
                    self._write_control_hi(self.CMD_STANDBY)
                    raise OSError("AD5933 timeout at {:.0f} Hz".format(freq))
                time.sleep_us(200)

            real = self._read_signed_16(self.REG_REAL_HI)
            imag = self._read_signed_16(self.REG_IMAG_HI)
            yield (freq, real, imag)

            if i < num_points - 1:
                self._write_control_hi(self.CMD_INCREMENT_FREQ)
                freq += step_hz

        self._write_control_hi(self.CMD_STANDBY)


# =============================================================================
# pH calibration storage (filesystem -- survives power cycles)
# =============================================================================
PH_CAL_PATH = "/ph_cal.txt"


def load_ph_cal():
    """Return (slope_mv_per_pH, offset_mv). Default: Nernstian @ 25 C."""
    try:
        with open(PH_CAL_PATH, "r") as f:
            line = f.readline().strip()
            slope_str, offset_str = line.split(",")
            return float(slope_str), float(offset_str)
    except (OSError, ValueError):
        return -59.16, 0.0


def save_ph_cal(slope, offset):
    with open(PH_CAL_PATH, "w") as f:
        f.write("{},{}\n".format(slope, offset))


# =============================================================================
# Command server
# =============================================================================
class Server:
    """AGENT.md command surface over USB serial."""

    EIS_INLINE_MAX_POINTS = 250
    EIS_PAGE_SIZE         = 50

    # STATUS bitmask (AGENT.md s3.1)
    STATUS_HP0  = 0x01
    STATUS_HP1  = 0x02
    STATUS_TH0  = 0x04
    STATUS_TH1  = 0x08
    STATUS_LOAD = 0x10
    STATUS_PH   = 0x20
    STATUS_EIS  = 0x40

    def __init__(self):
        self.i2c = I2C(1, sda=Pin(6), scl=Pin(7), freq=400_000)

        self.therm0 = Thermistor(28)
        self.therm1 = Thermistor(29)
        self.hx     = HX711(dout_pin=3, sck_pin=4, gain=128)
        self.ads    = ADS1115Sensor(self.i2c, addr=0x48)
        self.ad5933 = AD5933(self.i2c)

        self.hp0 = HeatPad(1)   # 200 mA pad
        self.hp1 = HeatPad(2)   # 400 mA pad
        self.hp0.off()
        self.hp1.off()

        self.ph_slope, self.ph_offset = load_ph_cal()

        # AGENT.md default EIS parameters
        self.eis_start  = 1000
        self.eis_stop   = 200000
        self.eis_steps  = 100
        self.eis_vrange = 1
        self.eis_gain   = 1

        self.eis_last = None    # list of (freq, real, imag) from last sweep

        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)
        self._buf = ""

        self._dispatch = self._build_dispatch()

    # ---------------------------------------------------------------- transport
    def _send(self, line):
        sys.stdout.write(line)
        if not line.endswith("\n"):
            sys.stdout.write("\n")

    def _err(self, code, msg):
        self._send("ERR:{}:{}".format(code, msg))

    def _readline_nonblocking(self):
        """Drain stdin, return one '\\n'-delimited line if available."""
        events = self._poll.poll(0)
        if events:
            ch = sys.stdin.read(1)
            if ch:
                self._buf += ch
        if "\n" in self._buf:
            line, _, rest = self._buf.partition("\n")
            self._buf = rest
            return line.rstrip("\r")
        return None

    # ---------------------------------------------------------------- status
    def _status_byte(self):
        b = (self.STATUS_HP0 | self.STATUS_HP1
             | self.STATUS_TH0 | self.STATUS_TH1
             | self.STATUS_LOAD)
        if self.ads.present:
            b |= self.STATUS_PH
        if self.ad5933.present:
            b |= self.STATUS_EIS
        return b

    # ---------------------------------------------------------------- handlers
    def _h_ping(self, arg):
        self._send("PING:OK")

    def _h_version(self, arg):
        self._send("VERSION:{}".format(VERSION))

    def _h_status(self, arg):
        self._send("STATUS:{:02X}".format(self._status_byte()))

    # heat pads
    def _h_set_hp(self, pad, arg):
        if arg is None:
            return self._err("ARG", "duty required")
        try:
            duty = int(arg)
        except ValueError:
            return self._err("ARG", "duty must be integer")
        if duty < 0 or duty > 100:
            return self._err("ARG", "duty out of range")
        (self.hp0 if pad == 0 else self.hp1).set_duty_pct(duty)
        self._send("HP{}:{}".format(pad, duty))

    def _h_get_hp(self, pad, arg):
        duty = self.hp0.get_duty_pct() if pad == 0 else self.hp1.get_duty_pct()
        self._send("HP{}:{}".format(pad, duty))

    # thermistors
    def _h_get_temp(self, idx, arg):
        therm = self.therm0 if idx == 0 else self.therm1
        mv, c = therm.read_mv_and_celsius()
        if c is None:
            return self._err("TIMEOUT", "TEMP{} open or shorted".format(idx))
        self._send("TEMP{}:{},{:.1f}".format(idx, mv, c))

    # load cell
    def _h_get_load(self, arg):
        raw, grams = self.hx.get_value()
        if raw is None:
            return self._err("TIMEOUT", "HX711")
        self._send("LOAD:{},{:.2f}".format(raw, grams))

    def _h_set_load_tare(self, arg):
        if self.hx.tare(samples=10):
            self._send("LOAD:TARE:OK")
        else:
            self._err("TIMEOUT", "HX711")

    def _h_set_load_gain(self, arg):
        if arg is None:
            return self._err("ARG", "gain required")
        try:
            g = int(arg)
        except ValueError:
            return self._err("ARG", "gain must be 128, 64, or 32")
        if g not in (128, 64, 32):
            return self._err("ARG", "gain must be 128, 64, or 32")
        try:
            self.hx.set_gain(g)
        except Exception:
            return self._err("TIMEOUT", "HX711")
        self._send("LOAD:GAIN:{}".format(g))

    def _h_get_load_cfg(self, arg):
        self._send("LOAD:CFG:{},{}".format(self.hx.gain, self.hx.offset))

    # pH
    def _read_ph_volts(self):
        if not self.ads.present:
            raise OSError("ADS1115 not present")
        ir_raw, ir_v = self.ads.read(0)
        ag_raw, ag_v = self.ads.read(1)
        return ir_raw, ir_v, ag_raw, ag_v

    def _h_get_ph(self, arg):
        try:
            _, ir_v, _, ag_v = self._read_ph_volts()
        except OSError as e:
            return self._err("I2CERR", str(e))
        ir_mv = int(ir_v * 1000)
        ag_mv = int(ag_v * 1000)
        diff_mv = ir_mv - ag_mv
        if self.ph_slope == 0:
            return self._err("NOCALIB", "slope is zero")
        ph = (diff_mv - self.ph_offset) / self.ph_slope
        self._send("PH:{},{},{},{:.2f}".format(ir_mv, ag_mv, diff_mv, ph))

    def _h_get_ph_raw(self, arg):
        try:
            ir_raw, _, ag_raw, _ = self._read_ph_volts()
        except OSError as e:
            return self._err("I2CERR", str(e))
        self._send("PH:RAW:{},{}".format(ir_raw, ag_raw))

    def _h_set_ph_cal(self, arg):
        if arg is None:
            return self._err("ARG", "slope:offset required")
        parts = arg.split(":")
        if len(parts) != 2:
            return self._err("ARG", "expected slope:offset")
        try:
            slope = float(parts[0])
            offset = float(parts[1])
        except ValueError:
            return self._err("ARG", "slope/offset must be float")
        self.ph_slope = slope
        self.ph_offset = offset
        try:
            save_ph_cal(slope, offset)
        except OSError as e:
            return self._err("I2CERR", "flash write: {}".format(e))
        self._send("PH:CAL:OK")

    # EIS
    def _h_set_eis_start(self, arg):
        try:
            hz = int(arg)
        except (TypeError, ValueError):
            return self._err("ARG", "start hz required")
        if hz < 1:
            return self._err("ARG", "start must be >= 1 Hz")
        self.eis_start = hz
        self._send("EIS:START:{}".format(hz))

    def _h_set_eis_stop(self, arg):
        try:
            hz = int(arg)
        except (TypeError, ValueError):
            return self._err("ARG", "stop hz required")
        if hz < 1:
            return self._err("ARG", "stop must be >= 1 Hz")
        self.eis_stop = hz
        self._send("EIS:STOP:{}".format(hz))

    def _h_set_eis_steps(self, arg):
        try:
            n = int(arg)
        except (TypeError, ValueError):
            return self._err("ARG", "steps required")
        if n < 1:
            return self._err("ARG", "steps must be >= 1")
        if n > 511:
            return self._err("ARG", "max 511 steps")
        self.eis_steps = n
        self._send("EIS:STEPS:{}".format(n))

    def _h_set_eis_vrange(self, arg):
        try:
            v = int(arg)
        except (TypeError, ValueError):
            return self._err("ARG", "vrange 1..4")
        if v not in (1, 2, 3, 4):
            return self._err("ARG", "vrange 1..4")
        self.eis_vrange = v
        self._send("EIS:VRANGE:{}".format(v))

    def _h_set_eis_gain(self, arg):
        try:
            g = int(arg)
        except (TypeError, ValueError):
            return self._err("ARG", "gain 1 or 5")
        if g not in (1, 5):
            return self._err("ARG", "gain 1 or 5")
        self.eis_gain = g
        self._send("EIS:GAIN:{}".format(g))

    def _h_get_eis_cfg(self, arg):
        self._send("EIS:CFG:{},{},{},{},{}".format(
            self.eis_start, self.eis_stop, self.eis_steps,
            self.eis_vrange, self.eis_gain))

    def _h_set_eis_run(self, arg):
        if not self.ad5933.present:
            return self._err("I2CERR", "AD5933 absent")
        try:
            self.ad5933.configure(self.eis_vrange, self.eis_gain)
            points = []
            for f, r, i in self.ad5933.sweep(
                    self.eis_start, self.eis_stop, self.eis_steps):
                points.append((f, r, i))
        except OSError:
            return self._err("TIMEOUT", "AD5933")
        except ValueError as e:
            return self._err("ARG", str(e))

        self.eis_last = points
        n = len(points)
        if n <= self.EIS_INLINE_MAX_POINTS:
            self._send_eis_inline(points)
        else:
            page_count = (n + self.EIS_PAGE_SIZE - 1) // self.EIS_PAGE_SIZE
            self._send("EIS:READY:{}:{}".format(n, page_count))

    def _h_get_eis_last(self, arg):
        if self.eis_last is None:
            return self._err("NODATA", "no sweep completed")
        n = len(self.eis_last)
        if n <= self.EIS_INLINE_MAX_POINTS:
            self._send_eis_inline(self.eis_last)
        else:
            page_count = (n + self.EIS_PAGE_SIZE - 1) // self.EIS_PAGE_SIZE
            self._send("EIS:READY:{}:{}".format(n, page_count))

    def _h_get_eis_page(self, arg):
        if self.eis_last is None:
            return self._err("NODATA", "no sweep completed")
        try:
            k = int(arg)
        except (TypeError, ValueError):
            return self._err("ARG", "page index required")
        n = len(self.eis_last)
        page_count = (n + self.EIS_PAGE_SIZE - 1) // self.EIS_PAGE_SIZE
        if k < 0 or k >= page_count:
            return self._err("ARG", "page out of range")
        start = k * self.EIS_PAGE_SIZE
        end = min(start + self.EIS_PAGE_SIZE, n)
        slice_str = self._format_points(self.eis_last[start:end])
        self._send("EIS:PAGE:{}:{}".format(k, slice_str))

    def _format_points(self, points):
        # AGENT.md format: "f,R,I;f,R,I;..."
        return ";".join("{:.0f},{},{}".format(f, r, i) for (f, r, i) in points)

    def _send_eis_inline(self, points):
        self._send("EIS:DATA:{}:{}".format(len(points), self._format_points(points)))

    # ---------------------------------------------------------------- dispatch
    def _build_dispatch(self):
        # (prefix, handler, takes_arg).
        # More specific prefixes first so that 'SET:LOAD:TARE' matches
        # before 'SET:LOAD' (which doesn't exist as a command anyway, but
        # the prefix-matching pass picks the longest match defensively).
        return [
            ("PING",           lambda a: self._h_ping(a),           False),
            ("VERSION",        lambda a: self._h_version(a),        False),
            ("STATUS",         lambda a: self._h_status(a),         False),

            ("SET:HP0",        lambda a: self._h_set_hp(0, a),      True),
            ("SET:HP1",        lambda a: self._h_set_hp(1, a),      True),
            ("GET:HP0",        lambda a: self._h_get_hp(0, a),      False),
            ("GET:HP1",        lambda a: self._h_get_hp(1, a),      False),

            ("GET:TEMP0",      lambda a: self._h_get_temp(0, a),    False),
            ("GET:TEMP1",      lambda a: self._h_get_temp(1, a),    False),

            ("SET:LOAD:TARE",  lambda a: self._h_set_load_tare(a),  False),
            ("SET:LOAD:GAIN",  lambda a: self._h_set_load_gain(a),  True),
            ("GET:LOAD:CFG",   lambda a: self._h_get_load_cfg(a),   False),
            ("GET:LOAD",       lambda a: self._h_get_load(a),       False),

            ("SET:PH:CAL",     lambda a: self._h_set_ph_cal(a),     True),
            ("GET:PH:RAW",     lambda a: self._h_get_ph_raw(a),     False),
            ("GET:PH",         lambda a: self._h_get_ph(a),         False),

            ("SET:EIS:START",  lambda a: self._h_set_eis_start(a),  True),
            ("SET:EIS:STOP",   lambda a: self._h_set_eis_stop(a),   True),
            ("SET:EIS:STEPS",  lambda a: self._h_set_eis_steps(a),  True),
            ("SET:EIS:VRANGE", lambda a: self._h_set_eis_vrange(a), True),
            ("SET:EIS:GAIN",   lambda a: self._h_set_eis_gain(a),   True),
            ("SET:EIS:RUN",    lambda a: self._h_set_eis_run(a),    False),
            ("GET:EIS:CFG",    lambda a: self._h_get_eis_cfg(a),    False),
            ("GET:EIS:LAST",   lambda a: self._h_get_eis_last(a),   False),
            ("GET:EIS:PAGE",   lambda a: self._h_get_eis_page(a),   True),
        ]

    def _dispatch_line(self, line):
        line = line.strip()
        if not line:
            return

        # Find the longest matching prefix in the dispatch table.
        best = None
        for prefix, handler, takes_arg in self._dispatch:
            if line == prefix:
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, handler, takes_arg, None)
            elif takes_arg and line.startswith(prefix + ":"):
                arg = line[len(prefix) + 1:]
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, handler, takes_arg, arg)

        if best is None:
            return self._err("UNK", "unknown command")

        _, handler, _, arg = best
        try:
            handler(arg)
        except Exception as e:
            self._err("UNK", "handler exception: {}".format(e))

    # ---------------------------------------------------------------- main loop
    def run(self):
        # Comment lines starting with '#' so a host parser can skip the banner.
        self._send("# SensorBoard v0 firmware {}".format(VERSION))
        self._send("# I2C devices: " + ",".join(hex(a) for a in self.i2c.scan()))
        self._send("# STATUS: 0x{:02X}".format(self._status_byte()))

        while True:
            line = self._readline_nonblocking()
            if line is not None:
                self._dispatch_line(line)
            else:
                time.sleep_ms(2)


def main():
    Server().run()

main()