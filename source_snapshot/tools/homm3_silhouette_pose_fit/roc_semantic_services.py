"""Process-wide semantic encoder and target-feature services.

The notebook creates one runtime namespace per animation.  Keeping the
encoder in that namespace meant that a full creature run repeatedly loaded
the same SigLIP/DINO weights and processor.  This module owns only reusable
model and target-feature state; candidate pose state remains local to an
experiment so one animation cannot contaminate another.

The module deliberately has no torch or transformers import at module load
time.  A fresh notebook kernel can therefore import the control surface
without allocating GPU memory, and the factory supplied by the solver remains
the single place that decides which model implementation to construct.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any, Callable, Mapping


def _validate_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or int(value) != value or int(value) < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _detach_to_cpu(value: Any) -> Any:
    """Move tensor-like cached values off the GPU without requiring torch."""

    detached = value.detach() if hasattr(value, "detach") else value
    if hasattr(detached, "to"):
        detached = detached.to("cpu")
    if hasattr(detached, "contiguous"):
        detached = detached.contiguous()
    return detached


def _dispose_model(model: Any) -> None:
    """Release an evicted model when its implementation exposes torch."""

    torch = getattr(model, "torch", None)
    try:
        del model
    finally:
        if torch is not None and hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()


class SemanticService:
    """Bounded process-wide cache for semantic models and target features."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._enabled = True
        self._encoder_cache_max_entries = 2
        self._target_vector_cache_max_entries = 512
        self._dense_target_cache_max_entries = 128
        self._global_encoders: OrderedDict[Any, Any] = OrderedDict()
        self._dense_encoders: OrderedDict[Any, Any] = OrderedDict()
        self._target_vectors: OrderedDict[Any, Mapping[str, Any]] = OrderedDict()
        self._dense_targets: OrderedDict[Any, dict[Any, Any]] = OrderedDict()
        self._stats = {
            "globalEncoderHits": 0,
            "globalEncoderMisses": 0,
            "denseEncoderHits": 0,
            "denseEncoderMisses": 0,
            "globalTargetHits": 0,
            "globalTargetMisses": 0,
            "denseTargetHits": 0,
            "denseTargetMisses": 0,
        }

    def configure(
        self,
        *,
        enabled: bool = True,
        encoder_cache_max_entries: int = 2,
        target_vector_cache_max_entries: int = 512,
        dense_target_cache_max_entries: int = 128,
    ) -> None:
        """Set cache policy for the next experiment without clearing hits.

        The notebook is single-process and initializes experiments
        sequentially.  Configuration is therefore intentionally explicit at
        initialization time rather than hidden in environment variables.
        Shrinking a cache evicts the oldest entries immediately.
        """

        encoder_limit = _validate_limit(
            "encoder_cache_max_entries", encoder_cache_max_entries
        )
        target_limit = _validate_limit(
            "target_vector_cache_max_entries", target_vector_cache_max_entries
        )
        dense_limit = _validate_limit(
            "dense_target_cache_max_entries", dense_target_cache_max_entries
        )
        with self._lock:
            if not bool(enabled) and self._enabled:
                # A deliberate isolation run should not leave the previously
                # cached models occupying VRAM while bypassing the cache.
                for cache in (self._global_encoders, self._dense_encoders):
                    while cache:
                        _key, model = cache.popitem(last=False)
                        _dispose_model(model)
                self._target_vectors.clear()
                self._dense_targets.clear()
            self._enabled = bool(enabled)
            self._encoder_cache_max_entries = encoder_limit
            self._target_vector_cache_max_entries = target_limit
            self._dense_target_cache_max_entries = dense_limit
            self._trim(self._global_encoders, encoder_limit, dispose=True)
            self._trim(self._dense_encoders, encoder_limit, dispose=True)
            self._trim(self._target_vectors, target_limit)
            self._trim(self._dense_targets, dense_limit)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _trim(self, cache: OrderedDict[Any, Any], limit: int, *, dispose: bool = False) -> None:
        while len(cache) > int(limit):
            _key, value = cache.popitem(last=False)
            if dispose:
                _dispose_model(value)

    def _get_encoder(
        self,
        cache: OrderedDict[Any, Any],
        kind: str,
        key: Any,
        factory: Callable[[], Any],
    ) -> Any:
        if not self._enabled:
            return factory()
        with self._lock:
            cached = cache.get(key)
            if cached is not None:
                cache.move_to_end(key)
                self._stats[f"{kind}EncoderHits"] += 1
                return cached
            self._stats[f"{kind}EncoderMisses"] += 1
            value = factory()
            cache[key] = value
            cache.move_to_end(key)
            self._trim(cache, self._encoder_cache_max_entries, dispose=True)
            return value

    def get_global_encoder(self, key: Any, factory: Callable[[], Any]) -> Any:
        return self._get_encoder(self._global_encoders, "global", key, factory)

    def get_dense_encoder(self, key: Any, factory: Callable[[], Any]) -> Any:
        return self._get_encoder(self._dense_encoders, "dense", key, factory)

    def _get_target(
        self,
        cache: OrderedDict[Any, Any],
        kind: str,
        key: Any,
    ) -> Any | None:
        if not self._enabled:
            return None
        with self._lock:
            value = cache.get(key)
            if value is None:
                self._stats[f"{kind}TargetMisses"] += 1
                return None
            cache.move_to_end(key)
            self._stats[f"{kind}TargetHits"] += 1
            return value

    def _put_target(
        self,
        cache: OrderedDict[Any, Any],
        kind: str,
        key: Any,
        value: Any,
        limit: int,
    ) -> None:
        if not self._enabled:
            return
        with self._lock:
            cache[key] = value
            cache.move_to_end(key)
            self._trim(cache, limit)

    def get_target_vector(self, key: Any) -> Mapping[str, Any] | None:
        return self._get_target(self._target_vectors, "global", key)

    def put_target_vector(self, key: Any, value: Mapping[str, Any]) -> None:
        if not isinstance(value, Mapping):
            raise TypeError("target semantic vectors must be a mapping")
        self._put_target(
            self._target_vectors,
            "global",
            key,
            dict(value),
            self._target_vector_cache_max_entries,
        )

    def get_dense_target(self, key: Any) -> dict[Any, Any] | None:
        return self._get_target(self._dense_targets, "dense", key)

    def put_dense_target(self, key: Any, value: Mapping[Any, Any]) -> None:
        if not isinstance(value, Mapping):
            raise TypeError("dense target features must be a mapping")
        cpu_value = {
            layer: _detach_to_cpu(features) for layer, features in value.items()
        }
        self._put_target(
            self._dense_targets,
            "dense",
            key,
            cpu_value,
            self._dense_target_cache_max_entries,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "enabled": self._enabled,
                "globalEncoderEntries": len(self._global_encoders),
                "denseEncoderEntries": len(self._dense_encoders),
                "globalTargetEntries": len(self._target_vectors),
                "denseTargetEntries": len(self._dense_targets),
                "encoderCacheMaxEntries": self._encoder_cache_max_entries,
                "targetVectorCacheMaxEntries": self._target_vector_cache_max_entries,
                "denseTargetCacheMaxEntries": self._dense_target_cache_max_entries,
            }

    def clear(self, *, models: bool = True, targets: bool = True) -> None:
        """Clear selected state for tests or an intentional memory reset."""

        with self._lock:
            if models:
                for cache in (self._global_encoders, self._dense_encoders):
                    while cache:
                        _key, model = cache.popitem(last=False)
                        _dispose_model(model)
            if targets:
                self._target_vectors.clear()
                self._dense_targets.clear()


_SERVICE: SemanticService | None = None
_SERVICE_LOCK = RLock()


def get_semantic_service() -> SemanticService:
    """Return the process-wide service used by notebook experiments."""

    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = SemanticService()
        return _SERVICE


def reset_semantic_service_for_tests() -> None:
    """Drop the singleton without importing model dependencies."""

    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is not None:
            _SERVICE.clear()
        _SERVICE = None
