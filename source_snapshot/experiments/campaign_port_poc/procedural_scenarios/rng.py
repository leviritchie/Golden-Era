"""Stable, stage-isolated random streams.

Python's ``random`` module is deterministic within a runtime but does not make a
cross-version sequence contract.  This module uses SplitMix64 and derives every
stage seed with SHA-256, so a new placement pass cannot perturb topology or
terrain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, MutableSequence, Sequence, TypeVar


_MASK_64 = (1 << 64) - 1
_UNIT_53 = float(1 << 53)
T = TypeVar("T")


class DeterministicRng:
    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        self._state = seed & _MASK_64

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK_64
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK_64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK_64
        return (value ^ (value >> 31)) & _MASK_64

    def random(self) -> float:
        return (self.next_u64() >> 11) / _UNIT_53

    def randbelow(self, stop: int) -> int:
        if isinstance(stop, bool) or not isinstance(stop, int) or stop <= 0:
            raise ValueError("stop must be a positive integer")
        limit = (1 << 64) - ((1 << 64) % stop)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % stop

    def randint(self, start: int, stop: int) -> int:
        if stop < start:
            raise ValueError("stop must not be less than start")
        return start + self.randbelow(stop - start + 1)

    def uniform(self, start: float, stop: float) -> float:
        return float(start) + (float(stop) - float(start)) * self.random()

    def choice(self, values: Sequence[T]) -> T:
        if not values:
            raise IndexError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]

    def shuffle(self, values: MutableSequence[T]) -> None:
        for index in range(len(values) - 1, 0, -1):
            swap = self.randbelow(index + 1)
            values[index], values[swap] = values[swap], values[index]

    def sample(self, values: Sequence[T], count: int) -> list[T]:
        if count < 0 or count > len(values):
            raise ValueError("sample count is outside the population")
        indices = list(range(len(values)))
        for index in range(count):
            swap = index + self.randbelow(len(indices) - index)
            indices[index], indices[swap] = indices[swap], indices[index]
        return [values[index] for index in indices[:count]]


@dataclass(frozen=True)
class StageSeed:
    stage: str
    seed: int


class StageRngFactory:
    """Derive independent named streams from all deterministic inputs."""

    def __init__(
        self,
        master_seed: int,
        *,
        generator_version: str,
        profile_hash: str,
        donor_hash: str,
        catalog_hash: str,
    ) -> None:
        if isinstance(master_seed, bool) or not isinstance(master_seed, int):
            raise TypeError("master_seed must be an integer")
        fields = (
            str(master_seed),
            generator_version,
            profile_hash,
            donor_hash,
            catalog_hash,
        )
        self._root = "\0".join(fields).encode("utf-8")
        self._issued: dict[str, int] = {}

    def seed_for(self, stage: str) -> int:
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("stage must be a non-empty string")
        digest = hashlib.sha256(self._root + b"\0" + stage.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big", signed=False)

    def stream(self, stage: str) -> DeterministicRng:
        seed = self.seed_for(stage)
        self._issued[stage] = seed
        return DeterministicRng(seed)

    @property
    def issued_seeds(self) -> tuple[StageSeed, ...]:
        return tuple(
            StageSeed(stage=stage, seed=seed)
            for stage, seed in sorted(self._issued.items())
        )


def deterministic_order(values: Iterable[T], *, key: object = None) -> tuple[T, ...]:
    if key is None:
        return tuple(sorted(values))
    if not callable(key):
        raise TypeError("key must be callable")
    return tuple(sorted(values, key=key))
