import unittest
import numpy as np
from actor_mask_trial import partition

class ActorMaskTests(unittest.TestCase):
    def test_exact_partition_and_unchanged_color(self):
        raw=np.random.default_rng(3).integers(0,256,(20,30,4),dtype=np.uint8)
        mask=np.indices((20,30))[1]<13
        mount,rider=partition(raw,mask)
        np.testing.assert_array_equal(mount[:,:,:3],raw[:,:,:3])
        np.testing.assert_array_equal(rider[:,:,:3],raw[:,:,:3])
        np.testing.assert_array_equal(mount[:,:,3].astype(int)+rider[:,:,3].astype(int),raw[:,:,3])
        self.assertFalse(np.any((mount[:,:,3]>0)&(rider[:,:,3]>0)))

    def test_bad_mask_fails(self):
        with self.assertRaises(ValueError):partition(np.zeros((2,3,4),np.uint8),np.zeros((2,3),np.uint8))

if __name__=='__main__':unittest.main()
