"""Explicit Linux ABI adapter. Import/constructor/denials never load a library.

Only LinuxBackendFactory consumes the shared live_gate admission. Private test
function tables are always synthetic and never satisfy production admission.
"""
from __future__ import annotations

import ctypes as C
from hashlib import sha256
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

from .live_models import BackendFault, CapturedBlockV1, canonical, parse_canonical

ABI_VERSION = 1
PRODUCTION_LINUX, TEST_FAKE = 1, 2
OK, AGAIN, CANCELLED, FAULT = 0, 1, 2, 3
MAX_CHUNK = 8 * 1024 * 1024
VALID_STATUS, VALID_HTSTAMP, VALID_TRIGGER = 1, 2, 4
VALID_AUDIO_STAMP, VALID_ACCURACY, VALID_HOST, VALID_VIDEO_STAMP = 8, 16, 32, 64
U32, I32, I64 = C.c_uint32, C.c_int32, C.c_int64


def _fields(names, typ=U32):
    return [(name, typ) for name in names.split()]


class Error(C.Structure):
    _fields_ = _fields("abi_version struct_size domain") + [("code", I32)]


class Identity(C.Structure):
    _fields_ = _fields("abi_version struct_size kind pointer_bits") + [("build_sha256", C.c_char * 65), ("profile_sha256", C.c_char * 65)]


class AudioConfig(C.Structure):
    _fields_ = _fields("abi_version struct_size card device subdevice channels rate chunk_frames period_frames period_min period_max buffer_frames buffer_min buffer_max max_chunk_bytes max_poll_descriptors") + [("expected_pcm_id", C.c_char * 64)]


class AudioActual(C.Structure):
    _fields_ = _fields("abi_version struct_size channels rate period_frames buffer_frames poll_descriptors format_s16_le") + [("pcm_id", C.c_char * 64)]


class VideoConfig(C.Structure):
    _fields_ = _fields("abi_version struct_size video_index width height buffer_count max_buffer_bytes max_mapped_bytes max_chunk_bytes cadence_numerator cadence_denominator") + [("expected_driver", C.c_char * 16), ("expected_card", C.c_char * 32), ("expected_bus_info", C.c_char * 32)]


class VideoActual(C.Structure):
    _fields_ = _fields("abi_version struct_size width height bytesperline sizeimage buffer_count mapped_bytes colorspace ycbcr_enc quantization xfer_func cadence_numerator cadence_denominator cadence_valid") + [("driver", C.c_char * 16), ("card", C.c_char * 32), ("bus_info", C.c_char * 32)]


class AudioRecord(C.Structure):
    _fields_ = _fields("abi_version struct_size valid frames bytes state audio_actual_type audio_report_valid audio_accuracy_report audio_accuracy_ns") + _fields("available_frames delay_frames htstamp_sec htstamp_nsec trigger_sec trigger_nsec audio_sec audio_nsec host_before_ns host_after_ns", I64)


class VideoRecord(C.Structure):
    _fields_ = _fields("abi_version struct_size valid bytes sequence raw_flags field timestamp_domain_flags timestamp_source_flags bytesused mapped_length bytesperline sizeimage padding_removed sequence_wrapped") + _fields("timestamp_sec timestamp_usec host_before_ns host_after_ns", I64)


RECORDS = (Error, Identity, AudioConfig, AudioActual, VideoConfig, VideoActual, AudioRecord, VideoRecord)


def _init(cls):
    value = cls()
    value.abi_version, value.struct_size = ABI_VERSION, C.sizeof(cls)
    return value


def _header(value):
    if value.abi_version != ABI_VERSION or value.struct_size != C.sizeof(value):
        raise BackendFault("native_record_layout", "abi")


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BackendFault("explicit_native_sha256_required", "admission")
    return value


def _cstring(value: str, cap: int) -> bytes:
    if type(value) is not str:
        raise BackendFault("native_identity_string", "contract")
    try:
        raw = value.encode("ascii")
    except UnicodeError as exc:
        raise BackendFault("native_identity_ascii", "contract") from exc
    if not raw or len(raw) >= cap or b"\0" in raw:
        raise BackendFault("native_identity_bounds", "contract")
    return raw


