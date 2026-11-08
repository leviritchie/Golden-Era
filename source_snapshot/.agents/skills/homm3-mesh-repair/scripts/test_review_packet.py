import unittest
from review_packet import job_fingerprint, replay_lineage, run, verify_fit


class ReviewPacketTests(unittest.TestCase):
    def test_segment_boundary_is_not_fabricated_continuity(self):
        frames = [dict(globalIndex=i, clipKey="idle" if i < 2 else "move",
                       segmentIndex=0 if i < 2 else 1, localIndex=i if i < 2 else 0)
                  for i in range(3)]
        frames[1]["prevFrameRef"] = {"acceptedPose": "original-reference"}
        rows = replay_lineage(frames)
        self.assertEqual([r["replayPredecessorIndex"] for r in rows], [None, 0, None])
        self.assertEqual(rows[1]["prevFrameRef"], frames[1]["prevFrameRef"])
        self.assertNotIn("prevFrameRef", rows[0])

    def test_reordered_master_rejected(self):
        with self.assertRaises(ValueError):
            replay_lineage([{"globalIndex": 1}])

    def test_empty_master_rejected(self):
        with self.assertRaises(ValueError):
            replay_lineage([])

    def test_existing_output_refused_before_reading_candidate(self):
        from pathlib import Path
        with self.assertRaisesRegex(ValueError, "must be new"):
            run("missing-candidate", Path(__file__).parent)

    def test_same_length_master_change_invalidates_saved_motion(self):
        import json
        import io
        from pathlib import Path
        from unittest.mock import patch
        frames = [dict(globalIndex=0, segmentIndex=0, localIndex=0, clipKey="idle")]

        def open_fixture(path, *args, **kwargs):
            data = json.dumps({"frames": frames}).encode() if path.name == "master_sequence.json" else b"fixture"
            return io.BytesIO(data)

        # Exercise the real hash function, replacing only IO to avoid platform temp ACLs.
        with patch.object(Path, "open", open_fixture), patch.object(Path, "is_file", return_value=False):
            job = dict(mesh="mesh.glb", sourceReport="registration.json", runDir="run")
            report = {"inputs": job, "fingerprint": job_fingerprint(job)}
            verify_fit(report)
            frames[0]["clipKey"] = "move"
            with self.assertRaisesRegex(ValueError, "inputs/code changed"):
                verify_fit(report)


if __name__ == "__main__":
    unittest.main()
