import csv
import io
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started REAL, ended REAL, mode TEXT, label TEXT);
        CREATE TABLE IF NOT EXISTS frames(id INTEGER PRIMARY KEY, run TEXT, ts REAL, address INTEGER, bus INTEGER, data TEXT, direction TEXT, source TEXT);
        CREATE INDEX IF NOT EXISTS frames_run ON frames(run, id);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run TEXT, ts REAL, kind TEXT, data TEXT);
        CREATE INDEX IF NOT EXISTS events_run ON events(run, id);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, data TEXT);
        """)
        self.db.commit()
        self.pending = 0
        self.last_commit = time.monotonic()
        # Preserve interrupted recordings after a process crash; do not label
        # device/ECU cleanup as successful merely because the server restarted.
        open_runs = self.db.execute("SELECT id FROM runs WHERE ended IS NULL").fetchall()
        for (key,) in open_runs:
            self.event(key,"interrupted",{"device_cleanup_verified":False,"reason":"Server restarted with an unfinalized recording"})
            self.end(key)

    def start(self, mode, label):
        key = uuid.uuid4().hex
        with self.lock:
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (key, time.time(), None, mode, label))
            self.db.commit()
        return key

    def end(self, key):
        with self.lock:
            self.db.execute("UPDATE runs SET ended=? WHERE id=?", (time.time(), key))
            self.db.commit()

    def frame(self, run, frame):
        with self.lock:
            self.db.execute("INSERT INTO frames(run,ts,address,bus,data,direction,source) VALUES(?,?,?,?,?,?,?)",
                            (run, frame.ts, frame.address, frame.bus, frame.data.hex(), frame.direction, frame.source))
            self.pending += 1
            if self.pending >= 200 or time.monotonic()-self.last_commit >= 1:
                self.db.commit(); self.pending = 0; self.last_commit = time.monotonic()

    def event(self, run, kind, data):
        with self.lock:
            self.db.execute("INSERT INTO events(run,ts,kind,data) VALUES(?,?,?,?)",
                            (run, time.time(), kind, json.dumps(data)))
            self.db.commit()

    def runs(self):
        with self.lock:
            return [dict(zip(("id", "started", "ended", "mode", "label", "frames"), row)) for row in
                    self.db.execute("SELECT r.*, (SELECT count(*) FROM frames f WHERE f.run=r.id) FROM runs r ORDER BY started DESC LIMIT 100")]

    def events(self):
        with self.lock:
            return [{"run":run,"ts":ts,"kind":kind,"data":json.loads(data)} for run,ts,kind,data in
                    self.db.execute("SELECT run,ts,kind,data FROM events ORDER BY id DESC LIMIT 200")]

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT data FROM settings WHERE key=?",(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def save_setting(self, key, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",(key,json.dumps(data)))
            self.db.commit()

    def report(self, run):
        with self.lock:
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone()
            if not row: raise ValueError("Unknown recording")
            events = [{"ts": ts, "kind": kind, "data": json.loads(data)} for ts, kind, data in
                      self.db.execute("SELECT ts,kind,data FROM events WHERE run=? ORDER BY id", (run,))]
            count = self.db.execute("SELECT count(*) FROM frames WHERE run=?", (run,)).fetchone()[0]
        return {"run": dict(zip(("id", "started", "ended", "mode", "label"), row)), "frame_count": count,
                "events": events, "hardware_tested_by_developer": False,
                "limitations": ["Timestamps are host receipt times, not hardware timestamps.",
                                "DBC definitions do not prove applicability to this vehicle.",
                                "Unknown DTC meanings and routine result bytes are not interpreted as success."]}

    def export(self, run, csv_format=False):
        self.report(run)
        last = 0
        if csv_format: yield "ts,address,bus,data,direction,source\n"
        while True:
            with self.lock:
                rows = self.db.execute("SELECT id,ts,address,bus,data,direction,source FROM frames WHERE run=? AND id>? ORDER BY id LIMIT 500", (run, last)).fetchall()
            if not rows: break
            for ident, ts, address, bus, data, direction, source in rows:
                last = ident
                if csv_format:
                    out = io.StringIO(); csv.writer(out).writerow([ts, f"0x{address:X}", bus, data, direction, source]); yield out.getvalue()
                else:
                    yield json.dumps(dict(ts=ts, address=address, bus=bus, data=data, direction=direction, source=source)) + "\n"

    def close(self):
        with self.lock:
            self.db.commit(); self.db.close()
