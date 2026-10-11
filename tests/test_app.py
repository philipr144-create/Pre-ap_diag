import json
import time
import pytest
from fastapi.testclient import TestClient
from teslalab.server import create_app
from teslalab.engine import Lab
from teslalab.safety import Denied
from teslalab.transport import Frame

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path,allowed_hosts={"testserver"})) as c:
        c.get("/"); c.headers["X-Lab-Request"]="1"; yield c

def post(client,path,body=None): return client.post("/api/"+path,json=body if body is not None else {})

def test_default_offline_no_auto_hardware_and_original_dbc_repair_reported(client):
    assert client.get("/api/state").json()["mode"]=="offline"
    catalog=client.get("/api/catalog").json()
    assert len(catalog["dbcs"])==2 and not catalog["decoder_errors"]
    assert catalog["decoder_warnings"] and catalog["permissions"]["enabled_actuations"]==[]
    assert not catalog["profiles"][0]["clear_verified"]
    assert len(catalog["control_reference_builders"])==3
    assert all(not b["enabled"] for b in catalog["control_reference_builders"])
    assert client.get("/api/references/teslacan.py").status_code==200
    assert client.get("/api/references/missing").status_code==400

def test_origin_session_host_and_header_rejections(tmp_path):
    with TestClient(create_app(tmp_path,allowed_hosts={"testserver"})) as c:
        assert c.get("/api/state").status_code==403
        c.get("/")
        assert c.post("/api/source",json={"mode":"demo"}).status_code==403
        assert c.get("/api/state",headers={"Origin":"https://evil.example"}).status_code==403
        assert c.get("/api/state",headers={"Host":"evil.example"}).status_code==403
        assert c.get("/api/state",headers={"Sec-Fetch-Site":"cross-site"}).status_code==403

def test_demo_clear_full_flow_snapshot_and_repeat_denied(client):
    assert post(client,"source",{"mode":"demo"}).status_code==200
    result=post(client,"diagnostic",{"action":"read_dtc","dry_run":False}).json()
    assert result["source"]=="demo" and len(result["records"])==3
    item=post(client,"clear/prepare",{"ecu":"eas"}).json()
    body={"action":"clear_dtc","dry_run":False,"token":item["token"],"phrase":item["phrase"]}
    assert post(client,"diagnostic",body).status_code==200
    assert post(client,"diagnostic",body).status_code==400
    after=post(client,"diagnostic",{"action":"read_dtc","dry_run":False}).json()
    assert after["records"]==[]
    run=client.get("/api/state").json()["run"]
    report=client.get(f"/api/runs/{run}/report").json()
    snapshot=next(e for e in report["events"] if e["kind"]=="pre_clear_snapshot")
    assert len(snapshot["data"]["records"])==3

def test_clear_without_scan_and_reread_invalidates_confirmation(client):
    post(client,"source",{"mode":"demo"})
    assert post(client,"clear/prepare",{"ecu":"eas"}).status_code==400
    post(client,"diagnostic",{"action":"read_dtc","dry_run":False})
    item=post(client,"clear/prepare",{"ecu":"eas"}).json()
    post(client,"diagnostic",{"action":"read_dtc","dry_run":False})
    assert post(client,"diagnostic",{"action":"clear_dtc","dry_run":False,**{k:item[k] for k in ("token","phrase")}}).status_code==400

def test_confirmation_cannot_cross_source_session(client):
    post(client,"source",{"mode":"demo"});post(client,"diagnostic",{"action":"read_dtc","dry_run":False})
    item=post(client,"clear/prepare",{"ecu":"eas"}).json()
    post(client,"source",{"mode":"demo"});post(client,"diagnostic",{"action":"read_dtc","dry_run":False})
    assert post(client,"diagnostic",{"action":"clear_dtc","dry_run":False,"token":item["token"],"phrase":item["phrase"]}).status_code==400

def test_unknown_and_manufacturer_writes_cannot_execute(client):
    post(client,"source",{"mode":"demo"})
    for action,ident in [("session","03"),("routine_start","0309"),("routine_results","030A")]:
        assert post(client,"diagnostic",{"action":action,"identifier":ident,"dry_run":False}).status_code==400
        assert post(client,"diagnostic",{"action":action,"identifier":ident,"dry_run":True}).json()["transmitted"] is False
    assert post(client,"diagnostic",{"action":"raw","payload":"31010305"}).status_code==422
    assert post(client,"diagnostic",{"action":"read_did","dry_run":False}).status_code==400
    assert post(client,"arm",{"car_off":True,"secured":True,"exclusive":True}).status_code==400

def test_ui_profiles_cannot_self_grant_permission(client):
    body={"key":"gateway","name":"Gateway","tx":0x700,"rx":0x708,"bus":0}
    assert post(client,"profiles",{**body,"transport_verified":True}).status_code==422
    result=post(client,"profiles",body).json()
    assert result["transport_verified"] is False
    assert post(client,"profiles",{"key":"conflict","name":"conflict","tx":0x64b,"rx":0x600,"bus":0}).status_code==400

