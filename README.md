# Adam Biotech — Bioprinter Monitoring System

A real-time sensor monitoring and failure detection platform for 3D bioprinting. Collects load cell and voltage data from the printer hardware, stores it in PostgreSQL, and displays it in a desktop dashboard with ML-based failure prediction.

## Architecture

```
XIAO MCU (MicroPython)
    ↓  Klipper extras (hx711, ads1115_sensor)
Moonraker WebSocket
    ↓  ingest.py (asyncio daemon)
PostgreSQL / Supabase
    ↓
Tauri Desktop Dashboard
```

| Component | Location | Purpose |
|---|---|---|
| MCU firmware | `main.py` | Reads HX711 load cell + ADS1115 ADC on the XIAO |
| Ingest daemon | `ingest.py` | Moonraker WebSocket → PostgreSQL |
| Desktop app | `dashboard/` + `src-tauri/` | Tauri 2 dashboard with live sensor charts |

## Dashboard

Five panels driven by sensor data and ML models:

- **Live Print** — real-time sensor cards (thermistors, load cell, pH, DO%), heat pad control, LSTM failure probability gauge, 30-second buffer chart, data pipeline status
- **Classifier** — RandomForest failure classification (Nozzle Clog, Under-extrusion, Temp Drift, Layer Delamination, Bioink Degradation)
- **Analytics** — print health score, pass/fail rate, session trends
- **Sessions** — full session log with bioink, duration, health score, and operator labels
- **Drift** — KS-test distribution shift detector with retrain pipeline trigger

## Setup

### Prerequisites

- [Rust](https://rustup.rs/) and [Tauri CLI v2](https://tauri.app/start/prerequisites/)
- Node.js (for `npm`)
- Python 3.11+
- A Klipper/Moonraker printer with `hx711` and `ads1115_sensor` extras configured
- PostgreSQL or a [Supabase](https://supabase.com) project

### Environment

Copy `.env.example` and fill in your Supabase credentials:

```bash
cp .env.example .env
```

```
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
```

### MCU Firmware

Flash `main.py` to the Seeed XIAO using the [MicroPico](https://marketplace.visualstudio.com/items?itemName=paulober.pico-w-go) VS Code extension or `mpremote`. The firmware reads:

- **HX711** load cell on GPIO 8 (DOUT) / GPIO 7 (SCK)
- **ADS1115** on I2C bus 1 — SDA GPIO 6 / SCL GPIO 7, address `0x48`

### Ingest Daemon

```bash
pip install websockets asyncpg

DATABASE_URL=postgresql://klipper:klipper@localhost/adam_sensors \
MOONRAKER_HOST=adampi.local \
python ingest.py
```

| Variable | Default | Description |
|---|---|---|
| `MOONRAKER_HOST` | `adampi.local` | Klipper/Moonraker hostname or IP |
| `MOONRAKER_PORT` | `7125` | Moonraker WebSocket port |
| `DATABASE_URL` | `postgresql://klipper:klipper@localhost:5432/adam_sensors` | asyncpg DSN |
| `PRINTER_NAME` | `adam` | Logical printer name stored in DB |
| `HX711_KEY` | `hx711 loadcell1` | Klipper object name — must match `printer.cfg` |
| `ADS0_KEY` | `ads1115_sensor thermistor1` | Klipper object name for ADS channel 0 |
| `ADS1_KEY` | `ads1115_sensor thermistor2` | Klipper object name for ADS channel 1 |
| `RECONNECT_DELAY` | `5` | Seconds between reconnect attempts |

### Desktop Dashboard

```bash
npm install
npm run dev    # development
npm run build  # production
```

The dashboard frontend is plain HTML/CSS/vanilla JS — no bundler or framework required.
