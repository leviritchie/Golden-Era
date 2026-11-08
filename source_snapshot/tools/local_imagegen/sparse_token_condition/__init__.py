"""True-sparse lattice token conditioner for SD3.5 (design B).

Known = Pillow-NEAREST sample sites only (x, y, rgb).
Unknown = empty/noise latent — never Stage A soft fill.
"""

from .observations import build_sparse_observations, observations_to_tensor
from .encoder import SparseLatticeEncoder

__all__ = [
    "build_sparse_observations",
    "observations_to_tensor",
    "SparseLatticeEncoder",
]
