# Architecture and extension boundaries

## Components

- `server.py`: loopback-only FastAPI service, typed fixed-action API, local Host/Origin checks, HttpOnly SameSite session, no CORS, bounded body import, CSP. UI bootstrap issues a per-process credential. API writes require the cookie and `X-Lab-Request: 1`.
- `engine.py`: one acquisition owner, a serialized control/transaction lock and independent receive worker. One consumer pumps Panda; diagnostic replies are routed into a bounded queue while all traffic is recorded/decoded. Source changes, stop, reads and clears cannot interleave.
- `transport.py`: standalone USB claim without invoking the ordinary Panda constructor. Packet compatibility and initial silent/no-output state checked before configuration. Bounded 20 ms USB reads; disengaged heartbeats and safety health checks. No SPI, remote process takeover, flash, reset, CAN-FD or bitrate mutation. Replay parser cannot create a live source.
- `uds.py`: fixed service constructors, single-frame requests, ISO-TP multi-frame responses up to 4095 bytes, response service/subfunction/DID/routine correlation, sequence checking, flow control, NRC parsing, bounded pending timeout and 8-second absolute transaction cap. Manufacturer positive data is retained raw.
- `safety.py`: fresh live bus-0 observations plus separate expiring operator attestations. Single-use clear challenges bind acquisition, source, ECU pair and scan timestamp. Clear request is always `14 FF FF FF`.
- `decoder.py`: cantools decoding, explicit DBC-to-bus map, original-file preservation and documented in-memory repair, last 300 graph samples per signal. Guard reads numeric raw values rather than display labels.
- `store.py`: SQLite WAL acquisitions, raw frames, source/direction, diagnostic/audit events and persistent candidate/mapping settings. SQL values are parameterized. Exports stream frame batches rather than loading a whole database into memory.
- `catalog.py`: evidence-backed names, confidence labels and disabled actuation registry. Dynamic API/UI profiles cannot enable live write permissions.
- `static/`: framework-free responsive UI; local assets only. Dynamic source/profile/recording values are escaped; raw transaction output uses textContent.

## Execution boundary

1. Browser selects a fixed named action; there is no arbitrary payload API.
2. Server constructs exact standard request bytes. Dry-run stops here and writes an audit event.
3. Manufacturer routine/session actions are rejected for execution regardless of UI settings or host flags.
4. Active read requires demo or live Panda; replay is never a diagnostic transport.
5. Live requires host permission, armed diagnostic mode, no quarantine/fault, fresh live Park/speed and car-off/secured/exclusive-ownership attestations. Profile transport evidence must be host-reviewed.
6. Clear additionally requires host write permission, a verified ECU-specific clear profile, a current saved scan and a single-use matching confirmation. Snapshot is committed before transmit.
7. ISO-TP guard is checked before request and flow-control sends and throughout receipt. Unexpected response, timeout or guard loss quarantines the transaction and disarms; ambiguous writes are never automatically retried.
8. Firmware safety rejection is recorded, trips quarantine and prevents success inference. A normal negative UDS response reports the ECU's rejection without treating it as a successful operation.

No hardware motion/action can be enabled simply by adding a catalog row or setting a browser checkbox. Adding an actuation requires an exact independently verified command schema, vehicle/software identity, verified prerequisites and telemetry validity, timing/cancellation, complete ECU session and Finish Service lifecycle, audited failure/cleanup behavior, dedicated server allowlist code and corresponding tests. Observed `71`/`6E` acknowledgments and terminal byte 02 alone are insufficient evidence.

## Diagnostic session handling

The app manages acquisition ownership and transmit permissions. It deliberately **does not claim to manage live manufacturer service state**. It neither silently enters session 03 to read nor silently executes 0309 afterward. Default/extended-session request plans and the captured 0309 cleanup sequence can be inspected. Sessions remain inspection-only until a verified lifecycle exists; a default-session request is not equated with Finish Service. Replay, device reconnection and host restart do not prove ECU session state.

This avoids repeating the incomplete historical height workflow. If EAS requires session changes for a read on the actual vehicle, that scan may be rejected and remain unavailable until its lifecycle is established. There is no unsafe bypass to force coverage.

## Local API

Open `/` first to receive the session cookie. POST examples also require `X-Lab-Request: 1`. A separate client can use a cookie jar, but it cannot bypass the same permission/interlock checks.

| Method / path | Purpose |
|---|---|
| GET `/api/catalog`, `/api/state` | Evidence/capabilities and source-labeled current state |
| GET `/api/devices` | Descriptor-only USB inventory |
| POST `/api/source` | `mode: demo/panda/replay`, optional serial or recording text |
| POST `/api/stop`, `/api/disarm` | Stop/finalize or disarm transmit |
| POST `/api/arm` | Three explicit attestations; host flag/live guard still required |
| POST `/api/mapping` | Complete `{0,1,2}` bus decoder map; resets interlocks |
| POST `/api/replay` | Pause, speed or frame-index seek; no CAN output |
| POST `/api/profiles` | Add an unverified candidate; cannot replace existing profiles |
| POST `/api/discover` | Up to 16 explicit profile keys, defaults dry-run |
| POST `/api/diagnostic` | `ecu`, fixed `action`, optional identifier, `dry_run` defaults true |
| POST `/api/clear/prepare` | Issue a 30-second ECU/scan/acquisition-bound confirmation |
| POST `/api/marker` | Record an operator observation |
| GET `/api/history`, `/api/history.csv` | Bounded graph history / export for a signal key |
| GET `/api/runs`, `/api/events`, `/api/events.json` | Acquisitions and last 200 audit events |
| GET `/api/runs/{id}/frames?format=jsonl/csv` | Streaming raw export |
| GET `/api/runs/{id}/report?format=json/txt` | Diagnostic evidence report |

## Known implementation limits

- Live ECU discovery needs verified physical pairs. Automatic address-range sweeps and inferred TX offsets are intentionally absent.
- Classic CAN only; no 29-bit ISO-TP addressing, CAN-FD, multi-frame outbound requests, security unlocking, firmware writes or transport encryption to remote adapters.
- UDS contains no transaction nonce. Serialized requests, response correlation and quarantine reduce misassociation, but a delayed identical unsolicited response cannot be perfectly distinguished. Do not use the adapter with another diagnostic client.
- There is no independent OS watchdog process and no proof of ECU recovery after process loss. Panda heartbeat fallback, final-silent attempts and interrupted-run metadata are separate safeguards.
- DBC checksum/counter validation and the precise QF validity contract are not proven. Car-off and work-area safety remain operator attestations. Interlocks are conservative software gates, not a certified safety controller.
- Signal graph history is bounded and resident in memory; raw frames are permanent. Source changes/seeks clear graph history. Offline re-decoding occurs through recording import, not a continuously stored decoded-signal table.
- SQLite has no automatic retention quota. Frame export during acquisition is a growing stream, not a frozen snapshot; finalize before archival exports.
- Imported `transport_verified` / `clear_verified` flags are a trusted host configuration decision requiring genuine ECU-specific evidence. The software validates schema and citation presence, not the scientific truth of a citation.
- Browser/session isolation is intended for local use. No multi-user account/role system or network-facing deployment is included.

Development verification is software-only. Device API tests use mocks and do not establish USB performance, CAN connectivity, firmware acceptance or vehicle safety.
