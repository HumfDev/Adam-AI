# AGENT.md — Biosensor MCU Firmware
## Command API Implementation Guide

This document contains everything an AI agent needs to implement the serial command API
for the XIAO RP2040 biosensor MCU. Read it entirely before writing any code.

---

## 1. Hardware Overview

### MCU
- **Board:** Seeed Studio XIAO RP2040
- **Core:** Dual-core ARM Cortex-M0+ @ up to 133 MHz
- **Logic voltage:** 3.3 V strictly — GPIO pins are NOT 5V tolerant
- **Flash:** 2 MB onboard
- **SRAM:** 264 KB

### Pin Assignments

| XIAO Pin | RP2040 GPIO | Assignment in this project       |
|----------|-------------|----------------------------------|
| D4       | GPIO6       | I2C SDA (AD5933 + ADS1113)       |
| D5       | GPIO7       | I2C SCL (AD5933 + ADS1113)       |
| D6       | GPIO0       | UART TX → host (Raspberry Pi / app) |
| D7       | GPIO1       | UART RX ← host                   |
| D0       | GPIO26      | ADC ch0 — Thermistor 0 (fallback onboard ADC for pH ch0) |
| D1       | GPIO27      | ADC ch1 — Thermistor 1 (fallback onboard ADC for pH ch1) |
| D8       | GPIO2       | HX711 SCK (bit-bang)              |
| D9       | GPIO4       | HX711 DOUT (bit-bang)             |
| D2       | GPIO28      | PWM — Heat pad 0 (200 mA path)    |
| D3       | GPIO29      | PWM — Heat pad 1 (400 mA path)    |

> All D0–D10 pins support PWM. The heat pad PWM signals drive external transistor
> gates — the pads themselves are powered from the 5 V supply rail, not from GPIO.

---

## 2. Serial Transport

### Physical layer
- Interface: UART via D6 (TX) / D7 (RX)
- Baud rate: **115200**
- Data bits: 8, stop bits: 1, no parity (8N1)
- No hardware flow control

### Frame format
```
Request  (host → MCU):   CMD[:<ARG>]\n
Response (MCU → host):   CMD:<VALUE>\n        on success
Error    (MCU → host):   ERR:<CODE>:<MSG>\n   on failure
```

- `\n` (0x0A) is the **sole** frame delimiter. Do not use `\r\n`.
- All fields are printable ASCII.
- The MCU echoes the command name in every response so the host can match
  responses without maintaining sequenced state.
- The MCU is a **server** — it only sends data when polled. It never
  spontaneously transmits.
- Requests must not be sent before the previous response has been received,
  except for `PING` which is always safe to issue.

### Timeouts (host-side guidance, implement on host not MCU)
| Command          | Recommended host timeout |
|------------------|--------------------------|
| PING, VERSION    | 200 ms                   |
| GET:TEMP*, GET:HP* | 500 ms                 |
| GET:LOAD         | 1 000 ms                 |
| GET:PH           | 1 000 ms                 |
| SET:EIS:RUN      | 30 000 ms (sweep can take several seconds) |
| All SET commands | 500 ms                   |

---

## 3. Complete Command Reference

### 3.1 System commands

#### `PING`
- **Request:** `PING\n`
- **Response:** `PING:OK\n`
- **Purpose:** Liveness check. Always responds immediately regardless of sensor state.

#### `VERSION`
- **Request:** `VERSION\n`
- **Response:** `VERSION:<semver>\n` — e.g. `VERSION:1.0.0\n`

#### `STATUS`
- **Request:** `STATUS\n`
- **Response:** `STATUS:<hex_byte>\n` — bitmask of sensor readiness

| Bit | Sensor           |
|-----|------------------|
| 0   | Heat pad 0 (HP0) |
| 1   | Heat pad 1 (HP1) |
| 2   | Thermistor 0 (TH0) |
| 3   | Thermistor 1 (TH1) |
| 4   | Load cell / HX711 |
| 5   | pH ADC (ADS1113 or onboard) |
| 6   | EIS / AD5933      |

Example: `STATUS:7F\n` means all seven sensors are ready.

