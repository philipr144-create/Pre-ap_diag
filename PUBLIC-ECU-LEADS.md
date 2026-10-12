# Public diagnostic address leads

These are independently published leads, not verified addresses/bus mappings on this 2013 car. They are not automatically enabled for live requests or writes.

| ECU / context | Request → response | Source / limitation |
|---|---|---|
| Baolong TPMS, Model S | `64F → 65F` | [OVMS Model S driver](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/blob/master/vehicle/OVMS.V3/components/vehicle_teslamodels/src/vehicle_teslamodels.cpp), request at line 421, response handler at line 329. Source uses chassis CAN; Panda bus mapping unknown. Applicability depends on installed TPMS hardware. |
| Legacy 85/90 pack BMS, battery-internal CAN | `602 → 612` | [PiCanScanMyTesla pack monitor](https://github.com/jetpax/PiCanScanMyTesla/blob/main/teslamon.py), lines 35–38. Battery-internal access differs from vehicle diagnostic-port access. Support on this car unverified. |

Do not infer that standard DTC clear is valid on the legacy BMS: the public pack implementation describes manufacturer routine-based faults/clearing, not a general verified `14 FF FF FF` workflow. No security-unlock bytes, BMS clears or TPMS programming actions are imported or enabled here.

Public CAN message IDs used for broadcasts are distinct from UDS diagnostic request/response pairs. The two supplied DBCs do not constitute a complete diagnostic ECU map.
