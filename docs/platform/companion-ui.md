# Imported acquisition companions

The **Imported companions** workbench section is separate from the legacy WAV + manifest importer. It submits one selected export to `POST /api/v1/acquisition-sessions/{platform_session_id}/recordings` through the same-origin proxy. The Acquisition-owned pure reader, not the UI, validates scientific structure and consistency.

## Import and inspect

A scoped admin selects an existing manual platform context and the seven original files: `wav`, `manifest`, `binding`, `source_receipt`, `source_header`, `source_final`, `export_receipt`. The form sends seven file parts and no scalar fields. It checks only file selection, flat basenames and the ratified byte limits before upload. The API independently authorizes the path and validates the complete package. Rejections never fall back to the old importer or truncate metadata.

The acknowledged recording ID opens retained evidence even when replay is pending or failed. The operator can also enter an exact recording ID, select an available recording, or inspect recent jobs. Known legacy records show **companions not retained**; absence does not imply capture failure or completeness. Original import/demo permissions and the evidence-review workflow remain unchanged.

The retained panel displays:

- Both namespace IDs: manual platform context and original capture session, plus source, selected segment, mapped site/zone/device and authenticated importer.
- Ordered declared channels, exact nominal/reference/epoch/rounding/uncertainty values, selected-receipt gaps and losses, and separate source-snapshot accounting.
- Actual-reader software-check coverage and the original parsed binding, separate from raw document bytes.
- Fixed unverified original-input/full-session/time/epoch/origin/authorization/calibration/completeness claims. Normal finalization means stored segments with an unattested trailing extent.

The original waveform remains in nominal segment seconds with all-channel normalized PCM16 extrema. No candidate UTC, verified synchronization, physical channel assignment, calibration or biological meaning is inferred. The manual context never overrides imported clock declarations. Evidence references and expressions render as escaped text, not links or executable markup.

Five role-based document controls download the exact retained JSON bytes. The client checks response length, SHA-256 header and body digest against the catalog before starting a download. It never parses and re-encodes the download; UTF-16/BOM source finals stay byte-identical. Parsed inspection views are not raw-byte evidence.

A failed authorization refresh clears retained evidence; raw-document failures also clear it. Upload errors preserve selected files. An exact qualified retry returns the original job without replacing importer provenance; a valid changed companion conflicts with HTTP 409.

## Companion-only browser gate

The existing hardened runner selects `qa/companion-browser-qa.ts` only when `PLATFORM_QA_COMPANION_ONLY=1`. Default, remaining, residual and legacy QA scripts/modes stay unchanged. Do not run concurrent builds or browsers against the shared `.next` directory.

After the unit, typecheck and build commands in `apps/aeolus-ui`, run:

```sh
bun run test
bun run typecheck
bun run build

PLATFORM_QA_COMPANION_ONLY=1 \
PLATFORM_QA_COMPANION_FIXTURES=path/to/synthetic-reader-fixtures \
PLATFORM_QA_API_PYTHON=.local/assurance-integration-v1/api/venv/bin/python \
PYTHONDONTWRITEBYTECODE=1 \
PLATFORM_QA_ARTIFACTS="$(mktemp -d /tmp/platform-tranche2-ui-browser-XXXXXX)" \
python3 qa/run-platform-qa.py
```

Use an outer hard-timeout supervisor with a 20-second TERM grace. The runner imposes a 330-second browser-process bound, closes its browser on exit, starts only owned process groups and refuses a nonempty artifact directory. The historical private fixture and command records are not redistributed; prepare synthetic fixture exports before running companion mode.

`prepare-companion-fixtures.py` reads the unchanged Acquisition positive/zero exports and validates them with the actual reader. It copies their synthetic source into an owned directory, then uses the actual exporter to produce a different canonical export-budget receipt for the valid 409 case and a UTF-16/BOM final with inert evidence text for a separate manual context. Every positive package passes the actual reader first. No response stub, scientific validator clone, native codec or device operation is used.

The named `companion-single-export` suite uses native browser authentication and real UI/API requests. It covers scoped device/context setup, seven-role uploads, positive and zero candidates, stereo order, gaps/losses, exact binding/projection values, all five raw UI downloads, idempotency, a valid changed-companion 409, malformed/oversize rejection, legacy absence, viewer/foreign-site denial, principal revocation and desktop/mobile page bounds. JSON proofs, original-byte downloads, screenshots and owned-group cleanup records go to the new artifact directory. Browser authentication never uses APIRequestContext cookie parsing.

This is a local synthetic software gate. It does not establish production hosting or identity readiness, field enrollment, physical operation, original-source truth, calibration, permission, synchronization, capture completeness or biological efficacy. Backend durability/migration/quota acceptance remains in its separately recorded API/Hub/proto/ops gate.
