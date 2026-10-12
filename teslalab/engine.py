from collections import deque
import json
import math
from pathlib import Path
import queue
import threading
import time
from .catalog import EAS, ROUTINES, DIDS, BLOCKED, manifest, reference_builders
from .decoder import Decoder
from .safety import Guard, Denied, Confirmations
from .store import Store
from .transport import Frame, PandaUSB, PandaSPI, parse_recording, usb_inventory
from .uds import DemoECU, IsoTP, decode_dtcs, make_request, NegativeResponse

class Lab:
    def __init__(self, data_dir, enable_diagnostics=False, enable_clear=False, profiles_path=None):
        self.store = Store(Path(data_dir) / "lab.sqlite3")
        self.decoder = Decoder(); self.guard = Guard(); self.confirm = Confirmations()
        self.lock = threading.RLock(); self.control = threading.RLock()
        self.stop_event = threading.Event(); self.thread = None; self.device = None
        self.active_queue = None; self.active_profile = None
        self.profiles = {"eas": {**EAS, "transport_verified": True}}
        if profiles_path:
            profiles = json.loads(Path(profiles_path).read_text())
            for profile in profiles:
                self.validate_profile(profile)
                if profile["key"] == "eas":
                    raise ValueError("Bundled EAS profile cannot be overridden")
                if profile.get("transport_verified") and not profile.get("evidence"):
                    raise ValueError("Verified profiles require a traceable evidence citation")
                if profile.get("clear_verified") and not profile.get("clear_evidence"):
                    raise ValueError("Verified clear requires ECU-specific evidence citation")
                if profile["key"] == "eas" and profile.get("clear_verified"):
                    raise ValueError("Bundled EAS uncertainty cannot be overridden by profile import")
                self.profiles[profile["key"]] = profile
        self.enable_diagnostics = enable_diagnostics; self.enable_clear = enable_clear
        self.demo = DemoECU(); self.mode = "offline"; self.run = None; self.fault = None
        self.tx_enabled = False; self.quarantined = False
        self.raw = deque(maxlen=500); self.count = 0; self.started = time.monotonic()
        self.last_dtc = {}; self.responses = {}; self.passive_candidates = {}
        self.replay = []; self.replay_index = 0; self.replay_speed = 1; self.paused = False
        for profile in self.store.setting("candidate_profiles",[]):
            if profile["key"] in self.profiles: continue
            try:
                self.validate_profile(profile)
                profile["transport_verified"] = False; profile["clear_verified"] = False
                self.profiles[profile["key"]] = profile
            except ValueError as exc: self.audit("candidate_restore_skipped",{"reason":str(exc)})
        mapping = self.store.setting("bus_map")
        if mapping:
            mapping = {int(k):v for k,v in mapping.items()}
            if set(mapping)=={0,1,2} and all(v in self.decoder.databases for v in mapping.values()):
                self.decoder.bus_map = mapping

    def validate_profile(self, p):
        if not isinstance(p, dict) or not isinstance(p.get("key"),str) or not 1 <= len(p["key"]) <= 40:
            raise ValueError("Profile needs a key of 1–40 characters")
        for field in ("tx", "rx"):
            if not isinstance(p.get(field),int) or not 0x600 <= p[field] <= 0x7ef or p[field] == 0x7df:
                raise ValueError("Use physical 11-bit diagnostic addresses 600–7EF, excluding 7DF")
        if p["tx"] == p["rx"] or p.get("bus") not in (0,1,2): raise ValueError("Invalid pair / bus")
        for field in ("transport_verified", "clear_verified"):
            if field in p and type(p[field]) is not bool: raise ValueError("Verification flags must be booleans")
        if len(self.profiles) >= 16: raise ValueError("Maximum 16 explicit ECU profiles")
        for row in self.profiles.values():
            if row["key"] != p["key"] and row["bus"] == p["bus"] and ({row["tx"],row["rx"]} & {p["tx"],p["rx"]}):
                raise ValueError("Address overlaps another ECU profile")

    def add_profile(self, p):
        with self.control:
            self.validate_profile(p)
            if p["key"] in self.profiles: raise Denied("Cannot overwrite an existing profile through the UI")
            p = {"key": p["key"], "name": str(p.get("name",p["key"]))[:80], "tx": p["tx"], "rx": p["rx"], "bus": p["bus"],
                 "transport_verified": False, "clear_verified": False, "confidence": "operator candidate; live TX disabled", "evidence": "none"}
            self.profiles[p["key"]] = p
            candidates = self.store.setting("candidate_profiles",[])
            candidates.append(p); self.store.save_setting("candidate_profiles",candidates)
            self.audit("profile_candidate",p)
            return p

    def audit(self, kind, data): self.store.event(self.run, kind, data)

    def catalog(self):
        return {"vehicle": "2013 Model S P85 · pre-AP", "profiles": list(self.profiles.values()),
                "routines": ROUTINES, "dids": DIDS, "blocked_actions": BLOCKED,
                "references": manifest(), "dbcs": self.decoder.catalog(), "decoder_errors": self.decoder.errors,
                "control_reference_builders":reference_builders(),
                "decoder_warnings": self.decoder.warnings,
                "bus_map": self.decoder.bus_map,
                "permissions": {"live_diagnostics": self.enable_diagnostics, "live_clear": self.enable_clear,
                                "enabled_actuations": [], "default": "passive receive only"}}

    def state(self):
        with self.lock:
            now = time.monotonic()
            signals = [{k:v for k,v in row.items() if k != "received"} | {"age": round(now-row["received"],2)} for row in self.decoder.latest.values()]
            return {"mode": self.mode, "run": self.run, "frames": self.count, "fault": self.fault,
                    "tx_enabled": self.tx_enabled, "quarantined": self.quarantined, "guard": self.guard.state(),
                    "signals": signals, "raw": [f.json() for f in list(self.raw)[-100:]],
                    "dtcs": self.last_dtc, "responses": self.responses,
                    "health": self.device.health if self.device else None,
                    "device": {"serial": self.device.serial,"firmware":self.device.firmware} if self.device else None,
                    "replay": {"index": self.replay_index, "total": len(self.replay), "speed": self.replay_speed, "paused": self.paused},
                    "decode_errors": self.decoder.decode_errors, "candidates": list(self.passive_candidates.values())}

    def ingest(self, frame):
        with self.lock:
            self.raw.append(frame); self.count += 1
            self.store.frame(self.run,frame)
            values = self.decoder.ingest(frame); self.guard.observe(frame,values)
            if frame.direction == "rx" and len(frame.data) >= 3 and frame.data[0]>>4 == 0:
                size = frame.data[0]&15
                if 1 <= size <= 7 and len(frame.data) >= size+1 and (0x50 <= frame.data[1] <= 0x7f):
                    key = (frame.bus,frame.address)
                    self.passive_candidates[key] = {"bus": frame.bus, "rx": frame.address, "tx": None,
                        "confidence": "heuristic single-frame UDS-like response; ECU identity / TX unknown", "source":frame.source}
            p = self.active_profile
            if p and self.active_queue and frame.source == "panda" and frame.bus == p["bus"]:
                if frame.direction == "rx" and frame.address == p["rx"]:
                    try: self.active_queue.put_nowait(frame.data)
                    except queue.Full: self.quarantined = True; self.fault = "Diagnostic queue overflow"
                if frame.direction == "rejected" and frame.address == p["tx"]:
                    self.quarantined = True; self.fault = "Panda firmware rejected diagnostic frame"

    def stop(self):
        with self.control:
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    self.fault = "Capture worker did not stop; reconnect refused"
                    raise Denied(self.fault)
                self.thread = None
            error = None
            had_device = self.device is not None
            if self.device:
                try: self.device.close()
                except Exception as exc: error = str(exc)
                self.device = None
            if self.run:
                self.audit("acquisition_end", {"silent_verified": error is None if had_device else None, "error":error})
                self.store.end(self.run)
                self.run = None
            self.mode = "offline"; self.tx_enabled = False
            self.guard.reset(); self.confirm.reset(); self.active_queue = None; self.active_profile = None
            if error: self.fault = error; raise Denied("Panda final silent mode unconfirmed: " + error)

    def start(self, mode, serial=None, text=None, speed=1, interface="usb"):
        with self.control:
            if mode not in ("demo", "panda", "replay"): raise ValueError("Unknown source")
            if interface not in ("usb","spi"): raise ValueError("Unknown Panda interface")
            if not .1 <= speed <= 20: raise ValueError("Replay speed must be 0.1–20")
            frames, skipped = parse_recording(text) if mode == "replay" else ([],0)
            self.stop()
            device = (PandaSPI(serial) if interface == "spi" else PandaUSB(serial)) if mode == "panda" else None
            with self.lock:
                self.device = device; self.decoder.reset(); self.raw.clear(); self.guard.reset()
                self.mode = mode; self.fault = None; self.quarantined = False; self.count = 0
                self.last_dtc.clear(); self.responses.clear(); self.passive_candidates.clear(); self.demo = DemoECU()
                self.started = time.monotonic(); self.replay = frames; self.replay_index = 0
                self.replay_speed = speed; self.paused = False
                self.run = self.store.start(mode, f"{mode} · {time.strftime('%Y-%m-%d %H:%M:%S')}")
                self.audit("acquisition_start", {"mode":mode, "skipped_import_records":skipped,
                    "bus_map": self.decoder.bus_map, "device":self.state()["device"]})
                self.stop_event.clear()
            self.thread = threading.Thread(target=self._worker,daemon=True); self.thread.start()
            return {"mode":mode,"run":self.run,"skipped_records":skipped}

    def _demo_frames(self):
        t = time.monotonic()-self.started
        for address, values in [(0x118,{"DI_gear":1,"DI_vehicleSpeed":0}),
                                (0x155,{"ESP_vehicleSpeed":0,"ESP_vehicleSpeedQF":1}),
                                (0x108,{"DI_torqueDriver":8*math.sin(t)})]:
            try:
                message = self.decoder.databases["tesla_preap"].get_message_by_frame_id(address)
                fields = {s.name: 0 for s in message.signals}
                fields.update({k:v for k,v in values.items() if k in fields})
                data = message.encode(fields,strict=False)
                self.ingest(Frame(time.time(),address,0,data,"rx","demo"))
            except (ValueError, KeyError, OverflowError): continue

    def _worker(self):
        try:
            while not self.stop_event.is_set():
                if self.mode == "demo":
                    self._demo_frames(); self.stop_event.wait(.1)
                elif self.mode == "panda":
                    for frame in self.device.pump(): self.ingest(frame)
                    if self.tx_enabled:
                        try:
                            self.guard.require()
                            if self.quarantined: raise Denied(self.fault or "Diagnostic transport quarantined")
                        except Denied as exc:
                            self.device.set_mode(False); self.tx_enabled = False; self.confirm.reset()
                            self.audit("automatic_disarm", {"reason":str(exc)})
                    self.stop_event.wait(.01)
                elif self.mode == "replay":
                    if self.paused or self.replay_index >= len(self.replay):
                        self.paused = True; self.stop_event.wait(.05); continue
                    frame = self.replay[self.replay_index]; self.ingest(frame); self.replay_index += 1
                    if self.replay_index < len(self.replay):
                        gap = max(0,min(2,self.replay[self.replay_index].ts-frame.ts)) / self.replay_speed
                        self.stop_event.wait(gap)
                else: break
        except Exception as exc:
            self.fault = str(exc); self.quarantined = True; self.tx_enabled = False
            self.guard.reset(); self.confirm.reset()
            self.audit("capture_fault", {"error":str(exc)})
            if self.device:
                try: self.device.set_mode(False)
                except Exception as cleanup: self.audit("silent_failure",{"error":str(cleanup)})

    def replay_control(self, index=None, paused=None, speed=None):
        with self.control, self.lock:
            if self.mode != "replay": raise Denied("Replay source required")
            if index is not None:
                if not 0 <= index < len(self.replay): raise ValueError("Seek index outside recording")
                self.replay_index = index; self.decoder.reset(); self.raw.clear(); self.guard.reset()
                self.audit("replay_seek",{"index":index})
            if paused is not None: self.paused = paused
            if speed is not None:
                if not .1 <= speed <= 20: raise ValueError("Replay speed must be 0.1–20")
                self.replay_speed = speed

    def set_bus_map(self, mapping):
        with self.control, self.lock:
            if self.tx_enabled: raise Denied("Disarm diagnostics before changing decoder mapping")
            if set(mapping) != {0,1,2} or any(v not in self.decoder.databases for v in mapping.values()):
                raise ValueError("Each physical bus needs an installed DBC")
            self.decoder.bus_map = mapping; self.decoder.reset(); self.guard.reset(); self.confirm.reset()
            self.store.save_setting("bus_map",mapping)
            self.audit("decoder_mapping",mapping)

    def arm(self, car_off, secured, exclusive):
        with self.control:
            if self.mode != "panda" or not self.device or not self.enable_diagnostics:
                raise Denied("Live Panda and host --enable-diagnostics permission required")
            if self.quarantined or self.fault: raise Denied("Reconnect after resolving the transport fault")
            if self.decoder.bus_map.get(0) != "tesla_preap": raise Denied("Bus-0 interlocks require supplied pre-AP decoder")
            self.guard.attest(car_off,secured,exclusive); self.guard.require()
            self.device.set_mode(True); self.tx_enabled = True
            self.audit("diagnostics_armed",{"expires_seconds":60,"car_off":"operator attestation"})
            return self.guard.state()

    def disarm(self):
        with self.control:
            if self.device: self.device.set_mode(False)
            self.tx_enabled = False; self.guard.attested_until = 0; self.confirm.reset()
            self.audit("diagnostics_disarmed",{})

    def require_live(self):
        if self.mode != "panda" or not self.device or not self.tx_enabled or not self.enable_diagnostics:
            raise Denied("Diagnostic transport is not armed")
        if self.quarantined or self.fault: raise Denied("Diagnostic transport fault; reconnect required")
        self.guard.require()

    def _transact(self, profile, payload):
        if self.mode == "demo": return self.demo.transact(profile,payload)
        self.require_live()
        if not profile.get("transport_verified"): raise Denied("Candidate transport pair is not verified for live requests")
        inbox = queue.Queue(maxsize=1024)
        with self.lock: self.active_profile = profile; self.active_queue = inbox
        def send(data):
            self.require_live()
            self.device.send(profile["tx"],profile["bus"],data)
            self.ingest(Frame(time.time(),profile["tx"],profile["bus"],data,"tx","panda"))
        def receive(timeout):
            try: return inbox.get(timeout=timeout)
            except queue.Empty: return None
        try:
            return IsoTP(send,receive,self.require_live).transact(payload)
        except NegativeResponse:
            raise
        except Exception:
            self.quarantined = True
            self.disarm()
            raise
        finally:
            with self.lock: self.active_profile = None; self.active_queue = None

    def plan(self, profile_key, action, identifier=None, parameter=None):
        profile = self.profiles.get(profile_key)
        if not profile: raise ValueError("Unknown ECU profile")
        payload = make_request(action,identifier.upper() if identifier else None,parameter)
        result = {"ecu":profile_key, "action":action, "tx":profile["tx"], "rx":profile["rx"],"bus":profile["bus"],
                "payload":payload.hex(" "), "iso_tp_single_frame":(bytes([len(payload)])+payload).ljust(8,b"\0").hex(" "),
                "dry_run":True, "transmitted":False,
                "live_enabled":action in ("read_dtc","read_did") and profile.get("transport_verified",False) and self.enable_diagnostics,
                "note":"No implicit session changes, TesterPresent, manufacturer cleanup, or automatic retries."}
        if action == "routine_start" and profile_key == "eas":
            result["execution_blocked"] = True
            result["cleanup_evidence"] = {"identity":"0309 Exit / Finish Service: user identified",
                "captured_sequence":["10 03","31 01 03 09","31 03 03 09","31 02 03 09"],
                "terminal_observation":"71 03 03 09 02; manufacturer success semantics unknown",
                "required_intended_workflow":"User requires Finish Service after commands; standalone-read scope unresolved",
                "automatic_execution":False}
        return result

    def diagnostic(self, profile_key, action, identifier=None, parameter=None, dry_run=True, token=None, phrase=None):
        with self.control:
            plan = self.plan(profile_key,action,identifier,parameter)
            profile = self.profiles[profile_key]
            if dry_run:
                self.audit("dry_run",plan); return plan
            if action not in ("read_dtc", "read_did", "clear_dtc"):
                raise Denied("Sessions and manufacturer routine services are inspection-only; verified safe lifecycle unavailable")
            if self.mode not in ("panda","demo"): raise Denied("Choose demo or an armed live Panda; replay never sends diagnostics")
            if action == "clear_dtc":
                self._require_clear(profile)
                self.confirm.consume(token,self._clear_binding(profile),phrase)
                self.audit("pre_clear_snapshot", self.last_dtc[profile_key])
            payload = bytes.fromhex(plan["payload"])
            self.audit("diagnostic_request",{**plan,"dry_run":False,"source":self.mode})
            try:
                reply = self._transact(profile,payload)
                result = {"ecu":profile_key,"action":action,"request":payload.hex(" "),"response":reply.hex(" "),
                          "source":self.mode,"ts":time.time(),"physical_success":False}
                if action == "read_dtc":
                    result.update(decode_dtcs(reply)); self.last_dtc[profile_key] = result
                elif action == "read_did":
                    result.update({"identifier":identifier,"data_hex":reply[3:].hex(" "),"interpretation":"Raw bytes; no inferred scaling"})
                elif action == "clear_dtc":
                    self.last_dtc.pop(profile_key,None)
                    result["note"] = "ECU acknowledged clear; read again to verify. Clearing does not repair a fault."
                self.responses[profile_key] = result; self.audit("diagnostic_response",result)
                return result
            except Exception as exc:
                self.audit("diagnostic_error",{"ecu":profile_key,"action":action,"error":str(exc),"source":self.mode})
                raise

    def _clear_binding(self, profile):
        return (self.run,self.mode,profile["key"],profile["tx"],profile["rx"],profile["bus"],
                self.last_dtc.get(profile["key"],{}).get("ts"))

    def _require_clear(self, profile):
        prior = self.last_dtc.get(profile["key"])
        if not prior or time.time()-prior["ts"] > 60 or prior["source"] != self.mode:
            raise Denied("Read and preserve this ECU's DTCs within the last 60 seconds first")
        if self.mode == "demo": return
        self.require_live()
        if not self.enable_clear or not profile.get("clear_verified") or not profile.get("clear_evidence"):
            raise Denied("Live clear disabled: host write permission and ECU-specific verified clear evidence required")

    def prepare_clear(self, key):
        with self.control:
            profile = self.profiles.get(key)
            if not profile: raise ValueError("Unknown ECU")
            self._require_clear(profile)
            result = self.confirm.issue(self._clear_binding(profile),f"CLEAR {key.upper()} ALL DTCS")
            self.audit("clear_confirmation_issued",{"ecu":key,"expires_seconds":30,"source":self.mode})
            return result

    def discover(self, keys, dry_run=True):
        with self.control:
            if not 1 <= len(keys) <= 16 or len(set(keys)) != len(keys): raise Denied("Select 1–16 distinct explicit ECU profiles")
            results = []
            for key in keys:
                try:
                    result = self.diagnostic(key,"read_dtc",dry_run=dry_run)
                    results.append({"ecu":key,"responded":not dry_run,"result":result})
                except NegativeResponse as exc:
                    results.append({"ecu":key,"responded":True,"service_supported":False,"error":str(exc)})
                except ValueError as exc:
                    results.append({"ecu":key,"responded":False,"error":str(exc)})
            self.audit("bounded_discovery",results)
            return results

    def history(self, key):
        with self.lock: return list(self.decoder.history.get(key,[]))

    def close(self):
        self.stop(); self.store.close()
