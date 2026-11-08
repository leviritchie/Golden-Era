using System;
using System.Text;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Opt-in (see <see cref="EsquirePikemanVisuals.VerboseEsquireHooks"/> / <c>esquirePikemanVerbose</c>) telemetry for the swapped Esquire battle prefab:
/// current animator state, transitions, <c>parameterCount</c>, and playing clip names — to debug "idle only" when <c>Player.log</c> stays quiet.
/// Per-parameter names/values are omitted: Il2CppInterop cannot use <c>AnimatorControllerParameter</c> / <c>Animator.parameters</c> on this game without <c>TypeLoadException</c> in the IL2CPP trampoline.
/// </summary>
public sealed class EsquireBattleAnimatorTelemetry : MonoBehaviour
{
	private static bool _typeRegistered;
	private static int _sessionAttachCount;

	private ManualLogSource _log;
	private Animator _anim;
	private MeshRenderer _quadRenderer;
	private int _lastFullPathHash = int.MinValue;
	private bool _lastInTransition;
	private int _frames;
	/// <summary>Verbose sessions: frequent heartbeats (high log volume).</summary>
	private const int HeartbeatFrames = 12;

	internal static void TryAttach(GameObject battleRoot, ManualLogSource log)
	{
		if (battleRoot == null || !EsquirePikemanVisuals.VerboseEsquireHooks)
			return;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<EsquireBattleAnimatorTelemetry>();
				_typeRegistered = true;
			}

			if (battleRoot.GetComponent<EsquireBattleAnimatorTelemetry>() != null)
				return;