def _record_dict(value):
    result = {}
    for key, _ in value._fields_:
        item = getattr(value, key)
        result[key] = item.decode("ascii", errors="strict") if isinstance(item, bytes) else item
    return result


def _check_status(status, error, *, retry=False):
    _header(error)
    if status in (OK, AGAIN, CANCELLED):
        if error.domain != 0 or error.code != 0:
            raise BackendFault("native_success_error_mismatch", "abi")
        if status == OK or (retry and status == AGAIN):
            return status
        raise BackendFault("native_cancelled" if status == CANCELLED else "unexpected_native_retry", "cancellation" if status == CANCELLED else "abi")
    if status != FAULT or error.domain not in (1, 2, 3) or error.code == 0:
        raise BackendFault("native_status_domain", "abi")
    if (error.domain == 2 and error.code >= 0) or (error.domain != 2 and error.code <= 0):
        raise BackendFault("native_error_sign", "abi")
    raise BackendFault("native_capture_fault", {1: "errno", 2: "alsa", 3: "contract"}[error.domain], error.code)


class _NativeAPI:
    """Bind every function exactly; validate layout and artifact before any open."""
    def __init__(self, library, *, build_sha256, profile_sha256, test_only=False):
        self.library = library
        self.synthetic = test_only
        signatures = {
            "pt_capture_abi_version": ([], U32),
            "pt_capture_identity": ([C.POINTER(Identity)], I32),
            "pt_capture_size": ([U32], U32),
            "pt_capture_offset": ([U32, U32], U32),
            "pt_copy_yuyv": ([C.POINTER(C.c_uint8), U32, U32, U32, U32, U32, C.POINTER(C.c_uint8), U32, C.POINTER(U32)], I32),
        }
        for prefix, config, actual, record in (("alsa", AudioConfig, AudioActual, AudioRecord), ("v4l2", VideoConfig, VideoActual, VideoRecord)):
            signatures.update({
                f"pt_{prefix}_open": ([C.POINTER(config), C.POINTER(C.c_void_p), C.POINTER(actual), C.POINTER(Error)], I32),
                f"pt_{prefix}_start": ([C.c_void_p, C.POINTER(Error)], I32),
                f"pt_{prefix}_poll_copy": ([C.c_void_p, C.POINTER(C.c_uint8), U32, I32, U32, C.POINTER(record), C.POINTER(Error)], I32),
                f"pt_{prefix}_stop_close": ([C.c_void_p, C.POINTER(Error)], I32),
            })
        try:
            for name, (args, result) in signatures.items():
                fn = getattr(library, name)
                fn.argtypes, fn.restype = args, result
            if library.pt_capture_abi_version() != ABI_VERSION:
                raise BackendFault("native_abi_version", "abi")
            for record_id, cls in enumerate(RECORDS, 1):
                if library.pt_capture_size(record_id) != C.sizeof(cls):
                    raise BackendFault("native_abi_size", "abi")
                for index, (field, _) in enumerate(cls._fields_):
                    if library.pt_capture_offset(record_id, index) != getattr(cls, field).offset:
                        raise BackendFault("native_abi_offset", "abi")
                if library.pt_capture_offset(record_id, len(cls._fields_)) != 2**32 - 1:
                    raise BackendFault("native_abi_extra_field", "abi")
            identity = _init(Identity)
            if library.pt_capture_identity(C.byref(identity)) != OK:
                raise BackendFault("native_identity_call", "abi")
            _header(identity)
            if identity.kind != (TEST_FAKE if test_only else PRODUCTION_LINUX):
                raise BackendFault("test_artifact_not_live" if not test_only else "test_artifact_required", "admission")
            if identity.pointer_bits != C.sizeof(C.c_void_p) * 8:
                raise BackendFault("native_pointer_width", "abi")
            if identity.build_sha256 != _hash(build_sha256).encode() or identity.profile_sha256 != _hash(profile_sha256).encode():
                raise BackendFault("native_build_profile_mismatch", "admission")
            self.identity = _record_dict(identity)
        except (AttributeError, UnicodeError) as exc:
            raise BackendFault("native_symbols_or_identity_missing", "dependency") from exc


