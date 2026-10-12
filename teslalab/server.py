import argparse
from contextlib import asynccontextmanager
import csv
import io
import json
from pathlib import Path
import secrets
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from .catalog import ROOT, PACKAGE, REFERENCES, manifest
from .engine import Lab
from .transport import usb_inventory

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Source(Input):
    mode: Literal["demo","panda","replay"]
    interface: Literal["usb","spi"] = "usb"
    serial: str | None = Field(default=None,max_length=80)
    text: str | None = Field(default=None,max_length=24_000_000)
    speed: float = Field(default=1,ge=.1,le=20)

class Diagnostic(Input):
    ecu: str = Field(default="eas",max_length=40)
    action: Literal["read_dtc","clear_dtc","read_did","routine_results","routine_start","session"]
    identifier: str | None = Field(default=None,pattern="^[0-9A-Fa-f]{2,4}$")
    parameter: str | None = Field(default=None,pattern="^[0-9A-Fa-f ]{0,8}$")
    dry_run: bool = True
    token: str | None = Field(default=None,max_length=100)
    phrase: str | None = Field(default=None,max_length=100)

class Arm(Input):
    car_off: bool = False
    secured: bool = False
    exclusive: bool = False

class ReplayControl(Input):
    index: int | None = Field(default=None,ge=0)
    paused: bool | None = None
    speed: float | None = Field(default=None,ge=.1,le=20)

class Profile(Input):
    key: str = Field(pattern="^[a-z0-9_-]{1,40}$")
    name: str = Field(max_length=80)
    tx: int
    rx: int
    bus: int = Field(ge=0,le=2)

class Discovery(Input):
    keys: list[str] = Field(min_length=1,max_length=16)
    dry_run: bool = True

class Mapping(Input):
    mapping: dict[int,str]

class Marker(Input):
    text: str = Field(min_length=1,max_length=1000)

