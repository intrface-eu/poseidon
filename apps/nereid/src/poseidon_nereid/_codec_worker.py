"""Internal owned native-codec process. No devices, URLs or external media opens."""
from __future__ import annotations

import ctypes
from fractions import Fraction
import io
import math
from pathlib import Path
import resource
import sys

from poseidon_acoustic.session import SessionError, canonical, load_json, publish, read_bounded, sha256
from .codec import DecodeLimits, MAX_METADATA, PINNED_AV, declaration, pair
from .codec_mp4 import preflight
from .video import encode_pgm


def _bundled_libraries(av, native):
    class DlInfo(ctypes.Structure):
        _fields_ = [("name", ctypes.c_char_p), ("base", ctypes.c_void_p),
                    ("symbol", ctypes.c_char_p), ("address", ctypes.c_void_p)]
    loader = ctypes.CDLL("libdl.so.2") if sys.platform.startswith("linux") else ctypes.CDLL(None)
    loader.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
    loader.dladdr.restype = ctypes.c_int
    package = Path(av.__file__).resolve().parent
    roots = (package / ".dylibs", package.parent / "av.libs")
    result = {}
    for symbol in ("avcodec_version", "avformat_version", "avutil_version"):
        info = DlInfo()
        if not loader.dladdr(ctypes.cast(getattr(native, symbol), ctypes.c_void_p), ctypes.byref(info)) or not info.name:
            raise SessionError("cannot attest loaded codec library location")
        path = Path(info.name.decode()).resolve()
        if not any(path.is_relative_to(root) for root in roots):
            raise SessionError("codec library is not bundled in the pinned PyAV wheel")
        result[symbol] = str(path.relative_to(package.parent))
    return result


def _native_environment(limits):
    if sys.version_info[:2] != (3, 12):
        raise SessionError("recorded codecs require the locked apps/nereid/.venv Python 3.12 environment")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (max(1, math.ceil(limits.timeout_s)), max(2, math.ceil(limits.timeout_s) + 1)))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_storage_bytes, limits.max_storage_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    memory = "10-ms parent RSS watchdog; macOS has no RLIMIT_AS enforcement"
    if sys.platform.startswith("linux"):
        address_limit = 2 * limits.max_rss_bytes
        resource.setrlimit(resource.RLIMIT_AS, (address_limit, address_limit))
        memory = f"RLIMIT_AS={address_limit} plus 10-ms parent RSS watchdog"
    elif sys.platform != "darwin":
        raise SessionError("native codec resource controls require Linux or macOS")
    try:
        import av
    except ImportError as exc:
        raise SessionError("PyAV unavailable: use apps/nereid/.venv after uv sync --locked; codec tests must not skip") from exc
    if av.__version__ != PINNED_AV:
        raise SessionError(f"requires locked PyAV {PINNED_AV}, found {av.__version__}")
    native = ctypes.CDLL(av._core.__file__)
    native.av_max_alloc.argtypes = [ctypes.c_size_t]
    native.av_max_alloc.restype = None
    native.av_max_alloc(16 * 1024 * 1024)
    native.avcodec_configuration.restype = ctypes.c_char_p
    native.avcodec_license.restype = ctypes.c_char_p
    av.logging.set_level(av.logging.PANIC)
    details = {"pyav": av.__version__, "python": sys.version.split()[0], "libraries": av.library_versions,
               "bundled_library_paths": _bundled_libraries(av, native),
               "avcodec_configuration": native.avcodec_configuration().decode(),
               "avcodec_license": native.avcodec_license().decode(),
               "implementation": "FFmpeg software h264, thread_count=1; no HWAccel or subprocess ffmpeg",
               "resource_controls": {"memory": memory, "max_native_single_allocation_bytes": 16 * 1024 * 1024,
                                     "cpu_limit_s": math.ceil(limits.timeout_s), "no_core_dump": True,
                                     "hard_wall_timeout_s": limits.timeout_s, "network_protocols": "none",
                                     "security_sandbox": False}}
    return av, details