class LinuxBackendFactory:
    synthetic = False

    def __init__(self, plan, *, artifact_path, artifact_sha256, build_sha256, profile_sha256):
        self.plan = plan
        self.artifact_path = Path(artifact_path)
        if not self.artifact_path.is_absolute() or ".." in self.artifact_path.parts:
            raise BackendFault("absolute_native_artifact_required", "admission")
        self.artifact_sha256 = _hash(artifact_sha256)
        self.build_sha256, self.profile_sha256 = _hash(build_sha256), _hash(profile_sha256)

    def open(self, source, limits, admission):
        # This call is the only authorization model, and consumes the source ticket.
        from .live_gate import validate_worker_admission
        validate_worker_admission(admission, self.plan, source)
        if sys.platform != "linux" or sys.byteorder != "little" or C.sizeof(C.c_void_p) != 8:
            raise BackendFault("unsupported_linux_native_platform", "dependency")
        if limits != self.plan.limits or source.backend not in ("linux_alsa", "linux_v4l2"):
            raise BackendFault("native_source_plan_mismatch", "admission")
        config = _source_config(source, limits)  # Validate exact native widths before loading.
        fd = path_fd = None
        try:
            # O_PATH inspects the selected artifact without invoking a character
            # device's open method if an operator supplied the wrong file type.
            path_fd = os.open(self.artifact_path, os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW)
            before = os.fstat(path_fd)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 32 * 1024 * 1024:
                raise BackendFault("native_artifact_file_bounds", "dependency")
            fd = os.open(f"/proc/self/fd/{path_fd}", os.O_RDONLY | os.O_CLOEXEC)
            hasher = sha256()
            remaining = before.st_size
            while remaining:
                data = os.read(fd, min(65536, remaining))
                if not data:
                    raise BackendFault("native_artifact_short_read", "dependency")
                remaining -= len(data)
                hasher.update(data)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or hasher.hexdigest() != self.artifact_sha256:
                raise BackendFault("native_artifact_hash", "admission")
            # Load the hashed owned descriptor, not a path replaced after hashing.
            library = C.CDLL(f"/proc/self/fd/{fd}", mode=os.RTLD_LOCAL | os.RTLD_NOW)
            api = _NativeAPI(library, build_sha256=self.build_sha256, profile_sha256=self.profile_sha256)
            return _NativeBackend(api, source, limits, config, admission.expires_monotonic)
        except OSError as exc:
            raise BackendFault("native_dependency_or_artifact_unavailable", "dependency", exc.errno) from exc
        finally:
            if fd is not None:
                os.close(fd)
            if path_fd is not None:
                os.close(path_fd)


def _source_config(source, limits):
    identity = parse_canonical(source.expected_identity_json)
    if source.backend == "linux_alsa":
        match = re.fullmatch(r"/dev/snd/pcmC([0-9]+)D([0-9]+)c", source.device_node or "")
        if not match or set(identity) != {"pcm_id"}:
            raise BackendFault("alsa_selector_identity", "contract")
        values = dict(card=int(match[1]), device=int(match[2]), subdevice=source.subdevice,
                      channels=len(source.channels), rate=source.sample_rate_hz,
                      chunk_frames=limits.chunk_frames, period_frames=source.period_frames,
                      period_min=source.period_frames, period_max=source.period_frames_max,
                      buffer_frames=source.buffer_frames, buffer_min=source.buffer_frames,
                      buffer_max=source.buffer_frames_max, max_chunk_bytes=limits.max_chunk_bytes,
                      max_poll_descriptors=64)
        if any(type(v) is not int or not 0 <= v <= 2**32 - 1 for v in values.values()):
            raise BackendFault("alsa_fixed_width_bounds", "contract")
        if max(values[k] for k in ("card", "device", "subdevice")) > 65535 or source.buffer_frames_max * len(source.channels) * 2 > MAX_CHUNK:
            raise BackendFault("alsa_native_budget", "contract")
        config = _init(AudioConfig)
        config.expected_pcm_id = _cstring(identity["pcm_id"], 64)
    elif source.backend == "linux_v4l2":
        match = re.fullmatch(r"/dev/video([0-9]+)", source.device_node or "")
        if not match or set(identity) != {"driver", "card", "bus_info"}:
            raise BackendFault("v4l2_selector_identity", "contract")
        values = dict(video_index=int(match[1]), width=source.width, height=source.height,
                      buffer_count=source.mapped_buffers, max_buffer_bytes=min(limits.max_chunk_bytes, source.mapped_bytes),
                      max_mapped_bytes=source.mapped_bytes, max_chunk_bytes=limits.max_chunk_bytes,
                      cadence_numerator=source.frame_rate_den or 0, cadence_denominator=source.frame_rate_num or 0)
        if any(type(v) is not int or not 0 <= v <= 2**32 - 1 for v in values.values()) or values["video_index"] > 65535 or source.mapped_bytes > 8 * MAX_CHUNK:
            raise BackendFault("v4l2_fixed_width_bounds", "contract")
        config = _init(VideoConfig)
        for key, cap in (("driver", 16), ("card", 32), ("bus_info", 32)):
            setattr(config, "expected_" + key, _cstring(identity[key], cap))
    else:
        raise BackendFault("native_backend_required", "contract")
    for key, value in values.items():
        setattr(config, key, value)
    return config


