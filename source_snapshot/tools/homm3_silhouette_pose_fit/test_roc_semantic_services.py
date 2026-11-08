"""Tests for the process-wide semantic model/target cache."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roc_semantic_services import get_semantic_service, reset_semantic_service_for_tests


class _FakeTensor:
    def __init__(self, device: str = "cuda:0"):
        self.device = device

    def detach(self):
        return self

    def to(self, device, **_kwargs):
        return _FakeTensor(str(device))

    def contiguous(self):
        return self


class SemanticServiceTests(unittest.TestCase):
    def tearDown(self):
        reset_semantic_service_for_tests()

    def test_encoder_instances_are_reused_by_key_and_bounded(self):
        service = get_semantic_service()
        service.configure(encoder_cache_max_entries=1)
        calls = []

        def factory():
            value = object()
            calls.append(value)
            return value

        first = service.get_global_encoder(("model-a",), factory)
        self.assertIs(first, service.get_global_encoder(("model-a",), factory))
        self.assertEqual(len(calls), 1)
        service.get_global_encoder(("model-b",), factory)
        service.get_global_encoder(("model-a",), factory)
        self.assertEqual(len(calls), 3)
        snapshot = service.snapshot()
        self.assertEqual(snapshot["globalEncoderHits"], 1)
        self.assertEqual(snapshot["globalEncoderEntries"], 1)

    def test_dense_targets_are_stored_on_cpu(self):
        service = get_semantic_service()
        service.configure()
        service.put_dense_target(("target",), {"last": _FakeTensor()})
        cached = service.get_dense_target(("target",))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["last"].device, "cpu")
        self.assertEqual(service.snapshot()["denseTargetHits"], 1)

    def test_disabled_service_does_not_reuse_or_store(self):
        service = get_semantic_service()
        service.configure(enabled=False)
        calls = []
        first = service.get_global_encoder(("model",), lambda: calls.append(1) or object())
        second = service.get_global_encoder(("model",), lambda: calls.append(1) or object())
        self.assertIsNot(first, second)
        self.assertEqual(len(calls), 2)
        service.put_target_vector(("target",), {"projected": [1.0]})
        self.assertIsNone(service.get_target_vector(("target",)))


if __name__ == "__main__":
    unittest.main()
