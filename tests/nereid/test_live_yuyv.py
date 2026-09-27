"""Pure byte arithmetic and raw driver claims, without video/device access."""
from dataclasses import replace
from hashlib import sha256
import unittest

from poseidon_nereid.live_yuyv import (
    BUFFER_ERROR, FIELD_NONE, TIMESTAMP_MONOTONIC, TIMESTAMP_SOE, UINT32_MAX,
    YUYVError, YUYVLayout, copy_active_rows, raw_timestamp, sequence_step,
)


class YUYVTests(unittest.TestCase):
    def layout(self):
        return YUYVLayout(2, 2, 6, 12, 12, 12, 8)

    def test_padding_removed_chroma_preserved_and_hashes_owned_payload(self):
        source = bytearray((1, 21, 2, 31, 99, 99, 3, 22, 4, 32, 98, 98))
        result = copy_active_rows(source, self.layout())
        source[:] = b"\0"*12
        self.assertEqual(result.payload, bytes((1, 21, 2, 31, 3, 22, 4, 32)))
        self.assertEqual(result.payload_sha256, sha256(result.payload).hexdigest())
        self.assertTrue(result.layout.padding_removed)
        self.assertFalse(result.full_kernel_buffer_byte_identical)

    def test_final_row_padding_need_not_be_initialized(self):
        layout = replace(self.layout(), bytesused=10)
        result = copy_active_rows(bytes(range(10)), layout)
        self.assertEqual(result.payload, bytes((0,1,2,3,6,7,8,9)))

    def test_no_padding_and_owned_memoryview(self):
        layout = YUYVLayout(2, 1, 4, 4, 4, 4, 4)
        data = bytearray(range(4))
        result = copy_active_rows(memoryview(data), layout)
        data[:] = b"\0"*4
        self.assertEqual(result.payload, bytes(range(4)))
        self.assertFalse(result.layout.padding_removed)

    def test_reject_dimensions_and_checked_arithmetic(self):
        for key, value in (("width",3),("width",True),("height",0),("height",2**32-1),("bytesperline",3),
                           ("bytesperline",2**32-1),("sizeimage",9),("mapped_length",11),("bytesused",9),
                           ("bytesused",13),("max_payload_bytes",7)):
            with self.subTest(key=key, value=value), self.assertRaises(YUYVError):
                replace(self.layout(), **{key:value})

    def test_reject_noncontiguous_or_short_buffer(self):
        for data in (bytes(9), bytes(13), memoryview(bytes(24))[::2], "not bytes"):
            with self.assertRaises(YUYVError):
                copy_active_rows(data, self.layout())

    def test_sequence_wrap_is_explicit_not_loss(self):
        self.assertFalse(sequence_step(None, UINT32_MAX))
        self.assertTrue(sequence_step(UINT32_MAX, 0))
        self.assertFalse(sequence_step(0, 1))
        for previous, current in ((0,0),(5,0),(0,2),(0,True),(0,2**32)):
            with self.assertRaises(YUYVError):
                sequence_step(previous,current)

    def test_unknown_clock_and_eof_are_distinct_from_monotonic_soe(self):
        unknown = raw_timestamp(flags=0,field=FIELD_NONE,seconds=0,microseconds=0,valid=True)
        monotonic = raw_timestamp(flags=TIMESTAMP_MONOTONIC|TIMESTAMP_SOE,field=FIELD_NONE,
                                  seconds=4,microseconds=999999,valid=True)
        self.assertEqual((unknown["timestamp_domain"],unknown["timestamp_source"]),("unknown","eof"))
        self.assertEqual((monotonic["timestamp_domain"],monotonic["timestamp_source"]),("monotonic","soe"))
        self.assertEqual(unknown["timestamp_seconds"],0)
        self.assertIsNone(monotonic["physical_exposure_start"])
        self.assertIsNone(monotonic["utc"])

    def test_invalid_timestamp_is_null_not_zero(self):
        value = raw_timestamp(flags=0,field=FIELD_NONE,seconds=0,microseconds=0,valid=False)
        self.assertIsNone(value["timestamp_seconds"])
        self.assertIsNone(value["timestamp_microseconds"])

    def test_error_interlace_unsupported_flags_and_timestamp_refused(self):
        base = dict(flags=0,field=FIELD_NONE,seconds=0,microseconds=0,valid=True)
        for change in ({"flags":BUFFER_ERROR},{"field":2},{"flags":0x4000},{"flags":0x20000},
                       {"seconds":-1},{"microseconds":1000000},{"valid":1},{"field":True}):
            with self.subTest(change=change), self.assertRaises(YUYVError):
                raw_timestamp(**(base|change))

    def test_timestamp_domain_or_source_change_stops(self):
        for flags in (TIMESTAMP_MONOTONIC,TIMESTAMP_SOE):
            with self.assertRaises(YUYVError):
                raw_timestamp(flags=flags,previous_flags=0,field=FIELD_NONE,seconds=0,microseconds=0,valid=True)


if __name__ == "__main__":
    unittest.main()
