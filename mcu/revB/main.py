import time
import math
from machine import I2C, Pin, PWM

# --- ADS1115 (I2C) — class is loaded but not used until you swap main() (see file bottom) ---
_REG_CONVERSION = 0x00
_REG_CONFIG = 0x01
_MUX = [0x4000, 0x5000, 0x6000, 0x7000]
_PGA = 0x0200
_MODE_ONE = 0x0100
_DR_128SPS = 0x0080
_OS_START = 0x8000


# Head pad
class HeatPad:
    def __init__(self, pin):
        self.pin = pin
        self.on = False

    def on(self):
        self.on = True
    
    def off(self):
        self.on = False


# Thermistor sensors
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


# Concentration
"""
AD5933 MicroPython driver for SensorBoard v0 (XIAO RP2040).

Hardware:
    XIAO RP2040  -- I2C1, SDA = GPIO6, SCL = GPIO7
    AD5933       -- I2C address 0x0D (fixed)
    Internal MCLK = 16.776 MHz (default; no external clock used)

NOTE on the user's request "voltage sweep of 1 kHz to 200 kHz":
    The AD5933 performs a *frequency* sweep at a programmable excitation
    *voltage* (one of four ranges, fixed for the whole sweep). It does not
    sweep voltage itself. This driver implements a frequency sweep, which
    is what the chip is built for.

NOTE on 200 kHz upper bound:
    The AD5933 datasheet specifies a maximum output frequency of 100 kHz
    (Table 1, Transmit Stage). The DDS math works up to ~MCLK/4 so the
    chip will still produce output above 100 kHz, but the on-chip
    anti-alias filter, PGA, and ADC are not characterized there --
    expect degraded magnitude/phase accuracy. Sweeping to 200 kHz is
    out of spec.
"""