---

### 3.2 Thermal — heat pads and thermistors

#### `SET:HP0:<duty_pct>`
- **Request:** `SET:HP0:50\n`
- **Response:** `HP0:50\n`
- **Arg:** Integer 0–100 (percent duty cycle). `0` turns the pad off.
- **Notes:**
  - HP0 is the 200 mA heat pad (COTS pad, 5 V 1 W).
  - PWM frequency is fixed at 1 kHz in firmware (suitable for resistive heating elements).
  - The PWM signal drives an external transistor gate — no current flows through GPIO.
  - Clamp incoming values to [0, 100]; respond with `ERR:ARG:duty out of range\n` otherwise.

#### `SET:HP1:<duty_pct>`
- **Request:** `SET:HP1:75\n`
- **Response:** `HP1:75\n`
- **Arg:** Integer 0–100.
- **Notes:** HP1 is the 400 mA heat pad (JLCPCB custom pad, 5 V 2 W). Same PWM scheme.

#### `GET:HP0`
- **Request:** `GET:HP0\n`
- **Response:** `HP0:<duty_pct>\n` — returns the currently set duty cycle (0–100).

#### `GET:HP1`
- **Request:** `GET:HP1\n`
- **Response:** `HP1:<duty_pct>\n`

#### `GET:TEMP0`
- **Request:** `GET:TEMP0\n`
- **Response:** `TEMP0:<raw_mv>,<celsius>\n`
  - `raw_mv` — ADC reading converted to millivolts (integer)
  - `celsius` — computed temperature, one decimal place (e.g. `24.7`)
- **Notes:**
  - Thermistor 0 is a 10 KΩ NTC in a voltage-divider with a fixed resistor.
  - The KNTC0603 thermistor (on the JLCPCB pad) uses the Steinhart-Hart equation or
    a Beta-parameter model. Use Beta = 3950 K as a starting default; allow
    calibration via flash-stored coefficients if needed.
  - Read from ADS1113 AIN0 if fitted; fall back to RP2040 onboard ADC on GPIO26.

#### `GET:TEMP1`
- **Request:** `GET:TEMP1\n`
- **Response:** `TEMP1:<raw_mv>,<celsius>\n`
- **Notes:** Thermistor 1 is a standalone 10 KΩ NTC (Amazon part). Same computation.
  Read from ADS1113 AIN1 if fitted; fall back to RP2040 GPIO27.

---

### 3.3 Load cell — HX711

The HX711 uses a **custom bit-bang serial protocol** (not I2C, not SPI).

#### HX711 hardware protocol (implement in firmware)
```
1. Wait for DOUT to go LOW (data ready signal, can take up to 100 ms after power-up).
2. Issue 24 clock pulses on SCK; read one bit on DOUT after each rising edge.
   Bit order: MSB first. Result is a 24-bit two's complement integer.
3. Issue 1, 2, or 3 additional clock pulses to set the gain for the NEXT conversion:
   - 25 pulses total → Channel A, Gain 128 (default)
   - 26 pulses total → Channel B, Gain 32
   - 27 pulses total → Channel A, Gain 64
4. SCK must be LOW between conversions. Never leave SCK HIGH for > 60 µs
   (this powers down the HX711).
5. Minimum SCK pulse width: 0.2 µs.
```

#### `GET:LOAD`
- **Request:** `GET:LOAD\n`
- **Response:** `LOAD:<raw_24bit>,<grams>\n`
  - `raw_24bit` — signed 32-bit decimal representation of the 24-bit two's complement value
  - `grams` — float with 2 decimal places after applying tare offset and calibration factor
- **Notes:** If DOUT does not go LOW within 200 ms, respond with `ERR:TIMEOUT:HX711\n`.

#### `SET:LOAD:TARE`
- **Request:** `SET:LOAD:TARE\n`
- **Response:** `LOAD:TARE:OK\n`
- **Notes:** Captures the current raw reading as the tare offset. Store in RAM (not flash).
  Tare resets to 0 on power cycle.

