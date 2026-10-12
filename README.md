# Model S Lab

## Focused update: SPI, filters and public ECU leads

The source picker now includes **local Comma SPI** alongside USB. SPI requires the server to run on the Linux Comma host, compatible Panda libraries, openpilot manager/pandad independently stopped, and an already silent/no-output device. It refuses process takeover, maintains an exclusive app lease, checks for competing processes, and uses the same guarded diagnostic path. This is not a Mac-to-Comma remote transport. No SPI hardware has been tested. USB behavior remains unchanged.

Live signal filters now include bus, measurements/status/flags/counters/other types, and text search across message, signal, DBC and unit. Type grouping is derived from DBC metadata; counters/checksums use names. Every observed decoded signal remains available with filters cleared; all supplied definitions are searchable in Evidence library, and unknown raw frames remain recorded.

See `PUBLIC-ECU-LEADS.md` for published TPMS `64F→65F` and battery-internal legacy BMS `602→612` leads. Neither is verified for this vehicle's diagnostic connector or mapped to a Panda bus; neither enables new writes. Earlier statements below excluding SPI apply to the original USB-only version and are superseded by this update.

A local diagnostic and monitoring workspace for a **2013 Tesla Model S P85, pre-AP**. Python host server, responsive browser UI, standalone USB Panda capture, reference DBC decoding, replay, diagnostic inspection, persistent recordings and evidence reports.

**Starts offline. No hardware was tested during development. No suspension, steering, pedal, brake, calibration, reset or programming actuation is enabled.** Manufacturer routines and session changes are inspectable as audited plans. Historical acknowledgments are not treated as proof that replaying them is safe.

## Start on this computer

