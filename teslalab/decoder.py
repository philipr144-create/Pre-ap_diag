from collections import deque
import time
import cantools
from .catalog import REFERENCES

class Decoder:
    def __init__(self):
        self.databases = {}
        self.errors = []
        self.warnings = []
        for path in REFERENCES.glob("*.dbc"):
            try:
                # Supplied research DBCs contain overlapping definitions. Keep the
                # original files; compatibility loading is explicitly reported.
                text = path.read_text()
                damaged = 'VAL_ 921 DAS_lssState 7 "LSS_STATE_OFF" 6 "LSS_STATE_ABORT" 5 "LSS_STATE_BLINDSPOT" 4 "LSS_STATE_MONITOR" 3 "LSS_STATE_ELK" 2'
                if damaged in text.splitlines():
                    text = "\n".join(line for line in text.splitlines() if line != damaged)
                    self.warnings.append({"file":path.name,"warning":"One truncated DAS_lssState VAL_ enumeration omitted in memory; original unchanged. No missing values inferred."})
                self.databases[path.stem] = cantools.database.load_string(text, database_format="dbc", strict=False)
            except Exception as exc:
                self.errors.append({"file": path.name, "error": str(exc)})
        self.bus_map = {0: "tesla_preap", 1: "tesla_powertrain", 2: "tesla_preap"}
        self.latest = {}
        self.history = {}
        self.decode_errors = 0

    def reset(self):
        self.latest.clear(); self.history.clear(); self.decode_errors = 0

    def catalog(self):
        return {name: [{"address": m.frame_id, "name": m.name, "length": m.length,
                       "signals": [{"name": s.name, "unit": s.unit, "scale": s.scale, "offset": s.offset,
                                    "start":s.start,"length":s.length,"byte_order":s.byte_order,"signed":s.is_signed,
                                    "choices": {str(k): str(v) for k, v in (s.choices or {}).items()}}
                                   for s in m.signals]} for m in db.messages]
                for name, db in self.databases.items()}

    def ingest(self, frame):
        if frame.direction != "rx" or frame.bus not in self.bus_map: return {}
        db_name = self.bus_map[frame.bus]
        db = self.databases.get(db_name)
        if not db: return {}
        try:
            message = db.get_message_by_frame_id(frame.address)
        except KeyError: return {}
        try:
            values = message.decode(frame.data, decode_choices=False)
        except (ValueError, cantools.database.errors.DecodeError):
            self.decode_errors += 1; return {}
        units = {s.name: s.unit or "" for s in message.signals}
        for name, value in values.items():
            key = f"{frame.bus}:{db_name}:{message.name}:{name}"
            row = {"key": key, "bus": frame.bus, "dbc": db_name, "message": message.name,
                   "name": name, "value": value, "unit": units[name], "ts": frame.ts,
                   "source": frame.source, "received": time.monotonic()}
            self.latest[key] = row
            self.history.setdefault(key, deque(maxlen=300)).append([frame.ts, value])
        return values
