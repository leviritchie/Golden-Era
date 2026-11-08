import sys
import unittest
import json
from unittest.mock import patch
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
from run_eagle_reference_capture_comparison import _rows, _verify_package, CLIPS, verify_source_identity, _sha

class EagleReferenceRunnerTests(unittest.TestCase):
    def test_context_identity_and_order_are_pinned(self):
        root=HERE/'mock_source_identity'
        contents={}
        with patch.object(Path,'read_bytes',lambda p:contents[str(p)]), \
                patch.object(Path,'read_text',lambda p:contents[str(p)].decode()), \
                patch.object(Path,'glob',lambda p,pattern:[p/f'{i:06d}.png' for i in range(3)]):
            idle=root/'idle.png'; frame=root/'frame.png'
            contents[str(idle)]=b'idle'; contents[str(frame)]=b'authored'
            frames=root/'clip'/'frames'
            for i,source in enumerate((idle,frame,idle)):
                contents[str(frames/f'{i:06d}.png')]=source.read_bytes()
            clip={'key':'g00_move','contextBefore':[str(idle)],'frames':[str(frame)],'contextAfter':[str(idle)]}
            manifest=root/'manifest.json'; contents[str(manifest)]=json.dumps({'clips':[clip]}).encode()
            corpus={'manifest':str(manifest),'manifestSha256':_sha(manifest),
                'sourceFrames':{str(p):{'sha256':_sha(p)} for p in (idle,frame)}}
            row={'key':'g00_move','capture':str(root/'clip'/'capture'/'raw_capture.npz'),
                'frames':[str(frame)],'sourceIndices':[1]}
            checked=verify_source_identity(corpus,row)
            self.assertEqual(checked['authoredSha256'],[_sha(frame)])
            wrong=dict(row,sourceIndices=[2])
            with self.assertRaisesRegex(ValueError,'order'): verify_source_identity(corpus,wrong)
            contents[str(frames/'000001.png')]=b'replaced'
            with self.assertRaisesRegex(ValueError,'hash drift'): verify_source_identity(corpus,row)
    def corpus(self, keys):
        return {'captures':[{'key':key} for key in keys]}

    def test_selects_required_three_from_larger_corpus(self):
        keys=['extra']+list(CLIPS)+['other']
        rows=_rows(self.corpus(keys))
        self.assertEqual(tuple(rows),CLIPS)

    def test_missing_or_duplicate_required_clip_rejected(self):
        with self.assertRaises(ValueError): _rows(self.corpus(['g00_move','g02_idle']))
        with self.assertRaises(ValueError): _rows(self.corpus(list(CLIPS)+['g00_move']))

    def test_reference_package_requires_exact_names_and_parents(self):
        baseline={'jointNames':['a','b'],'parents':np.array([-1,0])}
        same={'jointNames':['a','b'],'parents':np.array([-1,0])}
        _verify_package(same,baseline)
        with self.assertRaisesRegex(ValueError,'skeleton'):
            _verify_package({'jointNames':['a','c'],'parents':np.array([-1,0])},baseline)
        with self.assertRaisesRegex(ValueError,'skeleton'):
            _verify_package({'jointNames':['a','b'],'parents':np.array([-1,1])},baseline)

if __name__=='__main__': unittest.main()
