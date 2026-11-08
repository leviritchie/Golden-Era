import json
import struct
import unittest
from pathlib import Path

from repair_glb_json_padding import repair_json_padding


class JsonPaddingRepairTests(unittest.TestCase):
    def test_only_trailing_json_nuls_are_replaced(self):
        payload = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode()
        payload += (b" " + b"\x00") * ((4 - len(payload) % 4) // 2)
        payload += b"\x00" * ((4 - len(payload) % 4) % 4)
        binary = b"\x01\x02\x03\x00"
        blob = bytearray(b"glTF" + struct.pack("<I", 2))
        blob += struct.pack("<I", 12 + 8 + len(payload) + 8 + len(binary))
        blob += struct.pack("<I4s", len(payload), b"JSON") + payload
        blob += struct.pack("<I4s", len(binary), b"BIN\x00") + binary
        directory = Path("artifacts/homm3_mocap_v2/.json_padding_test")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "candidate.glb"
        try:
            path.write_bytes(blob)
            self.assertTrue(repair_json_padding(path))
            repaired = path.read_bytes()
            length = struct.unpack_from("<I", repaired, 12)[0]
            chunk = repaired[20 : 20 + length]
            json.loads(chunk.decode("utf-8"))
            self.assertNotIn(b"\x00", chunk)
            self.assertFalse(repair_json_padding(path))
        finally:
            if path.exists():
                path.unlink()
            if directory.exists():
                directory.rmdir()


if __name__ == "__main__":
    unittest.main()
