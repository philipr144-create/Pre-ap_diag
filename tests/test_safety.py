import pytest
from teslalab.safety import Guard, Confirmations, Denied
from teslalab.transport import Frame, parse_recording

def observed(guard,source="panda",speed=0,gear=1,qf=1,di=0,bus=0):
    guard.observe(Frame(0,0x155,bus,b"","rx",source),{"ESP_vehicleSpeed":speed,"ESP_vehicleSpeedQF":qf})
    guard.observe(Frame(0,0x118,bus,b"","rx",source),{"DI_gear":gear,"DI_vehicleSpeed":di})

def test_fresh_live_park_required_and_car_off_is_separate():
    now=[0]; guard=Guard(lambda:now[0]); observed(guard)
    with pytest.raises(Denied,match="attestation"): guard.require()
    guard.attest(True,True,True); guard.require()
    now[0]=.51
    with pytest.raises(Denied,match="Fresh"): guard.require()

@pytest.mark.parametrize("values",[{"source":"demo"},{"source":"replay"},{"speed":1},{"gear":4},{"qf":2},{"di":1},{"bus":1},{"speed":-1}])
def test_untrusted_or_unsafe_telemetry_fails_closed(values):
    guard=Guard(); observed(guard,**values); guard.attest(True,True,True)
    with pytest.raises(Denied): guard.require()

def test_invalid_new_quality_revokes_old_good_speed():
    guard=Guard(); observed(guard); observed(guard,qf=2); guard.attest(True,True,True)
    assert not guard.state()["fresh_stationary_park"]

def test_attestation_expiry_even_with_fresh_data():
    now=[0]; guard=Guard(lambda:now[0]); guard.attest(True,True,True); now[0]=61; observed(guard)
    with pytest.raises(Denied,match="expired"): guard.require()

def test_confirmation_single_use_binding_and_expiry():
    now=[0]; confirm=Confirmations(lambda:now[0]); item=confirm.issue(("run","eas"),"CLEAR EAS")
    with pytest.raises(Denied): confirm.consume(item["token"],("other-run","eas"),"CLEAR EAS")
    with pytest.raises(Denied): confirm.consume(item["token"],("run","eas"),"CLEAR EAS")
    item=confirm.issue(("run","eas"),"CLEAR EAS"); now[0]=31
    with pytest.raises(Denied): confirm.consume(item["token"],("run","eas"),"CLEAR EAS")
    item=confirm.issue(("run","eas"),"CLEAR EAS");confirm.consume(item["token"],("run","eas"),"CLEAR EAS")
    with pytest.raises(Denied): confirm.consume(item["token"],("run","eas"),"CLEAR EAS")

def test_replay_cannot_spoof_live_source_echoes_not_physical_buses():
    text='{"ts":1,"address":341,"bus":0,"data":"0000000000000000","source":"panda"}\n{"ts":2,"address":1627,"bus":128,"data":"035902ff00000000"}'
    frames,skipped=parse_recording(text)
    assert frames[0].source=="replay"
    assert frames[1].direction=="echo" and frames[1].bus==0
    assert skipped==0

def test_replay_candump_and_historical_batch():
    frames,skipped=parse_recording('(123.5) can0 65B#035902FF00000000\n{"at":124,"frames":[[1611,"031902ff00000000",192]]}\n{"event":"health"}')
    assert len(frames)==2 and frames[1].direction=="rejected" and skipped==1

@pytest.mark.parametrize("line",['{"ts":1,"address":1,"bus":4,"data":"00"}', '(1) can0 65B#0', '{"ts":NaN,"address":1,"bus":0,"data":"00"}'])
def test_bad_replay_rejected_before_source_change(line):
    with pytest.raises(ValueError): parse_recording(line)
