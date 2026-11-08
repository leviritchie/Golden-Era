using System.Text;

namespace OfflineUnlockMod;

/// <summary>
/// Central entry seam for future no-compromise custom law gameplay handlers.
/// This class intentionally performs no native mutation. It only validates that
/// a hook is entering through a known law-family handler and then delegates to
/// Homm3CustomLawRuntimeGuard, which currently denies every packet until proof
/// state is promoted from reviewed runtime evidence.
/// </summary>
internal static class Homm3CustomLawHandlerRegistry
{
	internal struct HandlerSlot
	{
		internal int LawIndex;
		internal string Packet;
		internal string HandlerKey;
		internal string Purpose;

		public override string ToString()
		{
			return "handler='" + HandlerKey
			       + "' lawIndex=" + LawIndex
			       + " packet='" + Packet
			       + "' purpose='" + Purpose + "'";
		}
	}

	internal static readonly HandlerSlot[] KnownHandlerSlots =
	{
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.HeroSightRadiusIndex,
			Packet = Homm3CustomLawPacketGate.Vision,
			HandlerKey = "vision.reveal",
			Purpose = "Adventure-map reveal and inspection laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			Packet = Homm3CustomLawPacketGate.CommittedDamage,
			HandlerKey = "damage.training",
			Purpose = "Training, damage-scaling, mitigation, and corpse/mana combat laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			Packet = Homm3CustomLawPacketGate.Counterattack,
			HandlerKey = "counterattack.doctrine",
			Purpose = "Faction-specific counterattack laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			Packet = Homm3CustomLawPacketGate.SpellCooldown,
			HandlerKey = "spell.low",
			Purpose = "Lower spell-school, spellbook, and cooldown-support laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.MeleeFormationIndex,
			Packet = Homm3CustomLawPacketGate.BattleAction,
			HandlerKey = "battle.melee-formation",
			Purpose = "Melee formation and adjacency laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.RangedFormationIndex,
			Packet = Homm3CustomLawPacketGate.BattleAction,
			HandlerKey = "battle.ranged-formation",
			Purpose = "Ranged formation, first-volley, and shooter-support laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.GoldIncomePercentIndex,
			Packet = Homm3CustomLawPacketGate.RewardResult,
			HandlerKey = "reward.gold-economy",
			Purpose = "Committed reward/result economy laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.MoraleFlatIndex,
			Packet = Homm3CustomLawPacketGate.Morale,
			HandlerKey = "morale.package",
			Purpose = "Faction morale replacement package laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.MoraleTriggerIndex,
			Packet = Homm3CustomLawPacketGate.Morale,
			HandlerKey = "morale.trigger",
			Purpose = "Morale-trigger and action-queue laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			Packet = Homm3CustomLawPacketGate.SpellCooldown,
			HandlerKey = "spell.high",
			Purpose = "High spell-school, spellbook, and cooldown-support laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.ExtraConstructionIndex,
			Packet = Homm3CustomLawPacketGate.Construction,
			HandlerKey = "construction.commit",
			Purpose = "Construction cost, eligibility, and extra-build laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex,
			Packet = Homm3CustomLawPacketGate.RewardResult,
			HandlerKey = "reward.calendar",
			Purpose = "Calendar, astrology, and daily reward laws.",
		},
		new HandlerSlot
		{
			LawIndex = Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			Packet = Homm3CustomLawPacketGate.SpellCooldown,
			HandlerKey = "spell.cooldown",
			Purpose = "Cooldown credit, reset, pressure, and cast-gate laws.",
		},
	};

	internal static bool TryEnterHandler(
		object sideOrLawOwner,
		string handlerKey,
		int lawIndex,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		context = default;
		if (!TryGetHandlerSlot(handlerKey, lawIndex, out var slot))
		{
			failReason = "unknown no-compromise law handler slot key='"
			             + (handlerKey ?? "null")
			             + "' lawIndex="
			             + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return false;
		}
		if (!Homm3CustomLawPacketGate.TryGetPacketForLawIndex(lawIndex, out var packet))
		{
			failReason = "handler slot has no packet mapping: " + slot;
			return false;
		}
		if (packet != slot.Packet)
		{
			failReason = "handler slot packet mismatch: " + slot + " runtimePacket='" + packet + "'";
			return false;
		}
		return Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(
			sideOrLawOwner,
			lawIndex,
			out context,
			out failReason);
	}

	internal static bool TryProbeHandler(
		object sideOrLawOwner,
		string handlerKey,
		int lawIndex,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		context = default;
		if (!TryGetHandlerSlot(handlerKey, lawIndex, out var slot))
		{
			failReason = "unknown no-compromise law handler slot key='"
			             + (handlerKey ?? "null")
			             + "' lawIndex="
			             + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return false;
		}
		if (!Homm3CustomLawPacketGate.TryGetPacketForLawIndex(lawIndex, out var packet))
		{
			failReason = "handler slot has no packet mapping: " + slot;
			return false;
		}
		if (packet != slot.Packet)
		{
			failReason = "handler slot packet mismatch: " + slot + " runtimePacket='" + packet + "'";
			return false;
		}
		return Homm3CustomLawRuntimeGuard.TryResolveCandidateActiveLaw(
			sideOrLawOwner,
			lawIndex,
			out context,
			out failReason);
	}

	internal static bool TryGetHandlerSlot(string handlerKey, int lawIndex, out HandlerSlot slot)
	{
		for (var i = 0; i < KnownHandlerSlots.Length; i++)
		{
			var candidate = KnownHandlerSlots[i];
			if (candidate.LawIndex == lawIndex && candidate.HandlerKey == handlerKey)
			{
				slot = candidate;
				return true;
			}
		}
		slot = default;
		return false;
	}

	internal static string DescribeHandlerSlots()
	{
		var sb = new StringBuilder();
		for (var i = 0; i < KnownHandlerSlots.Length; i++)
		{
			if (i > 0)
				sb.Append("; ");
			sb.Append(KnownHandlerSlots[i]);
		}
		return sb.ToString();
	}
}