def _no_external_open(*args, **kwargs):
    raise OSError("external codec I/O refused; only the supplied in-memory local MP4 is readable")


def _validate_access_unit(data: bytes, length_size: int):
    """avc1 only: a bounded sample must contain exactly one picture start.

    Reject in-band parameter changes and multiple pictures per sample before
    decode(), whose returned Python list otherwise could hold many frames.
    """
    cursor, nal_count, picture_starts, slices = 0, 0, 0, 0
    while cursor < len(data):
        if cursor + length_size > len(data):
            raise SessionError("truncated H264 NAL length")
        size = int.from_bytes(data[cursor:cursor + length_size], "big")
        cursor += length_size
        nal_count += 1
        if not size or cursor + size > len(data) or nal_count > 64:
            raise SessionError("truncated/oversized H264 access unit")
        header = data[cursor]
        kind = header & 31
        if header & 128 or kind not in {1, 5, 6, 9, 12}:
            raise SessionError("unsupported H264 NAL or in-band parameter change")
        if kind in {1, 5}:
            # first_mb_in_slice is the first unsigned Exp-Golomb field.
            prefix = data[cursor + 1:cursor + min(size, 16)].replace(b"\0\0\3", b"\0\0")
            if not prefix or not any(prefix):
                raise SessionError("missing H264 slice header")
            leading = 0
            for byte in prefix:
                if byte:
                    leading += 8 - byte.bit_length()
                    break
                leading += 8
            if leading > 31:
                raise SessionError("unbounded H264 slice header")
            picture_starts += leading == 0
            slices += 1
        cursor += size
    if not slices or picture_starts != 1:
        raise SessionError("one H264 picture per MP4 sample is required")


