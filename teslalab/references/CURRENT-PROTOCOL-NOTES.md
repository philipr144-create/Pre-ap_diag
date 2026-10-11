# Current Continental corrections — October 11, 2026

These corrections supersede older notes that call 0x0309 unidentified. Historical captures and test reports remain unchanged.

- User identifies routine **0x0309 as Exit / Finish Service** and states it must run after every command to leave diagnostic mode. Treat this as the required intended workflow, not an optional height follow-up.
- Captured height workflows corroborate this sequence: `10 03`, start `31 01 03 09`, poll `31 03 03 09`, observed terminal reply `71 03 03 09 02`, stop `31 02 03 09`. The capture establishes the sequence; the user supplies the Finish Service identification.
- The current app DOES NOT implement that finish sequence. Its existing height/Air Mass execution is therefore incomplete against this requirement. Restoring Panda/openpilot is distinct from finishing the ECU service procedure.
- The user recalls **Odin** preventing commanded height changes while permitting read-only access. Record this as a working explanation, not a confirmed root cause: no Odin-specific transaction evidence or definition was found in the available local notes. Do not infer write/movement support from a successful fault read.
- Resolve whether “every command” means every complete service action or also standalone fault reads before labeling a read-only operation that also starts a manufacturer routine. The recorded height sequence alone does not demonstrate the fault-read cleanup behavior.
- No CAN commands were transmitted for this correction. No live execution behavior was changed.
