# Development NVS boot identity

This adapter implements the reviewed wave3 allocation boundary against ESP-IDF APIs. Host tests execute the actual C++ implementation against explicit fake partition/NVS/RTOS functions. No target NVS operation, commissioning, erasure, flashing or device execution occurred in this slice. The parent owns real-SDK compile checks and aggregate evidence.

## Interface and ownership

`firmware/reef/include/poseidon/reef.hpp` defines `BootIdentity` with a virtual destructor and `allocate_boot(std::uint64_t&) noexcept -> JournalError`. Output remains unchanged on failure. `BootJournal` implements that interface without changing its serialized dual-slot behavior. `Runtime` accepts `BootIdentity&`; existing source callers supplying `BootJournal&` remain compatible.

The target adapter is declared in `firmware/esp-idf/include/poseidon/nvs_boot_identity.hpp`, namespace `poseidon::reef`:

```cpp
explicit NvsBootIdentity(bool enabled = false) noexcept;
JournalError open_existing(const PartitionSpec& spec = PartitionSpec{}) noexcept;
JournalError allocate_boot(std::uint64_t& output) noexcept override;
JournalError close() noexcept;
esp_err_t last_esp_error() const noexcept;
```

Construction makes no SDK calls, even with the gate enabled. With the default disabled gate, opening/allocation return `JournalError::io` and `ESP_ERR_NOT_ALLOWED`; close is a no-op success. Disabled construction, argument rejection, allocation, error inspection, close and destruction make **zero partition, NVS or RTOS calls**. There is no in-memory fallback.

The opening FreeRTOS worker owns the entire lifecycle. An atomic process-wide lease prevents competing allocator instances from using the fixed partition. A per-instance atomic operation guard rejects reentrancy and concurrent calls before they can interleave persistence operations. Wrong-worker allocation or close returns an error without changing the valid owner's allocation state. `last_esp_error()` uses atomic storage; rejected competing operations may update that diagnostic.

Open, allocate and close in the same worker. The object must outlive all operations; destruction must not race an operation. Wrong-worker destruction does not attempt SDK cleanup from the wrong task: it quarantines the process and abandons the still-owned SDK resources rather than allowing another allocator to reuse uncertain state. The intended monitor composition uses a process-lifetime object and explicit worker-owned close.

`close()` reports the **cleanup outcome**, not a historical allocation error. Successfully released/already-absent resources return `none`; owner, reentrancy or actual cleanup failure returns `io`. Capture the original storage error before close if needed. Closing never clears the process fault latch.

## Fixed existing-state boundary

Only this development partition and record location is accepted:

| Property | Value |
|---|---|
| Partition label | `reef_state` |
| Type / subtype | `data` / `nvs` |
| Address | `0x3f0000` |
| Size | `0x10000` |
| End, exclusive | `0x400000` |
| Namespace | `reef_boot` |
| Record key | `identity_v1` |

`PartitionSpec` is a compile-time integration input, not a downlink setting. A nonmatching label/type/subtype/address/size/namespace/key is rejected. The discovered partition must match metadata and must not be marked read-only or generically flash-encrypted. There is no fallback to the general `nvs` partition. This adapter does not change any partition CSV; the separate monitor-target owner controls the reviewed development layout.

Startup reads at most 256 chunks of 256 bytes to reject entirely erased storage **before NVS initialization**. A non-erased byte only permits further validation; it is not proof of provisioning. Read failures stop startup.

Before initializing, `nvs_get_stats` must establish that the fixed partition is not already registered/initialized. An already-initialized partition is treated as externally owned and rejected without deinitializing it. All application users of this fixed partition must honor the exclusive allocator lease; it is not a lock over arbitrary external code calling ESP-IDF directly.

After successful partition-specific initialization, the adapter opens the namespace read-only and requires an existing blob of exactly 32 bytes with the complete format below. Only then does it close that handle, open read-write, and revalidate the same record/floor. It never creates a namespace or baseline to recover from missing state. A pre-existing valid commissioned floor of zero may advance to one; zero is never returned as a boot ID.

## RNVS record

This is a **development format**, not authenticated provisioning material or an antirollback anchor.

| Bytes | Contents |
|---|---|
| 0–3 | ASCII `RNVS` |
| 4 | Version `1` |
| 5 | Commissioned marker `1` |
| 6–7 | Zero |
| 8–15 | Boot floor, little-endian uint64 |
| 16–23 | Bitwise complement of floor, little-endian uint64 |
| 24–27 | CRC-32/ISO-HDLC of bytes 0–23, little-endian uint32 |
| 28–31 | Zero |

