> Current correction: the user identifies 0x0309 as Exit / Finish Service, required after commands. See [current protocol notes](continental_diag/CURRENT-PROTOCOL-NOTES.md), including the Odin hypothesis and app implementation gap. Older findings below are historical.

# Continental EAS — consolidated technical handoff

Updated 10 October 2026. Consolidated from the user’s Toolbox observations, passive CAN captures, custom-run transaction logs, and referenced documentation. Read confidence qualifiers literally: accepted UDS requests do not prove successful physical leveling, calibration validity, or absence of persistent side effects.

## Current state and corrected chronology

- System is reported by the user/Toolbox as Continental EAS. Exact vehicle VIN/model year and ECU hardware/software identifiers have not been established in this reference.
- User reports Cycle lowered the front and raised the rear, and had done that previously without a lasting problem. The persistent front-low condition followed the custom Standard-height attempt. Do not attribute the fault to Cycle merely because it occurred first.
- Two custom Standard tests were executed: first with the captured but unidentified follow-up 0309, second without it. The second produced brief front movement. Both returned the observed terminal status 02; both restored Panda/openpilot. These are protocol results, not verification of correct physical Standard height.
- Subsequent Toolbox Standard → High → Standard traffic matched the target commands and included 0309 after each operation.
- User reports front remains dumped, leveling lowers front and raises rear, FR reading 302 mm versus other corners 159–190 mm, and calibration only reports Failed. Exact signal definition remains unknown. Red/yellow warning history and DTCs are recorded below.
- No successful recovery or Finish Service execution/result has been reported. User has found the Finish Service action in Toolbox.
- Current local live runners are disabled. Earlier test scripts were uploaded to /tmp on Comma; do not use older copies. The cause of the abnormal behavior and calibration rejection remains unresolved.

## Capture and device context

- Comma 3X: comma@192.168.0.23; internal SPI Panda serial 17001c001051333038363231; recorded firmware version DEV-282fae70-DEBUG. Reachability has been intermittent.
- Fork branch at inspection: repair/nav-signal-arbitration. Existing work was preserved. No Panda flashing performed.
- Installed Panda library: /data/openpilot/panda; runtime /usr/local/venv/bin/python. Default Python lacked usb1.
- Inspected lifecycle: launcher PID 3776 (launch_chffrplus.sh), managers 32943/34222, Python pandad 37805, native pandad 39814; tmux session comma. These are historical PIDs, not guaranteed current.
- Toolbox required IsOnroad=1/Service Plus during parked work. Software onroad state does not prove the vehicle is moving or parked.
- Capture acquires the SPI lock, suspends the inspected process tree, bypasses Panda constructor bitrate/CAN-FD resets, selects silent safety mode, keeps power save off, and sends Panda disengaged heartbeats every 250 ms. It records to Comma with host-receipt timestamps, not hardware arrival timestamps; markers include Mac click times.
- State/recovery file: /tmp/napcan-suspended.json. Original safety mode 37, parameter 1, power-save state restored before resuming the same process identities. Independent watchdog and recovery script are present. Recording limit approximately 19 minutes; watchdog approximately 20 minutes.
- Custom active tests selected Panda elm327 safety mode (3), parameter 1, and sent requests only to 0x64B on bus 0. They did not use allOutput. Panda safety mode is distinct from EAS diagnostic session 03.
- Raw logs contain bus 0 and 1 traffic. Bus 128 entries in active tests are transmit echoes, not another physical chassis bus. Suspension diagnostic visibility is proven only for the observed pair on bus 0. Source code/initial health reported 500 kbit/s CAN configuration.
- Full log downloads repeatedly timed out. Diagnostic extracts match the logs’ own final counts, but increasing SPI-error counters prevent a guarantee of complete physical-network capture. RX-overflow counters did not increase in the analyzed recordings.

## Executed custom transaction sequences

First attempt: 10 03; 31 01 03 05 04; repeated 31 03 03 05; 31 02 03 05; 10 03; 31 01 03 09; 31 03 03 09; 31 02 03 09. Original remote log /data/suspension-run-20261009-232658.jsonl.

Second attempt: 10 03; 31 01 03 05 04; nine polls 31 03 03 05; 31 02 03 05. No 0309. Remote log /data/suspension-run-20261009-232942.jsonl; local standard-only-transaction.jsonl. Terminal status after about 18.15 seconds. No 2E calibration writes, known Cycle parameter, ECU reset 11, or UDS TesterPresent 3E sent by these runners. They did not explicitly send 10 01 to exit extended session.