class _NativeBackend:
    def __init__(self, api, source, limits, config, admission_expiry):
        self.api, self.source, self.limits, self.config = api, source, limits, config
        self.synthetic = api.synthetic
        self.expiry = admission_expiry
        self.handle = C.c_void_p()
        self.pipe = None
        self.started = self.configured = self.closed = False
        self.deadline = None
        self.previous_sequence = self.previous_flags = None
        self.previous_audio_report = None
        self.prefix = "alsa" if source.kind == "audio" else "v4l2"
        self.actual = _init(AudioActual if self.prefix == "alsa" else VideoActual)
        self.scratch = (C.c_uint8 * limits.max_chunk_bytes)()
        try:
            if time.monotonic() >= self.expiry:
                raise BackendFault("native_admission_expired_before_open", "admission")
            # Pipes are owned IPC, not device descriptors; created after artifact admission.
            self.pipe = os.pipe()
            for fd in self.pipe:
                os.set_inheritable(fd, False)
                os.set_blocking(fd, False)
            error = _init(Error)
            result = self._fn("open")(C.byref(config), C.byref(self.handle), C.byref(self.actual), C.byref(error))
            _check_status(result, error)
            if not self.handle.value:
                raise BackendFault("native_null_handle", "abi")
            _header(self.actual)
            self._validate_actual()
        except BaseException:
            self._close_suppress()
            raise

    def _fn(self, suffix):
        return getattr(self.api.library, f"pt_{self.prefix}_{suffix}")

    def _validate_actual(self):
        a, c = self.actual, self.config
        if self.prefix == "alsa":
            if (a.channels != c.channels or a.rate != c.rate or a.format_s16_le != 1 or
                    not c.period_min <= a.period_frames <= c.period_max or
                    not c.buffer_min <= a.buffer_frames <= c.buffer_max or a.period_frames > a.buffer_frames or
                    not 1 <= a.poll_descriptors <= c.max_poll_descriptors or a.pcm_id != c.expected_pcm_id):
                raise BackendFault("alsa_returned_configuration", "abi")
        else:
            from poseidon_nereid.live_yuyv import YUYVLayout, YUYVError
            if (a.width != c.width or a.height != c.height or not 1 <= a.buffer_count <= c.buffer_count or
                    not a.sizeimage * a.buffer_count <= a.mapped_bytes <= c.max_mapped_bytes or a.sizeimage > c.max_buffer_bytes or
                    a.cadence_valid not in (0, 1) or bool(a.cadence_valid) != bool(c.cadence_numerator) or
                    (a.cadence_valid and (not (a.cadence_numerator and a.cadence_denominator) or
                     a.cadence_numerator * c.cadence_denominator != c.cadence_numerator * a.cadence_denominator)) or
                    a.driver != c.expected_driver or a.card != c.expected_card or a.bus_info != c.expected_bus_info):
                raise BackendFault("v4l2_returned_configuration", "abi")
            try:
                YUYVLayout(a.width, a.height, a.bytesperline, a.sizeimage, a.sizeimage, a.sizeimage, c.max_chunk_bytes)
            except YUYVError as exc:
                raise BackendFault("v4l2_returned_layout", "abi") from exc

    def configure(self):
        if self.closed or self.started:
            raise BackendFault("native_configuration_state", "contract")
        self.configured = True
        return canonical({"source_id": self.source.source_id, "source_plan_sha256": self.source.sha256,
                          "format": self.source.format, "synthetic": self.synthetic,
                          "device_access_occurred": not self.synthetic,
                          "requested": _record_dict(self.config), "actual": _record_dict(self.actual),
                          "native_identity": self.api.identity, "clock_quality": "unknown", "clock_relation": None,
                          "calibration_status": "uncalibrated", "hardware_qualification_established": False})

    def start(self):
        if self.closed or self.started or not self.configured:
            raise BackendFault("native_start_state", "contract")
        if time.monotonic() >= self.expiry:
            self._close_suppress()
            raise BackendFault("native_admission_expired_before_start", "admission")
        error = _init(Error)
        try:
            requested_at = time.monotonic()
            _check_status(self._fn("start")(self.handle, C.byref(error)), error)
            self.started = True
            self.deadline = requested_at + self.limits.duration_s
            if time.monotonic() >= self.deadline:
                raise BackendFault("native_start_exceeded_duration", "resource")
        except BaseException:
            self._close_suppress()
            raise

    def read(self, timeout_s):
        if self.closed or not self.started:
            raise BackendFault("native_read_state", "contract")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= self.limits.poll_timeout_s:
            raise BackendFault("native_poll_timeout_bounds", "contract")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self._close_suppress()
            raise BackendFault("native_duration_limit", "resource")
        record = _init(AudioRecord if self.prefix == "alsa" else VideoRecord)
        error = _init(Error)
        timeout_ms = max(1, min(60000, math.ceil(min(timeout_s, remaining) * 1000)))
        try:
            status = self._fn("poll_copy")(self.handle, self.scratch, len(self.scratch), self.pipe[0], timeout_ms, C.byref(record), C.byref(error))
            if _check_status(status, error, retry=True) == AGAIN:
                return None
            _header(record)
            if not 0 < record.bytes <= len(self.scratch):
                raise BackendFault("native_payload_length", "abi")
            # Copy to immutable owned bytes before the next call can reuse scratch.
            payload = bytes(self.scratch[:record.bytes])
            if self.prefix == "alsa":
                metadata = self._audio_metadata(record)
                units, sequence = record.frames, None
            else:
                metadata = self._video_metadata(record)
                units, sequence = 1, record.sequence
            metadata.update({"payload_sha256": sha256(payload).hexdigest(), "synthetic": self.synthetic,
                             "device_access_occurred": not self.synthetic, "physical_loss_units": None,
                             "physical_uncertainty_s": None, "utc": None})
            return CapturedBlockV1(payload, units, canonical(metadata), sequence)
        except BaseException:
            self._close_suppress()
            raise

    @staticmethod
    def _host(r):
        if r.valid & VALID_HOST:
            if r.host_before_ns < 0 or r.host_after_ns < r.host_before_ns:
                raise BackendFault("native_host_bracket", "abi")
            return {"clock": "host_monotonic", "before_ns": r.host_before_ns, "after_ns": r.host_after_ns}
        return None

    def _audio_metadata(self, r):
        if r.valid & ~(VALID_STATUS | VALID_HTSTAMP | VALID_TRIGGER | VALID_AUDIO_STAMP | VALID_ACCURACY | VALID_HOST):
            raise BackendFault("audio_validity_flags", "abi")
        if not 1 <= r.frames <= self.config.chunk_frames or r.bytes != r.frames * self.config.channels * 2:
            raise BackendFault("audio_short_read_count", "abi")
        if r.audio_report_valid not in (0, 1) or r.audio_accuracy_report not in (0, 1) or r.audio_actual_type > 5:
            raise BackendFault("audio_timestamp_report", "abi")
        if bool(r.valid & VALID_AUDIO_STAMP) != bool(r.audio_report_valid) or bool(r.valid & VALID_ACCURACY) != bool(r.audio_report_valid and r.audio_accuracy_report):
            raise BackendFault("audio_timestamp_validity", "abi")
        if r.valid & VALID_STATUS and (r.state != 3 or r.available_frames < 0):
            raise BackendFault("audio_not_running", "alsa", -5)
        report_key = (r.audio_report_valid, r.audio_actual_type)
        if self.previous_audio_report is not None and self.previous_audio_report != report_key:
            raise BackendFault("audio_timestamp_type_change", "contract")
        self.previous_audio_report = report_key
        def stamp(bit, sec, ns):
            if not r.valid & bit:
                return None
            if sec < 0 or not 0 <= ns < 1_000_000_000:
                raise BackendFault("audio_timestamp_range", "abi")
            return {"seconds": sec, "nanoseconds": ns}
        return {"validity_flags": r.valid, "frames": r.frames,
                "state": r.state if r.valid & VALID_STATUS else None,
                "available_frames": r.available_frames if r.valid & VALID_STATUS else None,
                "delay_frames": r.delay_frames if r.valid & VALID_STATUS else None,
                "status_htstamp": stamp(VALID_HTSTAMP, r.htstamp_sec, r.htstamp_nsec),
                "trigger_htstamp": stamp(VALID_TRIGGER, r.trigger_sec, r.trigger_nsec),
                "audio_htstamp": stamp(VALID_AUDIO_STAMP, r.audio_sec, r.audio_nsec),
                "audio_type_requested": 1, "audio_report_valid": bool(r.audio_report_valid),
                "audio_actual_type": r.audio_actual_type, "audio_accuracy_report": bool(r.audio_accuracy_report),
                "audio_accuracy_ns": r.audio_accuracy_ns if r.valid & VALID_ACCURACY else None,
                "host_delivery": self._host(r)}

    def _video_metadata(self, r):
        from poseidon_nereid.live_yuyv import YUYVLayout, YUYVError, raw_timestamp, sequence_step
        a, c = self.actual, self.config
        try:
            if r.valid & ~(VALID_HOST | VALID_VIDEO_STAMP) or r.bytesperline != a.bytesperline or r.sizeimage != a.sizeimage or r.mapped_length > c.max_buffer_bytes:
                raise BackendFault("video_record_configuration", "abi")
            layout = YUYVLayout(a.width, a.height, r.bytesperline, r.sizeimage, r.mapped_length, r.bytesused, c.max_chunk_bytes)
            wrap = sequence_step(self.previous_sequence, r.sequence)
            timing = raw_timestamp(flags=r.raw_flags, field=r.field, seconds=r.timestamp_sec, microseconds=r.timestamp_usec,
                                   valid=bool(r.valid & VALID_VIDEO_STAMP), previous_flags=self.previous_flags)
            if (r.bytes != layout.payload_bytes or r.padding_removed != int(layout.padding_removed) or r.sequence_wrapped != int(wrap) or
                    r.timestamp_domain_flags != timing["timestamp_domain_flags"] or r.timestamp_source_flags != timing["timestamp_source_flags"]):
                raise BackendFault("video_record_arithmetic", "abi")
        except YUYVError as exc:
            raise BackendFault("video_layout_or_discontinuity", "contract") from exc
        self.previous_sequence, self.previous_flags = r.sequence, r.raw_flags
        return {"validity_flags": r.valid, "raw_timestamp": timing, "driver_sequence": r.sequence,
                "sequence_wrapped": wrap, "original_stride": r.bytesperline, "original_sizeimage": r.sizeimage,
                "original_bytesused": r.bytesused, "mapped_length": r.mapped_length,
                "padding_removed": bool(r.padding_removed), "operation": "active-yuyv-rows-chroma-unchanged",
                "full_kernel_buffer_byte_identical": False, "host_delivery": self._host(r)}

    def cancel(self):
        if self.pipe is not None and not self.closed:
            try:
                os.write(self.pipe[1], b"x")
            except BlockingIOError:
                pass

    def _close_suppress(self):
        try:
            self.close()
        except Exception:
            pass  # Preserve the primary failure; normal close reports its own native error.

    def close(self):
        if self.closed:
            return
        self.closed = True
        handle, self.handle = self.handle, C.c_void_p()
        try:
            if handle.value:
                error = _init(Error)
                _check_status(self._fn("stop_close")(handle, C.byref(error)), error)
        finally:
            pipe, self.pipe = self.pipe, None
            if pipe is not None:
                for fd in pipe:
                    os.close(fd)
