## Sensor dashboard (local)

### Run it

From the repo root:

```bash
./sensor-dashboard/serve.sh
```

Then open:

- `http://localhost:8080/`

### Useful URLs

- **Select ADS section names**: `?sensor0=thermistor1&sensor1=thermistor2`
- **Enable HX711 widget**: `?hx711=1&loadcell=loadcell1`

Example:

- `http://localhost:8080/?sensor=thermistor1&hx711=1&loadcell=loadcell1`
- `http://localhost:8080/?sensor0=thermistor1&sensor1=thermistor2&hx711=1&loadcell=loadcell1`

### Point at your Moonraker host

The dashboard uses the page hostname as the Moonraker host.

- If you open it on your Pi (e.g. from Mainsail/Fluidd host), it will auto-target that host.
- If you open it from your laptop, the browser hostname is `localhost` and it will try `ws://localhost:7125`.

**Easy workaround**: open the dashboard via your Pi hostname/IP instead of localhost.

1. Run the server on the Pi in `sensor-dashboard/`
2. Open `http://<pi-hostname-or-ip>:8080/` from your laptop

That makes the WebSocket target `ws://<pi-hostname-or-ip>:7125/websocket` automatically.
