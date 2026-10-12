# Verification record — October 11, 2026

## Completed

- 52 automated tests passed on Python 3.12.13 using `requirements-lock.txt`.
- Python modules compiled; browser JavaScript passed the Node syntax check.
- Both supplied DBCs loaded: 48 pre-AP / 6 powertrain message definitions. The exact truncated enumeration omission is reported in the UI and README.
- All three original uploaded references compared byte-for-byte to the recovered attachments. Source hashes are in `SOURCE-MANIFEST.json` and diagnostic reports.
- Wheel package built. Its original reference files and UI assets compared byte-for-byte against the source project. An extracted installed-layout app served the dashboard, catalog, static JavaScript and offline state successfully.
- Browser checks at the native mobile viewport and a temporary 1440×960 desktop breakpoint showed the responsive UI.
- Synthetic demo produced decoded signals and changing graph history; DTC read showed separate identifiers/status bits; exact-phrase confirmation successfully cleared only the simulated ECU.
- EAS panel visibly distinguishes captured routines, user-identified Finish Service, provisional scaling and unknown behavior. All physical actuations are blocked.
- Preview server was left at `http://127.0.0.1:8765`, offline, with no live diagnostic host permission. Runtime preview data is separate from the distributed project.

## Hardware access attempt

Direct local libusb descriptor enumeration was attempted for Panda vendor identifiers `0xbbaa` / `0x3801`. It returned no matching devices. No vehicle CAN traffic was acquired and no CAN command was transmitted. Adapter API tests used a fake USB/Panda API; they are not hardware tests.

## Remaining validation boundaries

Real USB throughput, firmware compatibility, CAN wiring/bitrate/bus mapping, DBC applicability and telemetry validity, ECU coverage, actual DID/DTC responses, car-off telemetry, and any service/actuation cleanup remain unverified on the user's car.

Live EAS clear and manufacturer routines remain disabled. Historical height/calibration faults and uncertain Finish Service scope are retained as evidence rather than treated as solved. There is no claim of full Tesla Toolbox functionality.

## Non-failing test warning

The installed Starlette test client emits a deprecation warning for its httpx adapter and suggests a future httpx2 migration. All tests pass. This affects the test harness; no browser runtime error was observed in the checked dashboard.

## October 12 follow-up

55 tests pass, including added SPI platform/ownership refusal and mocked explicit SPI lifecycle tests. Added USB/SPI source selection, bus/type/text signal filtering, and source-linked public TPMS/BMS address leads. SPI remains hardware-unverified; no new physical actuation is enabled.
