"""Cascade Adam shrinks the learning rate after a worse step."""
from __future__ import annotations

from roc_gpu_cascade_experiment import GpuCascadeConfig, backtracked_learning_rate


def run() -> dict[str, object]:
    config = GpuCascadeConfig()
    config.validate()
    assert int(config.adaptive_learning_rate_reject_patience) == 1
    assert float(config.adaptive_learning_rate_max_multiplier) == 256.0

    current = 0.045
    after_first_reject = backtracked_learning_rate(
        current=current,
        base=0.045,
        reject_streak=1,
        patience=1,
        divisor=2.0,
        max_divisor=256.0,
    )
    assert after_first_reject == 0.0225, after_first_reject

    still_waiting = backtracked_learning_rate(
        current=0.045,
        base=0.045,
        reject_streak=1,
        patience=2,
        divisor=2.0,
        max_divisor=256.0,
    )
    assert still_waiting == 0.045, still_waiting

    grown_was_the_old_policy = 0.045 * (2.0 ** 3)
    shrunk = 0.045
    for streak in range(1, 4):
        shrunk = backtracked_learning_rate(
            current=shrunk,
            base=0.045,
            reject_streak=streak,
            patience=1,
            divisor=2.0,
            max_divisor=256.0,
        )
    assert shrunk == 0.045 / 8.0, shrunk
    assert shrunk < grown_was_the_old_policy

    at_floor = backtracked_learning_rate(
        current=0.045 / 256.0,
        base=0.045,
        reject_streak=20,
        patience=1,
        divisor=2.0,
        max_divisor=256.0,
    )
    assert at_floor == 0.045 / 256.0, at_floor

    return {
        "ok": True,
        "afterFirstReject": after_first_reject,
        "afterThreeRejects": shrunk,
        "floor": at_floor,
    }


if __name__ == "__main__":
    print(run())
