"""Conservative capability registry; observed acknowledgments do not verify safety."""
from pathlib import Path
import hashlib
import ast

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
REFERENCES = PACKAGE / "references"

EAS = {"key": "eas", "name": "Continental EAS", "tx": 0x64B, "rx": 0x65B,
       "bus": 0, "confidence": "captured bus-0 transport pair", "clear_verified": False,
       "evidence": "CONTINENTAL-EAS-HANDOFF.md", "session": "unknown; reads do not infer state"}

ROUTINES = [
    {"id": "0305", "name": "Level to Height", "confidence": "captured, labeled Toolbox actions",
     "meaning": "03 Low · 04 Standard · 05 High · 06 Very High", "enabled": False,
     "reason": "Abnormal suspension behavior remains unresolved; physical safety unverified."},
    {"id": "030A", "name": "Air Mass", "confidence": "captured, labeled Toolbox action",
     "meaning": "04 8B matched 116.3 bar·litre once; scaling is provisional", "enabled": False,
     "reason": "Measurement starts a manufacturer routine; full safe workflow unverified."},
    {"id": "0309", "name": "Exit / Finish Service", "confidence": "user identification; captured follow-up sequence",
     "meaning": "User requires cleanup after commands. Scope for standalone reads remains unresolved.",
     "enabled": False, "reason": "Not independently verified as a safe recovery; no automatic execution."},
    {"id": "0315", "name": "Unknown routine", "confidence": "start/results/stop captured",
     "meaning": "Earlier Air Mass attribution superseded by 030A", "enabled": False,
     "reason": "Meaning unknown."},
]
DIDS = [
    {"id": "0101", "name": "Toolbox preflight", "confidence": "read observed; NRC 31 captured", "writable": False},
    *[{"id": f"A03{i}", "name": f"Calibration value · {corner} provisional",
       "confidence": "write acknowledged; corner mapping and conversion unproven", "writable": False}
      for i, corner in enumerate(["FL", "FR", "RL", "RR"])],
    {"id": "A034", "name": "Calibration-related final write", "confidence": "value 01 acknowledged; commit meaning unknown", "writable": False},
    {"id": "F190", "name": "VIN (standard DID)", "confidence": "UDS convention; support on each ECU unverified", "writable": False},
]
BLOCKED = ["Height changes", "Inflate / deflate", "Compressor", "Cycle", "Calibration writes",
           "Steering / EPAS", "Brake / throttle / pedal", "ECU reset", "Security access",
           "Firmware programming", "Raw CAN transmit"]

def manifest():
    return [{"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
             "bytes": p.stat().st_size, "use": "reference only; never imported" if p.suffix == ".py" else "decoder/evidence"}
            for p in sorted(REFERENCES.iterdir()) if p.is_file()]

def reference_builders():
    """Inventory source without importing/executing driving control builders."""
    path = REFERENCES / "teslacan.py"
    tree = ast.parse(path.read_text())
    return [{"name":node.name,"line":node.lineno,"arguments":[a.arg for a in node.args.args],
             "description":ast.get_docstring(node) or "No verified diagnostic meaning supplied",
             "enabled":False,"reason":"Driving/control reference only; not a verified service action"}
            for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith("create_")]