Use Python 3.11 or newer. Open Terminal in this project folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m teslalab.server
```

Open **http://127.0.0.1:8765**. On macOS, `Start.command` performs the same first-time setup and launches the app. Initial dependency installation requires internet access. After installation, demo, replay and the UI work offline; there are no remote fonts, analytics or CDN scripts.

For development or an installed command:

```sh
.venv/bin/python -m pip install -e .
.venv/bin/model-s-lab
```

The server binds to loopback only. It does not expose a LAN listener. Port and database location can be selected:

```sh
.venv/bin/python -m teslalab.server --port 8766 --data-dir ./data
```

The default database is `data/lab.sqlite3` relative to the working folder. Keep the database, WAL and SHM files together while running; stop the app before copying the database. Recordings contain vehicle telemetry and may contain identifiers returned by DIDs. They remain local unless you export/share them yourself.

## Explore without hardware

1. Select **Explore with demo data**. Synthetic parked traffic produces a changing torque graph and labeled diagnostic responses.
2. Open **Live signals** to choose any decoded signal, inspect raw frames and export the visible graph samples.
3. In **ECU & fault scan**, read EAS DTCs. Demo returns three explicitly synthetic records. **Review clear** requires a preserved scan and an exact phrase; its challenge expires after 30 seconds and cannot be reused.
4. Use **UDS inspector** for DID reads or dry-run plans. The demo VIN response is deliberately `SYNTHETIC-NOT-A-VIN`.
5. Import `examples/synthetic-parked.jsonl` using the Replay source. Playback, pause/resume, speed and seek operate locally. **Replay never transmits frames, including recorded TX frames.**

Each source starts a new SQLite acquisition automatically. Switching/stopping finalizes it. Add observation markers and export raw JSONL/CSV, full JSON reports, or plain-text reports (`/api/runs/<id>/report?format=txt`). The recordings page also exports the last 200 audit events, including offline dry-runs and rejected API operations. Full per-acquisition events remain in its report.

## Standalone USB Panda / Red Panda

Install the USB extras only when needed:

```sh
.venv/bin/python -m pip install -r requirements-usb.txt
```

The file pins the official Panda and opendbc repositories used to verify the adapter API. **Your Panda firmware must match its Python packet interfaces.** The app checks versions and refuses mismatches; it never flashes, resets, changes CAN-FD settings or selects all-output mode. A matching existing checkout can instead be supplied as the parent directory containing the `panda` package:

```sh
.venv/bin/python -m teslalab.server --panda-repo /path/to/matching/checkout-parent
```

In **Live signals**, choose standalone USB Panda, enter its serial if multiple devices are connected, then start the source. **Check USB devices** enumerates descriptors without opening a CAN session. A compatible external Panda must already be in silent/no-output mode with controls disabled. The app claims the USB interface exclusively and refuses internal Comma hardware or transmit-capable/shared takeover. It does not stop openpilot processes or use SSH/SPI.

Passive capture retains installed bus speeds. Historical EAS captures used 500 kbit/s, but actual wiring, logical buses and bitrates must be established for your adapter; the app does not guess or change them. Adapter shutdown selects silent mode and restores its initial power-save setting, checking that silent mode took effect. It deliberately leaves the final mode silent rather than restoring a transmit mode. A restoration failure is reported and audited.

Panda USB transfer timestamps are **host receipt times**, not hardware arrival times. Transmit requests, echoes and firmware rejections are separate directions. Echo buses 128–130 map to physical buses 0–2 and never feed interlocks or signal decoding; rejected frames 192–194 are marked separately. USB errors abort capture, block requests and attempt to select silent mode. Firmware heartbeat fallback is an additional layer, not a guarantee of ECU cleanup after a crash.

## Active diagnostic reads

Passive receive works without transmit permission. To permit active reads, restart explicitly with:

```sh
.venv/bin/python -m teslalab.server --enable-diagnostics
```

This does not arm the adapter. In **Permissions & safety**, the operator must attest car off/not ready to drive, secured vehicle and exclusive adapter ownership. Arming is limited to 60 seconds and also requires:

- Fresh live **Panda RX** on physical bus 0, decoded using the supplied pre-AP DBC.
- `0x155 / ESP_vehicleSpeed` in `[0, 0.36)` kph with quality value 1.
- `0x118 / DI_gear` equal to 1 (DBC Park) and `DI_vehicleSpeed` within ±0.23 mph.
- Both speed/gear observations at most 0.5 seconds old; no quarantined transport or capture fault.

Quality value 1 is a conservative required value, **not independently validated as a complete validity contract for this ECU software**. Car-off state is an operator attestation; no proven ignition/ready-state signal is invented. Validate the telemetry and DBC applicability on the vehicle before enabling active use. If the vehicle stops emitting those signals when powered off, arming remains blocked; no stale-state override exists.

The adapter uses ELM327 diagnostic safety mode 3, parameter 1, rather than all-output. The host only constructs fixed services and checks the guard before every request/ISO-TP flow-control frame. It permits `19 02 FF` fault reads and `22 <DID>` raw DID reads for verified transport profiles. Live DID support/scaling is unknown until observed; raw bytes and negative responses are preserved. There is no raw-service endpoint, arbitrary CAN transmitter, automatic retry, implicit extended-session entry, TesterPresent keepalive or automatic Finish Service routine.

EAS reads are attempted in the ECU's existing/default state; the app does **not** enter session 03 to force support. If the ECU rejects a read because of session conditions, the rejection is reported. Routine results and session-control requests are dry-run inspection only, because their complete safe lifecycle is not verified. Adapter permissions, recordings and UDS diagnostic sessions are distinct concepts.

## ECU discovery and DTC clear

Only the EAS physical pair is supplied as captured vehicle-specific transport evidence: **bus 0, `0x64B → 0x65B`**. No complete ECU address map was available. Discovery sends a bounded `19 02 FF` request to selected explicit profiles (maximum 16); it never sweeps arbitrary control addresses or functional broadcast `0x7DF`. Negative responses count as responding ECUs without implying support for writes. Passive UDS-like responder candidates are heuristics with unknown request address/identity.

UI-added candidate profiles persist, but cannot self-grant live permissions. `examples/ecu-profiles.json` is deliberately **unverified** and supplies no Tesla-specific gateway mapping. For additional independently established ECU pairs, the host operator can review a JSON profile file and supply `--profiles <file>`. Profiles have `key`, `name`, integer `tx`, `rx`, `bus`, Boolean `transport_verified`, and an evidence citation. A verified-clear profile additionally requires Boolean `clear_verified` and `clear_evidence` documenting the tested **exact `14 FF FF FF`** request on that ECU/software. Merely setting a Boolean is not evidence; the host file is a trusted configuration boundary. UI requests cannot set these flags, and the bundled EAS profile cannot be overridden.

Live clear requires **both** `--enable-diagnostics --enable-clear`, a verified transport/clear profile, live interlocks, a scan from that ECU/acquisition within 60 seconds, and the exact 30-second single-use confirmation phrase. The prior DTC response is committed before the write. A new scan, source change, stop, disarm or expired challenge invalidates permission. A clear acknowledgment does not prove fault repair; scan again afterward. **EAS clear remains disabled live because the available evidence does not verify it.** Demo implements the complete confirmation flow for testing.

## Continental EAS: evidence and unknowns

| Item | Supported association | Boundary in this build |
|---|---|---|
| `64B → 65B`, bus 0 | Captured diagnostic transport | Guarded fault/DID reads; software applicability pending |
| Routine `0305` | Labeled Level to Height; 03 Low, 04 Standard, 05 High, 06 Very High | Dry-run only; unresolved abnormal suspension behavior |
| Routine `030A` | Labeled Air Mass; `04 8B` matched 116.3 bar·litre once | Scaling provisional; start disabled |
| Routine `0309` | User identifies Exit / Finish Service; captured start/poll/stop follow-up | User identification distinguished from independently verified meaning; no execution |
| Routine `0315` | Start/results/stop observed | Meaning unknown; older Air Mass attribution superseded |
| DID `0101` | Toolbox preflight read observed; NRC 31 seen | Support unverified in current ECU state |
| DIDs `A030–A033` | Calibration-related writes acknowledged historically | Corner mapping/units/conversion provisional; no write service |
| DID `A034` | Final value 01 acknowledged historically | Commit/validity meaning unknown; disabled |
| Result byte `02` | Observed polling-to-terminal transition | Never labeled physical success |
| Odin | User's working explanation | No defining transaction evidence; not a diagnosed root cause |

The October 11 correction supersedes older notes calling 0309 wholly unidentified. The captured cleanup sequence `10 03; 31 01 03 09; 31 03 03 09; 31 02 03 09` is shown as evidence in dry-run routine plans. Its required scope after standalone reads remains unresolved. Restoring Panda mode or default diagnostic session is not equivalent to executing Finish Service, and neither is treated as a verified repair.

Prior custom Standard tests were followed by unresolved front-low/calibration symptoms. Inflate/deflate, compressor, Cycle, calibration conversion, height/pressure DID scaling, routine side effects and safe cleanup have not been established. Therefore **zero physical actuations are enabled**. This is a usable monitoring/diagnostic implementation with an explicit capability boundary, not a claim of full Tesla Toolbox coverage.

DTC identifiers are three bytes, with the status byte stored separately. Only status bits included in the ECU availability mask are named. `confirmedDTC` does not itself prove an active fault or assign a component meaning. Historical snapshots are retained as references and never presented as current scans.

## DBCs and uploads

The original `tesla_preap.dbc`, `tesla_powertrain.dbc` and `teslacan.py` are in `teslalab/references/`, alongside the EAS handoff, superseding correction and October 6 historical DTC evidence. Reports include their SHA-256 hashes. **`teslacan.py` is never imported**; its control builders do not authorize diagnostic actuations.

Both DBCs load: 48 pre-AP and 6 powertrain message definitions. One original pre-AP line is truncated: `VAL_ 921 DAS_lssState ... 2` without a terminator. The decoder omits that exact incomplete enumeration **in memory**, records a warning, and infers no missing choices. Original files remain unchanged. Compatibility loading uses `strict=False`; definitions may contain overlapping research fields. Bad-length/multiplexor decode errors are counted. A DBC definition is not proof of vehicle applicability or a checksum/validity verifier.

Default decoder routing is pre-AP on buses 0/2 and powertrain on bus 1, an explicit assumption editable in the UI. Changing routing resets signal history and interlocks and persists the mapping. Evidence library includes a searchable browser of every message/signal, bit layout, scale, offset and unit.

Replay accepts exported JSONL, earlier `frames: [[address, hex, bus], ...]` JSONL batches and classic candump `(timestamp) can0 ID#HEX` lines. Metadata rows are skipped and counted. Limit: 24 MB / 150,000 frames per import, classic CAN up to 8 bytes. Original timestamps and order are preserved. Playback gaps are capped at two seconds before the selected speed factor; replay is a visualization, not a timing-accurate bus transmitter. Seeks clear graph history and append a marker to the replay acquisition. Replayed TX records stay historical records.

