from collections import deque
import pytest
from teslalab.uds import IsoTP, ProtocolError, NegativeResponse, decode_dtcs, make_request
from teslalab.safety import Denied

class Wire:
    def __init__(self, rows): self.rows=deque(bytes.fromhex(r) for r in rows); self.sent=[]; self.now=0; self.checks=0
    def clock(self): return self.now
    def recv(self, timeout):
        self.now += .01 if self.rows else timeout
        return self.rows.popleft() if self.rows else None
    def guard(self): self.checks+=1
    def client(self): return IsoTP(self.sent.append,self.recv,self.guard,self.clock)

def test_captured_multiframe_dtc():
    wire=Wire(["10 0f 59 02 ff 55 a3 01","21 08 55 a9 00 08 55 62","22 98 08 00 00 00 00 00"])
    result=decode_dtcs(wire.client().transact(bytes.fromhex("19 02 ff")))
    assert [d["code"] for d in result["records"]]==["55A301","55A900","556298"]
    assert result["records"][0]["flags"]==["confirmedDTC"]
    assert wire.sent==[bytes.fromhex("03 19 02 ff 00 00 00 00"),bytes.fromhex("30 00 00 00 00 00 00 00")]

def test_status_mask_is_respected():
    result=decode_dtcs(bytes.fromhex("59 02 08 55 a3 01 09"))
    assert result["records"][0]["flags"]==["confirmedDTC"]
    assert result["records"][0]["unsupported_set_bits"]=="01"

def test_pending_is_bounded_then_positive():
    wire=Wire(["03 7f 19 78 00 00 00 00","03 59 02 ff 00 00 00 00"])
    assert wire.client().transact(bytes.fromhex("19 02 ff"))==bytes.fromhex("59 02 ff")

@pytest.mark.parametrize("row",["03 62 f1 91 00 00 00 00","03 7f 19 31 00 00 00 00","08 62 f1 90 00 00 00 00","10 07 62 f1 90 00 00 00"])
def test_rejects_wrong_identifier_service_and_invalid_lengths(row):
    with pytest.raises(ProtocolError): Wire([row]).client().transact(bytes.fromhex("22 f1 90"))

def test_sequence_mismatch_and_unsolicited_cf():
    for rows in [["10 09 59 02 ff 55 a3 01","22 08 00 00 00 00 00 00"],["21 00 00 00 00 00 00 00"]]:
        with pytest.raises(ProtocolError): Wire(rows).client().transact(bytes.fromhex("19 02 ff"))

def test_pending_storm_still_has_absolute_timeout():
    wire=Wire(["03 7f 19 78 00 00 00 00"]*1000)
    with pytest.raises(ProtocolError,match="timeout"):
        wire.client().transact(bytes.fromhex("19 02 ff"),total_timeout=.5)
    assert wire.now < .6

def test_no_reply_timeout_never_retries_request():
    wire=Wire([])
    with pytest.raises(ProtocolError,match="timeout"): wire.client().transact(bytes.fromhex("19 02 ff"))
    assert len(wire.sent)==1

def test_guard_loss_prevents_flow_control():
    wire=Wire(["10 09 59 02 ff 55 a3 01"])
    def guard():
        wire.checks+=1
        if wire.checks==3: raise Denied("motion")
    with pytest.raises(Denied): IsoTP(wire.sent.append,wire.recv,guard,wire.clock).transact(bytes.fromhex("19 02 ff"))
    assert len(wire.sent)==1

def test_negative_response_has_nrc():
    with pytest.raises(NegativeResponse,match="request out of range"):
        Wire(["03 7f 22 31 00 00 00 00"]).client().transact(bytes.fromhex("22 01 01"))

@pytest.mark.parametrize("raw",["59 02", "59 02 ff 55", "62 02 ff"])
def test_malformed_dtcs(raw):
    with pytest.raises(ProtocolError): decode_dtcs(bytes.fromhex(raw))

def test_no_arbitrary_services_or_height_targets():
    with pytest.raises(Denied): make_request("raw", "0305")
    with pytest.raises(Denied): make_request("routine_start", "0305", "07")
    with pytest.raises(Denied): make_request("routine_start", "0315", "00")
    assert make_request("routine_start","0305","06")==bytes.fromhex("31 01 03 05 06")
