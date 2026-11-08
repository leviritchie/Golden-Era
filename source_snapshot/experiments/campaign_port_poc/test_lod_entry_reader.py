from __future__ import annotations

import struct
import unittest
import uuid
import zlib
from pathlib import Path
from unittest.mock import patch

import port_homecoming_poc as poc

ROOT = Path(__file__).resolve().parents[2]


def _lod(entries: list[tuple[str, bytes, bool]], *, trailing_bytes: int = 0) -> bytes:
    table_end = 92 + 32 * len(entries)
    header = bytearray(92)
    header[:4] = b"LOD\0"
    struct.pack_into("<I", header, 8, len(entries))
    records = bytearray()
    payloads = bytearray()
    for name, payload, compressed in entries:
        stored = zlib.compress(payload) if compressed else payload
        records.extend(name.encode("ascii")[:16].ljust(16, b"\0"))
        records.extend(
            struct.pack(
                "<IIII",
                table_end + len(payloads),
                len(payload),
                0,
                len(stored) if compressed else 0,
            )
        )
        payloads.extend(stored)
    return bytes(header + records + payloads + bytes(trailing_bytes))


class LodEntryReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / f".lod-reader-{uuid.uuid4().hex}.lod"
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))

    def _write(self, data: bytes) -> None:
        self.path.write_bytes(data)

    def test_reads_compressed_and_uncompressed_entries_case_insensitively(self) -> None:
        self._write(_lod([("Raw.bin", b"raw data", False), ("Packed.bin", b"packed data" * 20, True)]))
        self.assertEqual(poc.read_lod_entry(self.path, "raw.BIN"), b"raw data")
        self.assertEqual(poc.read_lod_entry(self.path, "PACKED.BIN"), b"packed data" * 20)

    def test_missing_entry_raises_file_not_found(self) -> None:
        self._write(_lod([("present.bin", b"present", False)]))
        with self.assertRaises(FileNotFoundError):
            poc.read_lod_entry(self.path, "missing.bin")

    def test_rejects_truncated_header_and_table(self) -> None:
        self._write(b"LOD\0" + bytes(20))
        with self.assertRaisesRegex(ValueError, "header"):
            poc.read_lod_entry(self.path, "x")

        header = bytearray(92)
        header[:4] = b"LOD\0"
        struct.pack_into("<I", header, 8, 1)
        self._write(bytes(header))
        with self.assertRaisesRegex(ValueError, "entry table"):
            poc.read_lod_entry(self.path, "x")

    def test_rejects_out_of_bounds_member_and_bad_compression(self) -> None:
        data = bytearray(_lod([("bad.bin", b"ok", False)]))
        struct.pack_into("<I", data, 92 + 16, len(data) - 1)
        struct.pack_into("<I", data, 92 + 20, 8)
        self._write(bytes(data))
        with self.assertRaisesRegex(ValueError, "invalid bounds"):
            poc.read_lod_entry(self.path, "bad.bin")

        data = bytearray(_lod([("bad.bin", b"payload", True)]))
        data[-1] ^= 0xFF
        self._write(bytes(data))
        with self.assertRaisesRegex(ValueError, "compressed LOD entry"):
            poc.read_lod_entry(self.path, "bad.bin")

        data = bytearray(_lod([("bad.bin", b"payload", True)]))
        compressed_size = struct.unpack_from("<I", data, 92 + 28)[0]
        struct.pack_into("<I", data, 92 + 28, compressed_size - 1)
        data.pop()
        offset = struct.unpack_from("<I", data, 92 + 16)[0]
        self.assertEqual(offset + compressed_size - 1, len(data))
        self._write(bytes(data))
        with self.assertRaisesRegex(ValueError, "uncompressed size"):
            poc.read_lod_entry(self.path, "bad.bin")

        data = bytearray(_lod([("bad.bin", b"payload", True)]))
        struct.pack_into("<I", data, 92 + 20, len(b"payload") - 1)
        self._write(bytes(data))
        with self.assertRaisesRegex(ValueError, "exceeds declared size"):
            poc.read_lod_entry(self.path, "bad.bin")

    def test_reads_only_header_index_and_requested_member(self) -> None:
        archive = _lod([("wanted.bin", b"small", False)], trailing_bytes=1024 * 1024)
        self._write(archive)
        original_open = Path.open

        class CountingReader:
            def __init__(self, stream):
                self.stream = stream
                self.bytes_read = 0

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def read(self, size=-1):
                data = self.stream.read(size)
                self.bytes_read += len(data)
                return data

            def __getattr__(self, name):
                return getattr(self.stream, name)

        readers: list[CountingReader] = []

        def tracked_open(path, *args, **kwargs):
            reader = CountingReader(original_open(path, *args, **kwargs))
            readers.append(reader)
            return reader

        with patch.object(Path, "open", tracked_open):
            self.assertEqual(poc.read_lod_entry(self.path, "wanted.bin"), b"small")
        self.assertEqual(len(readers), 1)
        self.assertEqual(readers[0].bytes_read, 92 + 32 + len(b"small"))


if __name__ == "__main__":
    unittest.main()