			battleRoot.AddComponent<EsquireBattleAnimatorTelemetry>();
			_sessionAttachCount++;
			log?.LogInfo(
				"EsquirePikeman battle Animator telemetry: attached to '"
				+ battleRoot.name
				+ "' (instance #"
				+ _sessionAttachCount
				+ "; esquirePikemanVerbose=true). State/param lines go to BepInEx LogOutput.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman battle Animator telemetry: attach failed: " + ex);
		}
	}

	private void Awake()
	{
		_log = Plugin.LogSource;
		try
		{
			_anim = GetComponentInChildren<Animator>(true);
		}
		catch
		{
			_anim = null;
		}

		try
		{
			var q = transform.Find("billboard/quad");
			if (q != null)
				_quadRenderer = q.GetComponent<MeshRenderer>();
			if (_quadRenderer == null)
				_quadRenderer = GetComponentInChildren<MeshRenderer>(true);
		}
		catch
		{
			_quadRenderer = null;
		}
	}

	private void OnEnable()
	{
		LogLine("OnEnable");
	}

	private void Update()
	{
		if (_anim == null)
			return;
		_frames++;
		var info = _anim.GetCurrentAnimatorStateInfo(0);
		var inTr = _anim.IsInTransition(0);
		var hash = info.fullPathHash;
		var changed = hash != _lastFullPathHash || inTr != _lastInTransition;
		if (changed)
		{
			_lastFullPathHash = hash;
			_lastInTransition = inTr;
			LogLine("state/transition");
			return;
		}

		if (_frames % HeartbeatFrames == 0)
			LogLine("heartbeat");
	}

	private void LogLine(string reason)
	{
		if (_anim == null)
		{
			_log?.LogInfo("Esquire battle Animator telemetry[" + reason + "]: no Animator under '" + name + "'.");
			return;
		}

		try
		{
			var sb = new StringBuilder(640);
			sb.Append("Esquire battle Animator telemetry[").Append(reason).Append("] '").Append(name).Append("' ");
			try
			{
				sb.Append("dt=").Append(Time.deltaTime.ToString("0.####")).Append(" udt=").Append(Time.unscaledDeltaTime.ToString("0.####")).Append(' ');
			}
			catch
			{
				sb.Append("dt=? ");
			}

			try
			{
				sb.Append("goActive=").Append(gameObject.activeInHierarchy);
				if (_anim.gameObject != null)
					sb.Append(" animGo=").Append(_anim.gameObject.activeInHierarchy);
				sb.Append(' ');
			}
			catch
			{
				sb.Append("goActive=? ");
			}

			var rac = _anim.runtimeAnimatorController;
			sb.Append("ctrl=").Append(rac != null ? rac.name : "(null)").Append(' ');
			sb.Append("enabled=").Append(_anim.enabled).Append(" speed=").Append(_anim.speed.ToString("0.###")).Append(' ');
			try
			{
				sb.Append("upd=").Append(_anim.updateMode.ToString()).Append(" cull=").Append(_anim.cullingMode.ToString());
				sb.Append(" init=").Append(_anim.isInitialized);
				sb.Append(" rootMo=").Append(_anim.applyRootMotion);
				sb.Append(' ');
			}
			catch
			{
				sb.Append("animFlags=? ");
			}

			var info = _anim.GetCurrentAnimatorStateInfo(0);
			sb.Append("L0 shortHash=0x").Append(info.shortNameHash.ToString("X8"));
			sb.Append(" fullHash=0x").Append(info.fullPathHash.ToString("X8"));
			sb.Append(" normTime=").Append(info.normalizedTime.ToString("0.###"));
			sb.Append(" length=").Append(info.length.ToString("0.###"));
			try
			{
				sb.Append(" stSpd=").Append(info.speed.ToString("0.###"));
				sb.Append(" stSpdMul=").Append(info.speedMultiplier.ToString("0.###"));
				sb.Append(" loop=").Append(info.loop);
			}
			catch
			{
				sb.Append(" stFlags=?");
			}

			sb.Append(" inTrans=").Append(_anim.IsInTransition(0));
			if (_anim.IsInTransition(0))
			{
				var next = _anim.GetNextAnimatorStateInfo(0);
				sb.Append(" nextShort=0x").Append(next.shortNameHash.ToString("X8"));
				sb.Append(" nextFull=0x").Append(next.fullPathHash.ToString("X8"));
				try
				{
					var tr = _anim.GetAnimatorTransitionInfo(0);
					sb.Append(" trDur=").Append(tr.duration.ToString("0.####"));
					sb.Append(" trNorm=").Append(tr.normalizedTime.ToString("0.####"));
					sb.Append(" trAny=").Append(tr.anyState);
					sb.Append(" trNameHash=0x").Append(tr.nameHash.ToString("X8"));
					sb.Append(" trFullHash=0x").Append(tr.fullPathHash.ToString("X8"));
				}
				catch
				{
					sb.Append(" trInfo=?");
				}
			}

			try
			{
				sb.Append(" paramCount=").Append(_anim.parameterCount);
			}
			catch
			{
				sb.Append(" paramCount=?");
			}

			try
			{
				var infos = _anim.GetCurrentAnimatorClipInfo(0);
				if (infos != null && infos.Length > 0)
				{
					sb.Append(" clips=");
					for (var i = 0; i < infos.Length; i++)
					{
						var c = infos[i].clip;
						if (c != null)
						{
							sb.Append(c.name).Append('@').Append(infos[i].weight.ToString("0.###")).Append('|');
						}
					}
				}
			}
			catch
			{
				sb.Append(" clips=?");
			}

			try
			{
				var lc = _anim.layerCount;
				sb.Append(" layerCount=").Append(lc);
				var maxL = Math.Min(lc, 6);
				for (var L = 0; L < maxL; L++)
				{
					float w;
					try
					{
						w = _anim.GetLayerWeight(L);
					}
					catch
					{
						w = -1f;
					}

					if (L == 0)
					{
						sb.Append(" L").Append(L).Append("w=").Append(w.ToString("0.###"));
						continue;
					}

					var li = _anim.GetCurrentAnimatorStateInfo(L);
					sb.Append(" L").Append(L).Append("=0x").Append(li.fullPathHash.ToString("X8"));
					sb.Append("w=").Append(w.ToString("0.###"));
					var cinf = _anim.GetCurrentAnimatorClipInfo(L);
					if (cinf != null && cinf.Length > 0)
					{
						sb.Append('[');
						for (var k = 0; k < cinf.Length; k++)
						{
							var ck = cinf[k].clip;
							if (ck != null)
								sb.Append(ck.name).Append('@').Append(cinf[k].weight.ToString("0.###")).Append(',');
						}

						sb.Append(']');
					}
				}
			}
			catch
			{
				sb.Append(" layers=?");
			}

			AppendQuadVisualSample(sb);

			// Avoid AnimatorControllerParameter (from .parameters, GetParameter, etc.): Il2CppInterop trampoline throws
			// TypeLoadException for Il2CppReferenceArray<AnimatorControllerParameter> / struct interop on this game.

			_log?.LogInfo(sb.ToString());
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Esquire battle Animator telemetry[" + reason + "] failed: " + ex);
		}
	}

	/// <summary>
	/// Samples the billboard quad <see cref="MeshRenderer"/> so we can compare animator clip state to the material actually bound
	/// (flip-book clips drive <c>m_Materials.Array.data[0]</c> on <c>billboard/quad</c> in the editor build).
	/// </summary>
	private void AppendQuadVisualSample(StringBuilder sb)
	{
		try
		{
			if (_quadRenderer == null)
			{
				sb.Append(" quad=(no MeshRenderer)");
				return;
			}

			sb.Append(" quad=en:").Append(_quadRenderer.enabled);
			try
			{
				sb.Append(" vis:").Append(_quadRenderer.isVisible);
				sb.Append(" qAct:").Append(_quadRenderer.gameObject.activeInHierarchy);
				var tr = _quadRenderer.transform;
				sb.Append(" path:").Append(BuildTransformPath(tr));
				sb.Append(" locScl:").Append(tr.localScale.ToString("0.####"));
				var b = _quadRenderer.bounds;
				sb.Append(" bnd:").Append(b.extents.ToString("0.####"));
			}
			catch
			{
				sb.Append(" zg=?");
			}

			var mats = _quadRenderer.sharedMaterials;
			if (mats == null || mats.Length == 0)
			{
				sb.Append(" mat=(none)");
				return;
			}

			var m0 = mats[0];
			if (m0 == null)
			{
				sb.Append(" mat[0]=(null) count=").Append(mats.Length);
				return;
			}

			sb.Append(" mat=").Append(m0.name);
			sb.Append(" mid=").Append(m0.GetInstanceID());
			try
			{
				var zj = m0.shader;
				sb.Append(" zj=").Append(zj != null ? zj.name : "(null)");
			}
			catch
			{
				sb.Append(" zj=?");
			}

			Texture main = null;
			try
			{
				main = m0.GetTexture("_MainTex");
			}
			catch
			{
			}

			if (main == null)
			{
				try
				{
					main = m0.GetTexture("_BaseMap");
				}
				catch
				{
				}
			}

			if (main != null)
				sb.Append(" tex=").Append(main.name).Append(" tid=").Append(main.GetInstanceID());
			else
				sb.Append(" tex=(no _MainTex/_BaseMap)");

			if (mats.Length > 1)
			{
				sb.Append(" matCount=").Append(mats.Length).Append(" mats[");
				for (var mi = 0; mi < Math.Min(mats.Length, 4); mi++)
				{
					var mx = mats[mi];
					sb.Append(mi).Append('=');
					if (mx == null)
						sb.Append("null;");
					else
						sb.Append(mx.name).Append('#').Append(mx.GetInstanceID()).Append(';');
				}

				sb.Append(']');
			}

			try
			{
				sb.Append(" shMode=").Append(_quadRenderer.shadowCastingMode.ToString());
				sb.Append(" recvSh=").Append(_quadRenderer.receiveShadows);
				sb.Append(" lmapIdx=").Append(_quadRenderer.realtimeLightmapIndex).Append(" stlmap=").Append(_quadRenderer.realtimeLightmapScaleOffset);
			}
			catch
			{
				sb.Append(" rndFlags=?");
			}
		}
		catch
		{
			sb.Append(" quad=?");
		}
	}

	private static string BuildTransformPath(Transform t)
	{
		if (t == null)
			return "?";
		try
		{
			var parts = new string[16];
			var n = 0;
			for (var cur = t; cur != null && n < parts.Length; cur = cur.parent)
				parts[n++] = cur.name;
			Array.Reverse(parts, 0, n);
			return string.Join("/", parts, 0, n);
		}
		catch
		{
			return "?";
		}
	}
}