#### `SET:LOAD:GAIN:<val>`
- **Request:** `SET:LOAD:GAIN:128\n`
- **Response:** `LOAD:GAIN:128\n`
- **Valid values:** `128`, `64`, `32` (corresponds to 25, 27, 26 SCK pulses respectively).
- **Error:** `ERR:ARG:gain must be 128, 64, or 32\n`

#### `GET:LOAD:CFG`
- **Request:** `GET:LOAD:CFG\n`
- **Response:** `LOAD:CFG:<gain>,<tare_raw>\n` — e.g. `LOAD:CFG:128,4194305\n`

---

### 3.4 pH electrodes — IrOx and Ag/AgCl

The two electrodes are buffered by AD8603 op-amps (unity gain) before reaching the ADC.
The MCU reads two differential voltages and computes a pH value.

#### ADC source selection
- **Primary:** ADS1113 over I2C (address `0x48`, single-ended AIN0 = IrOx, AIN1 = Ag/AgCl).
  - The ADS1113 has a single differential input — use two separate conversions in
    single-ended mode if using ADS1115, or two separate ADS1113 devices on different
    I2C addresses (ADDR pin to GND = 0x48, ADDR to VDD = 0x49).
  - Configure for ±2.048 V FSR, 16 SPS (slowest for best noise rejection on a pH signal).
- **Fallback:** RP2040 onboard ADC on GPIO26 (IrOx) and GPIO27 (Ag/AgCl) if ADS1113
  not present. The MCU auto-detects ADS1113 presence at boot via I2C scan.

#### `GET:PH`
- **Request:** `GET:PH\n`
- **Response:** `PH:<irox_mv>,<agcl_mv>,<diff_mv>,<pH>\n`
  - All millivolt fields are signed integers.
  - `pH` is a float with 2 decimal places.
  - pH computed from: `pH = (diff_mv - offset_mv) / slope_mv_per_pH`
  - Default calibration: slope = −59.16 mV/pH (Nernstian at 25 °C), offset = 0.

#### `GET:PH:RAW`
- **Request:** `GET:PH:RAW\n`
- **Response:** `PH:RAW:<irox_counts>,<agcl_counts>\n`
- **Notes:** Returns raw ADC counts before any conversion. Used during calibration.

#### `SET:PH:CAL:<slope_mv>:<offset_mv>`
- **Request:** `SET:PH:CAL:-59.16:0.00\n`
- **Response:** `PH:CAL:OK\n`
- **Notes:** Slope and offset are floats. Store in flash so calibration survives power cycles.
  Slope is typically negative (IrOx is anodic, response inverts sign convention).

---

### 3.5 Cell concentration — AD5933 EIS sweep

The AD5933 is connected via I2C. Its 7-bit I2C slave address is **0x0D**.

