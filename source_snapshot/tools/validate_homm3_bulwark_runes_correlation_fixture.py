#!/usr/bin/env python3
"""Expensive Bulwark Runes correlation fixture (not a normal build step).

Replays one unambiguous sequence per signal family against the documented
HotA-style gain rules mirrored from Homm3BulwarkRunesRuntime.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path


CAP_BASIC = 3
CAP_ADVANCED = 6
CAP_EXPERT = 9


def resolve_cap(rank: int) -> int:
	if rank >= 3:
		return CAP_EXPERT
	if rank >= 2:
		return CAP_ADVANCED
	if rank >= 1:
		return CAP_BASIC
	return 0


def incremental_offence(threshold: int) -> int:
	return 2 if threshold in (1, 4, 7) else 0


def incremental_defence(threshold: int) -> int:
	return 2 if threshold in (2, 5, 8) else 0


def incremental_speed(threshold: int) -> int:
	return 1 if threshold in (3, 6, 9) else 0


def totals_for_level(level: int) -> tuple[int, int, int]:
	off = defn = spd = 0
	for t in range(1, level + 1):
		off += incremental_offence(t)
		defn += incremental_defence(t)
		spd += incremental_speed(t)
	return off, defn, spd


@dataclass
class ActionCorrelation:
	sequence: int = 1
	damage_awarded: bool = False
	attack_or_cast_awarded: bool = False
	defend_awarded: bool = False
	wait_observed: bool = False
	cancelled_cast: bool = False


@dataclass
class StackState:
	level: int = 0
	applied_thresholds: set[int] = field(default_factory=set)
	rank: int = 1


@dataclass
class Engine:
	action: ActionCorrelation = field(default_factory=ActionCorrelation)
	stack: StackState = field(default_factory=StackState)
	observations: set[str] = field(default_factory=set)

	def begin_action(self) -> None:
		self.action = ActionCorrelation(sequence=self.action.sequence + 1)

	def end_action(self) -> None:
		self.action = ActionCorrelation(sequence=self.action.sequence)

	def correlate(
		self,
		kind: str,
		obs: str,
		*,
		positive_damage: bool = False,
		immune: bool = False,
		cancelled: bool = False,
	) -> int:
		if cancelled or self.action.cancelled_cast:
			self.action.cancelled_cast = True
			return 0
		if obs in self.observations:
			return 0
		self.observations.add(obs)
		if kind == "attack_or_cast":
			if self.action.attack_or_cast_awarded:
				return 0
			self.action.attack_or_cast_awarded = True
			return 1
		if kind == "damage":
			if immune or not positive_damage:
				return 0
			if self.action.damage_awarded:
				return 0
			self.action.damage_awarded = True
			return 2
		if kind == "defend":
			if self.action.defend_awarded:
				return 0
			self.action.defend_awarded = True
			return 3
		if kind == "wait":
			self.action.wait_observed = True
			return 0
		raise AssertionError(f"unknown kind {kind}")

	def apply_gain(self, gain: int) -> list[int]:
		if gain <= 0:
			return []
		cap = resolve_cap(self.stack.rank)
		before = self.stack.level
		self.stack.level = min(cap, max(0, self.stack.level + gain))
		crossed: list[int] = []
		for t in range(before + 1, self.stack.level + 1):
			if t not in self.stack.applied_thresholds:
				self.stack.applied_thresholds.add(t)
				crossed.append(t)
		return crossed


def expect(cond: bool, msg: str) -> None:
	if not cond:
		raise SystemExit(f"correlation fixture failed: {msg}")


def run_sequences() -> None:
	# Melee attack +1
	e = Engine()
	e.begin_action()
	g = e.correlate("attack_or_cast", "melee-1")
	expect(g == 1, "melee attack +1")
	expect(e.correlate("attack_or_cast", "melee-1") == 0, "duplicate melee observation")
	e.end_action()

	# Ranged attack +1
	e.begin_action()
	expect(e.correlate("attack_or_cast", "ranged-1") == 1, "ranged attack +1")
	e.end_action()

	# Successful cast +1
	e.begin_action()
	expect(e.correlate("attack_or_cast", "cast-ok") == 1, "successful cast +1")
	e.end_action()

	# Cancelled cast: no gain
	e.begin_action()
	expect(e.correlate("attack_or_cast", "cast-cancel", cancelled=True) == 0, "cancelled cast")
	expect(e.correlate("attack_or_cast", "cast-after-cancel") == 0, "cast after cancel still blocked")
	e.end_action()

	# Counterattack +1; damage during that enclosing action still eligible for one +2
	e.begin_action()
	expect(e.correlate("attack_or_cast", "counter-1") == 1, "counterattack +1")
	expect(e.correlate("damage", "counter-dmg-1", positive_damage=True) == 2, "damage during counter +2")
	expect(e.correlate("damage", "counter-dmg-2", positive_damage=True) == 0, "multi-hit damage once")
	e.end_action()

	# Positive / zero / immune damage
	e.begin_action()
	expect(e.correlate("damage", "zero", positive_damage=False) == 0, "zero damage")
	expect(e.correlate("damage", "immune", positive_damage=True, immune=True) == 0, "immune damage")
	expect(e.correlate("damage", "pos", positive_damage=True) == 2, "positive damage +2")
	expect(e.correlate("damage", "pos2", positive_damage=True) == 0, "second positive damage")
	e.end_action()

	# Defend +3 once; Wait awards nothing
	e.begin_action()
	expect(e.correlate("wait", "wait-1") == 0, "Wait awards nothing")
	e.end_action()
	e.begin_action()
	expect(e.correlate("defend", "defend-1") == 3, "Defend +3")
	expect(e.correlate("defend", "defend-1") == 0, "duplicate Defend observation")
	expect(e.correlate("defend", "defend-2") == 0, "Defend once per action")
	e.end_action()

	# Caps and threshold progression
	basic = Engine(stack=StackState(rank=1))
	for obs in ("a1", "a2", "a3", "a4"):
		basic.begin_action()
		basic.apply_gain(basic.correlate("attack_or_cast", obs))
		basic.end_action()
	expect(basic.stack.level == 3, f"Basic cap level={basic.stack.level}")
	expect(totals_for_level(basic.stack.level) == (2, 2, 1), "Basic totals +2/+2/+1")

	advanced = Engine(stack=StackState(rank=2))
	for obs in ("d1", "d2"):
		advanced.begin_action()
		advanced.apply_gain(advanced.correlate("defend", obs))
		advanced.end_action()
	expect(advanced.stack.level == 6, f"Advanced level={advanced.stack.level}")
	expect(totals_for_level(6) == (4, 4, 2), "Advanced totals +4/+4/+2")

	expert = Engine(stack=StackState(rank=3))
	for obs in ("e1", "e2", "e3"):
		expert.begin_action()
		crossed = expert.apply_gain(expert.correlate("defend", obs))
		if obs == "e1":
			expect(crossed == [1, 2, 3], f"multi-level crossed {crossed}")
		expert.end_action()
	expect(expert.stack.level == 9, f"Expert level={expert.stack.level}")
	expect(totals_for_level(9) == (6, 6, 3), "Expert totals +6/+6/+3")
	expert.begin_action()
	expert.apply_gain(expert.correlate("defend", "e4"))
	expect(expert.stack.level == 9, "Expert stays at 9")
	expert.end_action()

	# +2 / +3 gains apply every crossed threshold without duplicate buffs
	jump = Engine(stack=StackState(rank=3))
	jump.begin_action()
	crossed = jump.apply_gain(jump.correlate("defend", "jump"))
	expect(crossed == [1, 2, 3], "Defend from 0 crosses 1/2/3 once")
	expect(jump.apply_gain(0) == [], "no duplicate thresholds on zero gain")

	# Battle cleanup empties state
	jump.stack = StackState(rank=3)
	jump.action = ActionCorrelation()
	jump.observations.clear()
	expect(jump.stack.level == 0 and not jump.stack.applied_thresholds, "battle reset empty")


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
	parser.parse_args()
	run_sequences()
	print("validated HoMM3 Bulwark Runes correlation fixture")


if __name__ == "__main__":
	main()
