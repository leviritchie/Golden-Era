"""Offline safety fixtures for the owner HTTP probe; no cloud service is contacted."""
import base64
import hashlib
import io
import json
import unittest
import urllib.request
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import probe


class ProbeTests(unittest.TestCase):
    def test_fixture_is_deterministic_valid_and_synthetic(self):
        data = probe.synthetic_bundle(False)
        self.assertEqual(data, probe.synthetic_bundle(False))
        self.assertEqual(hashlib.sha256(data).hexdigest(), "28d8e8f21838f93dad9271c9b38481b053c8da62f7bdef8fb58f3cc27c88dbf5")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(json.loads(archive.read("metadata.json"))["synthetic"], True)
            self.assertEqual(archive.read("bepinex-log-tail.txt"), b"SYNTHETIC ONLY: not a game log.\n")
            self.assertEqual(archive.read("native-log-tail.txt"), b"SYNTHETIC ONLY: not a native log.\n")
            self.assertEqual(archive.read("screenshot.png")[:8], b"\x89PNG\r\n\x1a\n")

    def test_limit_fixture_is_exact_and_valid(self):
        data = probe.synthetic_bundle(True)
        self.assertEqual(len(data), probe.MAX_BUNDLE_BYTES)
        self.assertEqual(hashlib.sha256(data).hexdigest(), "f1cbcbb95c1ee9cf5124b17311704000859eaf2e28df15bcb14994a2c04c49dd")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())

    def test_redirect_drops_body_and_rejects_other_hosts_or_flows(self):
        handler = probe.GoogleContentRedirect()
        request = urllib.request.Request("https://script.google.com/macros/s/fixture/exec", data=b"synthetic")
        redirected = handler.redirect_request(request, None, 302, "", {}, "https://script.googleusercontent.com/fixture")
        self.assertEqual(redirected.get_method(), "GET")
        self.assertIsNone(redirected.data)
        for code, url in ((302, "https://accounts.google.com/login"), (307, "https://script.googleusercontent.com/x")):
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, code, "", {}, url)

    def test_no_upload_without_explicit_flag_or_to_unapproved_endpoint(self):
        for args in (("--endpoint", "https://script.google.com/macros/s/fixture/exec"),
                     ("--endpoint", "https://example.com/exec", "--submit-synthetic")):
            with patch("sys.argv", ["probe.py", *args]), patch("sys.stderr", new=io.StringIO()), \
                    patch.object(probe, "submit") as submit:
                with self.assertRaises(SystemExit) as failure:
                    probe.main()
                self.assertEqual(failure.exception.code, 2)
                submit.assert_not_called()

    def test_player_format_and_oversize_flags_use_only_mocked_synthetic_bytes(self):
        endpoint = "https://script.google.com/macros/s/fixture/exec"
        report_id = "00000000-0000-4000-8000-000000000001"
        captured = []

        def fake_submit(url, body):
            captured.append((url, body.copy()))
            return {"reportId": body["reportId"], "sha256": body["sha256"], "duplicate": False}

        with patch("sys.argv", ["probe.py", "--endpoint", endpoint, "--submit-synthetic",
                                 "--player-format", "--oversize", "--report-id", report_id]), \
                patch.object(probe, "submit", side_effect=fake_submit), \
                patch("sys.stdout", new=io.StringIO()) as output:
            result = probe.main()

        self.assertEqual(result, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0], endpoint)
        body = captured[0][1]
        self.assertEqual(body["purpose"], "player-report")
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["clientToken"], probe.CLIENT_TOKEN)
        self.assertEqual(body["reportId"], report_id)
        bundle = base64.b64decode(body["bundleBase64"], validate=True)
        self.assertEqual(len(bundle), probe.MAX_BUNDLE_BYTES + 1)
        self.assertEqual(body["sha256"], hashlib.sha256(bundle).hexdigest())
        with zipfile.ZipFile(io.BytesIO(bundle[:-1])) as archive:
            self.assertIsNone(archive.testzip())
            self.assertTrue(json.loads(archive.read("metadata.json"))["synthetic"])
            self.assertEqual(archive.read("bepinex-log-tail.txt"), b"SYNTHETIC ONLY: not a game log.\n")
            self.assertEqual(archive.read("native-log-tail.txt"), b"SYNTHETIC ONLY: not a native log.\n")
        self.assertIn('"storedBytesClaimed": 8388609', output.getvalue())

    def test_player_format_sends_a_contract_shaped_synthetic_bundle(self):
        endpoint = "https://script.google.com/macros/s/fixture/exec"
        report_id = "00000000-0000-4000-8000-000000000002"
        captured = []

        def fake_submit(url, body):
            captured.append(body.copy())
            return {"reportId": body["reportId"], "sha256": body["sha256"], "duplicate": False}

        with patch("sys.argv", ["probe.py", "--endpoint", endpoint, "--submit-synthetic",
                                 "--player-format", "--report-id", report_id]), \
                patch.object(probe, "submit", side_effect=fake_submit), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(probe.main(), 0)
        body = captured[0]
        self.assertEqual(sorted(body), ["bundleBase64", "clientToken", "purpose", "reportId", "sha256", "version"])
        contract = json.loads((Path(__file__).parent / "bundle_contract.json").read_text(encoding="utf-8"))
        bundle = base64.b64decode(body["bundleBase64"], validate=True)
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            self.assertEqual(set(names), set(contract["entries"]))
            for info in archive.infolist():
                self.assertLessEqual(info.file_size, contract["entries"][info.filename]["maxBytes"])
            report = json.loads(archive.read("report.json"))
        self.assertEqual(sorted(report), sorted(contract["reportFields"]))
        self.assertEqual(report["reportId"], report_id)
        self.assertEqual(report["screenshot"], "included")

        with patch("sys.argv", ["probe.py", "--endpoint", endpoint, "--submit-synthetic", "--player-format",
                                 "--at-limit"]), patch("sys.stderr", new=io.StringIO()), patch.object(probe, "submit") as submit:
            with self.assertRaises(SystemExit):
                probe.main()
            submit.assert_not_called()

    def test_http_success_is_not_report_success_and_never_retries(self):
        body = {"reportId": "synthetic-id", "sha256": "synthetic-sha"}
        for reply, content_type in (({"ok": False, "error": "disabled"}, "application/json"),
                                    ({"ok": True, "reportId": "other", "sha256": "synthetic-sha", "duplicate": False}, "application/json"),
                                    ({"ok": True}, "text/html")):
            class Response:
                status = 200
                headers = Message()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def read(self, count):
                    return json.dumps(reply).encode()

            Response.headers["Content-Type"] = content_type
            with patch.object(probe.urllib.request, "build_opener") as build:
                build.return_value.open.return_value = Response()
                with self.assertRaises(ValueError):
                    probe.submit("https://script.google.com/macros/s/fixture/exec", body)
                self.assertEqual(build.return_value.open.call_count, 1)
                self.assertIsInstance(build.call_args.args[0], probe.GoogleContentRedirect)


if __name__ == "__main__":
    unittest.main()
