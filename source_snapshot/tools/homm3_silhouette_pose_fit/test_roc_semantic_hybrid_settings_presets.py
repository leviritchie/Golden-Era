"""Contract tests for SETTINGS_OVERRIDE search/render budget presets."""
from __future__ import annotations

import sys
import unittest
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_crusader_full_animation_set as runner
from roc_semantic_hybrid_experiment import RocHybridConfig
from roc_semantic_hybrid_settings_presets import (
    SETTINGS_OVERRIDE_CHOICES,
    apply_settings_override,
    parse_settings_override_assignment,
    settings_override_values,
)


class SettingsOverridePresetTests(unittest.TestCase):
    def test_every_named_preset_only_uses_known_config_fields(self):
        known = {field.name for field in fields(RocHybridConfig)}
        base = RocHybridConfig(root=str(runner.ROOT))
        for name in SETTINGS_OVERRIDE_CHOICES:
            overrides = settings_override_values(name)
            unknown = sorted(set(overrides) - known)
            self.assertEqual(unknown, [], msg=f"{name} has unknown fields")
            cfg = apply_settings_override(base, name)
            if name == "custom":
                self.assertEqual(overrides, {})
                self.assertEqual(cfg.render_worker_count, base.render_worker_count)
            else:
                self.assertGreater(len(overrides), 0)
                for key, value in overrides.items():
                    self.assertEqual(getattr(cfg, key), value, msg=f"{name}.{key}")

    def test_smoke_is_cheaper_than_full(self):
        base = RocHybridConfig(root=str(runner.ROOT))
        smoke = apply_settings_override(base, "smoke")
        full = apply_settings_override(base, "full")
        self.assertEqual(smoke.frame_indices, (0,))
        self.assertEqual(smoke.render_worker_count, 1)
        self.assertFalse(smoke.parallel_candidate_rendering)
        self.assertGreater(full.render_worker_count, smoke.render_worker_count)
        self.assertGreater(full.multi_bone_beam_width, smoke.multi_bone_beam_width)
        self.assertGreater(full.clip_max_evaluations_per_axis, smoke.clip_max_evaluations_per_axis)

    def test_parse_settings_override_assignment(self):
        source = "SETTINGS_OVERRIDE = 'balanced'\nCONFIG = RocHybridConfig()\n"
        self.assertEqual(parse_settings_override_assignment(source), "balanced")
        self.assertEqual(parse_settings_override_assignment("CONFIG = RocHybridConfig()\n"), "custom")
        with self.assertRaises(ValueError):
            parse_settings_override_assignment("SETTINGS_OVERRIDE = 'nope'\n")

    def test_notebook_runner_honors_settings_override_assignment(self):
        notebook = runner.NOTEBOOK
        if not notebook.is_file():
            self.skipTest(f"notebook missing: {notebook}")
        source = runner._config_call_source(notebook)
        self.assertIn("SETTINGS_OVERRIDE", source)
        self.assertEqual(parse_settings_override_assignment(source), "custom")
        kwargs = runner._literal_config_kwargs(notebook, require_dino=False)
        cfg = runner._notebook_config(RocHybridConfig, kwargs, notebook=notebook)
        # custom leaves notebook render budget alone; smoke forces one worker.
        self.assertEqual(cfg.render_worker_count, 4)
        patched = source.replace("SETTINGS_OVERRIDE = 'custom'", "SETTINGS_OVERRIDE = 'smoke'", 1)
        self.assertNotEqual(patched, source)
        smoke = apply_settings_override(cfg, parse_settings_override_assignment(patched))
        self.assertEqual(smoke.render_worker_count, 1)
        self.assertEqual(smoke.frame_indices, (0,))


if __name__ == "__main__":
    unittest.main()