## Tests and verification

```sh
.venv/bin/python -m pytest -q
```

**52 tests passed** using Python 3.12.13 and the pinned runtime. Coverage includes DTC status masks, segmented responses, sequence errors, pending/timeout bounds, guard loss, replay source spoofing, freshness, confirmation expiry/binding/reuse, origin/session enforcement, write rejection, export/replay, persistent candidates, interrupted recordings, and a **mocked USB/Panda API**. Browser checks exercised mobile and desktop layouts, changing graphs and the synthetic read/confirmed-clear flow. A Starlette/httpx deprecation warning affects the test harness, not the app; it is recorded rather than hidden.

Direct libusb enumeration was attempted during development and found **no attached Panda device**. No CAN command was sent to a vehicle. Hardware performance, firmware compatibility, ECU coverage, observed car-off telemetry and real diagnostic results still require vehicle validation. Raw recording has no automatic retention/deletion limit: monitor disk space and stop/export recordings as needed. Commit batching is up to 200 frames or one second; a hard process/OS crash can lose the uncommitted tail. Unfinalized recordings are marked interrupted on next startup; device/ECU cleanup is never inferred from restart.

## Implementation / primary sources

See `ARCHITECTURE.md` for extension boundaries and API details. The adapter was checked against [official Panda Python](https://github.com/commaai/panda/blob/92eb565169fd553f4dfaf508c1a3f8dbc14fbfbf/python/__init__.py) and [official diagnostic safety filter](https://github.com/commaai/opendbc/blob/229dc7062d8986b4f954c7c97875b4ffd0044d12/opendbc/safety/modes/elm327.h). Generic diagnostic encoding/status conventions were cross-checked with [udsoncan service documentation](https://udsoncan.readthedocs.io/en/v1.17.1/udsoncan/services.html). The historical Tesla Finish Service lead is retained in the source handoff; it is not treated as a direct routine-ID specification.

Original uploads and research retain their original ownership/license terms. The project does not execute or relicense the uploaded reference code.
