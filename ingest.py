#!/usr/bin/env python3
"""
ingest.py — Moonraker WebSocket → PostgreSQL sensor ingestion daemon

Subscribes to Moonraker's JSON-RPC notify_status_update stream and writes
every sensor delta to PostgreSQL, matching the schema in schema.sql.

Sensors tracked:
  hx711 loadcell1            →  hx711_readings   (raw counts + weight_g)
  ads1115_sensor thermistor1 →  ads1115_readings  (A0 voltage)
  ads1115_sensor thermistor2 →  ads1115_readings  (A1 voltage)
  print_stats                →  print_sessions    (open/close lifecycle)

Usage:
  pip install websockets asyncpg
  DATABASE_URL=postgresql://klipper:klipper@localhost/adam_sensors \\
  MOONRAKER_HOST=adampi.local python ingest.py

Environment variables:
  MOONRAKER_HOST    Hostname or IP of the Moonraker server  (default: adampi.local)
  MOONRAKER_PORT    Moonraker WebSocket port                (default: 7125)
  DATABASE_URL      asyncpg DSN                             (default: see below)
  RECONNECT_DELAY   Seconds between reconnect attempts      (default: 5)
  LOG_LEVEL         Python logging level                    (default: INFO)
  PRINTER_NAME      Logical name stored in printers table   (default: adam)

  HX711_KEY         Klipper object name for load cell       (default: hx711 loadcell1)
  ADS0_KEY          Klipper object name for ADS channel 0   (default: ads1115_sensor thermistor1)
  ADS1_KEY          Klipper object name for ADS channel 1   (default: ads1115_sensor thermistor2)
"""

import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone

import asyncpg
import websockets

# ── Configuration ─────────────────────────────────────────────────────────────
MOONRAKER_HOST  = os.getenv("MOONRAKER_HOST",  "adampi.local")
MOONRAKER_PORT  = int(os.getenv("MOONRAKER_PORT",  "7125"))
DB_DSN          = os.getenv("DATABASE_URL",
                             "postgresql://klipper:klipper@localhost:5432/adam_sensors")
RECONNECT_DELAY = float(os.getenv("RECONNECT_DELAY", "5"))
LOG_LEVEL       = os.getenv("LOG_LEVEL",       "INFO")
PRINTER_NAME    = os.getenv("PRINTER_NAME",    "adam")

# Klipper/Moonraker object keys — must match [section_name] in printer.cfg exactly
HX711_KEY       = os.getenv("HX711_KEY", "hx711 loadcell1")
ADS0_KEY        = os.getenv("ADS0_KEY",  "ads1115_sensor thermistor1")
ADS1_KEY        = os.getenv("ADS1_KEY",  "ads1115_sensor thermistor2")
PRINT_STATS_KEY = "print_stats"

# Objects to subscribe to in Moonraker. None means "send all fields".
SUBSCRIBE_OBJECTS = {
    HX711_KEY:        None,
    ADS0_KEY:         None,
    ADS1_KEY:         None,
    PRINT_STATS_KEY:  None,
}

# Print states that Klipper's print_stats object can emit
_TERMINAL_STATES = {"complete", "cancelled", "error", "standby"}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ingest")

# ── Mutable process state ─────────────────────────────────────────────────────
_rpc_id             = 0
_current_session_id: int | None = None
_last_print_state:   str | None = None


def _next_id() -> int:
    global _rpc_id
    _rpc_id += 1
    return _rpc_id


def _rpc(method: str, params: dict) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params, "id": _next_id()}
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Database bootstrap ────────────────────────────────────────────────────────
async def ensure_printer(pool: asyncpg.Pool, name: str, host: str) -> int:
    """
    Upsert the printer row and return its id.
    On reconnect the host may have changed (new IP), so we always update it.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO printers (name, moonraker_host)
                 VALUES ($1, $2)
            ON CONFLICT (name)
              DO UPDATE SET moonraker_host = EXCLUDED.moonraker_host
              RETURNING id
            """,
            name, host,
        )
        return row["id"]


async def ensure_sensor(
    pool:        asyncpg.Pool,
    printer_id:  int,
    mcu_name:    str,
    device_type: str,
    sensor_name: str,
    config:      dict,
) -> int:
    """
    Upsert a sensor_devices row (identified by printer + type + name) and
    return its id. Config is updated on every startup so it stays in sync
    with whatever is in printer.cfg.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sensor_devices (printer_id, mcu_name, device_type, sensor_name, config)
                 VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (printer_id, device_type, sensor_name)
              DO UPDATE SET mcu_name = EXCLUDED.mcu_name,
                            config   = EXCLUDED.config
              RETURNING id
            """,
            printer_id, mcu_name, device_type, sensor_name,
            json.dumps(config),
        )
        return row["id"]


