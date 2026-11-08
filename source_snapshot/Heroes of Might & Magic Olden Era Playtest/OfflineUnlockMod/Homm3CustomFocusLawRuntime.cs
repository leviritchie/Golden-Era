namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated Focus/Energy support entry points.
/// Focus is not a standalone target packet in the law matrix. Future exact
/// hooks must enter through the law family that consumes the Focus event
/// (counterattack, spell package, or cooldown) and may only read exact native
/// payloads through Homm3FocusNativeAdapter here.
/// </summary>
internal static class Homm3CustomFocusLawRuntime
{
	internal static bool TryReadCounterattackFocusEvent(
		object lawOwner,
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForHandler(
			lawOwner,
			energyEventArgs,
			"counterattack.doctrine",
			Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryReadCounterattackFocusEventForEventSide(
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForEventSideHandler(
			energyEventArgs,
			"counterattack.doctrine",
			Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex,
			out info,
			out lawOwner,
			out context,
			out failReason);
	}

	internal static bool TryReadLowSpellFocusEvent(
		object lawOwner,
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForHandler(
			lawOwner,
			energyEventArgs,
			"spell.low",
			Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryReadLowSpellFocusEventForEventSide(
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForEventSideHandler(
			energyEventArgs,
			"spell.low",
			Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex,
			out info,
			out lawOwner,
			out context,
			out failReason);
	}

	internal static bool TryReadHighSpellFocusEvent(
		object lawOwner,
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForHandler(
			lawOwner,
			energyEventArgs,
			"spell.high",
			Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryReadHighSpellFocusEventForEventSide(
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForEventSideHandler(
			energyEventArgs,
			"spell.high",
			Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex,
			out info,
			out lawOwner,
			out context,
			out failReason);
	}

	internal static bool TryReadCooldownFocusEvent(
		object lawOwner,
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForHandler(
			lawOwner,
			energyEventArgs,
			"spell.cooldown",
			Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			out info,
			out context,
			out failReason);
	}

	internal static bool TryReadCooldownFocusEventForEventSide(
		object energyEventArgs,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		return TryReadEnergyEventForEventSideHandler(
			energyEventArgs,
			"spell.cooldown",
			Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			out info,
			out lawOwner,
			out context,
			out failReason);
	}

	internal static bool TryReadCooldownAbilityEnergyInfo(
		object lawOwner,
		object abilityOrWrapper,
		out Homm3FocusNativeAdapter.AbilityEnergyInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3FocusNativeAdapter.TryReadAbilityEnergyInfo(abilityOrWrapper, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			"spell.cooldown",
			Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			out context,
			out failReason);
	}

	private static bool TryReadEnergyEventForEventSideHandler(
		object energyEventArgs,
		string handlerKey,
		int lawIndex,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out object lawOwner,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		lawOwner = null;
		context = default;
		if (!Homm3FocusNativeAdapter.TryReadEnergyEvent(energyEventArgs, out info, out failReason))
			return false;
		if (info.Side == null)
		{
			failReason = "Focus/Energy event side is null";
			return false;
		}
		lawOwner = info.Side;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			handlerKey,
			lawIndex,
			out context,
			out failReason);
	}

	private static bool TryReadEnergyEventForHandler(
		object lawOwner,
		object energyEventArgs,
		string handlerKey,
		int lawIndex,
		out Homm3FocusNativeAdapter.EnergyEventInfo info,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		info = default;
		context = default;
		if (!Homm3FocusNativeAdapter.TryReadEnergyEvent(energyEventArgs, out info, out failReason))
			return false;
		return Homm3CustomLawHandlerRegistry.TryEnterHandler(
			lawOwner,
			handlerKey,
			lawIndex,
			out context,
			out failReason);
	}
}
