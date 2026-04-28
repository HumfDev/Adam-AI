# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Adam Biotech is a bioprinting monitoring system. It collects real-time sensor data from a 3D bioprinter and displays it in a desktop dashboard with ML-based failure detection.

## Components

### 1. MicroPython firmware (`main.py`)
Runs on a Seeed XIAO microcontroller (MicroPython). Reads an HX711 load cell (bit-bang GPIO) and an ADS1115 ADC (I2C) at 5 Hz and prints readings over serial. The XIAO is connected to the printer's Klipper MCU so Klipper can publish the readings via Moonraker.

### 2. Ingest daemon (`ingest.py`)
An asyncio Python service that subscribes to Moonraker's JSON-RPC WebSocket (`notify_status_update`) and writes every sensor delta to PostgreSQL. It tracks print session lifecycle (open/close) by watching Klipper's `print_stats` object. Uses `asyncpg` for async Postgres and `websockets` for the WebSocket client.

Run it:
```bash
pip install websockets asyncpg
DATABASE_URL=postgresql://klipper:klipper@localhost/adam_sensors \
MOONRAKER_HOST=adampi.local python ingest.py
```

Key environment variables (see `.env.example` for Supabase keys):
- `MOONRAKER_HOST` — hostname of the Klipper/Moonraker printer (default: `adampi.local`)
- `DATABASE_URL` — asyncpg DSN (default points to local `adam_sensors` DB)
- `PRINTER_NAME`, `HX711_KEY`, `ADS0_KEY`, `ADS1_KEY` — Klipper object names

### 3. Tauri desktop dashboard (`dashboard/` + `src-tauri/`)
A Tauri 2 app. The frontend is plain HTML/CSS/vanilla JS — **no bundler, no framework**. Tauri points directly at `dashboard/` as `frontendDist`. The Rust backend (`src-tauri/src/lib.rs`) is minimal; all logic is in the frontend.

```bash
npm run dev    # Tauri dev mode
npm run build  # Production build (bundle.active = false in tauri.conf.json, so no installers)
```

The dashboard currently uses **simulated data** (random-walk in `renderer.js`). Real data will come from Supabase once the live data pipeline is wired up.

Dashboard panels: **Live Print** (sensor cards, LSTM gauge, 30s buffer chart), **Classifier** (RandomForest failure class bars), **Analytics** (health score, pass/fail rate, trend), **Sessions** (session log table), **Drift** (KS-test distribution shift monitor).

## Data pipeline architecture

```
XIAO MCU (MicroPython)
    → Klipper extras (hx711, ads1115_sensor in printer.cfg)
    → Moonraker WebSocket (notify_status_update)
    → ingest.py
    → PostgreSQL / Supabase
    → Dashboard (Tauri + vanilla JS)
```

PostgreSQL schema tables: `printers`, `sensor_devices`, `print_sessions`, `hx711_readings`, `ads1115_readings`.

## Key conventions

- The ADS1115 Klipper extra reports voltage under both `voltage` and `temperature` keys (it masquerades as a temp sensor) — `ingest.py` accepts either.
- Moonraker sends only *changed* fields per delta, so any sensor key may be absent from a given update. All sensor writers check for `None` before inserting.
- `print_stats` is always processed before sensor rows in each dispatch cycle to ensure `_current_session_id` is set before sensor readings reference it.
- The `.micropico` file marks this repo for the MicroPico VS Code extension (deploy/run MicroPython on the XIAO).
