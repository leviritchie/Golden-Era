using System;
using Hex.Session.Hud;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Redraws the adventure-map resource bar after the mod writes a resource directly (Ransom, recruit spending, law and
/// reward payouts). The Data.Resource add the mod uses does not raise the bar's change event, so the shown totals stayed
/// stale until the next native resource change. Hex.Session.Hud.BhResPanel.CallOnChanged (a real name in 26615913)
/// re-reads every resource of the bound side into the bar. Main thread only; a miss is logged a few times and ignored.
/// </summary>
internal static class Homm3ResourceBarRefresh
{
	private static BhResPanel _panel;
	private static int _failLogs;
	private static float _nextScan;

	internal static void TryRefresh()
	{
		try
		{
			if (_panel == null || !_panel)
			{
				_panel = null;
				// No bar (menu, loading, battle): rescan at most every two seconds.
				if (Time.unscaledTime < _nextScan)
					return;
				_nextScan = Time.unscaledTime + 2f;
				foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<BhResPanel>()))
				{
					var panel = obj?.TryCast<BhResPanel>();
					if (panel != null && panel && panel.gameObject.scene.IsValid())
					{
						_panel = panel;
						break;
					}
				}
			}
			_panel?.CallOnChanged();
		}
		catch (Exception ex)
		{
			_panel = null;
			if (_failLogs++ < 4)
				Plugin.LogSource?.LogWarning("Resource bar refresh failed: " + ex.GetBaseException().Message);
		}
	}
}
