import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
import ownership_motion_comparison as comparison


class OwnershipMotionComparisonTests(unittest.TestCase):
    def test_temporal_ranges_ignore_static_pose_offset(self):
        before=torch.tensor([[[0.,0,0],[4,0,0]],[[2.,0,0],[4,0,0]]])
        after=torch.tensor([[[9.,0,0],[8,0,0]],[[10.,0,0],[8,0,0]]])
        report=comparison._motion_retention(before,after,np.array(['moving','held']))
        self.assertEqual(report['moving']['ratio'],.5)
        self.assertIsNone(report['held']['ratio'])

    def test_position_lane_requires_explicit_registration(self):
        root=Path('artifacts/test_tmp')/('ownership_motion_'+uuid.uuid4().hex)
        root.mkdir(parents=True)
        try:
            skin=root/'skin.npz';np.savez(skin,names=np.array(['joint']))
            corpus=root/'corpus.json';corpus.write_text(json.dumps({'unit':'test','captures':[]}))
            with patch.object(comparison,'validate_invariants'):
                with self.assertRaisesRegex(ValueError,'requires --registration'):
                    comparison.run(skin,skin,corpus,root/'camera.json',root/'output')
                registration=root/'registration';registration.mkdir()
                (registration/'pilot_report.json').write_text(json.dumps({'asset':'wrong','kind':'idle_registration_only'}))
                with self.assertRaisesRegex(ValueError,'registration asset'):
                    comparison.run(skin,skin,corpus,root/'camera.json',root/'output',registration)
            self.assertFalse((root/'output').exists())
        finally:
            shutil.rmtree(root)


if __name__=='__main__':
    unittest.main()
