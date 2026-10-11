"""Bounded classic-CAN ISO-TP; no raw service passthrough."""
import queue
import time
from .safety import Denied

FLAGS = ["testFailed", "testFailedThisOperationCycle", "pendingDTC", "confirmedDTC",
         "testNotCompletedSinceLastClear", "testFailedSinceLastClear",
         "testNotCompletedThisOperationCycle", "warningIndicatorRequested"]
NRC = {0x10:"general reject", 0x11:"service not supported", 0x12:"subfunction not supported",
       0x13:"incorrect length", 0x22:"conditions not correct", 0x31:"request out of range",
       0x33:"security access denied", 0x78:"response pending", 0x7e:"subfunction not supported in session",
       0x7f:"service not supported in session"}

class ProtocolError(ValueError): pass

class NegativeResponse(ProtocolError):
    def __init__(self, response):
        self.response = response
        super().__init__(f"NRC {response[2]:02X}: {NRC.get(response[2], 'unknown manufacturer response')}")

def decode_dtcs(response):
    if len(response) < 3 or response[:2] != b"\x59\x02" or (len(response)-3) % 4:
        raise ProtocolError("Malformed DTC status-mask response")
    mask = response[2]
    return {"raw": response.hex(" "), "availability_mask": f"{mask:02X}",
            "records": [{"code": response[i:i+3].hex().upper(), "status": f"{response[i+3]:02X}",
                         "flags": [name for bit,name in enumerate(FLAGS) if response[i+3] & mask & (1<<bit)],
                         "unsupported_set_bits": f"{response[i+3] & ~mask:02X}", "meaning": "Unknown; no verified Tesla DTC dictionary"}
                        for i in range(3, len(response), 4)]}

def expected_prefix(payload):
    prefix = bytes([payload[0]+0x40])
    if payload[0] in (0x10,0x19): prefix += payload[1:2]
    elif payload[0] == 0x22: prefix += payload[1:3]
    elif payload[0] == 0x31: prefix += payload[1:4]
    return prefix

class IsoTP:
    def __init__(self, send, receive, require, clock=time.monotonic):
        self.send = send; self.receive = receive; self.require = require; self.clock = clock

    def transact(self, payload, timeout=1.5, total_timeout=8):
        if not 1 <= len(payload) <= 7: raise ProtocolError("Single-frame requests only")
        self.require()
        self.send((bytes([len(payload)]) + payload).ljust(8, b"\0"))
        overall = self.clock() + total_timeout
        deadline = self.clock() + timeout
        buffer = bytearray(); length = 0; sequence = 1
        while self.clock() < min(overall, deadline):
            self.require()
            frame = self.receive(min(.05, max(0, min(overall, deadline)-self.clock())))
            if frame is None: continue
            if not frame: raise ProtocolError("Empty ISO-TP frame")
            kind = frame[0] >> 4
            if kind == 0:
                size = frame[0] & 15
                if length or not 1 <= size <= 7 or len(frame) < size+1: raise ProtocolError("Invalid single frame")
                response = bytes(frame[1:size+1])
            elif kind == 1:
                if length or len(frame) != 8: raise ProtocolError("Invalid first frame")
                length = ((frame[0]&15)<<8)|frame[1]
                if not 8 <= length <= 4095: raise ProtocolError("Invalid ISO-TP length")
                buffer = bytearray(frame[2:]); sequence = 1
                self.require(); self.send(bytes.fromhex("30 00 00 00 00 00 00 00"))
                deadline = self.clock()+timeout
                continue
            elif kind == 2:
                if not length or len(frame) != 8 or frame[0]&15 != sequence:
                    raise ProtocolError("Unexpected or out-of-sequence consecutive frame")
                sequence = (sequence+1)&15; buffer.extend(frame[1:])
                deadline = self.clock()+timeout
                if len(buffer) < length: continue
                response = bytes(buffer[:length]); length = 0
            else:
                raise ProtocolError("Unexpected ISO-TP frame type")
            if response[:1] == b"\x7f":
                if len(response) != 3 or response[1] != payload[0]: raise ProtocolError("Mismatched negative response")
                if response[2] == 0x78:
                    deadline = self.clock()+3; continue
                raise NegativeResponse(response)
            if not response.startswith(expected_prefix(payload)):
                raise ProtocolError("Mismatched response service / identifier")
            if payload[0] == 0x14 and response != b"\x54": raise ProtocolError("Malformed clear acknowledgment")
            return response
        raise ProtocolError("Diagnostic response timeout (no success inferred)")

def make_request(action, identifier=None, parameter=None):
    if action == "read_dtc": return bytes.fromhex("19 02 ff")
    if action == "clear_dtc": return bytes.fromhex("14 ff ff ff")
    if not identifier: raise Denied("Identifier is required for this service")
    if action == "read_did":
        value = int(identifier, 16)
        if not 0 <= value <= 65535: raise Denied("DID must be 0000–FFFF")
        return bytes([0x22])+value.to_bytes(2,"big")
    if action == "routine_results":
        value = int(identifier, 16)
        if not 0 <= value <= 65535: raise Denied("Routine ID must be 0000–FFFF")
        return bytes([0x31,3])+value.to_bytes(2,"big")
    if action == "session":
        if identifier not in ("01", "03"): raise Denied("Only default / extended session inspection")
        return bytes([0x10,int(identifier,16)])
    if action == "routine_start":
        if identifier not in ("0305", "0309", "030A", "0315"): raise Denied("Unknown routine cannot be constructed")
        extra = bytes.fromhex(parameter or "")
        if identifier == "0305" and extra not in (b"\x03",b"\x04",b"\x05",b"\x06"):
            raise Denied("Only captured height parameters can be previewed")
        if identifier != "0305" and extra: raise Denied("No verified parameter for this routine")
        return bytes([0x31,1])+bytes.fromhex(identifier)+extra
    raise Denied("Action is not in the service allowlist")

class DemoECU:
    """Synthetic responses, never represented as a live or historical scan."""
    def __init__(self): self.cleared = set()
    def transact(self, profile, payload):
        if payload[0] == 0x19:
            return bytes.fromhex("59 02 ff" if profile["key"] in self.cleared else "59 02 ff 55 a3 01 08 55 a9 00 08 55 62 98 08")
        if payload[0] == 0x14:
            self.cleared.add(profile["key"]); return b"\x54"
        if payload[0] == 0x22: return b"\x62"+payload[1:3]+b"SYNTHETIC-NOT-A-VIN"
        raise Denied("Manufacturer routines / session transitions are inspection-only")
