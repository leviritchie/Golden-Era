import unittest

from tools.validate_homm3_attachment_pipeline_contract import PIPELINE, validate_source, validate_repair_source, validate_skin_refit_source, validate_repair_dispatch
from tools.validate_homm3_attachment_pipeline_contract import validate_anatomical_source, validate_joint_anchor_audit_source, validate_owned_skinned_lab_source, validate_runtime_skin_quality_source


class AttachmentPipelineContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (PIPELINE / "run_skin_mesh_pilot.py").read_text(encoding="utf-8")

    def test_current_integration(self):
        self.assertTrue(validate_source(self.source)["attachmentBeforeExport"])

    def test_gate_removal_rejected(self):
        with self.assertRaisesRegex(ValueError, "before GLB"):
            validate_source(self.source.replace("= attachment_quality(", "= removed_gate("))

    def test_either_gate_instead_of_both_rejected(self):
        source = self.source.replace('report["restContract"]["ok"] and report["attachmentGate"]["passed"]',
                                     'report["restContract"]["ok"] or report["attachmentGate"]["passed"]')
        self.assertNotEqual(source, self.source)
        with self.assertRaisesRegex(ValueError, "eligibility"):
            validate_source(source)

    def test_completion_cannot_become_automatic(self):
        source = self.source.replace("if motion_completion_report is not None:", "if True:")
        with self.assertRaisesRegex(ValueError, "explicitly selected"):
            validate_source(source)

    def test_repair_contract(self):
        validate_repair_source((PIPELINE / "run_attachment_repair.py").read_text(encoding="utf-8"))

    def test_repair_export_cannot_be_promoted(self):
        source = (PIPELINE / "run_attachment_repair.py").read_text(encoding="utf-8")
        source = source.replace('result["candidateValidForExport"] = False', 'result["candidateValidForExport"] = True')
        with self.assertRaisesRegex(ValueError, "closure validation"):
            validate_repair_source(source)

    def test_repair_split_cannot_be_removed(self):
        source = (PIPELINE / "run_attachment_repair.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "shared topology"):
            validate_repair_source(source.replace("split_attachment(body,", "removed_stage(body,"))

    def test_body_parity_cannot_be_optional(self):
        source = (PIPELINE / "run_attachment_repair.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unconditionally"):
            validate_repair_source(source.replace("if body_error > 1e-5:", 'if recipe["consolidateRedundantOwner"] and body_error > 1e-5:'))

    def test_skin_refit_contract(self):
        validate_skin_refit_source((PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8"))

    def test_skin_refit_cannot_optimize_geometry(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "rest geometry"):
            validate_skin_refit_source(source.replace("allow_mesh=False", "allow_mesh=True"))

    def test_skin_refit_must_reconstruct_domain(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "shared make_repair_domain"):
            validate_skin_refit_source(source.replace("domain = make_repair_domain(", "domain = unverified_domain("))

    def test_skin_refit_cannot_skip_conditioning_or_frozen_gate(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "shared condition_body_welds"):
            validate_skin_refit_source(source.replace("conditioning = condition_body_welds(", "conditioning = unverified_weights("))
        with self.assertRaisesRegex(ValueError, "immutable rest"):
            validate_skin_refit_source(source.replace('np.array_equal(weights[frozen], original["weights"][frozen])', "True"))

    def test_skin_refit_cannot_claim_acceptance(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "acceptance"):
            validate_skin_refit_source(source.replace('"candidateValidForExport": False', '"candidateValidForExport": True'))

    def test_skin_refit_cannot_drop_source_owner_evidence(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "original source owner evidence"):
            validate_skin_refit_source(source.replace("source_weights_mapped=fitted", "unverified_weights=fitted"))

    def test_anatomical_initializer_must_be_reconstructed(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "shared initialize_profile_chains"):
            validate_skin_refit_source(source.replace("initialize_profile_chains(", "unverified_initializer("))

    def test_anatomical_selection_must_be_forwarded(self):
        with self.assertRaisesRegex(ValueError, "forward explicit anatomical"):
            validate_repair_dispatch(self.source.replace("anatomical_chain_regions=anatomical_chain_regions", "ignored_regions=anatomical_chain_regions"))

    def test_joint_anchor_weight_must_be_forwarded(self):
        with self.assertRaisesRegex(ValueError, "forward explicit joint anchor"):
            validate_repair_dispatch(self.source.replace("joint_anchor_weight=joint_anchor_weight", "ignored_anchor_weight=joint_anchor_weight"))

    def test_anatomical_segment_owner_cannot_shift_to_child(self):
        source = (PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8")
        validate_anatomical_source(source)
        with self.assertRaisesRegex(ValueError, "parent-outgoing"):
            validate_anatomical_source(source.replace("np.concatenate((chain[:-1], chain[-1:]))", "np.concatenate((chain[1:], chain[-1:]))"))

    def test_anatomical_frozen_prop_check_cannot_be_removed(self):
        source = (PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "frozen attachment"):
            validate_anatomical_source(source.replace('np.array_equal(weights[prop], skin["weights"][prop])', "True"))

    def test_schema2_run_selection_must_be_literal(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "v2 literally"):
            validate_skin_refit_source(source.replace('schema="profile-chain-initialization-v2"', 'schema=initialization_schema'))

    def test_schema2_readback_uses_stored_inner_schema(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stored anatomical"):
            validate_skin_refit_source(source.replace('schema=report["anatomicalInitialization"]["schema"]', 'schema="profile-chain-initialization-v1"'))

    def test_schema2_report_contract_cannot_drop_routing(self):
        source = (PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "expose routing"):
            validate_anatomical_source(source.replace("report[\"bodyRegionRouting\"] = routing", "report[\"routing\"] = routing"))

    def test_anatomical_schema_guard_rejects_v3_allowlist(self):
        source = (PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "only v1/v2"):
            validate_anatomical_source(source.replace('"profile-chain-initialization-v2")', '"profile-chain-initialization-v2", "profile-chain-initialization-v3")'))

    def test_anatomical_initializer_cannot_write_skin_regions(self):
        source = (PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not write skin regions"):
            validate_anatomical_source(source.replace('weights = skin["weights"].copy()', 'skin["regions"] = skin["regions"].copy()\n    weights = skin["weights"].copy()'))

    def test_routed_chain_must_validate_body_topology_first(self):
        source = (PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8")
        validate_anatomical_source(source)
        mutated = source.replace("                _require_body_label_adjacency(skin, prop, label, chain_name)\n", "")
        with self.assertRaisesRegex(ValueError, "topology first"):
            validate_anatomical_source(mutated)

    def test_joint_anchor_audit_entry_contract(self):
        source = (PIPELINE / "run_skin_joint_anchor_audit.py").read_text(encoding="utf-8")
        validate_joint_anchor_audit_source(source)

    def test_joint_anchor_audit_must_load_saved_refit(self):
        source = (PIPELINE / "run_skin_joint_anchor_audit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "load refit"):
            validate_joint_anchor_audit_source(source.replace("load_refit(refit_path, asset, fit_dir)", "load_saved_placeholder(refit_path, asset, fit_dir)"))

    def test_joint_anchor_audit_cannot_claim_acceptance(self):
        source = (PIPELINE / "run_skin_joint_anchor_audit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-accepting"):
            validate_joint_anchor_audit_source(source.replace('"accepted": False', '"accepted": True'))

    def test_skin_refit_anchor_spec_must_be_shared(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "share the anchor specification"):
            validate_skin_refit_source(source.replace("reconstructed = _anchor_spec(original, domain, get_profile(asset), regions,", "reconstructed = missing_anchor_spec(original, domain, get_profile(asset), regions,"))

    def test_skin_refit_optimizer_must_receive_anchor_objective(self):
        source = (PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fixed anchor object and weight"):
            validate_skin_refit_source(source.replace("joint_anchor=anchor_objective, joint_anchor_weight=joint_anchor_weight", "joint_anchor_weight=joint_anchor_weight"))

    def test_owned_lab_preserves_current_mocap_local_trs(self):
        source = (PIPELINE.parent.parent / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs").read_text(encoding="utf-8")
        self.assertTrue(validate_owned_skinned_lab_source(source)["fixedMocapLocalTrs"])

    def test_owned_lab_cannot_drop_fixed_mocap_translations(self):
        source = (PIPELINE.parent.parent / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fixed mocap local TRS"):
            validate_owned_skinned_lab_source(source.replace("m_LocalPosition.", "removedPosition."))

    def test_runtime_skin_quality_requires_explicit_capability_marker(self):
        source = (PIPELINE.parent.parent / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportVisuals.cs").read_text(encoding="utf-8")
        self.assertTrue(validate_runtime_skin_quality_source(source)["explicitSkinWeightCapability"])

    def test_runtime_skin_quality_cannot_raise_global_cap_unconditionally(self):
        source = (PIPELINE.parent.parent / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportVisuals.cs").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "capability marker"):
            validate_runtime_skin_quality_source(source.replace("var unlimitedMarker = instance.transform.Find(SkinWeightsUnlimitedMarkerName);", "var unlimitedMarker = instance.transform;"))


if __name__ == "__main__":
    unittest.main()