def test_replay_export_round_trip_and_never_live(client):
    text='{"ts":1,"address":341,"bus":0,"data":"0000000000000000"}\n{"ts":1.01,"address":1627,"bus":128,"data":"035902ff00000000"}'
    assert post(client,"source",{"mode":"replay","text":text,"speed":20}).status_code==200
    time.sleep(.08)
    state=client.get("/api/state").json()
    assert state["mode"]=="replay" and not state["guard"]["fresh_stationary_park"]
    assert post(client,"diagnostic",{"action":"read_dtc","dry_run":False}).status_code==400
    raw=client.get(f'/api/runs/{state["run"]}/frames').text
    assert all(json.loads(line)["source"]=="replay" for line in raw.splitlines())
    assert len(raw.splitlines())==2
    assert post(client,"replay",{"index":0,"paused":True}).status_code==200
    assert post(client,"source",{"mode":"replay","text":"bad"}).status_code==400
    assert client.get("/api/state").json()["mode"]=="replay"

def test_demo_did_discovery_report_and_marker(client):
    post(client,"source",{"mode":"demo"}); time.sleep(.15)
    assert client.get("/api/state").json()["signals"]
    post(client,"marker",{"text":"parked observation"})
    result=post(client,"diagnostic",{"action":"read_did","identifier":"F190","dry_run":False}).json()
    assert result["source"]=="demo" and "data_hex" in result
    result=post(client,"discover",{"keys":["eas"],"dry_run":False}).json()
    assert result[0]["responded"]
    assert post(client,"discover",{"keys":["eas","eas"]}).status_code==400
    run=client.get("/api/state").json()["run"]
    assert client.get(f"/api/runs/{run}/report").json()["evidence_manifest"]["references"]
    assert "Source: DEMO" in client.get(f"/api/runs/{run}/report?format=txt").text
    assert client.get(f"/api/runs/{run}/frames?format=csv").text.startswith("ts,address,bus")
    post(client,"stop")
    assert client.get("/api/runs").json()[0]["ended"]

def test_live_eas_clear_remains_unverified_even_with_host_flags(tmp_path):
    lab=Lab(tmp_path,True,True)
    try:
        lab.mode="panda"; lab.run="test";lab.tx_enabled=True
        lab.last_dtc["eas"]={"ts":time.time(),"source":"panda"}
        lab.require_live=lambda:None
        with pytest.raises(Denied,match="verified clear"):lab.prepare_clear("eas")
    finally:
        lab.mode="offline";lab.run=None;lab.close()

def test_dry_run_never_touches_device(tmp_path):
    lab=Lab(tmp_path,True)
    try:
        lab._transact=lambda *args:pytest.fail("transact called during dry-run")
        plan=lab.diagnostic("eas","read_dtc")
        assert plan["payload"]=="19 02 ff" and not plan["transmitted"]
    finally: lab.close()

def test_candidates_mapping_and_interrupted_recordings_survive_restart(tmp_path):
    lab=Lab(tmp_path)
    lab.add_profile({"key":"candidate","name":"Unknown","tx":0x700,"rx":0x708,"bus":1})
    lab.set_bus_map({0:"tesla_powertrain",1:"tesla_preap",2:"tesla_preap"})
    run=lab.store.start("panda","interrupted test")
    lab.store.close()  # Simulate process loss, not a successful adapter cleanup.
    reopened=Lab(tmp_path)
    try:
        assert not reopened.profiles["candidate"]["transport_verified"]
        assert reopened.decoder.bus_map[0]=="tesla_powertrain"
        report=reopened.store.report(run)
        assert any(e["kind"]=="interrupted" and not e["data"]["device_cleanup_verified"] for e in report["events"])
    finally:reopened.close()

def test_verified_other_ecu_clear_needs_host_permission_and_exact_request(tmp_path):
    path=tmp_path/"profiles.json"
    path.write_text(json.dumps([{"key":"verified_fixture","name":"Mock ECU only","tx":0x700,"rx":0x708,"bus":0,
                                "transport_verified":True,"evidence":"test fixture","clear_verified":True,"clear_evidence":"simulated fixture, not vehicle evidence"}]))
    lab=Lab(tmp_path,True,False,path)
    try:
        lab.mode="panda";lab.run=lab.store.start("panda","mock only")
        lab.last_dtc["verified_fixture"]={"ts":time.time(),"source":"panda","records":[]}
        lab.require_live=lambda:None
        with pytest.raises(Denied):lab.prepare_clear("verified_fixture")
        lab.enable_clear=True;sent=[]
        lab._transact=lambda profile,payload:sent.append(payload) or b"\x54"
        confirm=lab.prepare_clear("verified_fixture")
        lab.diagnostic("verified_fixture","clear_dtc",dry_run=False,token=confirm["token"],phrase=confirm["phrase"])
        assert sent==[bytes.fromhex("14 ff ff ff")]
    finally:lab.close()