class AD5933:
    # ---- I2C address ----
    I2C_ADDR = 0x0D

    # ---- Register map ----
    REG_CONTROL_HI       = 0x80
    REG_CONTROL_LO       = 0x81
    REG_START_FREQ_HI    = 0x82  # D23..D16
    REG_START_FREQ_MID   = 0x83  # D15..D8
    REG_START_FREQ_LO    = 0x84  # D7..D0
    REG_FREQ_INC_HI      = 0x85
    REG_FREQ_INC_MID     = 0x86
    REG_FREQ_INC_LO      = 0x87
    REG_NUM_INC_HI       = 0x88
    REG_NUM_INC_LO       = 0x89
    REG_SETTLING_HI      = 0x8A
    REG_SETTLING_LO      = 0x8B
    REG_STATUS           = 0x8F
    REG_TEMP_HI          = 0x92
    REG_TEMP_LO          = 0x93
    REG_REAL_HI          = 0x94
    REG_REAL_LO          = 0x95
    REG_IMAG_HI          = 0x96
    REG_IMAG_LO          = 0x97

    # ---- Control register D15..D12 (command nibble) ----
    CMD_NOP                = 0x00
    CMD_INIT_START_FREQ    = 0x10  # 0001
    CMD_START_SWEEP        = 0x20  # 0010
    CMD_INCREMENT_FREQ     = 0x30  # 0011
    CMD_REPEAT_FREQ        = 0x40  # 0100
    CMD_MEASURE_TEMP       = 0x90  # 1001
    CMD_POWER_DOWN         = 0xA0  # 1010
    CMD_STANDBY            = 0xB0  # 1011

    # ---- Control register D10..D9 (output excitation range) ----
    RANGE_2VPP    = 0x00  # 2.0 V p-p (Range 1)
    RANGE_200MVPP = 0x02  # 200 mV p-p (Range 4)  -- bits D10D9 = 01
    RANGE_400MVPP = 0x04  # 400 mV p-p (Range 3)  -- bits D10D9 = 10
    RANGE_1VPP    = 0x06  # 1.0 V p-p (Range 2)   -- bits D10D9 = 11

    # ---- Control register D8 (PGA gain) ----
    PGA_X5 = 0x00
    PGA_X1 = 0x01

    # ---- Control register D4 (reset) ----
    BIT_RESET = 0x10

    # ---- Control register D3 (clock source) ----
    CLK_INTERNAL = 0x00
    CLK_EXTERNAL = 0x08

    # ---- Status register bits ----
    STATUS_VALID_TEMP   = 0x01
    STATUS_VALID_DATA   = 0x02
    STATUS_SWEEP_DONE   = 0x04

    # ---- Block-mode command codes (sent as data byte, not register addr) ----
    CMD_BLOCK_WRITE      = 0xA0
    CMD_BLOCK_READ       = 0xA1
    CMD_ADDR_POINTER     = 0xB0

    # ---- Default internal oscillator frequency ----
    INTERNAL_MCLK_HZ = 16_776_000

    def __init__(self, i2c, addr=I2C_ADDR, mclk_hz=INTERNAL_MCLK_HZ,
                 v_range=RANGE_2VPP, pga=PGA_X1, clock_source=CLK_INTERNAL):
        self.i2c = i2c
        self.addr = addr
        self.mclk = mclk_hz
        self._lo_byte = (v_range & 0x06) | (pga & 0x01) | (clock_source & 0x08)

        # Verify the device is on the bus.
        if addr not in i2c.scan():
            raise OSError("AD5933 not found at 0x{:02X}".format(addr))

        # Put it in a known state: reset + standby, internal clock,
        # configured PGA and excitation range.
        self.reset()

    # ------------------------------------------------------------------
    # Low-level I2C helpers
    # ------------------------------------------------------------------
    def _write_reg(self, reg, value):
        """Write a single byte to a register (datasheet Fig. 30)."""
        self.i2c.writeto(self.addr, bytes([reg, value & 0xFF]))

    def _read_reg(self, reg):
        """Read a single byte using the address-pointer + receive-byte
        pattern (datasheet Fig. 31 + Fig. 33)."""
        # Set address pointer
        self.i2c.writeto(self.addr, bytes([self.CMD_ADDR_POINTER, reg]))
        # Receive byte
        return self.i2c.readfrom(self.addr, 1)[0]

    def _block_read(self, reg, n):
        """Read n bytes starting at reg using block-read protocol
        (datasheet Fig. 34)."""
        # Set pointer
        self.i2c.writeto(self.addr, bytes([self.CMD_ADDR_POINTER, reg]))
        # Block-read command + byte count
        self.i2c.writeto(self.addr, bytes([self.CMD_BLOCK_READ, n]))
        return self.i2c.readfrom(self.addr, n)

    # ------------------------------------------------------------------
    # Control register helpers
    # ------------------------------------------------------------------
    def _write_control(self, command_nibble):
        """Write the upper byte of the control register with a command,
        preserving the configured voltage range / PGA / clock source in
        the lower byte."""
        # D15..D8: command nibble in upper 4 bits, D11..D8 are reserved/PGA.
        # D8 is PGA gain (1 = x1, 0 = x5). We store PGA in self._lo_byte
        # actually -- but the datasheet places D8 in the *upper* byte
        # (bit 0 of register 0x80). Re-read carefully:
        #
        #   Register 0x80 holds D15..D8.
        #   Register 0x81 holds D7..D0.
        #   D8 (PGA) is therefore the LSB of 0x80.
        #   D10..D9 (range) are bits 2..1 of 0x80.
        #   D3 (clock source) is bit 3 of 0x81.
        #   D4 (reset) is bit 4 of 0x81.
        #
        # Rebuild upper byte: command in bits 7..4, range in bits 2..1,
        # PGA in bit 0, bit 3 reserved (0).
        hi = (command_nibble & 0xF0) | (self._lo_byte & 0x07)
        self._write_reg(self.REG_CONTROL_HI, hi)

    def _write_control_lo(self, extra_bits=0):
        """Write the lower control byte. extra_bits lets us pulse RESET."""
        lo = (self._lo_byte & 0x08) | (extra_bits & 0xFF)
        # Strip out bits we don't own in lo: only D4 (reset) and D3 (clock).
        # D7..D5, D2..D0 are reserved -> 0.
        lo &= 0x18
        self._write_reg(self.REG_CONTROL_LO, lo)

    def reset(self):
        """Issue a reset, then place the device in standby mode."""
        # Reset bit pulse (D4 = 1) on the lower control byte.
        self._write_control_lo(self.BIT_RESET)
        time.sleep_ms(1)
        # Clear reset, keep clock source bit.
        self._write_control_lo(0)
        # Standby mode in upper byte.
        self._write_control(self.CMD_STANDBY)

    def power_down(self):
        self._write_control(self.CMD_POWER_DOWN)

    def standby(self):
        self._write_control(self.CMD_STANDBY)

    # ------------------------------------------------------------------
    # Frequency programming
    # ------------------------------------------------------------------
    def _freq_to_code(self, freq_hz):
        """Datasheet Eq. 1: code = (freq / (MCLK/4)) * 2^27.
        Uses truncation to match the datasheet's worked example
        (30 kHz @ 16 MHz MCLK -> 0x0F5C28)."""
        code = int((freq_hz / (self.mclk / 4.0)) * (1 << 27))
        if code < 0 or code > 0xFFFFFF:
            raise ValueError("Frequency {} Hz out of 24-bit DDS range".format(freq_hz))
        return code & 0xFFFFFF

    def set_start_frequency(self, freq_hz):
        code = self._freq_to_code(freq_hz)
        self._write_reg(self.REG_START_FREQ_HI,  (code >> 16) & 0xFF)
        self._write_reg(self.REG_START_FREQ_MID, (code >> 8)  & 0xFF)
        self._write_reg(self.REG_START_FREQ_LO,   code        & 0xFF)

    def set_frequency_increment(self, step_hz):
        code = self._freq_to_code(step_hz)
        self._write_reg(self.REG_FREQ_INC_HI,  (code >> 16) & 0xFF)
        self._write_reg(self.REG_FREQ_INC_MID, (code >> 8)  & 0xFF)
        self._write_reg(self.REG_FREQ_INC_LO,   code        & 0xFF)

    def set_number_of_increments(self, n):
        if n < 0 or n > 511:
            raise ValueError("Number of increments must be 0..511")
        self._write_reg(self.REG_NUM_INC_HI, (n >> 8) & 0x01)
        self._write_reg(self.REG_NUM_INC_LO,  n       & 0xFF)

    def set_settling_cycles(self, cycles, multiplier=1):
        """Settling-time cycles register (0x8A/0x8B).
        multiplier: 1, 2, or 4 (D10..D9 of 0x8A)."""
        if cycles < 0 or cycles > 511:
            raise ValueError("Settling cycles must be 0..511")
        mult_bits = {1: 0b00, 2: 0b01, 4: 0b11}.get(multiplier)
        if mult_bits is None:
            raise ValueError("Settling multiplier must be 1, 2, or 4")
        hi = ((mult_bits & 0x03) << 1) | ((cycles >> 8) & 0x01)
        self._write_reg(self.REG_SETTLING_HI, hi)
        self._write_reg(self.REG_SETTLING_LO, cycles & 0xFF)

    # ------------------------------------------------------------------
    # Status & data
    # ------------------------------------------------------------------
    def status(self):
        return self._read_reg(self.REG_STATUS)

    def _read_signed_16(self, reg_hi):
        data = self._block_read(reg_hi, 2)
        raw = (data[0] << 8) | data[1]
        if raw & 0x8000:
            raw -= 0x10000
        return raw

    def read_real_imag(self):
        real = self._read_signed_16(self.REG_REAL_HI)
        imag = self._read_signed_16(self.REG_IMAG_HI)
        return real, imag

    # ------------------------------------------------------------------
    # High-level sweep
    # ------------------------------------------------------------------
    def sweep(self, start_hz, stop_hz, num_points, settling_cycles=15):
        """Run a full frequency sweep and yield (freq, real, imag, |Z|_raw)
        tuples for each point.

        |Z|_raw = sqrt(real^2 + imag^2). Without a calibration step
        (gain factor + system-phase offset) this is *not* impedance in
        ohms -- it's just the raw DFT magnitude. Calibration is left to
        the caller; see datasheet "Impedance Calculation" section.
        """
        if num_points < 2:
            raise ValueError("Need at least 2 points")
        step_hz = (stop_hz - start_hz) / (num_points - 1)

        # --- Datasheet Figure 28 sweep sequence ---
        # 1. Power-down -> standby (already in standby after reset).
        self.standby()
        # 2. Program sweep parameters.
        self.set_start_frequency(start_hz)
        self.set_frequency_increment(step_hz)
        self.set_number_of_increments(num_points - 1)
        self.set_settling_cycles(settling_cycles)
        # 3. Initialize with start frequency (DDS on, no measurement yet).
        self._write_control(self.CMD_INIT_START_FREQ)
        time.sleep_ms(10)  # let the front-end settle
        # 4. Start the sweep.
        self._write_control(self.CMD_START_SWEEP)

        freq = start_hz
        for i in range(num_points):
            # Wait for valid real/imag data at this point.
            t0 = time.ticks_ms()
            while not (self.status() & self.STATUS_VALID_DATA):
                if time.ticks_diff(time.ticks_ms(), t0) > 500:
                    raise OSError("Timeout waiting for AD5933 data at {:.0f} Hz".format(freq))
                time.sleep_us(200)

            real, imag = self.read_real_imag()
            mag_raw = math.sqrt(real * real + imag * imag)
            yield (freq, real, imag, mag_raw)

            # If this was the last point, the sweep-complete flag will be set;
            # otherwise advance to next frequency.
            if i < num_points - 1:
                self._write_control(self.CMD_INCREMENT_FREQ)
                freq += step_hz

        # Park the device.
        self.standby()