# ── Session lifecycle ─────────────────────────────────────────────────────────
async def open_session(
    pool:       asyncpg.Pool,
    printer_id: int,
    filename:   str | None,
) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO print_sessions (printer_id, filename, state, started_at)
                 VALUES ($1, $2, 'printing', $3)
              RETURNING id
            """,
            printer_id, filename, _utcnow(),
        )
    sid = row["id"]
    log.info("Session opened  id=%d  file=%s", sid, filename)
    return sid


async def close_session(
    pool:       asyncpg.Pool,
    session_id: int,
    state:      str,
    filament_mm: float | None = None,
    layers:      int   | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE print_sessions
               SET state            = $1,
                   ended_at         = $2,
                   filament_used_mm = COALESCE($3, filament_used_mm),
                   layer_count      = COALESCE($4, layer_count)
             WHERE id = $5
            """,
            state, _utcnow(), filament_mm, layers, session_id,
        )
    log.info("Session closed  id=%d  state=%s", session_id, state)


async def handle_print_stats(
    pool:       asyncpg.Pool,
    printer_id: int,
    data:       dict,
) -> None:
    """
    Track print session open/close based on Klipper's print_stats object.
    Klipper transitions: standby → printing → (complete | cancelled | error) → standby
    """
    global _current_session_id, _last_print_state

    state    = data.get("state")
    filename = data.get("filename")

    if not state or state == _last_print_state:
        return
    _last_print_state = state

    if state == "printing":
        if _current_session_id is None:
            _current_session_id = await open_session(pool, printer_id, filename)
        else:
            log.debug("Already have session %d — skipping open", _current_session_id)

    elif state in _TERMINAL_STATES and _current_session_id is not None:
        # Pull final stats if available (Klipper may include them in the same delta)
        filament = data.get("filament_used")
        layers   = data.get("current_layer") or data.get("total_layer")
        await close_session(pool, _current_session_id, state,
                            filament_mm=filament, layers=layers)
        _current_session_id = None


# ── Sensor writers ────────────────────────────────────────────────────────────
async def insert_hx711(
    pool:      asyncpg.Pool,
    session_id: int | None,
    device_id:  int,
    data:       dict,
) -> None:
    """
    Write one HX711 delta to hx711_readings.
    Moonraker only sends fields that changed, so any key may be absent.
    We only write a row if we have at least a raw count.
    """
    raw = data.get("raw")
    if raw is None:
        return  # delta had no raw value — nothing to store

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO hx711_readings
                        (session_id, sensor_device_id, ts, raw, weight_g, gain, errors)
                 VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            session_id,
            device_id,
            _utcnow(),
            raw,
            data.get("weight_g"),   # None when scale not calibrated — that's fine
            data.get("gain"),
            data.get("errors"),
        )


