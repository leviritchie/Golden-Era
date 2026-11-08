"""Topology-aware welded weight field with fail-closed support masks."""
from __future__ import annotations

import numpy as np
import torch


class TopologyWeightField(torch.nn.Module):
    def __init__(self, vertices, triangles, initial_weights, rigid_rows, device="cpu"):
        super().__init__()
        v = np.asarray(vertices, dtype=np.float64); tri = np.asarray(triangles, dtype=np.int64)
        initial = np.asarray(initial_weights, dtype=np.float64)
        if v.ndim != 2 or v.shape[1] != 3 or not len(v) or tri.ndim != 2 or tri.shape[1] != 3 or (len(tri) and (tri.min() < 0 or tri.max() >= len(v))) or initial.ndim != 2 or len(initial) != len(v):
            raise ValueError("vertices, triangles, and weights have invalid shapes")
        if not np.isfinite(v).all() or not np.isfinite(initial).all() or np.any(initial < -1e-10):
            raise ValueError("vertices and initial weights must be finite and weights nonnegative")
        if not np.allclose(initial.sum(1), 1, atol=1e-6):
            raise ValueError("initial weights must have normalized rows")
        if np.any(np.count_nonzero(initial > 1e-8, axis=1) > 8):
            raise ValueError("initial weights exceed 8 influences")
        groups = {}
        for i, point in enumerate(v): groups.setdefault(tuple(point.tolist()), []).append(i)
        welds = list(groups.values()); weld_of = np.empty(len(v), dtype=np.int64)
        self._weld_rows = welds
        for wi, rows in enumerate(welds):
            weld_of[rows] = wi
            if not np.allclose(initial[rows], initial[rows[0]], atol=1e-6, rtol=0):
                raise ValueError("welded vertices have divergent initial weights")
        self.vertex_count, self.joint_count = len(v), initial.shape[1]
        self.register_buffer("weld_of", torch.as_tensor(weld_of, device=device))
        self.register_buffer("_initial", torch.as_tensor(initial[[rows[0] for rows in welds]], dtype=torch.float32, device=device))
        self.register_buffer("_allowed", self._initial > 1e-8)
        rigid = set(int(i) for i in rigid_rows)
        if any(i < 0 or i >= len(v) for i in rigid): raise ValueError("rigid row is out of range")
        self._rigid_welds = sorted(set(int(weld_of[i]) for i in rigid))
        for wi in self._rigid_welds:
            row = self._initial[wi]
            if int((row > 1e-8).sum()) != 1: raise ValueError("rigid rows must be one-hot")
        edge_set = set()
        for a, b, c in tri:
            for x, y in ((a,b),(b,c),(c,a)):
                x, y = int(weld_of[x]), int(weld_of[y])
                if x != y: edge_set.add(tuple(sorted((x,y))))
        self.register_buffer('_edges', torch.as_tensor(sorted(edge_set), dtype=torch.long, device=device).reshape(-1,2))
        self.register_buffer("_prior", torch.log(self._initial.clamp_min(1e-8)))
        self.logits = torch.nn.Parameter(torch.zeros_like(self._prior))

    def _group_values(self, values=None):
        if values is None:
            values = torch.softmax(torch.where(self._allowed, self._prior + self.logits, torch.tensor(-1e9, device=self.logits.device)), dim=1)
            if self._rigid_welds:
                values = values.clone(); values[self._rigid_welds] = self._initial[self._rigid_welds]
            return values
        values = torch.as_tensor(values, dtype=torch.float32, device=self.logits.device)
        if values.shape != (self.vertex_count, self.joint_count): raise ValueError("penalty weights shape mismatch")
        return values[[rows[0] for rows in self._weld_rows]]

    def weights(self):
        return self._group_values()[self.weld_of]

    def penalty(self, weights=None):
        values = self._group_values(weights)
        prior = ((values - self._initial) ** 2).mean()
        delta = values - self._initial
        smooth = ((delta[self._edges[:,0]] - delta[self._edges[:,1]]) ** 2).mean() if len(self._edges) else values.sum() * 0
        return prior + smooth

    def validate(self):
        value = self.weights()
        if not torch.isfinite(value).all() or not torch.allclose(value.sum(1), torch.ones(self.vertex_count, device=value.device), atol=1e-5):
            raise ValueError("weights are not finite and normalized")
        if int((value > 1e-8).sum(1).max()) > 8: raise ValueError("weights exceed 8 influences")
        if self._rigid_welds and not torch.equal(self._group_values()[self._rigid_welds], self._initial[self._rigid_welds]):
            raise ValueError("rigid weights changed")
        return True


