"""Serial command parser and dispatcher for CMD[:ARG] frames."""

VERSION = "1.0.0"


class CommandProcessor:
    def __init__(self, status_supplier):
        self._status_supplier = status_supplier
        self.hp0 = None
        self.hp1 = None
        self.temp0 = None
        self.temp1 = None
        self.load_cell = None
        self.ph = None
        self.eis = None

    @staticmethod
    def _err(code, msg):
        return "ERR:{}:{}".format(code, msg)

    @staticmethod
    def _to_int(token, msg):
        try:
            return int(token)
        except Exception:
            raise ValueError(msg)

    @staticmethod
    def _to_float(token, msg):
        try:
            return float(token)
        except Exception:
            raise ValueError(msg)

    def _set_heat_pad(self, pad, name, args):
        if pad is None:
            return self._err("NODATA", "{} unavailable".format(name))
        if len(args) != 1:
            return self._err("ARG", "missing duty")
        try:
            duty = self._to_int(args[0], "duty out of range")
            pad.set_duty_pct(duty)
        except ValueError as ex:
            return self._err("ARG", str(ex))
        return "{}:{}".format(name, pad.get_duty_pct())

    def _get_heat_pad(self, pad, name):
        if pad is None:
            return self._err("NODATA", "{} unavailable".format(name))
        return "{}:{}".format(name, pad.get_duty_pct())

    def _get_temp(self, sensor, name):
        if sensor is None:
            return self._err("NODATA", "{} unavailable".format(name))
        try:
            raw_mv, celsius = sensor.read()
        except Exception as ex:
            return self._err("TIMEOUT", str(ex))
        return "{}:{},{:.1f}".format(name, int(raw_mv), celsius)

    def _get_load(self):
        if self.load_cell is None:
            return self._err("NODATA", "load cell unavailable")
        try:
            raw, grams = self.load_cell.read()
        except TimeoutError:
            return self._err("TIMEOUT", "HX711")
        return "LOAD:{},{:.2f}".format(raw, grams)

    def _set_load_tare(self):
        if self.load_cell is None:
            return self._err("NODATA", "load cell unavailable")
        try:
            self.load_cell.tare()
        except TimeoutError:
            return self._err("TIMEOUT", "HX711")
        return "LOAD:TARE:OK"

    def _set_load_gain(self, args):
        if self.load_cell is None:
            return self._err("NODATA", "load cell unavailable")
        if len(args) != 1:
            return self._err("ARG", "missing gain")
        try:
            gain = self._to_int(args[0], "gain must be 128, 64, or 32")
            self.load_cell.set_gain(gain)
        except ValueError:
            return self._err("ARG", "gain must be 128, 64, or 32")
        return "LOAD:GAIN:{}".format(gain)

    def _get_load_cfg(self):
        if self.load_cell is None:
            return self._err("NODATA", "load cell unavailable")
        gain, tare = self.load_cell.get_cfg()
        return "LOAD:CFG:{},{}".format(gain, tare)

    def _get_ph(self):
        if self.ph is None:
            return self._err("NODATA", "ph unavailable")
        try:
            irox_mv, agcl_mv, diff_mv, p_h = self.ph.read()
        except Exception as ex:
            return self._err("TIMEOUT", str(ex))
        return "PH:{},{},{},{:.2f}".format(irox_mv, agcl_mv, diff_mv, p_h)

    def _get_ph_raw(self):
        if self.ph is None:
            return self._err("NODATA", "ph unavailable")
        try:
            irox, agcl = self.ph.read_raw_counts()
        except Exception as ex:
            return self._err("TIMEOUT", str(ex))
        return "PH:RAW:{},{}".format(irox, agcl)

    def _set_ph_cal(self, args):
        if self.ph is None:
            return self._err("NODATA", "ph unavailable")
        if len(args) != 2:
            return self._err("ARG", "calibration requires slope and offset")
        try:
            slope = self._to_float(args[0], "invalid slope")
            offset = self._to_float(args[1], "invalid offset")
            self.ph.set_calibration(slope, offset)
        except Exception as ex:
            return self._err("ARG", str(ex))
        return "PH:CAL:OK"

    def _get_eis_cfg(self):
        if self.eis is None:
            return self._err("NODATA", "eis unavailable")
        cfg = self.eis.get_cfg()
        return "EIS:CFG:{},{},{},{},{}".format(cfg[0], cfg[1], cfg[2], cfg[3], cfg[4])

    def _set_eis_param(self, param, args):
        if self.eis is None:
            return self._err("NODATA", "eis unavailable")
        if len(args) != 1:
            return self._err("ARG", "missing value")
        try:
            value = args[0]
            if param == "START":
                self.eis.set_start(value)
            elif param == "STOP":
                self.eis.set_stop(value)
            elif param == "STEPS":
                self.eis.set_steps(value)
            elif param == "VRANGE":
                self.eis.set_vrange(value)
            elif param == "GAIN":
                self.eis.set_gain(value)
        except ValueError as ex:
            return self._err("ARG", str(ex))
        return "EIS:{}:{}".format(param, int(args[0]))

    def _run_eis(self):
        if self.eis is None:
            return self._err("NODATA", "eis unavailable")
        try:
            mode, count, payload_or_pages = self.eis.run()
        except RuntimeError:
            return self._err("BUSY", "EIS")
        except TimeoutError:
            return self._err("TIMEOUT", "AD5933")
        except ValueError as ex:
            return self._err("ARG", str(ex))

        if mode == "READY":
            return "EIS:READY:{}:{}".format(count, payload_or_pages)
        return "EIS:DATA:{}:{}".format(count, payload_or_pages)

    def _get_eis_last(self):
        if self.eis is None:
            return self._err("NODATA", "eis unavailable")
        points = self.eis.get_last()
        if not points:
            return self._err("NODATA", "no sweep completed")
        payload = self.eis.format_points(points)
        return "EIS:DATA:{}:{}".format(len(points), payload)

    def _get_eis_page(self, args):
        if self.eis is None:
            return self._err("NODATA", "eis unavailable")
        if len(args) != 1:
            return self._err("ARG", "missing page index")
        try:
            page_idx = self._to_int(args[0], "invalid page")
            points, _ = self.eis.get_page(page_idx)
        except ValueError as ex:
            return self._err("ARG", str(ex))
        payload = self.eis.format_points(points)
        return "EIS:PAGE:{}:{}".format(page_idx, payload)

    def handle(self, raw_line):
        line = raw_line.strip()
        if not line:
            return self._err("ARG", "empty command")
        parts = line.split(":")

        try:
            if parts[0] == "PING":
                return "PING:OK"
            if parts[0] == "VERSION":
                return "VERSION:{}".format(VERSION)
            if parts[0] == "STATUS":
                return "STATUS:{:02X}".format(self._status_supplier())

            if parts[0] == "SET" and len(parts) >= 2:
                target = parts[1]
                args = parts[2:]

                if target == "HP0":
                    return self._set_heat_pad(self.hp0, "HP0", args)
                if target == "HP1":
                    return self._set_heat_pad(self.hp1, "HP1", args)
                if target == "LOAD" and len(args) >= 1 and args[0] == "TARE":
                    return self._set_load_tare()
                if target == "LOAD" and len(args) >= 1 and args[0] == "GAIN":
                    return self._set_load_gain(args[1:])
                if target == "PH" and len(args) >= 1 and args[0] == "CAL":
                    return self._set_ph_cal(args[1:])
                if target == "EIS" and len(args) >= 1:
                    if args[0] in ("START", "STOP", "STEPS", "VRANGE", "GAIN"):
                        return self._set_eis_param(args[0], args[1:])
                    if args[0] == "RUN":
                        return self._run_eis()

            if parts[0] == "GET" and len(parts) >= 2:
                target = parts[1]
                args = parts[2:]

                if target == "HP0":
                    return self._get_heat_pad(self.hp0, "HP0")
                if target == "HP1":
                    return self._get_heat_pad(self.hp1, "HP1")
                if target == "TEMP0":
                    return self._get_temp(self.temp0, "TEMP0")
                if target == "TEMP1":
                    return self._get_temp(self.temp1, "TEMP1")
                if target == "LOAD":
                    if args and args[0] == "CFG":
                        return self._get_load_cfg()
                    return self._get_load()
                if target == "PH":
                    if args and args[0] == "RAW":
                        return self._get_ph_raw()
                    return self._get_ph()
                if target == "EIS":
                    if args and args[0] == "CFG":
                        return self._get_eis_cfg()
                    if args and args[0] == "LAST":
                        return self._get_eis_last()
                    if args and args[0] == "PAGE":
                        return self._get_eis_page(args[1:])

        except Exception as ex:
            return self._err("ARG", str(ex))

        return self._err("UNK", "unknown command")