async def insert_ads1115(
    pool:       asyncpg.Pool,
    session_id: int | None,
    device_id:  int,
    channel:    int,
    data:       dict,
) -> None:
    """
    Write one ADS1115 delta to ads1115_readings.
    The Klipper extra reports voltage under both 'voltage' and 'temperature'
    keys (it masquerades as a temp sensor). Accept either.
    """
    voltage = data.get("voltage") if data.get("voltage") is not None else data.get("temperature")
    if voltage is None:
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ads1115_readings
                        (session_id, sensor_device_id, ts, channel, voltage)
                 VALUES ($1, $2, $3, $4, $5)
            """,
            session_id, device_id, _utcnow(), channel, voltage,
        )


# ── Status dispatcher ─────────────────────────────────────────────────────────
async def dispatch(
    pool:       asyncpg.Pool,
    printer_id: int,
    device_ids: dict,
    status:     dict,
) -> None:
    """
    Route each key in a Moonraker status slice to the appropriate handler.
    All handlers run concurrently; print_stats is awaited first so the session
    id is established before sensor rows reference it.
    """
    # Handle print_stats first so _current_session_id is set before sensor writes
    if PRINT_STATS_KEY in status:
        await handle_print_stats(pool, printer_id, status[PRINT_STATS_KEY])

    sensor_tasks = []

    if HX711_KEY in status:
        sensor_tasks.append(
            insert_hx711(pool, _current_session_id, device_ids[HX711_KEY], status[HX711_KEY])
        )
    if ADS0_KEY in status:
        sensor_tasks.append(
            insert_ads1115(pool, _current_session_id, device_ids[ADS0_KEY], 0, status[ADS0_KEY])
        )
    if ADS1_KEY in status:
        sensor_tasks.append(
            insert_ads1115(pool, _current_session_id, device_ids[ADS1_KEY], 1, status[ADS1_KEY])
        )

    if sensor_tasks:
        await asyncio.gather(*sensor_tasks)


# ── WebSocket loop ────────────────────────────────────────────────────────────
async def ingest_loop(
    pool:       asyncpg.Pool,
    printer_id: int,
    device_ids: dict,
) -> None:
    uri = f"ws://{MOONRAKER_HOST}:{MOONRAKER_PORT}/websocket"
    log.info("Connecting to %s", uri)

    async with websockets.connect(
        uri,
        ping_interval=20,
        ping_timeout=10,
        open_timeout=10,
    ) as ws:
        log.info("WebSocket connected")

        # Subscribe for live push updates
        await ws.send(_rpc("printer.objects.subscribe", {"objects": SUBSCRIBE_OBJECTS}))
        # Immediately query current state so we don't wait for the next delta
        await ws.send(_rpc("printer.objects.query",     {"objects": SUBSCRIBE_OBJECTS}))

        async for raw_msg in ws:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                log.debug("Non-JSON message received, skipping")
                continue

            # Two shapes to handle:
            #   1. Response to printer.objects.query / subscribe:
            #        { "result": { "status": { ... } } }
            #   2. Live push notification:
            #        { "method": "notify_status_update", "params": [ { ... }, eventtime ] }
            status: dict | None = None

            result = msg.get("result")
            if isinstance(result, dict) and isinstance(result.get("status"), dict):
                status = result["status"]
            elif (
                msg.get("method") == "notify_status_update"
                and isinstance(msg.get("params"), list)
                and msg["params"]
            ):
                status = msg["params"][0]

            if status:
                await dispatch(pool, printer_id, device_ids, status)


# ── Entry point ───────────────────────────────────────────────────────────────
async def main() -> None:
    log.info("adam-ingest starting  printer=%s  host=%s", PRINTER_NAME, MOONRAKER_HOST)

    pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=8)
    log.info("PostgreSQL pool ready  dsn=%s", DB_DSN.split("@")[-1])  # hide credentials

    # Bootstrap printer + sensor rows (idempotent — safe to re-run on every start)
    printer_id = await ensure_printer(pool, PRINTER_NAME, MOONRAKER_HOST)
    log.info("Printer id=%d  name=%s", printer_id, PRINTER_NAME)

    device_ids = {
        HX711_KEY: await ensure_sensor(
            pool, printer_id, "xiao", "hx711", "loadcell1",
            {"gain": 128, "dout_pin": "gpio26", "sck_pin": "gpio27",
             "report_time": 0.5},
        ),
        ADS0_KEY: await ensure_sensor(
            pool, printer_id, "xiao", "ads1115", "thermistor1",
            {"channel": 0, "i2c_bus": "i2c1a", "i2c_address": "0x48"},
        ),
        ADS1_KEY: await ensure_sensor(
            pool, printer_id, "xiao", "ads1115", "thermistor2",
            {"channel": 1, "i2c_bus": "i2c1a", "i2c_address": "0x48"},
        ),
    }
    log.info("Sensor device ids: %s", device_ids)

    # Graceful SIGINT / SIGTERM shutdown
    loop = asyncio.get_event_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    while not stop.is_set():
        try:
            await ingest_loop(pool, printer_id, device_ids)
        except (websockets.ConnectionClosed, OSError, TimeoutError) as exc:
            log.warning("Connection lost: %s — retrying in %.0fs", exc, RECONNECT_DELAY)
        except asyncpg.PostgresError as exc:
            log.error("Database error: %s — retrying in %.0fs", exc, RECONNECT_DELAY)
        except Exception:
            log.exception("Unexpected error in ingest loop")

        if not stop.is_set():
            await asyncio.sleep(RECONNECT_DELAY)

    log.info("Shutdown signal received — closing pool")
    await pool.close()
    log.info("Exited cleanly")


if __name__ == "__main__":
    asyncio.run(main())
