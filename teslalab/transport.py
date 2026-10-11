"""Receive-only sources and deliberately narrow standalone USB access."""
from dataclasses import dataclass
import json
import math
import re
import time

@dataclass
class Frame:
    ts: float
    address: int
    bus: int
    data: bytes
    direction: str = "rx"
    source: str = "replay"

    def json(self):
        return dict(ts=self.ts, address=self.address, bus=self.bus, data=self.data.hex(),
                    direction=self.direction, source=self.source)

def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)

def parse_recording(text):
    """Canonical JSONL, earlier frames batches, and candump. Never a TX source."""
    frames = []
    skipped = 0
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line: continue
        try:
            if line.startswith("{"):
                row = json.loads(line)
                # The historical recorder also writes health/marker records.
                if "frames" in row:
                    ts = float(row.get("ts", row.get("at", time.time())))
                    candidates = [Frame(ts, number(a), int(b), bytes.fromhex(d)) for a,d,b in row["frames"]]
                elif "address" in row or "addr" in row:
                    candidates = [Frame(float(row.get("ts", row.get("t", row.get("at", time.time())))),
                                        number(row.get("address", row.get("addr"))), int(row.get("bus", 0)),
                                        bytes.fromhex(row.get("data", row.get("dat", ""))), row.get("direction", "rx"))]
                else:
                    skipped += 1; continue
            else:
                match = re.fullmatch(r"\((\d+(?:\.\d+)?)\)\s+(?:v?can)([0-2])\s+([0-9A-Fa-f]{1,8})#([0-9A-Fa-f]*)", line)
                if not match: raise ValueError("Expected JSONL frame or candump line")
                ts, bus, address, data = match.groups()
                candidates = [Frame(float(ts), int(address, 16), int(bus), bytes.fromhex(data))]
            for frame in candidates:
                if not math.isfinite(frame.ts) or frame.ts < 0 or not 0 <= frame.address <= 0x1fffffff or len(frame.data) > 8:
                    raise ValueError("Invalid timestamp/address or non-classic CAN length")
                if frame.bus >= 192:
                    frame.bus -= 192; frame.direction = "rejected"
                elif frame.bus >= 128:
                    frame.bus -= 128; frame.direction = "echo"
                if frame.bus not in (0,1,2) or frame.direction not in ("rx", "tx", "echo", "rejected"):
                    raise ValueError("Invalid bus or direction")
                frame.source = "replay"  # Uploaded labels can never satisfy live interlocks.
                frames.append(frame)
            if len(frames) > 150000: raise ValueError("Maximum 150,000 frames per import")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"Recording line {line_no}: {exc}") from exc
    if not frames: raise ValueError("No CAN frames found")
    return frames, skipped

def usb_inventory():
    try:
        import usb1
        with usb1.USBContext() as context:
            return {"devices": [{"vendor": f"{d.getVendorID():04x}", "product": f"{d.getProductID():04x}"}
                                for d in context.getDeviceList(skip_on_error=True)
                                if d.getVendorID() in (0xbbaa, 0x3801)], "probe": "USB descriptors only; no CAN commands"}
    except Exception as exc:
        return {"devices": [], "error": str(exc), "probe": "USB enumeration unavailable"}

class PandaUSB:
    """Avoid Panda constructor resets, bitrate changes, SPI fallback or flashing.

    Interface follows pinned Panda 92eb565 / opendbc 229dc706 (see docs).
    Compatible firmware is required; packet versions are checked before changes.
    """
    def __init__(self, serial):
        from panda import Panda
        from panda.python import unpack_can_buffer
        from panda.python.usb import PandaUsbHandle
        import usb1
        self.lock = __import__("threading").RLock()
        self.p = None; self.initial = None; self.mode = 0; self.health = {}; self.buffer = b""
        self.unpack = unpack_can_buffer
        context = usb1.USBContext(); context.open(); handle = None
        try:
            devices = [d for d in context.getDeviceList(skip_on_error=True)
                       if d.getVendorID() in Panda.USB_VIDS and d.getProductID() in Panda.USB_PIDS]
            selected = [d for d in devices if not serial or d.getSerialNumber() == serial]
            if len(selected) != 1: raise ValueError("Select exactly one standalone USB Panda by serial")
            device = selected[0]
            if device.getProductID() & 0xf0 == 0xe0: raise ValueError("Bootstub detected; no flashing supported")
            actual = device.getSerialNumber()
            handle = device.open(); handle.claimInterface(0)
            p = Panda.__new__(Panda)
            p._context = context; p._handle = PandaUsbHandle(handle); p._handle_open = True
            p._disable_checks = False; p.can_rx_overflow_buffer = b""; p.bootstub = False
            p._serial = p._connect_serial = actual
            versions = p.get_packets_versions()
            p.health_version, p.can_version = versions[:2]
            if p.can_version != p.CAN_PACKET_VERSION: raise ValueError("CAN packet version mismatch; use matching library")
            h = p.health()
            if h["controls_allowed"] or h["safety_mode"] not in (0,19):
                raise ValueError("Panda must already be standalone and silent/no-output; takeover refused")
            if p.get_type() in p.INTERNAL_DEVICES:
                raise ValueError("Internal Comma Panda is not supported; use standalone USB Panda")
            self.p = p; self.initial = h; self.serial = actual
            self.firmware = p.get_version()
            self.set_mode(False)
        except BaseException:
            if self.p:
                self.close()
            else:
                if handle: handle.close()
                context.close()
            raise

    def check(self):
        h = self.p.health()
        if h["safety_mode"] != self.mode or h["safety_param"] != (1 if self.mode else 0) or h["controls_allowed"]:
            raise ValueError("Unexpected Panda safety state; diagnostics aborted")
        self.health = h
        return h

    def set_mode(self, active):
        with self.lock:
            self.mode = 3 if active else 0
            self.p.set_safety_mode(self.mode, 1 if active else 0)
            self.p.set_power_save(0)
            self.p.send_heartbeat(engaged=False)
            self.check()

    def pump(self):
        import usb1
        with self.lock:
            self.p.send_heartbeat(engaged=False)
            self.check()
            try: raw = self.p._handle.bulkRead(1, 16384, timeout=20)
            except usb1.USBErrorTimeout: return []
            rows, self.buffer = self.unpack(self.buffer + raw)
        frames = []
        for address, data, bus in rows:
            direction = "rx"
            if bus >= 192: bus -= 192; direction = "rejected"
            elif bus >= 128: bus -= 128; direction = "echo"
            frames.append(Frame(time.time(), address, bus, bytes(data), direction, "panda"))
        return frames

    def send(self, address, bus, data):
        with self.lock:
            self.check()
            if self.mode != 3 or len(data) != 8 or bus not in (0,1,2) or not 0x600 <= address <= 0x7ef or address == 0x7df:
                raise ValueError("Outside permitted physical diagnostic transport")
            self.p.can_send(address, data, bus, timeout=50)

    def close(self):
        if not self.p: return
        with self.lock:
            try:
                self.p.set_safety_mode(0, 0)
                if self.initial:
                    self.p.set_power_save(self.initial["power_save_enabled"])
                    # Never restore a transmit-capable mode; accepted initial modes
                    # are silent/no-output only. Keep final silent mode intentionally.
                if self.p.health()["safety_mode"] != 0: raise ValueError("Final silent mode unconfirmed")
            finally:
                self.p.close(); self.p = None