#### AD5933 key registers (reference for implementation)
| Register(s) | Name                   | Notes                                  |
|-------------|------------------------|----------------------------------------|
| 0x80–0x81   | Control                | Mode bits D15:D12, voltage D10:D9, PGA D8 |
| 0x82–0x84   | Start frequency        | 24-bit code                            |
| 0x85–0x87   | Frequency increment    | 24-bit code                            |
| 0x88–0x89   | Number of increments   | 9-bit, max 511                         |
| 0x8A–0x8B   | Settling time cycles   | 9-bit + 2-bit multiplier               |
| 0x8F        | Status                 | Bit 1 = data valid, bit 2 = sweep done |
| 0x94–0x95   | Real data              | 16-bit signed (two's complement)       |
| 0x96–0x97   | Imaginary data         | 16-bit signed (two's complement)       |

#### Frequency code formula
```
code = round( (freq_hz / (mclk_hz / 4)) * 2^27 )
```
Default MCLK is the internal 16.776 MHz oscillator. For a 1 kHz start:
`code = round( (1000 / (16776000 / 4)) * 134217728 ) = 0x000F`

#### AD5933 sweep sequence (must be followed exactly)
```
1. Send power-down command  (control reg D15:D12 = 1010)
2. Send standby command     (control reg D15:D12 = 1011)
3. Write start frequency, increment, num_increments, settling cycles registers
4. Send "initialize with start frequency" (D15:D12 = 0001)
5. Wait ≥ 1 ms (settling)
6. Send "start frequency sweep"           (D15:D12 = 0010)
7. Poll status register 0x8F:
   - Bit 1 set → read real (0x94–0x95) and imaginary (0x96–0x97) registers
   - After reading, send "increment frequency" (D15:D12 = 0011)
   - Bit 2 set → sweep complete, send reset/standby
8. Collect all (freq, real, imag) tuples as the sweep result
```

#### Voltage range encoding (control register D10:D9)
| D10 | D9 | Range | Output       |
|-----|----|-------|--------------|
| 0   | 0  | 1     | 2.0 Vpp typ  |
| 0   | 1  | 4     | 200 mVpp typ |
| 1   | 0  | 3     | 400 mVpp typ |
| 1   | 1  | 2     | 1.0 Vpp typ  |

The API `VRANGE` parameter maps directly: `1`→`00`, `2`→`11`, `3`→`10`, `4`→`01`.

#### `SET:EIS:START:<hz>`
- **Request:** `SET:EIS:START:1000\n`
- **Response:** `EIS:START:1000\n`
- **Constraint:** Must be ≥ 1 Hz. Store in RAM; apply to AD5933 registers only at sweep time.

#### `SET:EIS:STOP:<hz>`
- **Request:** `SET:EIS:STOP:200000\n`
- **Response:** `EIS:STOP:200000\n`
- **Notes:** Stop frequency is used with STEPS to derive the increment:
  `increment_hz = (stop_hz - start_hz) / steps`

#### `SET:EIS:STEPS:<n>`
- **Request:** `SET:EIS:STEPS:100\n`
- **Response:** `EIS:STEPS:100\n`
- **Constraint:** 1 ≤ n ≤ 511. Error if exceeded: `ERR:ARG:max 511 steps\n`

#### `SET:EIS:VRANGE:<1-4>`
- **Request:** `SET:EIS:VRANGE:1\n`
- **Response:** `EIS:VRANGE:1\n`
- **Mapping:** 1 = 2 Vpp, 2 = 1 Vpp, 3 = 400 mVpp, 4 = 200 mVpp

#### `SET:EIS:GAIN:<1|5>`
- **Request:** `SET:EIS:GAIN:1\n`
- **Response:** `EIS:GAIN:1\n`
- **Mapping:** 1 = PGA ×1 (control bit D8 = 1), 5 = PGA ×5 (D8 = 0)

#### `GET:EIS:CFG`
- **Request:** `GET:EIS:CFG\n`
- **Response:** `EIS:CFG:<start_hz>,<stop_hz>,<steps>,<vrange>,<gain>\n`
- **Example:** `EIS:CFG:1000,200000,100,1,1\n`

#### `SET:EIS:RUN`
- **Request:** `SET:EIS:RUN\n`
- **Response (success):** `EIS:DATA:<n>:<f0>,<R0>,<I0>;<f1>,<R1>,<I1>;...\n`
  - `n` = number of data points (equals STEPS + 1)
  - `f` = frequency in Hz (integer)
  - `R` = real component (signed 16-bit integer, from registers 0x94–0x95)
  - `I` = imaginary component (signed 16-bit integer, from registers 0x96–0x97)
  - Points separated by `;`, fields within a point separated by `,`
- **Response (error):** `ERR:BUSY:EIS\n` if a sweep is already running, or
  `ERR:TIMEOUT:AD5933\n` if the chip does not respond.
- **Notes:**
  - The MCU blocks during the sweep. For 100 steps at 1 kHz start, total time is
    approximately 2–5 seconds. The host must use a long timeout (30 s recommended).
  - The host applies gain factor calibration; the MCU returns raw DFT output.
  - If the response string would exceed ~2 KB (roughly 250 points), the firmware
    should instead respond with `EIS:READY:<n>\n` and support paged retrieval.

#### `GET:EIS:LAST`
- **Request:** `GET:EIS:LAST\n`
- **Response:** `EIS:DATA:<n>:...\n` — identical format to `SET:EIS:RUN` response, but
  re-transmits the last completed sweep without triggering hardware.
- **Error:** `ERR:NODATA:no sweep completed\n` if no sweep has been run since boot.

#### Paged retrieval (for large sweeps)
If sweep size exceeds firmware buffer (~2 KB), the `SET:EIS:RUN` response becomes:
- `EIS:READY:<n>:<page_count>\n` — signals that `page_count` pages are available.

#### `GET:EIS:PAGE:<k>`
- **Request:** `GET:EIS:PAGE:0\n`
- **Response:** `EIS:PAGE:<k>:<data_slice>\n` — same point format, one page at a time.
- Page size: 50 points per page (configurable in firmware).

---

## 4. Error Codes

| Code      | Meaning                                    |
|-----------|--------------------------------------------|
| `UNK`     | Command not recognized                     |
| `ARG`     | Argument missing, out of range, or invalid |
| `BUSY`    | Sensor is occupied (e.g. sweep in progress)|
| `TIMEOUT` | Sensor did not respond in time             |
| `NOCALIB` | Calibration values not set                 |
| `NODATA`  | Requested data has not been collected yet  |
| `I2CERR`  | I2C bus error (NACK or bus fault)          |

Full error frame: `ERR:<CODE>:<human readable message>\n`

---

## 5. Firmware Architecture Notes

### State to persist in flash
- pH calibration slope and offset (`SET:PH:CAL`)
- Any future EIS gain factor calibration

### State held in RAM only (reset on power cycle)
- Heat pad duty cycles (HP0, HP1) — default to 0 on boot
- HX711 tare offset
- EIS sweep parameters (default values below)
- Last completed EIS sweep data

### EIS default parameters (on boot)
```
START   = 1000 Hz
STOP    = 200000 Hz
STEPS   = 100
VRANGE  = 1   (2.0 Vpp)
GAIN    = 1   (×1 PGA)
```

### I2C bus sharing
Both the AD5933 and ADS1113 share the same I2C bus (D4/D5):
- AD5933 address: `0x0D`
- ADS1113 #0 (IrOx / Thermistor 0): `0x48` (ADDR pin to GND)
- ADS1113 #1 (Ag/AgCl / Thermistor 1): `0x49` (ADDR pin to VDD)

Never initiate an EIS sweep and a pH/temperature read concurrently. The MCU's
single-threaded command loop prevents this naturally — process one command fully
before accepting the next.

### Boot sequence
1. Initialize GPIO (PWM outputs to 0, HX711 SCK low)
2. I2C scan: detect AD5933 at 0x0D, ADS1113 at 0x48 / 0x49
3. Set `STATUS` bitmask accordingly
4. Load pH calibration from flash if present
5. Begin listening on UART

### PWM implementation note
The RP2040 has 8 PWM slices, each with two channels (A and B). GPIO28 and GPIO29
(D2 and D3) are on PWM slice 6A and 6B respectively — they can be controlled
independently at the same base frequency. Set wrap = 999, clock divider = 125 to
achieve 1 kHz at 125 MHz system clock. Duty cycle in counts = `duty_pct * 10`.

### HX711 timing caution
The RP2040 runs at up to 133 MHz — bit-bang delays must be explicitly inserted.
Minimum SCK pulse width is 0.2 µs; use `sleep_us(1)` between transitions to be safe.
Never leave SCK high for more than 60 µs or the HX711 enters power-down mode.

---

## 6. Example Interaction Sequences

### Basic sensor poll
```
→ PING\n
← PING:OK\n

→ GET:TEMP0\n
← TEMP0:1642,24.7\n

→ GET:TEMP1\n
← TEMP1:1598,23.1\n

→ GET:LOAD\n
← LOAD:4194305,12.34\n

→ GET:PH\n
← PH:412,180,232,6.82\n
```

### Heat pad control
```
→ SET:HP0:50\n
← HP0:50\n

→ SET:HP1:75\n
← HP1:75\n

→ GET:HP0\n
← HP0:50\n
```

### EIS sweep — configure then run
```
→ SET:EIS:START:1000\n
← EIS:START:1000\n

→ SET:EIS:STOP:200000\n
← EIS:STOP:200000\n

→ SET:EIS:STEPS:50\n
← EIS:STEPS:50\n

→ SET:EIS:VRANGE:1\n
← EIS:VRANGE:1\n

→ SET:EIS:GAIN:1\n
← EIS:GAIN:1\n

→ GET:EIS:CFG\n
← EIS:CFG:1000,200000,50,1,1\n

→ SET:EIS:RUN\n
← EIS:DATA:51:1000,907,516;4980,843,491;...;200000,-312,88\n
```

### Load cell tare then weigh
```
→ SET:LOAD:TARE\n
← LOAD:TARE:OK\n

→ GET:LOAD\n
← LOAD:0,0.00\n        (immediately after tare — should be near zero)

[place sample]

→ GET:LOAD\n
← LOAD:204800,5.12\n
```

### Error examples
```
→ SET:HP0:110\n
← ERR:ARG:duty out of range\n

→ SET:EIS:STEPS:600\n
← ERR:ARG:max 511 steps\n

→ GET:EIS:LAST\n          (before any sweep has run)
← ERR:NODATA:no sweep completed\n

→ SET:LOAD:GAIN:16\n
← ERR:ARG:gain must be 128, 64, or 32\n
```

---

## 7. Implementation Checklist

Use this to track progress. All items are required for a complete implementation.

### Transport layer
- [ ] UART initialized at 115200 8N1 on GPIO0/GPIO1
- [ ] `readline()` function that buffers until `\n`
- [ ] Command dispatcher that routes to handler functions
- [ ] Unknown command returns `ERR:UNK:...`

### System commands
- [ ] `PING` → `PING:OK`
- [ ] `VERSION` → `VERSION:x.y.z`
- [ ] `STATUS` → `STATUS:<hex>` with correct bitmask logic

### Heat pads
- [ ] PWM on GPIO28 (HP0) at 1 kHz, duty 0–100
- [ ] PWM on GPIO29 (HP1) at 1 kHz, duty 0–100
- [ ] `SET:HP0`, `SET:HP1` with range validation
- [ ] `GET:HP0`, `GET:HP1`

### Thermistors
- [ ] I2C scan at boot to detect ADS1113 at 0x48 / 0x49
- [ ] ADS1113 read function (configure FSR ±2.048 V, trigger conversion, poll ready bit)
- [ ] Fallback to onboard ADC (GPIO26, GPIO27) if ADS1113 absent
- [ ] Steinhart-Hart / Beta-model temperature conversion
- [ ] `GET:TEMP0`, `GET:TEMP1`

### Load cell
- [ ] HX711 bit-bang read (24 bits + gain-select pulses)
- [ ] DOUT ready detection with 200 ms timeout
- [ ] Tare offset storage in RAM
- [ ] `GET:LOAD`, `SET:LOAD:TARE`, `SET:LOAD:GAIN:<val>`, `GET:LOAD:CFG`

### pH
- [ ] ADS1113 dual-channel read (AIN0, AIN1 as single-ended)
- [ ] Fallback to onboard ADC
- [ ] Nernst equation pH computation with configurable slope/offset
- [ ] Flash storage for calibration coefficients
- [ ] `GET:PH`, `GET:PH:RAW`, `SET:PH:CAL:<slope>:<offset>`

### EIS / AD5933
- [ ] AD5933 I2C driver (register write, block write, block read)
- [ ] Frequency code computation from Hz
- [ ] Full sweep sequence (standby → init → sweep → poll → collect)
- [ ] EIS parameter storage in RAM with defaults
- [ ] `SET:EIS:START`, `SET:EIS:STOP`, `SET:EIS:STEPS`, `SET:EIS:VRANGE`, `SET:EIS:GAIN`
- [ ] `GET:EIS:CFG`
- [ ] `SET:EIS:RUN` with full data response
- [ ] `GET:EIS:LAST`
- [ ] Paged retrieval if sweep data exceeds buffer

### Boot
- [ ] GPIO and peripheral initialization
- [ ] I2C scan and STATUS bitmask population
- [ ] Flash read for pH calibration
- [ ] UART ready before accepting commands