CRC parameters: polynomial `0x04c11db7`, reflected implementation polynomial `0xedb88320`, initial value `0xffffffff`, final XOR `0xffffffff`, reflected input/output. There is no native-struct serialization. The complete expected record is compared, so magic/version/marker/reserved/complement violations remain rejected even when a test recomputes a valid checksum. CRC is not a signature or authorization check.

Allocation rereads the existing floor and requires it to match the owned instance's last validated floor. A coherent unexpected change is a fault, not permission to overwrite another writer's state. `UINT64_MAX` is terminal. The adapter writes one complete incremented record, requires `nvs_set_blob` and `nvs_commit` success, then reads back and validates the exact expected next floor before publishing it.

## Faults and cleanup

- **F1 — Startup:** absent partition/namespace/key, malformed type/length/format or SDK errors reject startup. No erase, reseed, commissioning, partition-image or reset API is supplied. `ESP_ERR_NVS_NO_FREE_PAGES` and `ESP_ERR_NVS_NEW_VERSION_FOUND` do not trigger the SDK examples' erase/reinitialize pattern.
- **F2 — Uncertain persistence:** any allocation read/set/commit/readback failure, unexpected floor or exhaustion faults the instance and latches a **process-wide** fault. No ID is published. Close/reopen, destruction and constructing a new allocator cannot bypass the latch. There is no production or test reset entry point. A genuinely new process must inspect persistent state again; a new process does not prove that storage has become valid.
- **F3 — Owned resources:** only successfully opened handles are closed; only a successfully initialized partition owned by this lifecycle is deinitialized. Initialization failure may leave unknown SDK state, so the adapter does not deinitialize an initialization it cannot establish ownership of; it quarantines the process. Failed deinitialization also quarantines resources/process and is not retried implicitly from destruction.

Native ESP error values are retained without reducing every failure to `ESP_FAIL`. Adapter policy rejections use explicit ESP codes such as `ESP_ERR_INVALID_ARG`, `ESP_ERR_INVALID_STATE` or `ESP_ERR_NOT_ALLOWED`. A cleanup error is a new diagnostic; callers needing the original allocation error must capture it before cleanup.

ESP-IDF may write before `nvs_commit`, and `ESP_ERR_NVS_REMOVE_FAILED` explicitly describes a new value possibly already written. No failure handler restores an assumed older floor. NVS internal recovery may repair/discard entries or pages during initialization; readback through its API is not independent power-cycle verification. This is not raw-byte ByteStore equivalence, an atomic multi-key transaction, flash endurance evidence, universal corruption detection, physical brownout qualification or rollback-resistant storage.

## Host verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests/firmware -p test_nvs_boot_identity.py -v
PYTHONDONTWRITEBYTECODE=1 REEF_SANITIZE=1 python3 -m unittest discover \
  -s tests/firmware -p test_nvs_boot_identity.py -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/aquilon/src python3 -m unittest discover \
  -s tests/firmware -p test_runtime.py -v
```

Set `REEF_TEST_TMPDIR` to an existing campaign-owned temporary directory. The stdlib harness compiles the **actual** adapter plus core runtime/codec against `tests/firmware/abi_nvs/` and the synthetic backend in `nvs_identity_cases.cpp`. Each case runs in a fresh child process; within a case, failed-instance/closed-instance/new-instance attempts exercise the same process-wide fault latch. Fake backing bytes may change before a simulated set/commit failure to test uncertain early writes. This is not execution against real NVS.

Compiler flags include C++17, `-DNDEBUG`, `-Wall -Wextra -Werror -pedantic` and `-pthread`. Negative checks remain active in release mode. Temporary binaries are cleaned, and compiler/child processes have hard subprocess timeouts. ASan/UBSan is optional through `REEF_SANITIZE=1`.

Evidence on 2026-09-08, Darwin arm64 / Apple Clang 21.0.0:

- **T1:** Final NVS ABI suite: **100/100 passed**, exit 0, 1.381 seconds.
- **T2:** Final NVS ABI suite with ASan/UBSan: **100/100 passed**, exit 0, 6.466 seconds, no findings.
- **T3:** Existing `test_runtime.py`: **113/113 passed**, exit 0, 3.291 seconds. The only core edits introduce the allocation interface and constructor/reference dispatch compatibility.

Coverage includes fixed-partition rejection, first/last/full erased preflight, all 32 record-byte corruptions, semantic mutations with recomputed CRC, length/type failures, both read-only/read-write validation stages, prewrite and postcommit failures, early persistence on failed SDK calls, no-wrap boundaries and independent Python-zlib-derived golden bytes. Ownership cases include external initialization, competing instances, wrong-worker calls, same-thread reentrancy, a real concurrent host thread, cleanup failures and wrong-worker destruction. Full regression and real-SDK build evidence belong to the parent report; no hardware result is implied.