# ----------------------------------------------------------------------
# Demo
# ----------------------------------------------------------------------
def main():
    # I2C1 on GPIO6/7 per SensorBoard v0 pinout.
    # AD5933 timing: standard mode (100 kHz) is safest; the chip is rated
    # for fast mode too but we don't need the throughput.
    i2c = I2C(1, sda=Pin(6), scl=Pin(7), freq=100_000)
    print("I2C scan:", [hex(a) for a in i2c.scan()])

    ad = AD5933(i2c,
                v_range=AD5933.RANGE_2VPP,
                pga=AD5933.PGA_X1,
                clock_source=AD5933.CLK_INTERNAL)
    print("AD5933 found and reset.")

    START_HZ = 10_000
    STOP_HZ  = 50_000   # NOTE: above 100 kHz is out of spec
    NUM_PTS  = 100      # 100 points -> ~2 kHz resolution

    if STOP_HZ > 100_000:
        print("WARNING: stop frequency {} Hz exceeds the 100 kHz "
              "rated maximum. Results above 100 kHz are not "
              "guaranteed by the AD5933 datasheet.".format(STOP_HZ))

    print("Sweeping {} Hz -> {} Hz, {} points...".format(START_HZ, STOP_HZ, NUM_PTS))
    print("{:>10s}  {:>8s}  {:>8s}  {:>12s}".format(
        "freq[Hz]", "real", "imag", "|Z|_raw"))

    for freq, real, imag, mag in ad.sweep(START_HZ, STOP_HZ, NUM_PTS,
                                          settling_cycles=15):
        print("{:>10.0f}  {:>8d}  {:>8d}  {:>12.1f}".format(
            freq, real, imag, mag))

    print("Sweep complete.")


if __name__ == "__main__":
    main()


# Load cell sensor
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
    hx = HX711(dout_pin=2, sck_pin=1, gain=128)

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
