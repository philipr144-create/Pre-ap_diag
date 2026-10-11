import secrets
import time

class Denied(ValueError): pass

class Guard:
    """Live CAN observations and expiring operator attestations are distinct."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.observations = {}
        self.attested_until = 0

    def observe(self, frame, values):
        if frame.source != "panda" or frame.direction != "rx" or frame.bus != 0: return
        now = self.clock()
        # Exact message/signal identities from supplied pre-AP DBC.
        if frame.address == 0x155 and "ESP_vehicleSpeed" in values:
            valid = values.get("ESP_vehicleSpeedQF") == 1
            self.observations["speed_kph"] = (values["ESP_vehicleSpeed"] if valid else None, now)
        if frame.address == 0x118 and "DI_gear" in values:
            self.observations["gear"] = (values["DI_gear"], now)
            self.observations["di_speed_mph"] = (values.get("DI_vehicleSpeed"), now)

    def attest(self, car_off, secured, exclusive):
        if not (car_off and secured and exclusive):
            raise Denied("Attest car off, vehicle secured, and exclusive standalone Panda ownership")
        self.attested_until = self.clock() + 60

    def state(self):
        now = self.clock()
        def fresh(key):
            val, at = self.observations.get(key, (None, -999))
            return val if now - at <= .5 else None
        speed, gear, di = fresh("speed_kph"), fresh("gear"), fresh("di_speed_mph")
        return {"speed_kph": speed, "gear": gear, "di_speed_mph": di,
                "fresh_stationary_park": speed is not None and 0 <= speed < .36 and gear == 1 and di is not None and abs(di) < .23,
                "attestation_seconds": max(0, round(self.attested_until - now, 1)),
                "car_off": "operator attestation only; no verified car-off CAN signal",
                "speed_quality": "QF=1 required; applicability must be confirmed on vehicle"}

    def require(self):
        if not self.state()["fresh_stationary_park"]:
            raise Denied("Fresh live bus-0 Park and two stationary speed signals with valid QF required")
        if self.clock() >= self.attested_until:
            raise Denied("Car-off / secured / exclusive-ownership attestation missing or expired")

    def reset(self):
        self.observations.clear(); self.attested_until = 0

class Confirmations:
    def __init__(self, clock=time.monotonic):
        self.clock = clock; self.pending = {}
    def issue(self, binding, phrase):
        self.pending = {k:v for k,v in self.pending.items() if v[0] > self.clock()}
        token = secrets.token_urlsafe(24)
        self.pending[token] = (self.clock() + 30, binding, phrase)
        return {"token": token, "phrase": phrase, "expires_seconds": 30}
    def consume(self, token, binding, phrase):
        item = self.pending.pop(token, None)
        if not item or item[0] <= self.clock() or item[1] != binding or item[2] != phrase:
            raise Denied("Confirmation expired, already used, or does not match this operation")
    def reset(self): self.pending.clear()