def _decode(directory: Path, limits, declared, av, details):
    declared = declaration(declared)
    original = read_bounded(directory / "source.mp4", limits.max_input_bytes)
    if sha256(original) != declared["source_sha256"]:
        raise SessionError("worker source checksum mismatch")
    parsed = preflight(original, limits)
    frames, packet_by_pts, decoded_pts = [], {}, set()
    storage = len(original) + len(canonical(declared))
    options = {"enable_drefs": "0", "use_absolute_path": "0", "protocol_whitelist": "",
               "probesize": str(min(len(original), 1024 * 1024)), "analyzeduration": "1000000"}
    with av.open(io.BytesIO(original), mode="r", format="mov", options=options,
                 io_open=_no_external_open) as container:
        if not 0 < len(container.streams) <= limits.max_streams or len(container.streams) != len(parsed["tracks"]):
            raise SessionError("native/container stream count mismatch or budget exceeded")
        streams = [s for s in container.streams if s.index == declared["stream_index"]]
        if len(streams) != 1:
            raise SessionError("requested absolute stream index is absent")
        stream = streams[0]
        codec = stream.codec_context
        if stream.type != "video" or codec.name != "h264":
            raise SessionError("selected stream must be software-decoded H264 video")
        tracks = [t for t in parsed["tracks"] if t["track_id"] == stream.id]
        if len(tracks) != 1 or tracks[0]["sample_description"] != "avc1":
            raise SessionError("selected stream does not bind one avc1 sample table")
        track = tracks[0]
        sample_count = len(track["samples"])
        if sample_count > limits.max_frames or stream.frames != sample_count:
            raise SessionError("selected stream frame count exceeds budget or is ambiguous")
        dimensions = track["original_dimensions"]
        if ([codec.width, codec.height] != dimensions or max(dimensions) > limits.max_dimension
                or dimensions[0] * dimensions[1] > limits.max_pixels):
            raise SessionError("H264 and MP4 dimensions disagree or exceed budget")
        if codec.format is None or codec.format.name != "yuv420p":
            raise SessionError("only decoded 8-bit yuv420p H264 is supported")
        extra = codec.extradata
        if not extra or len(extra) < 7 or len(extra) > 65536 or extra[0] != 1:
            raise SessionError("bounded AVC configuration record required")
        length_size = (extra[4] & 3) + 1
        if length_size not in (1, 2, 4):
            raise SessionError("unsupported AVC NAL length field")
        codec.thread_count = 1
        codec.options = {"max_pixels": str(limits.max_pixels), "err_detect": "explode+crccheck+bitstream+buffer"}
        stream_info = {"index": stream.index, "track_id": stream.id, "codec": codec.name,
                       "time_base": pair(stream.time_base), "start_time": stream.start_time,
                       "duration": stream.duration, "declared_frames": stream.frames,
                       "original_dimensions": dimensions, "original_pixel_format": codec.format.name,
                       "extradata_sha256": sha256(extra),
                       "reported_average_rate_not_used": pair(stream.average_rate) if stream.average_rate else None,
                       "color_primaries_code": codec.color_primaries, "color_transfer_code": codec.color_trc,
                       "display_matrix_not_applied": track["display_matrix"]}
        packet_count = 0
        for packet in container.demux(stream):
            if packet.size:
                if packet_count >= sample_count or packet.is_corrupt:
                    raise SessionError("extra or corrupt encoded packet")
                sample = track["samples"][packet_count]
                if (packet.pos, packet.size) != (sample["offset"], sample["size"]):
                    raise SessionError("packet byte extent does not match original MP4 sample table")
                data = bytes(packet)
                if data != original[packet.pos:packet.pos + packet.size]:
                    raise SessionError("demuxed packet differs from original encoded bytes")
                _validate_access_unit(data, length_size)
                if packet.pts is None or packet.dts is None or packet.time_base is None:
                    raise SessionError("missing encoded packet PTS/DTS/time base")
                pts_key = packet.pts * packet.time_base
                if pts_key in packet_by_pts:
                    raise SessionError("repeated encoded presentation timestamp")
                packet_by_pts[pts_key] = dict(sample, demux_index=packet_count, pts=packet.pts, dts=packet.dts,
                                             duration=packet.duration, time_base=pair(packet.time_base),
                                             sha256=sha256(data), keyframe=packet.is_keyframe,
                                             track_time_base=track["track_time_base"])
                packet_count += 1
            for frame in packet.decode():
                if len(frames) >= limits.max_frames or frame.is_corrupt:
                    raise SessionError("corrupt decoded frame or frame budget exceeded")
                if frame.pts is None or frame.time_base is None:
                    raise SessionError("missing decoded PTS/time base")
                pts_key = frame.pts * frame.time_base
                if pts_key not in packet_by_pts or pts_key in decoded_pts:
                    raise SessionError("decoded frame has no unique source packet association")
                if frames and pts_key <= frames[-1]["pts"] * Fraction(*frames[-1]["time_base"]):
                    raise SessionError("repeated or backwards decoded presentation timestamp")
                decoded_pts.add(pts_key)
                if [frame.width, frame.height] != dimensions or frame.format.name != "yuv420p":
                    raise SessionError("midstream dimension/pixel-format changes refused")
                plane = frame.planes[0]
                raw = bytes(plane)
                pixels = b"".join(raw[y * plane.line_size:y * plane.line_size + frame.width] for y in range(frame.height))
                pgm = encode_pgm(frame.width, frame.height, pixels)
                # Reserve room for the bounded map and a second PGM copy in the
                # existing session. The parent also enforces actual final bytes.
                storage += 2 * len(pgm) + 4096
                if storage + 3 * MAX_METADATA + 8192 > limits.max_storage_bytes:
                    raise SessionError("decoded storage budget exceeded")
                name = f"frame-{len(frames):06d}.pgm"
                publish(directory, name, pgm)
                frames.append({"frame_index": len(frames), "path": name, "sha256": sha256(pgm),
                               "width": frame.width, "height": frame.height,
                               "pts": frame.pts, "time_base": pair(frame.time_base),
                               "decoder_duration": frame.duration,
                               "decoder_duration_basis": "decoder metadata, not an attested presentation/exposure duration",
                               "picture_type": {1: "I", 2: "P", 3: "B"}.get(int(frame.pict_type), str(frame.pict_type)),
                               "keyframe": frame.key_frame, "color_space_code": frame.colorspace,
                               "color_range_code": frame.color_range, "original_pixel_format": frame.format.name,
                               "encoded_sample": packet_by_pts[pts_key]})
        if packet_count != sample_count or len(frames) != sample_count or decoded_pts != set(packet_by_pts):
            raise SessionError("truncated, discarded, duplicated or incomplete frame/sample association")
        if codec.options:
            raise SessionError("native decoder did not consume required pixel/error options")
    if sha256(read_bounded(directory / "source.mp4", limits.max_input_bytes)) != declared["source_sha256"]:
        raise SessionError("archived encoded source changed during native decode")
    return {"decoder": details, "stream": stream_info, "container": parsed, "frames": frames}