## Reading the tables below

CAN IDs are transport addresses; routine IDs and DIDs are identifiers inside UDS payloads. Values such as 04 are routine parameters, not CAN IDs. Command examples are captured evidence, not a verified repair recipe.


# Continental suspension address reference

Updated 9 October 2026. This is the consolidated reference for the captures analyzed in this workspace. CAN addresses, UDS routine identifiers, data identifiers (DIDs), and parameter bytes are different kinds of identifiers. Payloads below omit ISO-TP framing and padding. Observed does not mean independently safe or fully validated for replay.

## CAN diagnostic addresses

| Address | Type | Meaning | Evidence |
|---|---|---|---|
| `0x64B` | CAN ID | Toolbox requests toward Continental suspension ECU | Observed on Panda bus 0 in all three analyzed captures |
| `0x65B` | CAN ID | Suspension diagnostic responses | Observed on Panda bus 0; paired with `0x64B` |

Bus 0 is the Panda's logical bus number in this setup, not a statement that every chassis CAN network is physically reachable. These are the suspension diagnostic addresses identified; other raw CAN IDs in the logs have not been mapped here.

## Manufacturer-specific routines and data identifiers

| Identifier | Kind | Meaning / interpretation | Captured example | Confidence / limitation |
|---|---|---|---|---|
| `0x0305` | Routine ID | Level to Height | `31 01 03 05 04` | Confirmed association from labeled height tests |
| `0x030A` | Routine ID | Air Mass | `31 01 03 0A` | Confirmed association from labeled test; 116.3 bar·litre reading matched |
| `0x0309` | Routine ID | Follow-up after Level to Height | `31 01 03 09` | Observed after every captured height operation; purpose unknown |
| `0x0315` | Routine ID | Unknown routine in earlier Air Mass workflow | `31 01 03 15` | Start, results, stop observed; NOT established as Air Mass itself |
| `0x0101` | Read DID | Unknown Toolbox preflight read | `22 01 01` | Observed; `7F 22 31` rejection captured during calibration |
| `0xA030` | Write DID | Calibration corner value; likely FL | `2E A0 30 01 82` | Accepted; encoded 386. Corner assignment provisional |
| `0xA031` | Write DID | Calibration corner value; likely FR | `2E A0 31 01 82` | Accepted; encoded 386. Equal front inputs cannot establish left/right order |
| `0xA032` | Write DID | Calibration corner value; likely RL | `2E A0 32 01 76` | Accepted; encoded 374. Corner assignment inferred from entered order |
| `0xA033` | Write DID | Calibration corner value; likely RR | `2E A0 33 01 74` | Accepted; encoded 372. Corner assignment inferred from entered order |
| `0xA034` | Write DID | Final calibration-related write | `2E A0 34 01` | Accepted; value 1. Commit/validity meaning unproven |

Calibration input notes: FL 207, FR 207, RL 132, RR 130; units not explicitly saved. Toolbox outcome: Succeeded. Encoded front values differ by +179; encoded rear values differ by +242 in this one sample. This does not establish a general conversion formula or permission to reuse those bytes for another calibration. No calibration routine ID was identified: this transaction used DID writes.

## Target bytes for routine 0x0305

| Target byte | Toolbox selection | CAN evidence |
|---|---|---|
| `0x03` | Low | Captured: `31 01 03 05 03` |
| `0x04` | Standard | Captured: `31 01 03 05 04` |
| `0x05` | High | Captured in the labeled High action on the latest run |
| `0x06` | Very High | Captured: `31 01 03 05 06`; original marker incorrectly said High |

Correction to preserve: `06` is Very High, not High. Earlier tentative Air Mass attribution to `0315` was superseded by labeled evidence identifying `030A`.

## Protocol bytes observed

| Bytes | Meaning / observation |
|---|---|
| `10 01` / `50 01` | Session 01 request / positive response; seen before Air Mass |
| `10 03` / `50 03` | Session 03 request / positive response; seen before height routines |
| `22` | ReadDataByIdentifier service |
| `2E` / `6E` | WriteDataByIdentifier request / positive response |
| `31 01` / `71 01` | Routine start / positive response |
| `31 02` / `71 02` | Routine stop / positive response |
| `31 03` / `71 03` | Routine results request / positive response |
| `7F 2E 78` | Response pending for calibration write; followed by positive `6E` acknowledgments |
| `7F 22 31` | Request-out-of-range rejection of DID read |
| First result byte `01` then `02` | Observed polling-to-terminal transition; full manufacturer status definition unknown |
| Air Mass result `04 8B` | Candidate big-endian raw 1163, scale 0.1 gives user reading 116.3 bar·litre; only one nonzero reading validated |
| Air Mass last result byte `01` | Associated with Toolbox air mass status OK in one labeled test; provisional |

