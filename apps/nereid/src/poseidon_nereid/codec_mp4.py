"""Bounded, nonfragmented MP4 sample-table preflight, before native decoding.

Not a general ISO BMFF reader. External references, fragments, compressed movie
headers, multiple sample descriptions and non-unit edit rates are unsupported.
"""
from __future__ import annotations

import struct
from fractions import Fraction

from poseidon_acoustic.session import SessionError


MAX_TABLE_ENTRIES = 4096


def _u(data: bytes, offset: int, size: int = 4) -> int:
    if offset < 0 or offset + size > len(data):
        raise SessionError("truncated MP4 field")
    return int.from_bytes(data[offset:offset + size], "big")


def boxes(data: bytes, start: int = 0, end: int | None = None) -> list[tuple[bytes, int, int]]:
    end = len(data) if end is None else end
    result = []
    while start < end:
        if end - start < 8 or len(result) >= MAX_TABLE_ENTRIES:
            raise SessionError("truncated or oversized MP4 box list")
        size, kind = struct.unpack_from(">I4s", data, start)
        header = 8
        if size == 1:
            size, header = _u(data, start + 8, 8), 16
        if size < header or start + size > end:
            raise SessionError("unbounded or truncated MP4 box")
        result.append((kind, start + header, start + size))
        start += size
    return result


def _one(items, kind: bytes, *, optional: bool = False):
    matches = [item for item in items if item[0] == kind]
    if not matches and optional:
        return None
    if len(matches) != 1:
        raise SessionError(f"MP4 requires one {kind.decode('ascii', 'replace')} box")
    return matches[0]


def _children(data, item):
    return boxes(data, item[1], item[2])


def _table(data, item, width: int, *, versions=(0,)):
    payload = data[item[1]:item[2]]
    if len(payload) < 8 or payload[0] not in versions or payload[1:4] != b"\0\0\0":
        raise SessionError("unsupported MP4 table version/flags")
    count = _u(payload, 4)
    if count > MAX_TABLE_ENTRIES or len(payload) != 8 + width * count:
        raise SessionError("MP4 table count/length exceeds bounds")
    return payload, count