def _fixture(directory, limits, av, details):
    pts = [2000, 2040, 2100, 2120, 2200, 2240]
    destination = directory / "synthetic.mp4"
    # Exclusive local file object, never a string passed as a codec URL.
    with destination.open("xb") as output:
        with av.open(output, mode="w", format="mp4") as container:
            container.metadata["title"] = "SYNTHETIC NEREID integer luma fixture, not field evidence"
            stream = container.add_stream("libx264", rate=25)
            stream.width, stream.height, stream.pix_fmt = 32, 24, "yuv420p"
            stream.time_base = Fraction(1, 1000)
            stream.codec_context.time_base = Fraction(1, 1000)
            stream.codec_context.thread_count = 1
            stream.options = {"preset": "medium", "crf": "18",
                              "x264-params": "bframes=2:b-adapt=0:scenecut=0:keyint=30:threads=1"}
            for i, stamp in enumerate(pts):
                frame = av.VideoFrame(32, 24, "yuv420p")
                for channel, plane in enumerate(frame.planes):
                    plane.update(bytes([30 + i * 25 if channel == 0 else 128]) * plane.buffer_size)
                frame.pts, frame.time_base = stamp, Fraction(1, 1000)
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    if destination.stat().st_size > limits.max_input_bytes:
        raise SessionError("synthetic codec fixture exceeds input budget")
    return {"schema": "poseidon.nereid-synthetic-codec-recipe.provisional.v1", "provenance": "synthetic",
            "software_only": True, "biological_classifier": False, "calibration": "none", "encoder": "libx264",
            "environment": details, "pts": pts, "time_base": [1, 1000], "width": 32, "height": 24,
            "luma_rule": "30 + 25 * frame_index; U=V=128; no natural imagery",
            "bframes": 2, "b_adapt": 0, "crf": 18, "preset": "medium",
            "final_display_duration_s": [1, 50], "source_sha256": sha256(read_bounded(destination, limits.max_input_bytes))}


def main():
    job = Path(sys.argv[1]).parent
    try:
        request = load_json(job / "request.json", MAX_METADATA)
        limits = DecodeLimits(**request["limits"])
        av, details = _native_environment(limits)
        directory = Path(request["directory"])
        if request["operation"] == "decode":
            result = _decode(directory, limits, request["declaration"], av, details)
        elif request["operation"] == "fixture":
            result = _fixture(directory, limits, av, details)
        else:
            raise SessionError("unknown internal codec operation")
        payload = canonical(result)
        if len(payload) > MAX_METADATA:
            raise SessionError("worker result exceeds metadata budget")
        publish(job, "result.json", payload)
        return 0
    except Exception as exc:
        publish(job, "result.json", canonical({"error": f"{type(exc).__name__}: {exc}"[:512]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