class RepairWeightField(torch.nn.Module):
    """Explicit post-split repair field with ownership-aware welds.

    This field intentionally keeps the completed motion and geometry outside the
    weight solve.  Coincident vertices weld only when their ownership id agrees;
    frozen rows are returned from the original buffer without averaging.
    """

    def __init__(self, vertices, triangles, initial_weights, ownership_ids,
                 train_mask, allowed_support, device="cpu"):
        super().__init__()
        v = np.asarray(vertices, dtype=np.float64)
        tri_raw = np.asarray(triangles)
        initial = np.asarray(initial_weights, dtype=np.float64)
        owners = np.asarray(ownership_ids)
        train_raw = np.asarray(train_mask)
        support_raw = np.asarray(allowed_support)
        tri = tri_raw.astype(np.int64, copy=False)
        train = train_raw.astype(bool, copy=False)
        support = support_raw.astype(bool, copy=False)
        if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all():
            raise ValueError("vertices must be finite [V,3]")
        if tri_raw.dtype.kind not in "iu" or tri.ndim != 2 or tri.shape[1] != 3 or np.any(tri < 0) or np.any(tri >= len(v)):
            raise ValueError("triangles must be valid integer [F,3]")
        if initial.ndim != 2 or len(initial) != len(v) or not np.isfinite(initial).all() or np.any(initial < 0):
            raise ValueError("initial_weights must be finite nonnegative [V,J]")
        if not np.allclose(initial.sum(1), 1.0, atol=1e-6):
            raise ValueError("initial weights must be normalized")
        if owners.shape != (len(v),) or owners.dtype.kind not in "iu":
            raise ValueError("ownership_ids must be integer [V]")
        if train_raw.dtype.kind != "b" or support_raw.dtype.kind != "b" or train.shape != (len(v),) or support.shape != initial.shape:
            raise ValueError("train_mask/support shape mismatch")
        if np.any((initial > 0.0) & ~support):
            raise ValueError("allowed support must include all initial influences")
        if np.any(support.sum(1) > 8) or np.any(support.sum(1) == 0):
            raise ValueError("allowed support must contain 1..8 joints")

        groups = {}
        for i, point in enumerate(v):
            groups.setdefault((tuple(point.tolist()), int(owners[i])), []).append(i)
        welds = list(groups.values())
        weld_of = np.empty(len(v), dtype=np.int64)
        train_groups = []
        for wi, rows in enumerate(welds):
            weld_of[rows] = wi
            if len({bool(train[i]) for i in rows}) != 1:
                raise ValueError("train_mask must agree across weld group")
            if any(not np.array_equal(support[i], support[rows[0]]) for i in rows):
                raise ValueError("allowed_support must agree across weld group")
            if train[rows[0]]:
                if not np.allclose(initial[rows], initial[rows[0]], atol=1e-6, rtol=0):
                    raise ValueError("train weld has divergent initial weights")
                train_groups.append(wi)
        self.vertex_count, self.joint_count = len(v), initial.shape[1]
        self._weld_rows = welds
        self.register_buffer("weld_of", torch.as_tensor(weld_of, dtype=torch.long, device=device))
        self.register_buffer("initial_weights", torch.as_tensor(initial, dtype=torch.float32, device=device))
        self.register_buffer("_representatives", torch.as_tensor([rows[0] for rows in welds], dtype=torch.long, device=device))
        self.register_buffer("_group_initial", torch.as_tensor(initial[[r[0] for r in welds]], dtype=torch.float32, device=device))
        self.register_buffer("_support", torch.as_tensor(support[[r[0] for r in welds]], dtype=torch.bool, device=device))
        self.register_buffer("_train_groups", torch.as_tensor(train_groups, dtype=torch.long, device=device))
        self.register_buffer("_train_mask", torch.as_tensor(train, dtype=torch.bool, device=device))
        edges = set()
        for a, b, c in tri:
            for x, y in ((a, b), (b, c), (c, a)):
                x, y = int(x), int(y)
                if x != y and owners[x] == owners[y]:
                    gx, gy = int(weld_of[x]), int(weld_of[y])
                    if gx != gy: edges.add(tuple(sorted((gx, gy))))
        self.register_buffer("_edges", torch.as_tensor(sorted(edges), dtype=torch.long, device=device).reshape(-1, 2))
        self.delta = torch.nn.Parameter(torch.zeros((len(welds), self.joint_count), device=device))

    @staticmethod
    def _project_simplex(values, support):
        masked = values.masked_fill(~support, -1e9)
        ordered, _ = torch.sort(masked, dim=1, descending=True)
        cssv = torch.cumsum(ordered, dim=1) - 1.0
        rank = torch.arange(1, values.shape[1] + 1, device=values.device, dtype=values.dtype).view(1, -1)
        cond = ordered - cssv / rank > 0
        rho = cond.sum(1).clamp_min(1)
        theta = cssv.gather(1, (rho - 1).view(-1, 1)).squeeze(1) / rho.to(values.dtype)
        projected = torch.clamp(values - theta[:, None], min=0.0).masked_fill(~support, 0.0)
        return projected

    def weights(self):
        out = self.initial_weights.clone()
        if len(self._train_groups):
            g = self._train_groups
            trained = self._project_simplex(self._group_initial[g] + self.delta[g], self._support[g])
            expanded_groups = self._group_initial.clone()
            expanded_groups[g] = trained
            expanded = expanded_groups[self.weld_of]
            out = torch.where(self._train_mask[:, None], expanded, out)
        return out

    def penalty(self, weights=None):
        values = self.weights() if weights is None else weights
        delta = values - self.initial_weights
        prior = (delta ** 2).mean()
        group_delta = delta[self._representatives]
        smooth = ((group_delta[self._edges[:, 0]] - group_delta[self._edges[:, 1]]) ** 2).mean() if len(self._edges) else prior * 0
        return prior + smooth

    def validate(self):
        value = self.weights()
        if not torch.isfinite(value).all() or torch.any(value < -1e-7) or not torch.allclose(value.sum(1), torch.ones(self.vertex_count, device=value.device), atol=1e-5):
            raise ValueError("weights are not finite and normalized")
        if int((value > 1e-8).sum(1).max()) > 8 or torch.any((value > 1e-8) & ~self._support[self.weld_of]):
            raise ValueError("weights exceed declared support")
        if not torch.equal(value[~self._train_mask], self.initial_weights[~self._train_mask]):
            raise ValueError("frozen weights changed")
        expected = value[self._representatives[self.weld_of]]
        if not torch.equal(value[self._train_mask], expected[self._train_mask]):
            raise ValueError("train weld weights diverged")
        return True

    def support_stats(self):
        value = self.weights().detach().cpu().numpy()
        return {"vertexCount": self.vertex_count, "weldCount": len(self._weld_rows),
                "trainableWeldCount": int(len(self._train_groups)),
                "maxInfluences": int((value > 1e-8).sum(1).max()),
                "originalMeanAbsDelta": float(np.abs(value - self.initial_weights.detach().cpu().numpy()).mean())}