def preflight(data: bytes, limits) -> dict:
    top = boxes(data)
    if not top or top[0][0] != b"ftyp" or any(
            kind not in {b"ftyp", b"moov", b"mdat", b"free", b"skip"} for kind, _, _ in top):
        raise SessionError("only nonfragmented self-contained MP4 is supported")
    ftyp = _one(top, b"ftyp")
    brand = data[ftyp[1]:ftyp[2]]
    if len(brand) < 8 or len(brand) % 4 or brand[:4] not in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1"}:
        raise SessionError("unsupported MP4 brand")
    mdats = [(a, b) for kind, a, b in top if kind == b"mdat"]
    if not mdats:
        raise SessionError("MP4 has no local media data")
    movie = _children(data, _one(top, b"moov"))
    if any(kind in {b"mvex", b"cmov", b"rmra"} for kind, _, _ in movie):
        raise SessionError("fragmented/compressed/referenced movie refused")
    mvhd = _one(movie, b"mvhd")
    movie_header = data[mvhd[1]:mvhd[2]]
    if not movie_header or movie_header[0] not in (0, 1):
        raise SessionError("unsupported movie timescale")
    movie_timescale = _u(movie_header, 20 if movie_header[0] else 12)
    if movie_timescale == 0:
        raise SessionError("zero movie timescale")
    tracks = [item for item in movie if item[0] == b"trak"]
    if not 0 < len(tracks) <= limits.max_streams:
        raise SessionError("MP4 stream count exceeds budget")
    result, all_ranges, total_samples = [], [], 0
    for track in tracks:
        children = _children(data, track)
        tkhd = _one(children, b"tkhd")
        header = data[tkhd[1]:tkhd[2]]
        if not header or header[0] not in (0, 1):
            raise SessionError("unsupported track header")
        track_id = _u(header, 20 if header[0] else 12)
        matrix_offset = 52 if header[0] else 40
        if len(header) < matrix_offset + 44:
            raise SessionError("truncated track display matrix")
        display_matrix = list(struct.unpack_from(">9i", header, matrix_offset))
        media = _children(data, _one(children, b"mdia"))
        mdhd = _one(media, b"mdhd")
        header = data[mdhd[1]:mdhd[2]]
        if not header or header[0] not in (0, 1):
            raise SessionError("unsupported media header")
        version = header[0]
        timescale = _u(header, 20 if version else 12)
        duration = _u(header, 24 if version else 16, 8 if version else 4)
        if not timescale or not 0 < Fraction(duration, timescale) <= limits.max_duration_s:
            raise SessionError("MP4 media duration exceeds budget or is missing")
        info = _children(data, _one(media, b"minf"))
        dinf = _children(data, _one(info, b"dinf"))
        dref = _one(dinf, b"dref")
        payload = data[dref[1]:dref[2]]
        if len(payload) < 8 or payload[:4] != b"\0\0\0\0" or _u(payload, 4) != 1:
            raise SessionError("only one self-contained data reference is supported")
        refs = boxes(payload, 8)
        if len(refs) != 1 or refs[0][0] != b"url " or payload[refs[0][1]:refs[0][2]] != b"\0\0\0\1":
            raise SessionError("external MP4 data reference refused")
        table = _children(data, _one(info, b"stbl"))
        stsd = _one(table, b"stsd")
        payload = data[stsd[1]:stsd[2]]
        if len(payload) < 8 or payload[:4] != b"\0\0\0\0" or _u(payload, 4) != 1:
            raise SessionError("multiple sample descriptions are unsupported")
        descriptions = boxes(payload, 8)
        if len(descriptions) != 1 or _u(payload, descriptions[0][1] + 6, 2) != 1:
            raise SessionError("invalid sample description data reference")
        description = descriptions[0]
        dimensions = ([_u(payload, description[1] + 24, 2), _u(payload, description[1] + 26, 2)]
                      if description[0] == b"avc1" else None)
        if dimensions and (not all(dimensions) or max(dimensions) > limits.max_dimension
                           or dimensions[0] * dimensions[1] > limits.max_pixels):
            raise SessionError("MP4 original dimensions exceed pixel budget")
        stsz = _one(table, b"stsz")
        payload = data[stsz[1]:stsz[2]]
        if len(payload) < 12 or payload[:4] != b"\0\0\0\0":
            raise SessionError("invalid sample size table")
        uniform, count = _u(payload, 4), _u(payload, 8)
        total_samples += count
        if not 0 < count <= MAX_TABLE_ENTRIES or total_samples > MAX_TABLE_ENTRIES:
            raise SessionError("MP4 sample count exceeds budget")
        if len(payload) != 12 + (0 if uniform else 4 * count):
            raise SessionError("truncated sample size table")
        sizes = [uniform] * count if uniform else [_u(payload, 12 + i * 4) for i in range(count)]
        if any(not 0 < size <= limits.max_input_bytes for size in sizes):
            raise SessionError("empty or oversized encoded sample")
        stco = _one(table, b"stco", optional=True)
        co64 = _one(table, b"co64", optional=True)
        if (stco is None) == (co64 is None):
            raise SessionError("one chunk offset table required")
        width = 4 if stco else 8
        payload, chunks = _table(data, stco or co64, width)
        offsets = [_u(payload, 8 + width * i, width) for i in range(chunks)]
        payload, entries = _table(data, _one(table, b"stsc"), 12)
        runs = [struct.unpack_from(">III", payload, 8 + i * 12) for i in range(entries)]
        if not runs or runs[0][0] != 1 or any(
                not 0 < first <= chunks or not 0 < samples <= count or description != 1
                or (i and first <= runs[i - 1][0])
                for i, (first, samples, description) in enumerate(runs)):
            raise SessionError("invalid bounded sample-to-chunk table")
        samples, run = [], 0
        for chunk, offset in enumerate(offsets, 1):
            if run + 1 < len(runs) and chunk == runs[run + 1][0]:
                run += 1
            for _ in range(runs[run][1]):
                if len(samples) >= count:
                    raise SessionError("sample-to-chunk count mismatch")
                size = sizes[len(samples)]
                if not any(lo <= offset and offset + size <= hi for lo, hi in mdats):
                    raise SessionError("sample points outside local mdat or is truncated")
                samples.append({"sample_index": len(samples), "offset": offset, "size": size})
                all_ranges.append((offset, offset + size))
                offset += size
        if len(samples) != count:
            raise SessionError("missing MP4 samples")
        payload, entries = _table(data, _one(table, b"stts"), 8)
        dts, index = 0, 0
        for i in range(entries):
            n, delta = struct.unpack_from(">II", payload, 8 + i * 8)
            if n == 0 or delta == 0 or index + n > count:
                raise SessionError("missing, repeated or excessive decode timestamps")
            for sample in samples[index:index + n]:
                sample.update({"track_dts": dts, "track_pts": dts, "track_duration": delta})
                dts += delta
            index += n
        if index != count or Fraction(dts, timescale) > limits.max_duration_s:
            raise SessionError("MP4 timestamp count/decode-duration budget mismatch")
        ctts = _one(table, b"ctts", optional=True)
        if ctts:
            payload, entries = _table(data, ctts, 8, versions=(0, 1))
            index = 0
            for i in range(entries):
                n = _u(payload, 8 + i * 8)
                shift = int.from_bytes(payload[12 + i * 8:16 + i * 8], "big", signed=payload[0] == 1)
                if not n or index + n > count:
                    raise SessionError("invalid composition timestamp table")
                for sample in samples[index:index + n]:
                    sample["track_pts"] += shift
                index += n
            if index != count:
                raise SessionError("missing composition timestamps")
        stss = _one(table, b"stss", optional=True)
        if stss:
            payload, entries = _table(data, stss, 4)
            sync = [_u(payload, 8 + i * 4) for i in range(entries)]
            if sync != sorted(set(sync)) or any(not 1 <= i <= count for i in sync):
                raise SessionError("invalid sync sample table")
        edits = []
        edts = _one(children, b"edts", optional=True)
        if edts:
            elst = _one(_children(data, edts), b"elst")
            payload = data[elst[1]:elst[2]]
            if not payload or payload[0] not in (0, 1):
                raise SessionError("unsupported edit list")
            width = 20 if payload[0] else 12
            payload, entries = _table(data, elst, width, versions=(0, 1))
            if not 1 <= entries <= 2:
                raise SessionError("only one playable edit plus optional initial empty edit supported")
            for i in range(entries):
                fields = struct.unpack_from(">Qqhh" if payload[0] else ">Iihh", payload, 8 + i * width)
                length, media_time, rate, fractional_rate = fields
                if (rate, fractional_rate) != (1, 0) or not length or media_time < -1:
                    raise SessionError("unsupported MP4 edit rate or extent")
                if length > movie_timescale * limits.max_duration_s and media_time != -1:
                    raise SessionError("playable edit duration exceeds budget")
                edits.append({"movie_duration": length, "track_media_time": media_time})
            if edits[-1]["track_media_time"] == -1 or (len(edits) == 2 and edits[0]["track_media_time"] != -1):
                raise SessionError("discontinuous/repeated playable edits refused")
        result.append({"track_id": track_id, "sample_description": descriptions[0][0].decode("ascii", "replace"),
                       "track_time_base": [1, timescale], "track_duration": duration,
                       "original_dimensions": dimensions, "display_matrix": display_matrix,
                       "edit_list": edits, "samples": samples})
    if len({t["track_id"] for t in result}) != len(result):
        raise SessionError("duplicate track identity")
    ranges = sorted(all_ranges)
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
        raise SessionError("overlapping encoded sample byte ranges")
    return {"brand": brand[:4].decode(), "movie_time_base": [1, movie_timescale], "tracks": result}
