from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from poseidon_proto.companion import DOCUMENT_ROLES, PART_LIMITS, MAX_COMPANION_BYTES, MAX_QUEUE_SLOTS, MAX_RETAINED_COMPANION_BYTES
from poseidon_trident import Hub, HubError
from poseidon_trident.companion_schema import COMPANION_COLUMNS, companion_logical_bytes, occupied_queue_slots
from poseidon_trident.platform_schema import PLATFORM_COLUMNS
from poseidon_trident.workspace import _EXPECTED_COLUMNS, HUB_SCHEMA_VERSION
from poseidon_trident.control_schema import CONTROL_COLUMNS

from _companion_support import make_exports, context, submit, rewrite_binding
from _support import active_wav, manifest_bytes


ROOT = Path(__file__).resolve().parents[2]


class Interrupted(BaseException):
    pass


class CompanionImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory(prefix="synthetic-companion-fixtures-")
        cls.first, cls.later = make_exports(Path(cls.fixtures.name))

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-companion-hub-")
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.hub = Hub(self.workspace)
        context(self.hub)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(lambda: self.hub.close())

    def assert_code(self, code, operation, *args, **kwargs):
        with self.assertRaises(HubError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def actor(self, role="admin", subject="synthetic-admin", sites=None, device_id=None):
        issued = self.hub.create_principal({"subject": subject, "role": role, "site_ids": sites or ["synthetic-site"], "device_id": device_id})
        return self.hub.for_principal(self.hub.authenticate(issued["token"])), issued

    def clean_counts(self):
        with self.hub._workspace.connect(read_only=True) as connection:
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in COMPANION_COLUMNS}
        self.assertEqual(counts, {table: 0 for table in COMPANION_COLUMNS})
        self.assertEqual(self.hub.list_jobs()["total"], 0)
        self.assertEqual(list((self.workspace / ".staging").iterdir()), [])
        self.assertEqual(list((self.workspace / "recordings").iterdir()), [])

    def interrupt(self, phase, bundle=None):
        def fault(current):
            if current == phase:
                raise Interrupted(phase)
        with patch.object(self.hub, "_companion_failpoint", side_effect=fault):
            with self.assertRaises(Interrupted):
                submit(self.hub, bundle or self.first)

    def test_real_stereo_candidate_and_gap_zero_capture_preserve_every_role(self):
        first_job = submit(self.hub, self.first)
        pending = self.hub.get_acquisition_companion(first_job["recording_id"])
        self.assertEqual(pending["job"]["status"], "queued")
        self.assertEqual(pending["platform_session_id"], "platform-context")
        self.assertEqual(pending["capture_session_id"], "synthetic-capture")
        self.assertEqual([entry["channel_id"] for entry in pending["validation"]["source"]["channels"]], ["right", "left"])
        self.assertEqual(pending["validation"], json.loads(self.first["validated"].projection_bytes))
        self.assertEqual(pending["binding"], json.loads(self.first["bytes"]["binding"]))
        self.hub.process_next_job()
        self.assertEqual(self.hub.get_recording(first_job["recording_id"])["event_count"], 1)
        later_job = submit(self.hub, self.later)
        self.hub.process_next_job()
        later = self.hub.get_acquisition_companion(later_job["recording_id"])
        self.assertEqual(self.hub.get_recording(later_job["recording_id"])["event_count"], 0)
        self.assertEqual(later["validation"]["selected_receipt"]["missing_units"], 7840)
        self.assertEqual(later["validation"]["selected_receipt"]["dropped_units"], 100)
        for key in ("full_original_session_bytes_verified", "original_input_bytes_verified", "predecessor_receipt_bytes_verified",
                    "acquisition_completeness_verified", "clock_relation_verified", "epoch_declaration_verified", "origin_verified", "authorization_verified"):
            self.assertIs(later["validation"]["verification"][key], False)
        for job, bundle in ((first_job, self.first), (later_job, self.later)):
            directory = self.workspace / "recordings" / job["recording_id"]
            self.assertEqual({path.name for path in directory.iterdir()}, {"source.wav", "manifest.json"})
            self.assertEqual((directory / "source.wav").read_bytes(), bundle["bytes"]["wav"])
            self.assertEqual((directory / "manifest.json").read_bytes(), bundle["bytes"]["manifest"])
            for role in DOCUMENT_ROLES:
                document = self.hub.get_companion_document(job["recording_id"], role)
                self.assertEqual(document, {"bytes": bundle["bytes"][role], "name": bundle["names"][role], "sha256": hashlib.sha256(bundle["bytes"][role]).hexdigest()})
        self.hub.close()
        with Hub(self.workspace) as reopened:
            self.assertEqual(reopened.get_acquisition_companion(later_job["recording_id"]), later)

    def test_actual_exporter_noncanonical_utf16_final_roundtrips_without_normalization(self):
        first, _ = make_exports(self.root / "utf16", capture_id="synthetic-utf16", final_encoding="utf-16")
        self.assertTrue(first["bytes"]["source_final"].startswith((b"\xff\xfe", b"\xfe\xff")))
        job = submit(self.hub, first)
        self.assertEqual(self.hub.get_companion_document(job["recording_id"], "source_final")["bytes"], first["bytes"]["source_final"])
        self.hub.close()
        with Hub(self.workspace) as reopened:
            self.assertEqual(reopened.get_companion_document(job["recording_id"], "source_final")["bytes"], first["bytes"]["source_final"])

    def test_qualified_retry_and_legacy_retry_preserve_original_actor_and_documents(self):
        actor, _ = self.actor()
        job = submit(actor, self.first)
        before = actor.get_acquisition_companion(job["recording_id"])
        self.assertEqual(submit(self.hub, self.first), job)
        legacy = self.hub.submit_recording(io.BytesIO(self.first["bytes"]["wav"]), self.first["bytes"]["manifest"])
        self.assertEqual(legacy, job)
        self.assertEqual(actor.get_acquisition_companion(job["recording_id"]), before)
        self.assertEqual(before["actor_subject"], "synthetic-admin")
        self.assertEqual(before["auth_mode"], "scoped_token")

    def test_no_silent_legacy_backfill_or_context_rescope(self):
        self.hub.submit_recording(io.BytesIO(self.first["bytes"]["wav"]), self.first["bytes"]["manifest"])
        self.assert_code("companion_import_conflict", submit, self.hub, self.first)
        self.assertEqual(self.hub.get_acquisition_companion("synthetic-first")["state"], "absent")
        self.assert_code("companion_document_not_found", self.hub.get_companion_document, "synthetic-first", "binding")
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recording_sessions").fetchone()[0], 0)

    def test_context_snapshot_and_source_segment_cannot_remap(self):
        submit(self.hub, self.first)
        context(self.hub, session_id="other-context")
        self.assert_code("companion_segment_conflict", submit, self.hub, self.first, "other-context")
        changed, _ = make_exports(self.root / "changed-snapshot", capture_id="other-capture", first_id="other-record")
        self.assert_code("companion_snapshot_conflict", submit, self.hub, changed)
        remapped, _ = make_exports(self.root / "remapped", first_id="remapped-record")
        self.assertEqual(remapped["validated"].header_sha256, self.first["validated"].header_sha256)
        self.assert_code("companion_segment_conflict", submit, self.hub, remapped)
        different, _ = make_exports(self.root / "different-declaration", epoch_operator="other-synthetic-declarant")
        self.assertEqual(different["bytes"]["manifest"], self.first["bytes"]["manifest"])
        self.assert_code("companion_import_conflict", submit, self.hub, different)
        self.assertEqual(self.hub.list_jobs()["total"], 1)

    def test_actual_reader_rejects_hash_rewritten_semantic_lie_before_reservation(self):
        changed = rewrite_binding(self.first, lambda binding: binding["time"].update({"started_at": "2030-01-01T00:00:00Z"}))
        self.assert_code("invalid_export", submit, self.hub, changed)
        self.clean_counts()

    def test_all_raw_roles_missing_unknown_names_and_malformed_bytes_fail_without_import(self):
        for role in DOCUMENT_ROLES:
            with self.subTest(role=role):
                changed = deepcopy(self.first)
                changed["bytes"][role] += b"x"
                self.assert_code("invalid_export", submit, self.hub, changed)
        for raw in (b'{"x":NaN}', b'{"x":1,"x":2}', b"{" + b'"x":[' * 100, b"\xff"):
            changed = deepcopy(self.first)
            changed["bytes"]["binding"] = raw
            self.assert_code("invalid_export", submit, self.hub, changed)
        changed = deepcopy(self.first)
        changed["names"]["binding"] = "../binding-000000.json"
        self.assert_code("invalid_request", submit, self.hub, changed)
        self.clean_counts()

    def test_every_part_cap_and_actual_wav_stream_limit(self):
        for role, cap in PART_LIMITS.items():
            with self.subTest(role=role):
                changed = deepcopy(self.first)
                changed["bytes"][role] = b"x" * (cap + 1)
                self.assert_code("request_too_large", submit, self.hub, changed)
        self.clean_counts()
        self.assertEqual(MAX_COMPANION_BYTES, 4194304)
        self.assertEqual(MAX_RETAINED_COMPANION_BYTES, 268435456)

    def test_queue_includes_preparing_and_exact_retry_succeeds_when_full(self):
        job = submit(self.hub, self.first)
        raw = active_wav()
        for index in range(MAX_QUEUE_SLOTS - 1):
            self.hub.submit_recording(io.BytesIO(raw), manifest_bytes(raw, recording_id=f"legacy-{index}"))
        self.assertEqual(submit(self.hub, self.first), job)
        self.assert_code("companion_queue_full", submit, self.hub, self.later)
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(occupied_queue_slots(connection), 32)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 0)

    def test_preparing_reservation_counts_against_legacy_queue(self):
        self.interrupt("intent_reserved")
        raw = active_wav()
        for index in range(MAX_QUEUE_SLOTS - 1):
            self.hub.submit_recording(io.BytesIO(raw), manifest_bytes(raw, recording_id=f"legacy-{index}"))
        self.assert_code("queue_full", self.hub.submit_recording, io.BytesIO(raw), manifest_bytes(raw, recording_id="too-many"))
        self.assert_code("companion_queue_full", submit, self.hub, self.later)
        self.hub.close()
        with Hub(self.workspace) as reopened:
            with reopened._workspace.connect(read_only=True) as connection:
                self.assertEqual(occupied_queue_slots(connection), 31)

    def test_retained_plus_reserved_quota_and_exact_retry(self):
        needed = sum(len(self.first["bytes"][role]) for role in DOCUMENT_ROLES)
        with patch("poseidon_trident.companion.MAX_RETAINED_COMPANION_BYTES", needed):
            job = submit(self.hub, self.first)
            self.assertEqual(submit(self.hub, self.first), job)
            self.assert_code("companion_capacity_full", submit, self.hub, self.later)
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(companion_logical_bytes(connection), needed)

    def test_reserved_companion_bytes_block_second_new_import(self):
        needed = sum(len(self.first["bytes"][role]) for role in DOCUMENT_ROLES)
        self.interrupt("intent_reserved")
        with patch("poseidon_trident.companion.MAX_RETAINED_COMPANION_BYTES", needed):
            self.assert_code("companion_capacity_full", submit, self.hub, self.later)
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(companion_logical_bytes(connection), needed)

    def test_concurrent_exact_imports_commit_one_job_and_binding(self):
        barrier = threading.Barrier(3)
        results, failures = [], []
        def worker():
            try:
                barrier.wait()
                results.append(submit(self.hub, self.first))
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.hub.list_jobs()["total"], 1)
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recording_companion_documents").fetchone()[0], 5)

    def test_scoped_roles_cross_site_and_exact_device_reads_from_pending(self):
        for role in ("viewer", "reviewer", "device"):
            actor, _ = self.actor(role, "actor-" + role, device_id="synthetic-device" if role == "device" else None)
            self.assert_code("forbidden", submit, actor, self.first)
            self.assert_code("forbidden", actor.companion_admission, "platform-context")
        outside, _ = self.actor("admin", "other-site-admin", ["other-site"])
        self.assert_code("not_found", outside.companion_admission, "platform-context")
        self.assert_code("not_found", submit, outside, self.first)
        actor, _ = self.actor()
        job = submit(actor, self.first)
        viewer, _ = self.actor("viewer", "allowed-reader")
        self.assertEqual(viewer.get_acquisition_companion(job["recording_id"])["job"]["status"], "queued")
        self.assertEqual(viewer.get_companion_document(job["recording_id"], "binding")["bytes"], self.first["bytes"]["binding"])
        self.assert_code("recording_not_found", outside.get_acquisition_companion, job["recording_id"])
        self.assert_code("recording_not_found", outside.get_companion_document, job["recording_id"], "binding")

    def test_eager_admission_is_bounded_and_release_does_not_require_live_token(self):
        actor, issued = self.actor()
        first = actor.companion_admission("platform-context")
        second = actor.companion_admission("platform-context")
        self.assert_code("companion_admission_full", actor.companion_admission, "platform-context")
        self.hub.revoke_principal(issued["principal"]["id"])
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)
        with self.hub.companion_admission("platform-context"), self.hub.companion_admission("platform-context"):
            self.assert_code("companion_admission_full", self.hub.companion_admission, "platform-context")

    def test_revoked_principal_during_read_cannot_reserve_or_commit(self):
        actor, issued = self.actor()
        class RevokingStream(io.BytesIO):
            done = False
            def read(inner, count=-1):
                data = super().read(count)
                if not inner.done:
                    inner.done = True
                    self.hub.revoke_principal(issued["principal"]["id"])
                return data
        self.assert_code("unauthorized", actor.submit_recording_with_companions,
                         RevokingStream(self.first["bytes"]["wav"]), self.first["bytes"]["manifest"],
                         {role: self.first["bytes"][role] for role in DOCUMENT_ROLES}, session_id="platform-context", filenames_by_role=self.first["names"])
        self.clean_counts()

    def test_authority_revalidated_after_rename_and_cleanup_keeps_no_reservation(self):
        actor, issued = self.actor()
        def revoke(phase):
            if phase == "renamed":
                self.hub.revoke_principal(issued["principal"]["id"])
        with patch.object(self.hub, "_companion_failpoint", side_effect=revoke):
            self.assert_code("unauthorized", submit, actor, self.first)
        self.clean_counts()

    def test_registered_device_revalidated_at_commit(self):
        def revoke(phase):
            if phase == "renamed":
                self.hub.revoke_device("synthetic-device")
        with patch.object(self.hub, "_companion_failpoint", side_effect=revoke):
            self.assert_code("companion_device_inactive", submit, self.hub, self.first)
        self.clean_counts()

    def test_every_interruption_phase_reconciles_to_none_or_complete(self):
        phases = ["intent_reserved", "directory_owned", "file_opened.source.wav", "file_completed.source.wav",
                  "file_opened.manifest.json", "file_completed.manifest.json", "staged", "ready", "renamed", "source_inserted", "binding_inserted", "projection_inserted",
                  *("document_inserted." + role for role in DOCUMENT_ROLES), "audit_inserted", "before_commit", "after_commit"]
        self.hub.close()
        for index, phase in enumerate(phases):
            with self.subTest(phase=phase):
                path = self.root / f"phase-{index}"
                self.hub = Hub(path)
                context(self.hub)
                self.interrupt(phase)
                self.hub.close()
                with Hub(path) as reopened:
                    self.assertEqual(reopened.list_jobs()["total"], 1 if phase == "after_commit" else 0)
                    with reopened._workspace.connect(read_only=True) as connection:
                        self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 0)
                        self.assertEqual(connection.execute("SELECT COUNT(*) FROM recording_companion_documents").fetchone()[0], 5 if phase == "after_commit" else 0)
                    self.assertEqual(list((path / ".staging").iterdir()), [])
                    if phase == "after_commit":
                        original = reopened.get_acquisition_companion("synthetic-first")
                        self.assertEqual(submit(reopened, self.first)["id"], original["job"]["id"])

    def test_partial_receiving_stage_is_aborted_only_with_registered_ownership(self):
        def partial(phase):
            if phase == "file_opened.source.wav":
                with self.hub._workspace.connect(read_only=True) as connection:
                    row = connection.execute("SELECT * FROM companion_import_intents").fetchone()
                target = self.workspace / ".staging" / row["staging_name"] / "source.wav"
                target.write_bytes(self.first["bytes"]["wav"][:32])
                raise Interrupted("during-copy")
        with patch.object(self.hub, "_companion_failpoint", side_effect=partial):
            with self.assertRaises(Interrupted):
                submit(self.hub, self.first)
        self.hub.close()
        with Hub(self.workspace) as reopened:
            self.assertEqual(reopened.list_jobs()["total"], 0)
            self.assertEqual(list((self.workspace / ".staging").iterdir()), [])
            with reopened._workspace.connect(read_only=True) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 0)

    def test_receiving_injection_inode_substitution_and_changed_or_shortened_bytes_are_preserved(self):
        self.hub.close()
        for case in ("injected-directory", "injected-file", "directory-inode", "file-inode", "partial-prefix", "short-completed"):
            with self.subTest(case=case):
                path = self.root / case
                self.hub = Hub(path)
                context(self.hub)
                markers = []
                wanted = {"injected-directory": "intent_reserved", "injected-file": "intent_reserved",
                          "directory-inode": "directory_owned", "file-inode": "file_completed.source.wav",
                          "partial-prefix": "file_opened.source.wav", "short-completed": "staged"}[case]
                def inject(phase):
                    if phase != wanted:
                        return
                    with self.hub._workspace.connect(read_only=True) as connection:
                        row = connection.execute("SELECT * FROM companion_import_intents").fetchone()
                    package = path / ".staging" / row["staging_name"]
                    if case.startswith("injected"):
                        package.mkdir()
                        if case == "injected-file":
                            marker = package / "source.wav"
                            marker.write_bytes(self.first["bytes"]["wav"][:32])
                            markers.append(marker)
                        else:
                            markers.append(package)
                    elif case == "directory-inode":
                        saved = self.root / "saved-owned-directory"
                        package.rename(saved)
                        package.mkdir()
                        markers.extend((package, saved))
                    elif case == "file-inode":
                        marker = package / "source.wav"
                        saved = self.root / "saved-owned-source.wav"
                        marker.rename(saved)
                        marker.write_bytes(self.first["bytes"]["wav"])
                        markers.extend((marker, saved))
                    else:
                        marker = package / "source.wav"
                        marker.chmod(0o600)
                        prefix = self.first["bytes"]["wav"][:32]
                        marker.write_bytes((b"X" + prefix[1:]) if case == "partial-prefix" else prefix)
                        markers.append(marker)
                    raise Interrupted(case)
                with patch.object(self.hub, "_companion_failpoint", side_effect=inject):
                    with self.assertRaises(Interrupted):
                        submit(self.hub, self.first)
                before = {str(marker): marker.read_bytes() if marker.is_file() else None for marker in markers}
                self.hub.close()
                with self.assertRaises(HubError) as caught:
                    Hub(path)
                self.assertEqual(caught.exception.code, "companion_recovery_failed")
                for marker in markers:
                    self.assertTrue(marker.exists())
                    if marker.is_file():
                        self.assertEqual(marker.read_bytes(), before[str(marker)])
                with closing(sqlite3.connect(path / "hub.sqlite3")) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 1)

    def test_creation_before_checkpoint_crash_is_explicitly_fail_closed(self):
        from poseidon_trident.companion_storage import capture_import_ownership
        self.hub.close()
        for event in ("directory", "file_opened"):
            with self.subTest(event=event):
                path = self.root / ("missing-checkpoint-" + event)
                self.hub = Hub(path)
                context(self.hub)
                def interrupt_before_checkpoint(workspace, intent_id, actual, target, info):
                    if actual == event:
                        raise Interrupted("creation-checkpoint-window")
                    capture_import_ownership(workspace, intent_id, actual, target, info)
                with patch("poseidon_trident.companion.capture_import_ownership", side_effect=interrupt_before_checkpoint):
                    with self.assertRaises(Interrupted):
                        submit(self.hub, self.first)
                self.hub.close()
                existing = {entry.relative_to(path).as_posix() for entry in (path / ".staging").rglob("*")}
                with self.assertRaises(HubError) as caught:
                    Hub(path)
                self.assertEqual(caught.exception.code, "companion_recovery_failed")
                self.assertEqual({entry.relative_to(path).as_posix() for entry in (path / ".staging").rglob("*")}, existing)

    def test_expected_source_intent_blobs_are_exact_bounded_and_strictly_binary(self):
        self.interrupt("intent_reserved")
        with self.hub._workspace.connect() as connection:
            row = connection.execute("SELECT * FROM companion_import_intents").fetchone()
            self.assertEqual(bytes(row["wav_bytes"]), self.first["bytes"]["wav"])
            self.assertEqual(bytes(row["manifest_bytes"]), self.first["bytes"]["manifest"])
            for column, maximum in (("wav_bytes", PART_LIMITS["wav"]), ("manifest_bytes", PART_LIMITS["manifest"])):
                for invalid in ("not a BLOB", b"", b"x" * (maximum + 1)):
                    with self.subTest(column=column, length=len(invalid)):
                        with self.assertRaises(sqlite3.IntegrityError):
                            connection.execute(f"UPDATE companion_import_intents SET {column} = ?", (invalid,))
        self.hub.close()
        with Hub(self.workspace) as reopened:
            with reopened._workspace.connect(read_only=True) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 0)

    def test_normal_failure_after_unknown_precreation_injection_preserves_the_file(self):
        markers = []
        def inject(phase):
            if phase == "intent_reserved":
                with self.hub._workspace.connect(read_only=True) as connection:
                    row = connection.execute("SELECT staging_name FROM companion_import_intents").fetchone()
                package = self.workspace / ".staging" / row["staging_name"]
                package.mkdir()
                marker = package / "source.wav"
                marker.write_bytes(self.first["bytes"]["wav"][:32])
                markers.append(marker)
        with patch.object(self.hub, "_companion_failpoint", side_effect=inject):
            self.assert_code("companion_recovery_failed", submit, self.hub, self.first)
        self.assertEqual(markers[0].read_bytes(), self.first["bytes"]["wav"][:32])
        self.assertEqual(self.hub.list_jobs()["total"], 0)
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 1)

    def test_real_process_exit_after_rename_is_aborted_without_partial_catalog(self):
        self.hub.close()
        script = """import os,sys\nfrom pathlib import Path\nfrom poseidon_trident import Hub\nfrom _companion_support import load_export,submit\nh=Hub(Path(sys.argv[1]))\ndef fault(phase):\n if phase=='renamed':os._exit(73)\nh._companion_failpoint=fault\nsubmit(h,load_export(Path(sys.argv[2])))\n"""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(str(ROOT / value) for value in ("libs/proto-py/src", "apps/acoustic/src", "apps/trident/src", "tests/trident"))
        result = subprocess.run([sys.executable, "-S", "-c", script, str(self.workspace), str(self.first["directory"])], env=env, timeout=20, capture_output=True, text=True)
        self.assertEqual(result.returncode, 73, result.stderr)
        with Hub(self.workspace) as reopened:
            self.assertEqual(reopened.list_jobs()["total"], 0)
            self.assertEqual(list((self.workspace / ".staging").iterdir()), [])
            self.assertEqual(list((self.workspace / "recordings").iterdir()), [])

    def test_unknown_staging_extra_files_symlinks_hardlinks_and_tampering_preserved(self):
        self.hub.close()
        for case in ("unknown", "extra", "symlink", "hardlink", "changed"):
            with self.subTest(case=case):
                path = self.root / case
                self.hub = Hub(path)
                context(self.hub)
                if case == "unknown":
                    marker = path / ".staging" / "user-owned.part"
                    marker.write_bytes(b"preserve unknown bytes")
                else:
                    self.interrupt("renamed")
                    package = path / "recordings/synthetic-first"
                    marker = package / ("user-owned.part" if case == "extra" else "source.wav")
                    if case == "extra":
                        marker.write_bytes(b"preserve extra bytes")
                    elif case in ("symlink", "hardlink"):
                        original = self.root / (case + "-outside.wav")
                        original.write_bytes(self.first["bytes"]["wav"])
                        marker.unlink()
                        if case == "symlink":
                            marker.symlink_to(original)
                        else:
                            os.link(original, marker)
                    else:
                        marker.chmod(0o600)
                        marker.write_bytes(b"X" + marker.read_bytes()[1:])
                before = marker.read_bytes()
                self.hub.close()
                with self.assertRaises(HubError):
                    Hub(path)
                self.assertEqual(marker.read_bytes(), before)
                self.assertTrue(marker.exists() or marker.is_symlink())

    def test_cleanup_failure_preserves_intent_and_returns_storage_error(self):
        def fail(phase):
            if phase == "renamed":
                raise RuntimeError("synthetic commit fault")
        with patch.object(self.hub, "_companion_failpoint", side_effect=fail), patch("poseidon_trident.companion_storage._remove_checked", side_effect=OSError("synthetic cleanup failure")):
            self.assert_code("companion_recovery_failed", submit, self.hub, self.first)
        with self.hub._workspace.connect(read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companion_import_intents").fetchone()[0], 1)
        self.hub.close()
        with Hub(self.workspace) as reopened:
            self.assertEqual(reopened.list_jobs()["total"], 0)

    def test_failed_replay_keeps_companions_queryable_without_available_record(self):
        job = submit(self.hub, self.first)
        with patch("poseidon_trident.hub.replay_to_store", side_effect=RuntimeError("synthetic processing fault")):
            self.hub.process_next_job()
        self.assertEqual(self.hub.get_acquisition_companion(job["recording_id"])["job"]["status"], "failed")
        self.assertEqual(self.hub.get_companion_document(job["recording_id"], "source_final")["bytes"], self.first["bytes"]["source_final"])
        self.assert_code("recording_not_found", self.hub.get_recording, job["recording_id"])

    def test_corrupted_documents_hash_rows_projection_and_pins_refused_on_reads_and_restart(self):
        self.hub.close()
        corruptions = {
            "document": ("UPDATE recording_companion_documents SET body = ? WHERE role = 'binding'", b"X" + self.first["bytes"]["binding"][1:]),
            "hash": ("UPDATE recording_companion_documents SET sha256 = ? WHERE role = 'source_receipt'", "0" * 64),
            "projection": ("UPDATE recording_companion_imports SET projection_bytes = ?", b"{}"),
            "projection_hash": ("UPDATE recording_companion_imports SET projection_sha256 = ?", "0" * 64),
            "pin": ("UPDATE acquisition_source_bindings SET final_sha256 = ?", "0" * 64),
        }
        for name, (sql, value) in corruptions.items():
            with self.subTest(corruption=name):
                path = self.root / ("corrupt-" + name)
                self.hub = Hub(path)
                context(self.hub)
                submit(self.hub, self.first)
                with self.hub._workspace.connect() as connection:
                    connection.execute(sql, (value,))
                self.assert_code("companion_store_error", self.hub.get_acquisition_companion, "synthetic-first")
                self.assert_code("companion_store_error", self.hub.get_companion_document, "synthetic-first", "export_receipt")
                self.hub.close()
                before = (path / "hub.sqlite3").read_bytes()
                with self.assertRaises(HubError) as caught:
                    Hub(path)
                self.assertEqual(caught.exception.code, "companion_store_error")
                self.assertEqual((path / "hub.sqlite3").read_bytes(), before)

    def test_hash_rewritten_projection_corruption_still_fails_actual_reader_comparison(self):
        submit(self.hub, self.first)
        projection = json.loads(self.first["validated"].projection_bytes)
        projection["verification"]["acquisition_completeness_verified"] = True
        raw = json.dumps(projection).encode()
        with self.hub._workspace.connect() as connection:
            connection.execute("UPDATE recording_companion_imports SET projection_bytes = ?, projection_sha256 = ?", (raw, hashlib.sha256(raw).hexdigest()))
        self.assert_code("companion_store_error", self.hub.get_acquisition_companion, "synthetic-first")

    def test_hash_rewritten_raw_companion_corruption_fails_the_actual_reader(self):
        submit(self.hub, self.first)
        altered = rewrite_binding(self.first, lambda body: body["time"].update({"combined_start_uncertainty_s": "0"}))
        with self.hub._workspace.connect() as connection:
            for role in ("binding", "export_receipt"):
                raw = altered["bytes"][role]
                connection.execute("UPDATE recording_companion_documents SET body = ?, byte_count = ?, sha256 = ? WHERE role = ?",
                                   (raw, len(raw), hashlib.sha256(raw).hexdigest(), role))
        self.assert_code("companion_store_error", self.hub.get_acquisition_companion, "synthetic-first")
        self.assert_code("companion_store_error", self.hub.get_companion_document, "synthetic-first", "source_header")
        self.hub.close()
        with self.assertRaises(HubError) as caught:
            Hub(self.workspace)
        self.assertEqual(caught.exception.code, "companion_store_error")

    def test_v2_to_v3_migration_preserves_platform_rows_and_files(self):
        self.hub.submit_demo()
        self.hub.process_next_job()
        self.hub.close()
        with closing(sqlite3.connect(self.workspace / "hub.sqlite3")) as connection, connection:
            for table in reversed({**COMPANION_COLUMNS, **CONTROL_COLUMNS}):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("PRAGMA user_version = 2")
            connection.execute("UPDATE metadata SET value = '2' WHERE key = 'workspace_schema'")
            original = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in {**_EXPECTED_COLUMNS, **PLATFORM_COLUMNS} if table != "metadata"}
        files = {path.relative_to(self.workspace).as_posix(): path.read_bytes() for path in self.workspace.rglob("*") if path.is_file() and path.name != "hub.sqlite3"}
        with Hub(self.workspace) as reopened:
            with reopened._workspace.connect(read_only=True) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], HUB_SCHEMA_VERSION)
                for table, rows in original.items():
                    self.assertEqual([tuple(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()], rows)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual({path.relative_to(self.workspace).as_posix(): path.read_bytes() for path in self.workspace.rglob("*") if path.is_file() and path.name != "hub.sqlite3"}, files)

    def test_v2_failed_migration_is_fully_rolled_back(self):
        self.hub.close()
        with closing(sqlite3.connect(self.workspace / "hub.sqlite3")) as connection, connection:
            for table in reversed({**COMPANION_COLUMNS, **CONTROL_COLUMNS}):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("PRAGMA user_version = 2")
            connection.execute("UPDATE metadata SET value = '2' WHERE key = 'workspace_schema'")
        with patch("poseidon_trident.workspace.COMPANION_SQL", "CREATE TABLE interrupted (id TEXT); INVALID SQL;"):
            with self.assertRaises(HubError) as caught:
                Hub(self.workspace)
            self.assertEqual(caught.exception.code, "migration_failed")
        with closing(sqlite3.connect(self.workspace / "hub.sqlite3")) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'interrupted'").fetchone())


if __name__ == "__main__":
    unittest.main()
