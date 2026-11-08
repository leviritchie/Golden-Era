"""Soft CPU/GPU motion-retention floor for region-centroid trajectories."""
from __future__ import annotations

from collections.abc import Mapping
import numpy as np
import torch


class RegionMotionFloor:
    def __init__(self, baseline, regions, clip_slices: Mapping[str, tuple[int, int]], *, fraction=.9, min_range=1e-4):
        self.baseline = torch.as_tensor(baseline).detach()
        if self.baseline.ndim != 3 or self.baseline.shape[-1] != 3 or self.baseline.shape[0] < 1:
            raise ValueError("baseline must be finite [F,V,3]")
        if not torch.is_floating_point(self.baseline) or not torch.isfinite(self.baseline).all():
            raise ValueError("baseline must be finite floating-point [F,V,3]")
        self.regions = np.asarray(regions)
        if self.regions.shape != (self.baseline.shape[1],) or self.regions.dtype.kind not in "OUSU":
            raise ValueError("regions must be a string label for every vertex")
        if any(not isinstance(x, str) or not x.strip() for x in self.regions):
            raise ValueError("region labels must be non-empty strings")
        if not np.isfinite(float(fraction)) or not 0 < float(fraction) <= 1:
            raise ValueError("fraction must be in (0,1]")
        if not np.isfinite(float(min_range)) or float(min_range) < 0:
            raise ValueError("min_range must be finite and non-negative")
        self.fraction, self.min_range = float(fraction), float(min_range)
        self.clip_slices = self._validate_slices(clip_slices, self.baseline.shape[0])
        self.region_names = tuple(dict.fromkeys(str(x) for x in self.regions))
        self.baseline_ranges = self._ranges(self.baseline)

    @staticmethod
    def _validate_slices(slices, frame_count):
        if not isinstance(slices, Mapping) or not slices:
            raise ValueError("clip_slices must be a non-empty mapping")
        ordered = sorted(slices.items(), key=lambda item: item[1][0] if isinstance(item[1], tuple) else -1)
        expected = 0; result = {}
        for key, pair in ordered:
            if not isinstance(key, str) or not key or not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("clip slices must be named (start,end) tuples")
            start, end = pair
            if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("clip slice bounds must be integers")
            if start != expected or start < 0 or end <= start or end > frame_count:
                raise ValueError("clip slices must form complete disjoint contiguous coverage")
            result[key] = (start, end); expected = end
        if expected != frame_count:
            raise ValueError("clip slices must cover every frame exactly once")
        return result

    def _ranges(self, values):
        centroids = []
        for start, end in self.clip_slices.values():
            clip = values[start:end]
            rows = []
            for name in self.region_names:
                mask = torch.as_tensor(self.regions == name, device=clip.device)
                rows.append(clip[:, mask].mean(dim=1))
            centroids.append(torch.stack(rows))
        ranges = torch.stack([torch.linalg.vector_norm(c.amax(1) - c.amin(1), dim=-1) for c in centroids])
        return ranges

    def loss(self, current):
        values = torch.as_tensor(current)
        if values.shape != self.baseline.shape or not torch.is_floating_point(values) or not torch.isfinite(values).all():
            raise ValueError("current must match finite floating-point baseline shape")
        base = self.baseline_ranges.to(values.device, values.dtype)
        now = self._ranges(values)
        observable = base > self.min_range
        if not bool(observable.any()):
            return values.sum() * 0
        deficits = torch.relu(self.fraction - now[observable] / base[observable])
        return torch.mean(deficits * deficits)

    def report(self, current):
        values = torch.as_tensor(current)
        now = self._ranges(values).detach().cpu().numpy()
        base = self.baseline_ranges.detach().cpu().numpy()
        rows = []
        for ci, key in enumerate(self.clip_slices):
            for ri, region in enumerate(self.region_names):
                b, n = float(base[ci, ri]), float(now[ci, ri])
                rows.append({'clip': key, 'region': region, 'baselineRange': b, 'currentRange': n,
                             'ratio': None if b <= self.min_range else n / b,
                             'ignoredBaseline': bool(b <= self.min_range)})
        return {'fraction': self.fraction, 'minRange': self.min_range, 'rows': rows,
                'observableCount': sum(not row['ignoredBaseline'] for row in rows),
                'thresholdCount': sum(not row['ignoredBaseline'] and row['currentRange'] < self.fraction * row['baselineRange'] for row in rows)}