def create_app(data_dir=None, enable_diagnostics=False, enable_clear=False, profiles_path=None, allowed_hosts=None):
    lab = Lab(data_dir or Path.cwd() / "data",enable_diagnostics,enable_clear,profiles_path)
    credential = secrets.token_urlsafe(32)
    hosts = allowed_hosts or {"127.0.0.1","localhost","::1"}
    @asynccontextmanager
    async def lifespan(app):
        yield
        lab.close()
    app = FastAPI(title="Model S Lab",lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.lab = lab

    @app.middleware("http")
    async def local_only(request, call_next):
        host = urlparse("http://"+request.headers.get("host","")).hostname
        if host not in hosts: return JSONResponse({"error":"Untrusted host"},status_code=403)
        origin = request.headers.get("origin")
        if origin and (urlparse(origin).hostname != host or urlparse(origin).netloc != request.headers.get("host")):
            return JSONResponse({"error":"Cross-origin request rejected"},status_code=403)
        if request.headers.get("sec-fetch-site") in ("cross-site","same-site"):
            return JSONResponse({"error":"Cross-site request rejected"},status_code=403)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.cookies.get("lab_session",""),credential):
                return JSONResponse({"error":"Open the local dashboard first"},status_code=403)
            if request.method != "GET" and request.headers.get("x-lab-request") != "1":
                return JSONResponse({"error":"Dashboard request header required"},status_code=403)
            if request.headers.get("content-length"):
                try: length = int(request.headers["content-length"])
                except ValueError: return JSONResponse({"error":"Invalid content length"},status_code=400)
                if length < 0: return JSONResponse({"error":"Invalid content length"},status_code=400)
                if length > 25_000_000: return JSONResponse({"error":"Import exceeds 25 MB"},status_code=413)
            if request.method != "GET":
                total = 0
                chunks = []
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > 25_000_000: return JSONResponse({"error":"Import exceeds 25 MB"},status_code=413)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request,exc):
        lab.audit("api_denied",{"path":request.url.path,"reason":str(exc)})
        return JSONResponse({"error":str(exc)},status_code=400)

    @app.exception_handler(RuntimeError)
    async def runtime_error(request,exc):
        lab.audit("runtime_error",{"path":request.url.path,"reason":str(exc)})
        return JSONResponse({"error":str(exc)},status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        lab.audit("api_invalid_input",{"path":request.url.path})
        return JSONResponse({"error":"Invalid request fields or service. This endpoint accepts only the documented allowlist."},status_code=422)

    @app.exception_handler(ImportError)
    async def import_error(request,exc): return JSONResponse({"error":"Panda library unavailable. Install the matching pinned USB dependencies; see README."},status_code=400)

    @app.get("/")
    def index():
        response = FileResponse(PACKAGE / "static" / "index.html")
        response.set_cookie("lab_session",credential,httponly=True,samesite="strict")
        return response

    app.mount("/static",StaticFiles(directory=PACKAGE / "static"),name="static")

    @app.get("/api/state")
    def state(): return lab.state()

    @app.get("/api/catalog")
    def catalog(): return lab.catalog()

    @app.get("/api/references/{name}")
    def reference(name:str):
        if name not in {r["name"] for r in manifest()}: raise ValueError("Unknown reference file")
        return FileResponse(REFERENCES / name,media_type="application/octet-stream",filename=name)

    @app.get("/api/devices")
    def devices(): return usb_inventory()

    @app.post("/api/source")
    def source(body:Source): return lab.start(**body.model_dump())

    @app.post("/api/stop")
    def stop(): lab.stop(); return {"stopped":True}

    @app.post("/api/arm")
    def arm(body:Arm): return lab.arm(**body.model_dump())

    @app.post("/api/disarm")
    def disarm(): lab.disarm(); return {"armed":False}

    @app.post("/api/replay")
    def replay(body:ReplayControl): lab.replay_control(**body.model_dump()); return {"ok":True}

    @app.post("/api/mapping")
    def mapping(body:Mapping): lab.set_bus_map(body.mapping); return {"ok":True}

    @app.post("/api/marker")
    def marker(body:Marker):
        if lab.mode == "offline": raise ValueError("Start an acquisition before adding a marker")
        lab.audit("operator_marker",{"text":body.text,"source":lab.mode})
        return {"saved":True}

    @app.post("/api/profiles")
    def profile(body:Profile): return lab.add_profile(body.model_dump())

    @app.post("/api/discover")
    def discover(body:Discovery): return lab.discover(**body.model_dump())

    @app.post("/api/diagnostic")
    def diagnostic(body:Diagnostic):
        args = body.model_dump(); args["profile_key"] = args.pop("ecu")
        return lab.diagnostic(**args)

    @app.post("/api/clear/prepare")
    def prepare(body:dict):
        if set(body) != {"ecu"}: raise ValueError("Specify ECU only")
        return lab.prepare_clear(body["ecu"])

    @app.get("/api/history")
    def history(key:str): return lab.history(key)

    @app.get("/api/history.csv")
    def signal_csv(key:str):
        rows = lab.history(key); buf = io.StringIO(); writer = csv.writer(buf)
        writer.writerow(["timestamp","value"]); writer.writerows(rows)
        return Response(buf.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=signal.csv"})

    @app.get("/api/runs")
    def runs(): return lab.store.runs()

    @app.get("/api/events")
    def events(): return lab.store.events()

    @app.get("/api/events.json")
    def events_download():
        return JSONResponse(lab.store.events(),headers={"Content-Disposition":"attachment; filename=lab-audit.json"})

    @app.get("/api/runs/{run}/report")
    def report(run:str, format:Literal["json","txt"]="json"):
        data = lab.store.report(run); data["evidence_manifest"] = manifest_for_report(lab)
        if format == "txt":
            lines=["MODEL S LAB — DIAGNOSTIC EVIDENCE REPORT", "Vehicle target: 2013 Tesla Model S P85 pre-AP",
                   "Source: " + data["run"]["mode"].upper(),"Acquisition: " + run,
                   "Frames recorded: " + str(data["frame_count"]),"Hardware tested by developer: NO", "", "LIMITATIONS"]
            lines += ["- " + item for item in data["limitations"]]
            lines += ["", "EVENTS (timestamps are Unix seconds)"]
            for event in data["events"]:
                lines += [f"{event['ts']:.3f}  {event['kind']}",json.dumps(event["data"],indent=2)]
            lines += ["", "EVIDENCE, CONFIDENCE & PERMISSIONS",json.dumps(data["evidence_manifest"],indent=2)]
            return Response("\n".join(lines),media_type="text/plain",headers={"Content-Disposition":"attachment; filename=diagnostic-report.txt"})
        return JSONResponse(data,headers={"Content-Disposition":"attachment; filename=diagnostic-report.json"})

    @app.get("/api/runs/{run}/frames")
    def frames(run:str, format:Literal["jsonl","csv"]="jsonl"):
        lab.store.report(run)
        return StreamingResponse(lab.store.export(run,format=="csv"),media_type="text/plain" if format=="jsonl" else "text/csv",
                                 headers={"Content-Disposition":f"attachment; filename=can-recording.{format}"})
    return app

def manifest_for_report(lab):
    cat = lab.catalog()
    return {k:cat[k] for k in ("references","routines","dids","permissions","bus_map")}

def main():
    parser = argparse.ArgumentParser(description="Model S Lab · loopback-only local server")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--data-dir",default=str(Path.cwd() / "data"))
    parser.add_argument("--enable-diagnostics",action="store_true",help="Allow explicit, interlocked live read requests")
    parser.add_argument("--enable-clear",action="store_true",help="Allow clear only for ECU profiles with verified clear evidence")
    parser.add_argument("--profiles",help="Host-reviewed JSON ECU profiles; UI candidates cannot grant verification")
    parser.add_argument("--panda-repo",help="Parent checkout containing the matching panda package")
    args = parser.parse_args()
    if args.panda_repo:
        import sys
        sys.path.insert(0,str(Path(args.panda_repo).resolve()))
    import uvicorn
    print(f"Model S Lab: http://127.0.0.1:{args.port} · starts offline · no hardware tested")
    uvicorn.run(create_app(args.data_dir,args.enable_diagnostics,args.enable_clear,args.profiles),host="127.0.0.1",port=args.port,access_log=False)

if __name__ == "__main__": main()
