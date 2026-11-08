import unittest
from unittest.mock import patch

import numpy as np
import torch

from attachment_quality import attachment_quality


class AttachmentQualityTests(unittest.TestCase):
    def base(self):
        rest = torch.tensor([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]])
        tri = torch.tensor([[0,1,2],[0,1,3],[0,2,3],[1,2,3]])
        regions = ["tool","tool","tool","body"]
        names = ["root","hand"]
        weights = torch.tensor([[0.,1.],[0.,1.],[0.,1.],[1.,0.]])
        return rest,tri,regions,names,weights
    def test_rigid_rotating_prop_passes(self):
        rest,tri,regions,names,w=self.base(); posed=rest[None].repeat(2,1,1); posed[1,:,0]=torch.tensor([0.,0.,-1.,0.]); posed[1,:,1]=torch.tensor([0.,1.,0.,0.])
        out=attachment_quality(posed,rest,tri,w,regions,names,[{"region":"tool","donorJoints":["hand"]}]); self.assertTrue(out["passed"])
    def test_deformed_part_fails(self):
        rest,tri,regions,names,w=self.base(); posed=rest[None].repeat(2,1,1); posed[1,1,0]=2.
        self.assertFalse(attachment_quality(posed,rest,tri,w,regions,names,[{"region":"tool","donorJoints":["hand"]}])["passed"])
    def test_mixed_connector_reports_exposure(self):
        rest,tri,regions,names,w=self.base(); w[3]=torch.tensor([.5,.5]); posed=rest[None]
        out=attachment_quality(posed,rest,tri,w,regions,names,[{"region":"tool","donorJoints":["hand"]}]); self.assertGreater(out["attachments"][0]["donorInfluenceOutsidePartVertexCount"],0)
    def test_missing_and_empty(self):
        rest,tri,regions,names,w=self.base();
        self.assertFalse(attachment_quality(rest[None],rest,tri,w,regions,names,[])["applicable"])
        with self.assertRaises(ValueError): attachment_quality(rest[None],rest,tri,w,regions,names,[{"region":"x","donorJoints":["hand"]}])
        with self.assertRaises(ValueError): attachment_quality(rest[None],rest,tri,w,regions,names,[{"region":"tool","donorJoints":[]}])

    def test_rigid_part_translated_from_stationary_body_fails_interface(self):
        rest, tri, regions, names, w = self.base(); posed = rest[None].repeat(2, 1, 1); posed[1, :3, 0] += 2.
        out = attachment_quality(posed, rest, tri, w, regions, names, [{"region": "tool", "donorJoints": ["hand"]}])
        self.assertFalse(out["passed"]); self.assertTrue(out["attachments"][0]["rigidFitMaxResidual"] < 1e-5)

    def test_compression_uses_smallest_principal_stretch(self):
        rest, tri, regions, names, w = self.base(); posed = rest[None].repeat(2, 1, 1); posed[1, :3, 1] *= .1
        out = attachment_quality(posed, rest, tri, w, regions, names, [{"region": "tool", "donorJoints": ["hand"]}])
        self.assertFalse(out["passed"]); self.assertGreater(out["attachments"][0]["compressionViolationFraction"], 0.)

    def test_single_bad_frame_is_not_diluted_by_good_frames(self):
        rest, tri, regions, names, w = self.base(); posed = rest[None].repeat(101, 1, 1); posed[-1, 1, 0] = 2.
        out = attachment_quality(posed, rest, tri, w, regions, names, [{"region": "tool", "donorJoints": ["hand"]}])
        self.assertFalse(out["passed"]); self.assertGreater(out["attachments"][0]["rigidFitMaxResidual"], 1e-5)

    def test_geometry_ownership_uses_physical_boundary_not_mixed_sleeve(self):
        rest = torch.tensor([[0., 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 0], [2, 0, 0], [0, 2, 0]])
        tri = torch.tensor([[0, 1, 2], [3, 4, 5], [1, 2, 6]])
        regions = ["body", "body", "body", "weapon", "weapon", "weapon", "body"]
        names = ["body", "hand"]
        weights = torch.tensor([[1., 0], [1, 0], [1, 0], [0, 1], [0, 1], [0, 1], [.5, .5]])
        posed = rest[None].repeat(2, 1, 1)
        posed[1, 6, 0] = 4.
        descriptors = [{"region": "weapon", "donorJoints": ["hand"]}]
        profile = {"geometryOwnership": {"sha256": "mask"}, "rigidAttachments": descriptors}
        prepared = {"triangles": tri.numpy(), "regions": regions, "names": names,
                    "ownershipBoundaryPairs": np.array([[0, 4]]),
                    "geometryOwnershipReport": {"interfaces": [{
                        "region": "weapon", "interfaceMode": "split_shared",
                        "boundaryPairIndices": [0], "sharedSourceVertexIds": [0]}]}}
        mixed = attachment_quality(posed, rest, tri, weights, regions, names, descriptors)
        self.assertFalse(mixed["passed"])
        with patch("geometry_ownership.validate_prepared_ownership"), \
             patch("target_asset.load_target_asset", return_value=prepared), \
             patch("geometry_ownership.animated_boundary_gate",
                   return_value={"maxBoundaryGap": 1.0, "passed": True}):
            owned = attachment_quality(posed, rest, tri, weights, regions, names, descriptors,
                                      ownership_profile=profile, prepared_skin=prepared, expected_frame_count=2)
            self.assertTrue(owned["passed"])
            self.assertEqual(owned["attachments"][0]["interfacePolicy"], "physical_boundary")
            self.assertFalse(owned["attachments"][0]["mixedInfluenceDiagnostic"]["gatesExport"])
            with self.assertRaisesRegex(ValueError, "physical_boundary"):
                attachment_quality(posed, rest, tri, weights, regions, names,
                                    [{"region": "weapon", "donorJoints": ["hand"], "interfacePolicy": "mixed_influence"}],
                                    ownership_profile=profile, prepared_skin=prepared, expected_frame_count=2)


if __name__ == "__main__": unittest.main()