## Still unknown

Inflate/Deflate valve or compressor identifiers, selected-corner encoding for those actions, Cycle target encoding, calibration check commands, calibration write conversion/units and definite corner order, height/pressure sensor DIDs and scaling, and the exact purpose of routines 0309 and 0315.

## Evidence files

- Earlier workflow: `air-mass-level-standard-decoded.jsonl`, source `can-20261009-173234.jsonl`.
- Labeled routines: `labeled-routines-decoded.jsonl`, `labeled-actions.json`, complete diagnostic extract `labeled-routines-extract.jsonl`; original source `/data/can-20261009-175352-14af6c.jsonl` on Comma. Mac full-log transfer was incomplete.
- Calibration: `calibration-decoded.jsonl`, `calibration-diagnostics-extract.jsonl`, `calibration-panel-results.json`; original source `/data/can-20261009-181542-881baf.jsonl` on Comma. Mac full-log transfer timed out; all 6 recorded diagnostic requests and 11 responses were recovered in the extract.

The diagnostic extracts match their recorder counts. SPI errors increased during recordings, so physical-network completeness is not guaranteed. A successful write acknowledgment does not independently validate ride height or persistence.

## Latest height run update

Source `can-20261009-183131-1056cf.jsonl`: labeled Standard → High → Standard. Target 05 is now captured as High (`31 01 03 05 05`). All three operations were followed by 0309, including both Standard operations. This strengthens the association of 0309 with Toolbox’s normal height workflow; it does not identify 0309 as Cycle or establish that it caused the previously reported movement. Extract contains all 58 requests and 58 responses counted by the recorder. Last Standard end marker preceded terminal CAN result by approximately 4.94 seconds. Written outcomes were not populated.

# EAS abnormal-corner investigation

The user reports the ECU still responds through Toolbox and moves between heights, but calibration on one corner is abnormal. The affected corner is FR, reported as 302 mm while the other corners were 159–190 mm; the exact Toolbox signal name and whether these are live or stored values remain unknown. This is a post-live-test symptom report; causation remains unresolved.

## Commands under investigation

`31 01 03 05 04` starts routine 0305 with target 04. Its association with Standard is supported by multiple independently labeled Toolbox actions. This is not a calibration DID write, but that does not prove it cannot change internal control state.

`31 01 03 09` starts manufacturer-specific routine 0309. Toolbox sends it after Low, Standard, High and Very High in the recovered recordings. Result replies have been `71 03 03 09 02`; Toolbox then sends stop `31 02 03 09`. Completion arrives around 1.03–1.05 seconds after start, corresponding to the first poll. This establishes its position in the workflow, not whether it resets, checks, stores, or otherwise changes suspension state. No named definition of 0309 has been recovered. Calling it Cycle or a calibration reset would be speculation.

The first custom Standard test included 0309. The second omitted it. Both used diagnostic session 03, polled 0305 and sent a stop after the observed terminal 02. Neither custom test issued 2E calibration writes. Our code did not send `10 01` to explicitly return the ECU to default session after the action. It restored Panda safety mode and openpilot, which is distinct from resetting the suspension ECU's diagnostic session. Whether this difference matters remains unknown; do not transmit a speculative session reset as a remedy.

## Calibration evidence

Prior Toolbox calibration wrote A030=386, A031=386, A032=374, A033=372, A034=1. User inputs were FL207 FR207 RL132 RR130, units not explicitly recorded. Assigning the four DIDs to those corners is still inferred; equal front inputs cannot establish front left/right ordering. We have no before/after readback of stored calibration or sensor signals, so these logs cannot determine if the custom routines altered stored values, if the sensor/reference became inconsistent, or if the displayed value is being interpreted with incorrect scaling.

## Evidence needed next, without actuating or recalibrating

From an existing Toolbox display/export: affected corner, full name of the displayed signal, value and units; all four stored calibration values and all four current sensor/height values if available; existing EAS diagnostic trouble codes and text. Preserve values before clearing codes or writing calibration. No further crawling or physical calibration is required to start this comparison.

