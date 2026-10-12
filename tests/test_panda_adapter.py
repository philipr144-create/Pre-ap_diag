"""Fake USB/Panda API only: these tests do not exercise hardware."""
import sys
import types
import pytest
from teslalab.transport import PandaUSB, PandaSPI

@pytest.fixture
def panda_api(monkeypatch):
    calls=[]
    class Raw:
        def claimInterface(self,n): calls.append(("claim",n))
        def close(self): calls.append(("raw_close",))
    class Device:
        product=0xddcc
        def getVendorID(self): return 0xbbaa
        def getProductID(self): return self.product
        def getSerialNumber(self): return "TEST-SERIAL"
        def open(self): calls.append(("open",)); return Raw()
    device=Device()
    class Context:
        def open(self): pass
        def close(self): calls.append(("context_close",))
        def getDeviceList(self,**kw): return [device]
    class Handle:
        def __init__(self,raw): self.raw=raw
        def bulkRead(self,*args,**kw): calls.append(("read",kw["timeout"]));return b""
        def close(self): self.raw.close()
    class Panda:
        USB_VIDS=(0xbbaa,);USB_PIDS=(0xddcc,0xddee);CAN_PACKET_VERSION=1
        INTERNAL_DEVICES=(b"\x09",b"\x0a");mode=0;param=0;power=1;controls=False;kind=b"\x07"
        def __init__(self,*args,**kw): pytest.fail("Panda constructor must not run")
        def get_packets_versions(self): return (1,1)
        def health(self):return dict(safety_mode=self.mode,safety_param=self.param,power_save_enabled=self.power,controls_allowed=self.controls)
        def get_type(self):return self.kind
        def get_version(self):return "fake"
        def set_safety_mode(self,mode,param):self.mode=mode;self.param=param;calls.append(("mode",mode,param))
        def set_power_save(self,power):self.power=power;calls.append(("power",power))
        def send_heartbeat(self,engaged):calls.append(("heartbeat",engaged))
        def can_send(self,address,data,bus,**kw):calls.append(("send",address,data,bus))
        def close(self):self._handle.close();self._context.close()
    package=types.ModuleType("panda");package.Panda=Panda
    python=types.ModuleType("panda.python");python.unpack_can_buffer=lambda raw:([],b"")
    usb=types.ModuleType("panda.python.usb");usb.PandaUsbHandle=Handle
    usb1=types.ModuleType("usb1");usb1.USBContext=Context;usb1.USBErrorTimeout=type("USBErrorTimeout",(Exception,),{})
    for name,module in [("panda",package),("panda.python",python),("panda.python.usb",usb),("usb1",usb1)]:monkeypatch.setitem(sys.modules,name,module)
    return Panda,device,calls

def test_passive_no_constructor_reset_bitrate_or_can_transmit(panda_api):
    panda,_,calls=panda_api
    adapter=PandaUSB("TEST-SERIAL"); adapter.pump()
    assert adapter.mode==0 and not any(c[0]=="send" for c in calls)
    with pytest.raises(ValueError):adapter.send(0x64b,0,b"\0"*8)
    adapter.close()
    assert ("mode",0,0) in calls and ("power",1) in calls
    assert ("read",20) in calls

@pytest.mark.parametrize("attr,value",[("mode",37),("controls",True),("kind",b"\x09")])
def test_refuses_shared_active_and_internal_panda(panda_api,attr,value):
    panda,device,calls=panda_api;setattr(panda,attr,value)
    with pytest.raises(ValueError):PandaUSB("TEST-SERIAL")
    assert not any(c[0] in ("send","mode") for c in calls)
    assert ("raw_close",) in calls

def test_bootstub_refused_without_open_or_flash(panda_api):
    panda,device,calls=panda_api;device.product=0xddee
    with pytest.raises(ValueError,match="Bootstub"):PandaUSB("TEST-SERIAL")
    assert not any(c[0]=="open" for c in calls)

def test_transport_never_uses_alloutput_and_rejects_functional_broadcast(panda_api):
    panda,device,calls=panda_api;adapter=PandaUSB("TEST-SERIAL")
    adapter.set_mode(True)
    for address,bus,data in [(0x7df,0,b"\0"*8),(0x551,0,b"\0"*8),(0x64b,3,b"\0"*8),(0x64b,0,b"\0"*6)]:
        with pytest.raises(ValueError):adapter.send(address,bus,data)
    adapter.send(0x64b,0,bytes.fromhex("031902ff00000000"))
    assert all(c[1] in (0,3) for c in calls if c[0]=="mode")
    adapter.close()

def test_spi_rejects_nonlinux_before_device_access(monkeypatch):
    monkeypatch.setattr(sys,"platform","darwin")
    with pytest.raises(ValueError,match="Linux Comma host"): PandaSPI()

def test_spi_refuses_running_openpilot_before_device_access(monkeypatch):
    monkeypatch.setattr(sys,"platform","linux")
    def refuse(self):raise ValueError("pandad is running")
    monkeypatch.setattr(PandaSPI,"require_exclusive",refuse)
    with pytest.raises(ValueError,match="pandad"): PandaSPI()

def test_spi_uses_explicit_connection_and_preserves_silent_shutdown(panda_api,monkeypatch):
    panda,device,calls=panda_api
    monkeypatch.setattr(sys,"platform","linux")
    monkeypatch.setattr(PandaSPI,"require_exclusive",lambda self:None)
    context=types.SimpleNamespace(close=lambda:calls.append(("spi_context_close",)))
    handle=types.SimpleNamespace(close=lambda:calls.append(("spi_close",)))
    monkeypatch.setattr(panda,"spi_connect",lambda serial:(context,handle,"SPI-TEST",False),raising=False)
    adapter=PandaSPI()
    assert adapter.serial=="SPI-TEST" and adapter.mode==0
    adapter.close()
    assert ("spi_close",) in calls and adapter.lease is None