To identify 0309, seek Toolbox's named routine definition or action details mapping the routine identifier to its purpose. If unavailable, retain its unknown status. Never identify it by deliberately executing it to observe a fault.

Live execution is disabled in both current local runner scripts pending investigation. No further active ECU commands were sent during this analysis.

## Comparison with original CAN calibration

| DID | Inferred corner | User-entered value | Captured raw bytes | Unsigned big-endian value |
|---|---|---:|---|---:|
| A030 | FL (provisional) | 207 | 01 82 | 386 |
| A031 | FR (provisional) | 207 | 01 82 | 386 |
| A032 | RL (provisional) | 132 | 01 76 | 374 |
| A033 | RR (provisional) | 130 | 01 74 | 372 |

Both front calibration writes were identical. There is no FR-only calibration outlier in this captured transaction, regardless of which of A030/A031 maps to FL/FR. The raw value 302 would be 01 2E if encoded as an unsigned big-endian integer; that value does not occur in these four captured calibration writes. No conversion from these bytes to the present Toolbox signal is established.

FR 302 differs from the earlier entered FR 207 by 95, but these cannot be treated as a 95 mm physical change until we establish identical measurement definitions. Compared with the other displayed values, FR is 112–143 mm higher.

Raw/2 yields 193, 193, 187, 186, superficially near some present readings, but neither scaling by one-half nor equality of the displayed signal and calibration DIDs has evidence. This numerical resemblance is not a valid conversion. Similarly, raw minus entered gives front 179 and rear 242 only for this one captured example.

The original calibration transaction predates both custom height tests. It is a baseline, not a readback of the ECU after the symptom. It cannot exclude subsequent persistent changes caused by a routine, altered sensor/reference state, or physical linkage movement. Current stored calibration readback and raw sensor comparison through Toolbox are needed to distinguish them.

## Subsequent warning report

User reports yellow suspension warning while driving; red suspension warning at initial driving, absent in Service Mode, disappeared around 15 mph. Calibration result only says Failed. Warning color alone does not identify the EAS fault, and disappearance at speed does not establish recovery. Jack Mode status and exact warning text must be distinguished from fault warnings using Toolbox alerts/DTCs. No further height commands or calibration bypass are justified by these observations.

## Reported DTCs

User supplied 55A301, 55A900, 556298 as codes present at the time of warnings. No status byte, ECU-specific description, DTC format identifier, occurrence counter or timestamp supplied. Treat all six hex digits as the reported identifier; do not assume the final byte is UDS status or diagnose a component from a guessed dictionary.

## Toolbox DTC status update

User confirms source is Toolbox ECU DTC scan, with no descriptions and status code 8. If that field is the raw UDS DTC status byte, 8=0x08 sets confirmedDTC only; testFailed (0x01) is not set. This does not establish the component meaning or cause, and absent flags must be interpreted using the ECU status availability mask. No active/current or fault-free claim is justified from this alone. Codes remain 55A301, 55A900, 556298. Primary implementation reference: https://udsoncan.readthedocs.io/en/v1.24.1/_modules/udsoncan/common/dtc.html .

## Mode audit and documented service-exit lead

Audit confirms the custom runner entered EAS diagnostic session 03 (`10 03`), which Toolbox also used for all captured height operations. It did not explicitly send default session `10 01` afterward. It sent Panda heartbeats, not UDS TesterPresent keepalives. Generic UDS uses an inactivity timer for non-default sessions; the installed EAS timeout and actual state have not been verified. Therefore an indefinitely stuck diagnostic session cannot be inferred merely from missing `10 01`. Source: https://uds.readthedocs.io/en/stable/pages/knowledge_base/service.html .

A distinct documented Toolbox action exists: Continental Air Suspension Finish Service, identifier PROC_EAS_X_FINISH-SERVICE. Tesla calls it after the Continental pressurization/air-mass workflow. Source: https://service.tesla.com/docs/ModelS/ServiceManual/en-au/air/GUID-B16933F5-8ADF-4356-97CC-C66B4FADADB7.html . Its description and prerequisites should be inspected in Toolbox before selecting it as a recovery procedure. This is a concrete lead for investigating service-state exit, not proof the ECU is in that state, not proof of a fix, and not a mapping of routine 0309. No service-exit command was sent.
