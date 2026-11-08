using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using BepInEx.Unity.IL2CPP.Utils;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.UI;
using UnityObject = UnityEngine.Object;
using UnityImage = UnityEngine.UI.Image;

namespace OfflineUnlockMod;

// Current-build Submit ownership; native UI/runtime proof is still pending (docs/mod_bug_reporting.md).
internal static class ModBugReportSubmission
{
	private const string HostObjectName = "OFFLINE_UNLOCK_MOD_BUG_REPORT_SUBMISSION";
	private const int WindowId = 0x4B52;
	private const float ConsentWindowWidth = 520f;
	private const float ConsentWindowHeight = 460f;
	private const float ReferenceScreenHeight = 720f;
	private const float StatusWindowWidth = 380f;
	private const int MaxScreenshotSourcePixels = 16 * 1024 * 1024;
	private const int MaxScreenshotWidth = 1280;
	private const int MaxScreenshotHeight = 720;
	private const float IteratorWatchdogSeconds = 10f;

	private enum FlowState
	{
		AwaitingIterator,
		AwaitingIteratorStateOne,
		CapturingScreenshot,
		PackagingAndSubmitting,
		Acknowledged,
		Unconfirmed,
		ScreenshotFailed,
		CaptureFailed,
		Cancelled,
		StartFailed,
	}

	private sealed class Transaction
	{
		internal readonly string ReportId;
		internal readonly bool IncludeScreenshot;
		internal IntPtr ScreenPointer;
		internal IntPtr IteratorPointer;
		internal float StartedAtRealtime;
		internal FlowState State;
		internal ModBugReportRedirect.CaptureData Capture;
		internal Task<ModBugReportRedirect.ReportOutcome> Task;
		internal ModBugReportRedirect.ReportOutcome Outcome;
		internal string Error;
		internal bool Minimized;
		internal bool RestoredAfterRestart;

		internal Transaction(string reportId, bool includeScreenshot, IntPtr screenPointer)
		{
			ReportId = reportId;
			IncludeScreenshot = includeScreenshot;
			ScreenPointer = screenPointer;
			StartedAtRealtime = Time.realtimeSinceStartup;
			State = FlowState.AwaitingIterator;
		}
	}

	private static ManualLogSource _log;
	private static LauncherConfig _cfg;
	private static MethodInfo _submitMethod;
	private static MethodInfo _moveNextMethod;
	private static MethodInfo _closeMethod;
	private static PropertyInfo _iteratorState;
	private static PropertyInfo _iteratorOwner;
	private static PropertyInfo[] _iteratorStrings;
	private static PropertyInfo _iteratorNativeLog;
	private static PropertyInfo _iteratorAttachments;
	private static object _consentScreen;
	private static IntPtr _consentScreenPointer;
	private static object _pendingNewReportScreen;
	private static IntPtr _pendingNewReportScreenPointer;
	private static IntPtr _authorizedSubmitPointer;
	private static IntPtr _authorizedClosePointer;
	private static bool _consentChecked;
	private static bool _includeScreenshotChecked;
	private static bool _abandonRetryConfirmation;
	private static Vector2 _consentScroll;
	private static bool _visible;
	private static bool _suppressOverlayForCapture;
	private static bool _registered;
	private static Transaction _transaction;

	internal static bool IsOverlayVisible => _visible;
	private static ModBugReportSubmissionHost _host;
	private static GUIStyle _wrappedLabel;
	private static Canvas _pointerShieldCanvas;
	private static GraphicRaycaster _pointerShieldRaycaster;
	private static UnityImage _pointerShieldImage;
	private static readonly GUI.WindowFunction WindowCallback = (Action<int>)DrawWindow;

	internal static bool TryRegister(Harmony harmony, ManualLogSource log, LauncherConfig cfg, out string error)
	{
		error = null;
		if (_registered)
			return true;
		if (harmony == null || log == null || cfg == null)
		{
			error = "harmony, logger, and config are required";
			return false;
		}
		if (GameBuild.Kind != GameBuildKind.Current)
		{
			error = "submission UI is pinned only to current build 25672315; found " + GameBuild.Describe();
			return false;
		}
		if (!cfg.ModBugReporting || ModBugReportRedirect.State != ModBugReportRedirect.GuardState.Redirecting)
		{
			error = "native SendReport sink is not protected for mod bug reporting";
			return false;
		}
		if (!ModBugReportTransport.IsEndpoint(cfg.ModBugReportingEndpoint))
		{
			error = "a valid Google Apps Script relay endpoint is required; local-only reporting is not enabled";
			return false;
		}

		try
		{
			var screen = GameMember.FindTypeFromHints("bugReport.submit.screen", GameSymbols.ModBugReporting.ScreenTypeHints);
			if (screen == null)
			{
				error = "current bug report screen type did not resolve";
				return false;
			}

			var submit = GameMember.FindEveryMethodByNames(
				screen,
				GameSymbols.ModBugReporting.CurrentSubmitHandler,
				m => m != null && m.IsPublic && !m.IsStatic && !m.IsVirtual
				     && m.ReturnType == typeof(void) && m.GetParameters().Length == 0,
				out var submitError);
			if (submit == null || submit.Length != 1)
			{
				error = "expected exactly one pinned current Submit callback: " + (submitError ?? "unexpected method count");
				return false;
			}
			if (!TryReadNativeMethodName(
				screen,
				GameSymbols.ModBugReporting.CurrentSubmitHandlerMethodInfoFieldName,
				out var submitNativeName,
				out error)
				|| !string.Equals(submitNativeName, GameSymbols.ModBugReporting.CurrentSubmitHandlerNativeName, StringComparison.Ordinal))
			{
				error ??= "current Submit callback does not match its centralized native method pin";
				return false;
			}

			var iteratorTypes = screen.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
				.Where(t => string.Equals(ReadObfuscatedName(t), GameSymbols.ModBugReporting.CurrentSubmitIteratorObfuscatedName, StringComparison.Ordinal))
				.ToArray();
			if (iteratorTypes.Length != 1 || iteratorTypes[0].BaseType?.FullName != "Il2CppSystem.Object")
			{
				error = "expected exactly one current Send iterator by obfuscated-name pin, found " + iteratorTypes.Length;
				return false;
			}

			var iteratorType = iteratorTypes[0];
			if (!string.Equals(iteratorType.FullName, GameSymbols.ModBugReporting.CurrentSubmitIteratorManagedTypeFullName, StringComparison.Ordinal))
			{
				error = "current Send iterator wrapper owner changed: " + iteratorType.FullName;
				return false;
			}

			var moveNext = GameMember.FindEveryMethodByNames(
				iteratorType,
				GameSymbols.ModBugReporting.CurrentSubmitIteratorMoveNext,
				m => m != null && m.IsPublic && !m.IsStatic && m.IsVirtual
				     && m.ReturnType == typeof(bool) && m.GetParameters().Length == 0,
				out var moveNextError);
			if (moveNext == null || moveNext.Length != 1)
			{
				error = "expected exactly one current iterator MoveNext(bool) target: " + (moveNextError ?? "unexpected method count");
				return false;
			}

			if (!TryResolveFieldProperty(iteratorType, GameSymbols.ModBugReporting.CurrentSubmitIteratorState, typeof(int), out _iteratorState, out error)
				|| !TryResolveFieldProperty(iteratorType, GameSymbols.ModBugReporting.CurrentSubmitIteratorOwner, screen, out _iteratorOwner, out error))
				return false;

			_iteratorStrings = new PropertyInfo[GameSymbols.ModBugReporting.CurrentSubmitIteratorStrings.Length];
			for (var i = 0; i < _iteratorStrings.Length; i++)
			{
				if (!TryResolveFieldProperty(
					iteratorType,
					GameSymbols.ModBugReporting.CurrentSubmitIteratorStrings[i],
					typeof(string),
					out _iteratorStrings[i],
					out error))
					return false;
			}

			if (!TryResolveFieldProperty(
				iteratorType,
				GameSymbols.ModBugReporting.CurrentSubmitIteratorNativeLog,
				typeof(Il2CppStructArray<byte>),
				out _iteratorNativeLog,
				out error)
				|| !TryResolveFieldProperty(
					iteratorType,
					GameSymbols.ModBugReporting.CurrentSubmitIteratorAttachments,
					typeof(Il2CppSystem.Collections.Generic.Dictionary<string, Il2CppStructArray<byte>>),
					out _iteratorAttachments,
					out error))
				return false;

			var close = GameMember.FindEveryMethodByNames(
				screen,
				GameSymbols.ModBugReporting.CurrentScreenClose,
				m => m != null && m.IsPublic && !m.IsStatic && !m.IsVirtual
				     && m.ReturnType == typeof(void) && m.GetParameters().Length == 0,
				out var closeError);
			if (close == null || close.Length != 1)
			{
				error = "expected exactly one current bug report Close method: " + (closeError ?? "unexpected method count");
				return false;
			}

			_submitMethod = submit[0];
			_moveNextMethod = moveNext[0];
			_closeMethod = close[0];
			_log = log;
			_cfg = cfg;

			AttachHost();
			harmony.Patch(
				_submitMethod,
				prefix: new HarmonyMethod(typeof(ModBugReportSubmission), nameof(SubmitPrefix)) { priority = Priority.First });
			harmony.Patch(
				_moveNextMethod,
				prefix: new HarmonyMethod(typeof(ModBugReportSubmission), nameof(IteratorMoveNextPrefix)) { priority = Priority.First });
			harmony.Patch(
				_closeMethod,
				prefix: new HarmonyMethod(typeof(ModBugReportSubmission), nameof(ClosePrefix)) { priority = Priority.First });
			_registered = true;
			log.LogInfo("ModBugReporting: explicit current-build Submit flow registered; native send tail is suppressed until relay acknowledgement.");
			RestoreUnsentReport();
			return true;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	// A finalized bundle that was never acknowledged or abandoned (for example, the game closed mid-upload) comes back
	// as a minimized unconfirmed status. Nothing is sent until the player presses Retry; Abandon releases it.
	private static void RestoreUnsentReport()
	{
		try
		{
			var unsent = ModBugReportRedirect.FindLatestUnsentReport();
			if (unsent == null || _transaction != null)
				return;
			_transaction = new Transaction(unsent.ReportId, false, IntPtr.Zero)
			{
				State = FlowState.Unconfirmed,
				Outcome = unsent,
				Error = unsent.Error,
				Minimized = true,
				RestoredAfterRestart = true,
			};
			_visible = true;
			SafeLogInfo("ModBugReporting: an unsent report from a previous session is available for explicit retry (reportId=" + unsent.ReportId + ").");
		}
		catch (Exception ex)
		{
			SafeLogWarning("ModBugReporting: unsent report restore failed (" + ex.GetType().Name + ").");
		}
	}

	private static bool TryResolveFieldProperty(Type owner, GameSymbols.FieldSymbol symbol, Type expectedType, out PropertyInfo property, out string error)
	{
		property = null;
		error = null;
		if (GameSymbolScope.IsSentinel(symbol.NativeFieldInfoName) || GameSymbolScope.IsSentinel(symbol.FieldName))
		{
			error = symbol.Id + " current symbol scope was refused";
			return false;
		}

		const BindingFlags instanceFlags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		var properties = owner.GetProperties(instanceFlags)
			.Where(p => string.Equals(p.Name, symbol.FieldName, StringComparison.Ordinal)
			            && p.GetIndexParameters().Length == 0 && p.GetMethod != null)
			.ToArray();
		var nativeFieldInfo = owner.GetField(
			symbol.NativeFieldInfoName,
			BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly);
		if (properties.Length != 1 || properties[0].PropertyType != expectedType
			|| nativeFieldInfo == null || nativeFieldInfo.FieldType != typeof(IntPtr))
		{
			error = "current iterator field pin did not match " + symbol.Id;
			return false;
		}

		try
		{
			RuntimeHelpers.RunClassConstructor(owner.TypeHandle);
			if ((IntPtr)nativeFieldInfo.GetValue(null) == IntPtr.Zero)
			{
				error = "current iterator native field metadata is unavailable for " + symbol.Id;
				return false;
			}
		}
		catch (Exception ex)
		{
			error = "current iterator field metadata failed for " + symbol.Id + " (" + ex.GetType().Name + ")";
			return false;
		}

		property = properties[0];
		return true;
	}

	private static bool TryReadNativeMethodName(Type owner, string methodInfoFieldName, out string name, out string error)
	{
		name = null;
		error = null;
		try
		{
			RuntimeHelpers.RunClassConstructor(owner.TypeHandle);
			var field = owner.GetField(
				methodInfoFieldName,
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly);
			if (field == null || field.FieldType != typeof(IntPtr))
			{
				error = "current Submit method metadata field is missing";
				return false;
			}
			var methodInfo = (IntPtr)field.GetValue(null);
			if (methodInfo == IntPtr.Zero)
			{
				error = "current Submit method metadata is unavailable";
				return false;
			}
			name = Marshal.PtrToStringAnsi(IL2CPP.il2cpp_method_get_name(methodInfo));
			if (string.IsNullOrEmpty(name))
				error = "current Submit native method name is unavailable";
			return !string.IsNullOrEmpty(name);
		}
		catch (Exception ex)
		{
			error = "current Submit method pin failed (" + ex.GetType().Name + ")";
			return false;
		}
	}

	private static string ReadObfuscatedName(MemberInfo member)
	{
		foreach (var attribute in CustomAttributeData.GetCustomAttributes(member))
		{
			if (attribute.AttributeType.Name != "ObfuscatedNameAttribute" || attribute.ConstructorArguments.Count == 0)
				continue;
			return attribute.ConstructorArguments[0].Value as string;
		}
		return null;
	}

	private static void AttachHost()
	{
		if (_host != null)
			return;
		ClassInjector.RegisterTypeInIl2Cpp<ModBugReportSubmissionHost>();
		var go = new GameObject(HostObjectName) { hideFlags = HideFlags.HideAndDontSave };
		_host = go.AddComponent<ModBugReportSubmissionHost>();
		if (_host == null)
		{
			UnityObject.Destroy(go);
			throw new InvalidOperationException("submission host AddComponent returned null");
		}
		UnityObject.DontDestroyOnLoad(go);
		AttachPointerShield();
	}

	private static void AttachPointerShield()
	{
		var canvasObject = new GameObject("OFFLINE_UNLOCK_MOD_BUG_REPORT_POINTER_SHIELD", new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<GraphicRaycaster>(),
		})
		{
			hideFlags = HideFlags.HideAndDontSave,
		};
		var canvas = canvasObject.GetComponent<Canvas>();
		var raycaster = canvasObject.GetComponent<GraphicRaycaster>();
		if (canvas == null || raycaster == null)
		{
			UnityObject.Destroy(canvasObject);
			throw new InvalidOperationException("report pointer shield canvas/raycaster could not be created");
		}

		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = 32767;
		var imageObject = new GameObject("ReportWindowRaycastTarget", new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<CanvasRenderer>(),
			Il2CppType.Of<UnityImage>(),
		});
		imageObject.transform.SetParent(canvasObject.transform, false);
		var image = imageObject.GetComponent<UnityImage>();
		if (image == null)
		{
			UnityObject.Destroy(canvasObject);
			throw new InvalidOperationException("report pointer shield image could not be created");
		}

		var imageRect = image.rectTransform;
		imageRect.anchorMin = Vector2.zero;
		imageRect.anchorMax = Vector2.one;
		imageRect.offsetMin = Vector2.zero;
		imageRect.offsetMax = Vector2.zero;
		image.color = new UnityEngine.Color(0f, 0f, 0f, 0f);
		image.raycastTarget = true;
		image.maskable = false;
		image.canvasRenderer.cullTransparentMesh = false;
		image.enabled = false;
		_pointerShieldCanvas = canvas;
		_pointerShieldRaycaster = raycaster;
		_pointerShieldImage = image;
		UnityObject.DontDestroyOnLoad(canvasObject);
	}

	private static bool SubmitPrefix(object __instance)
	{
		try
		{
			var pointer = NativePointer(__instance);
			if (pointer == IntPtr.Zero)
				return false;
			if (_authorizedSubmitPointer == pointer)
			{
				_authorizedSubmitPointer = IntPtr.Zero;
				return true;
			}
			if (_transaction != null && _transaction.State == FlowState.Unconfirmed)
			{
				var pendingPointer = NativePointer(_pendingNewReportScreen);
				if (_pendingNewReportScreenPointer == IntPtr.Zero || pendingPointer != _pendingNewReportScreenPointer
				    || _pendingNewReportScreenPointer == pointer)
				{
					_pendingNewReportScreen = __instance;
					_pendingNewReportScreenPointer = pointer;
					_abandonRetryConfirmation = true;
				}
				_transaction.Minimized = false;
				_visible = true;
				return false;
			}

			if (_transaction != null && !IsTerminal(_transaction.State))
			{
				_transaction.Minimized = false;
				_visible = true;
				return false;
			}
			_transaction = null;
			if (_consentScreenPointer != IntPtr.Zero)
				return false;

			_consentScreen = __instance;
			_consentScreenPointer = pointer;
			_consentChecked = false;
			_includeScreenshotChecked = false;
			_consentScroll = Vector2.zero;
			_visible = true;
			return false;
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: Submit consent interception failed (" + ex.GetType().Name + ").");
			return false;
		}
	}

	private static bool ClosePrefix(object __instance)
	{
		try
		{
			var pointer = NativePointer(__instance);
			if (pointer != IntPtr.Zero && pointer == _authorizedClosePointer)
			{
				_authorizedClosePointer = IntPtr.Zero;
				return true;
			}
			if (pointer != IntPtr.Zero && pointer == _consentScreenPointer)
			{
				ClearConsent();
				return true;
			}
			if (pointer != IntPtr.Zero && pointer == _pendingNewReportScreenPointer)
			{
				_pendingNewReportScreen = null;
				_pendingNewReportScreenPointer = IntPtr.Zero;
				_abandonRetryConfirmation = false;
			}

			var transaction = _transaction;
			if (pointer != IntPtr.Zero && transaction != null && pointer == transaction.ScreenPointer
			    && (transaction.State == FlowState.AwaitingIterator || transaction.State == FlowState.AwaitingIteratorStateOne))
			{
				transaction.ScreenPointer = IntPtr.Zero;
				transaction.IteratorPointer = IntPtr.Zero;
				transaction.State = FlowState.Cancelled;
				transaction.Error = "cancelled_by_player";
				_visible = true;
			}
			return true;
		}
		catch (Exception ex)
		{
			SafeLogWarning("ModBugReporting: Close interception failed (" + ex.GetType().Name + "); native close is allowed.");
			return true;
		}
	}

	private static bool IteratorMoveNextPrefix(object __instance, ref bool __result)
	{
		try
		{
			var transaction = _transaction;
			if (transaction == null || transaction.ScreenPointer == IntPtr.Zero
			    || (transaction.State != FlowState.AwaitingIterator && transaction.State != FlowState.AwaitingIteratorStateOne))
				return BlockNativeIterator(ref __result);

			var iteratorPointer = NativePointer(__instance);
			if (iteratorPointer == IntPtr.Zero)
				return FailAndBlock(transaction, null, "native_iterator_identity_unavailable", ref __result);

			var state = (int)_iteratorState.GetValue(__instance);
			var screen = _iteratorOwner.GetValue(__instance);
			if (NativePointer(screen) != transaction.ScreenPointer)
				return FailAndBlock(transaction, null, "native_iterator_owner_mismatch", ref __result);

			if (state == 0 && transaction.State == FlowState.AwaitingIterator && transaction.IteratorPointer == IntPtr.Zero)
			{
				transaction.IteratorPointer = iteratorPointer;
				transaction.State = FlowState.AwaitingIteratorStateOne;
				return true;
			}
			if (iteratorPointer != transaction.IteratorPointer || state != 1
			    || transaction.State != FlowState.AwaitingIteratorStateOne)
			{
				return FailAndBlock(transaction, screen, "native_iterator_identity_or_state_unexpected", ref __result);
			}

			var args = new object[GameSymbols.ModBugReporting.SendReportParameterCount];
			for (var i = 0; i < _iteratorStrings.Length; i++)
				args[i] = _iteratorStrings[i].GetValue(__instance);
			args[5] = _iteratorNativeLog.GetValue(__instance);
			args[6] = _iteratorAttachments.GetValue(__instance);
			args[7] = null;
			args[8] = null;
			transaction.Capture = ModBugReportRedirect.CaptureFromArgs(args, includeScreenshot: false);

			if (!TryCloseNativeForm(screen))
			{
				return FailAndBlock(transaction, null, "native_form_close_failed", ref __result);
			}
			transaction.ScreenPointer = IntPtr.Zero;

			if (transaction.IncludeScreenshot)
			{
				transaction.State = FlowState.CapturingScreenshot;
				_suppressOverlayForCapture = true;
				MonoBehaviourExtensions.StartCoroutine(_host, CaptureScreenshotAndSubmit(transaction));
			}
			else
			{
				BeginPackageAndSubmit(transaction);
			}
			return false;
		}
		catch (Exception ex)
		{
			_suppressOverlayForCapture = false;
			var transaction = _transaction;
			if (transaction != null)
				FailCapture(transaction, null, "native_capture_failed:" + ex.GetType().Name);
			SafeLogError("ModBugReporting: native iterator interception failed (" + ex.GetType().Name + ").");
			return BlockNativeIterator(ref __result);
		}
	}

	private static bool FailAndBlock(Transaction transaction, object screen, string code, ref bool result)
	{
		FailCapture(transaction, screen, code);
		return BlockNativeIterator(ref result);
	}

	private static bool BlockNativeIterator(ref bool result)
	{
		result = false;
		return false;
	}

	private static bool TryCloseNativeForm(object screen)
	{
		if (screen == null)
			return false;
		var pointer = NativePointer(screen);
		if (pointer == IntPtr.Zero)
			return false;
		try
		{
			_authorizedClosePointer = pointer;
			_closeMethod.Invoke(screen, null);
			return true;
		}
		catch (Exception ex)
		{
			SafeLogWarning("ModBugReporting: native form close failed (" + ex.GetType().Name + ").");
			return false;
		}
		finally
		{
			_authorizedClosePointer = IntPtr.Zero;
		}
	}

	private static void FailCapture(Transaction transaction, object screen, string code)
	{
		try
		{
			if (screen != null)
				TryCloseNativeForm(screen);
			transaction.ScreenPointer = IntPtr.Zero;
			transaction.IteratorPointer = IntPtr.Zero;
			transaction.Capture = null;
			transaction.State = FlowState.CaptureFailed;
			transaction.Error = code;
			_visible = true;
			SafeLogError("ModBugReporting: explicit capture stopped before native send (" + code + ").");
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: capture failure handler encountered (" + ex.GetType().Name + ").");
		}
	}

	private static IEnumerator CaptureScreenshotAndSubmit(Transaction transaction)
	{
		yield return new WaitForEndOfFrame();
		if (!ReferenceEquals(_transaction, transaction) || transaction.State != FlowState.CapturingScreenshot)
		{
			_suppressOverlayForCapture = false;
			yield break;
		}

		// The overlay was hidden for this frame; capture at end of frame, then restore it before any further work.
		var captured = TryCaptureScreenshotPng(out var png, out var captureError);
		_suppressOverlayForCapture = false;
		if (!captured)
		{
			SetScreenshotFailed(transaction, captureError);
			yield break;
		}

		try
		{
			transaction.Capture = ModBugReportRedirect.WithScreenshot(transaction.Capture, png);
			BeginPackageAndSubmit(transaction);
		}
		catch (Exception ex)
		{
			SetScreenshotFailed(transaction, "screenshot_attach_failed:" + ex.GetType().Name);
		}
	}

	// ScreenCapture.CaptureScreenshotAsTexture at end of frame, Graphics.Blit downscale on the GPU, one ReadPixels of the
	// small target, and Unity's ImageConversion.EncodeToPNG. Every Unity object is released on the same frame.
	private static bool TryCaptureScreenshotPng(out byte[] png, out string error)
	{
		png = null;
		error = null;
		Texture2D full = null;
		Texture2D scaled = null;
		RenderTexture target = null;
		var previousActive = RenderTexture.active;
		try
		{
			var screenWidth = Screen.width;
			var screenHeight = Screen.height;
			if (screenWidth <= 0 || screenHeight <= 0 || (long)screenWidth * screenHeight > MaxScreenshotSourcePixels)
				throw new InvalidOperationException("screenshot_source_dimensions_exceed_limit");

			var scale = Math.Min(1f, Math.Min((float)MaxScreenshotWidth / screenWidth, (float)MaxScreenshotHeight / screenHeight));
			var width = Math.Max(1, (int)Math.Floor(screenWidth * scale));
			var height = Math.Max(1, (int)Math.Floor(screenHeight * scale));

			full = ScreenCapture.CaptureScreenshotAsTexture();
			if (full == null)
				throw new InvalidOperationException("screenshot_capture_unavailable");

			target = RenderTexture.GetTemporary(width, height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Default);
			if (target == null)
				throw new InvalidOperationException("screenshot_render_target_unavailable");
			Graphics.Blit(full, target);
			RenderTexture.active = target;
			scaled = new Texture2D(width, height, TextureFormat.RGB24, false);
			scaled.ReadPixels(new Rect(0f, 0f, width, height), 0, 0, false);
			scaled.Apply(false);

			var encoded = ImageConversion.EncodeToPNG(scaled);
			if (encoded == null || encoded.Length == 0)
				throw new InvalidOperationException("screenshot_png_encode_failed");
			if (encoded.Length > ModBugReportRedirect.ScreenshotMaxBytes)
				throw new InvalidOperationException("screenshot_png_exceeds_limit");
			png = encoded.ToArray();
			return png != null && png.Length == encoded.Length;
		}
		catch (Exception ex)
		{
			png = null;
			error = ex is InvalidOperationException && ex.Message.StartsWith("screenshot_", StringComparison.Ordinal)
				? ex.Message
				: "screenshot_capture_failed:" + ex.GetType().Name;
			return false;
		}
		finally
		{
			try { RenderTexture.active = previousActive; }
			catch (Exception ex) { SafeLogWarning("ModBugReporting: screenshot render target restore failed (" + ex.GetType().Name + ")."); }
			ReleaseTemporaryRenderTexture(target);
			DestroyTexture(full);
			DestroyTexture(scaled);
		}
	}

	private static void ReleaseTemporaryRenderTexture(RenderTexture texture)
	{
		if (texture == null)
			return;
		try { RenderTexture.ReleaseTemporary(texture); }
		catch (Exception ex) { SafeLogWarning("ModBugReporting: screenshot render target cleanup failed (" + ex.GetType().Name + ")."); }
	}

	private static void DestroyTexture(Texture2D texture)
	{
		if (texture == null)
			return;
		try { UnityObject.Destroy(texture); }
		catch (Exception ex) { SafeLogWarning("ModBugReporting: screenshot texture cleanup failed (" + ex.GetType().Name + ")."); }
	}

	private static void SetScreenshotFailed(Transaction transaction, string error)
	{
		_suppressOverlayForCapture = false;
		transaction.State = FlowState.ScreenshotFailed;
		transaction.Error = error ?? "screenshot_capture_failed";
		_visible = true;
		SafeLogWarning("ModBugReporting: the opted-in screenshot could not be attached (" + transaction.Error + ").");
	}

	private static void BeginPackageAndSubmit(Transaction transaction)
	{
		transaction.State = FlowState.PackagingAndSubmitting;
		transaction.Error = null;
		try
		{
			var endpoint = _cfg?.ModBugReportingEndpoint ?? "";
			transaction.Task = ModBugReportRedirect.PackageAndSubmitAsync(transaction.Capture, endpoint, transaction.ReportId);
		}
		catch (Exception ex)
		{
			transaction.Task = null;
			transaction.State = FlowState.Unconfirmed;
			transaction.Error = "submission_start_failed:" + ex.GetType().Name;
		}
	}

	private static void Pump()
	{
		try
		{
			var transaction = _transaction;
			if (transaction == null || transaction.Task == null || !transaction.Task.IsCompleted)
				return;

			transaction.Outcome = transaction.Task.GetAwaiter().GetResult();
			if (transaction.Outcome != null && transaction.Outcome.Acknowledged)
			{
				transaction.State = FlowState.Acknowledged;
				transaction.Error = null;
				SafeLogInfo("ModBugReporting: report relay acknowledgement verified (reportId=" + transaction.ReportId + ").");
			}
			else
			{
				transaction.State = FlowState.Unconfirmed;
				transaction.Error = transaction.Outcome?.Error ?? "relay_unconfirmed";
				SafeLogWarning("ModBugReporting: report was not acknowledged (reportId=" + transaction.ReportId + ", result=" + transaction.Error + ").");
			}
		}
		catch (Exception ex)
		{
			var transaction = _transaction;
			if (transaction != null)
			{
				transaction.State = FlowState.Unconfirmed;
				transaction.Error = "submission_result_failed:" + ex.GetType().Name;
			}
			SafeLogWarning("ModBugReporting: report result could not be read (" + ex.GetType().Name + ").");
		}
		finally
		{
			var completedTransaction = _transaction;
			if (completedTransaction != null)
			{
				completedTransaction.Task = null;
				completedTransaction.Capture = null;
				_visible = true;
			}
		}
	}

	private static void BeginRetry(Transaction transaction)
	{
		var endpoint = _cfg?.ModBugReportingEndpoint ?? "";
		if (transaction.Outcome?.BundlePath == null || !ModBugReportTransport.IsEndpoint(endpoint))
			return;
		transaction.State = FlowState.PackagingAndSubmitting;
		transaction.Error = null;
		try
		{
			transaction.Task = ModBugReportRedirect.RetryAndSubmitAsync(endpoint, transaction.ReportId);
		}
		catch (Exception ex)
		{
			transaction.Task = null;
			transaction.State = FlowState.Unconfirmed;
			transaction.Error = "retry_start_failed:" + ex.GetType().Name;
		}
	}

	private static bool IsTerminal(FlowState state)
	{
		return state == FlowState.Acknowledged || state == FlowState.Unconfirmed
		       || state == FlowState.ScreenshotFailed || state == FlowState.CaptureFailed
		       || state == FlowState.Cancelled || state == FlowState.StartFailed;
	}

	private static void SafeLogInfo(string message)
	{
		try { _log?.LogInfo(message); }
		catch { }
	}

	private static void SafeLogWarning(string message)
	{
		try { _log?.LogWarning(message); }
		catch { }
	}

	private static void SafeLogError(string message)
	{
		try { _log?.LogError(message); }
		catch { }
	}

	private static void ClearConsent()
	{
		_consentScreen = null;
		_consentScreenPointer = IntPtr.Zero;
		_consentChecked = false;
		_includeScreenshotChecked = false;
		if (_transaction == null)
			_visible = false;
	}

	private static IntPtr NativePointer(object value)
	{
		return value is Il2CppObjectBase native && native.Pointer != IntPtr.Zero ? native.Pointer : IntPtr.Zero;
	}

	private static void DrawWindow(int id)
	{
		var transaction = _transaction;
		if (_consentScreenPointer != IntPtr.Zero)
			DrawConsentContents();
		else if (_abandonRetryConfirmation && transaction != null && transaction.State == FlowState.Unconfirmed)
			DrawAbandonRetryConfirmation(transaction);
		else if (transaction != null)
			DrawTransactionContents(transaction);
	}

	private static void DrawAbandonRetryConfirmation(Transaction transaction)
	{
		var hasBundle = transaction.Outcome?.BundlePath != null;
		var confirmationText = hasBundle
			? "Discard this unsent report? It won't be offered again, now or after a restart. The saved copy on your PC is not deleted right away; it is cleaned up after 30 days."
			: "This report has no saved copy to send again. Discarding just closes this message; nothing is sent or deleted.";
		GUILayout.Label(confirmationText, WrappedLabel());
		VerticalGap(10f);
		var previousEnabled = GUI.enabled;
		GUILayout.BeginHorizontal();
		try
		{
			var pendingScreenIsCurrent = _pendingNewReportScreen != null
			                             && NativePointer(_pendingNewReportScreen) == _pendingNewReportScreenPointer;
			GUI.enabled = previousEnabled && pendingScreenIsCurrent;
			if (GUILayout.Button("Discard and start new", GUILayout.Height(30f)))
				AbandonRetryAndOpenNewConsent(transaction);
			GUI.enabled = previousEnabled;
			if (GUILayout.Button("Discard", GUILayout.Height(30f)))
				AbandonRetry(transaction);
			if (GUILayout.Button("Keep it", GUILayout.Height(30f)))
				_abandonRetryConfirmation = false;
		}
		finally
		{
			GUI.enabled = previousEnabled;
			GUILayout.EndHorizontal();
		}
	}

	private static void AbandonRetryAndOpenNewConsent(Transaction transaction)
	{
		if (!ReferenceEquals(_transaction, transaction) || transaction.State != FlowState.Unconfirmed)
			return;
		var screen = _pendingNewReportScreen;
		var screenPointer = _pendingNewReportScreenPointer;
		if (screen == null || screenPointer == IntPtr.Zero || NativePointer(screen) != screenPointer)
		{
			_pendingNewReportScreen = null;
			_pendingNewReportScreenPointer = IntPtr.Zero;
			_abandonRetryConfirmation = false;
			_visible = true;
			return;
		}

		RecordAbandoned(transaction);
		_transaction = null;
		_pendingNewReportScreen = null;
		_pendingNewReportScreenPointer = IntPtr.Zero;
		_abandonRetryConfirmation = false;
		_consentScreen = screen;
		_consentScreenPointer = screenPointer;
		_consentChecked = false;
		_includeScreenshotChecked = false;
		_consentScroll = Vector2.zero;
		_visible = true;
	}

	private static void AbandonRetry(Transaction transaction)
	{
		if (!ReferenceEquals(_transaction, transaction) || transaction.State != FlowState.Unconfirmed)
			return;
		RecordAbandoned(transaction);
		_transaction = null;
		_abandonRetryConfirmation = false;
		_visible = _consentScreenPointer != IntPtr.Zero;
	}

	private static void RecordAbandoned(Transaction transaction)
	{
		if (transaction.Outcome?.BundlePath == null)
			return;
		try
		{
			if (!ModBugReportRedirect.MarkAbandoned(transaction.ReportId))
				SafeLogWarning("ModBugReporting: abandoned state was not recorded (reportId=" + transaction.ReportId + ").");
		}
		catch (Exception ex)
		{
			SafeLogWarning("ModBugReporting: abandoned state could not be recorded (" + ex.GetType().Name + ").");
		}
	}

	private static void DrawConsentContents()
	{
		_consentScroll = GUILayout.BeginScrollView(_consentScroll, GUILayout.ExpandHeight(true));
		try
		{
			GUILayout.Label(
				"Your report goes to the Golden Era mod team's private Google Drive. It does not go to the game's developer, "
				+ "and you don't need a Google account.",
				WrappedLabel());
			VerticalGap(8f);
			GUILayout.Label(
				"What's sent: your title, description and category, the game and mod logs, your Windows version, "
				+ "the mod version, and basic details about the game and mod files.", WrappedLabel());
			VerticalGap(8f);
			GUILayout.Label(
				"What's not sent: files you attached (only their names and sizes may be listed) and the contact details you typed.",
				WrappedLabel());
			VerticalGap(8f);
			GUILayout.Label(
				"Personal details such as your Windows user name, Steam name or ID, and email or IP addresses are removed "
				+ "from the text and logs automatically, but this may miss something, so please don't type anything private. "
				+ "Like any website, Google can see your IP address when the report is sent; it is not saved with the report.",
				WrappedLabel());
			VerticalGap(8f);
			GUILayout.Label("Reports are kept for up to 90 days. A copy stays on your PC for up to 30 days.", WrappedLabel());
			if (_cfg?.ModBugReportingIncludeScreenshot == true)
			{
				VerticalGap(8f);
				_includeScreenshotChecked = GUILayout.Toggle(
					_includeScreenshotChecked,
					"Also send a screenshot (optional). It shows whatever is on your screen and personal details are not removed from it.",
					WrappedLabel());
			}
		}
		finally
		{
			GUILayout.EndScrollView();
		}

		_consentChecked = GUILayout.Toggle(
			_consentChecked,
			"I agree to send this report to the Golden Era mod team.",
			WrappedLabel());
		VerticalGap(6f);
		var previousEnabled = GUI.enabled;
		GUILayout.BeginHorizontal();
		try
		{
			GUI.enabled = previousEnabled && _consentChecked && NativePointer(_consentScreen) == _consentScreenPointer;
			if (GUILayout.Button("Send report", GUILayout.Height(30f)))
				ConfirmConsent();
			GUI.enabled = previousEnabled;
			if (GUILayout.Button("Cancel", GUILayout.Height(30f)))
				ClearConsent();
		}
		finally
		{
			GUI.enabled = previousEnabled;
			GUILayout.EndHorizontal();
		}
	}

	// GUILayout.Space is stripped from the game's IMGUI module ("Method unstripping failed" every frame,
	// which aborted the consent window after its first label); a fixed-height empty label spaces the same.
	private static void VerticalGap(float pixels)
	{
		GUILayout.Label(string.Empty, GUILayout.Height(pixels));
	}

	private static GUIStyle WrappedLabel()
	{
		if (_wrappedLabel == null)
			_wrappedLabel = new GUIStyle(GUI.skin.label) { wordWrap = true };
		return _wrappedLabel;
	}

	private static void DrawTransactionContents(Transaction transaction)
	{
		if (transaction.Minimized)
		{
			GUILayout.Label(CompactStatusText(transaction));
			var previous = GUI.enabled;
			GUILayout.BeginHorizontal();
			try
			{
				if (GUILayout.Button("Open", GUILayout.Height(26f)))
					transaction.Minimized = false;
				if (IsTerminal(transaction.State) && GUILayout.Button(transaction.State == FlowState.Unconfirmed ? "Hide" : "Dismiss", GUILayout.Height(26f)))
					DismissTransaction(transaction);
			}
			finally
			{
				GUI.enabled = previous;
				GUILayout.EndHorizontal();
			}
			return;
		}

		GUILayout.Label(StatusText(transaction), WrappedLabel());
		if (transaction.State == FlowState.Unconfirmed && transaction.Outcome?.BundlePath != null)
		{
			VerticalGap(6f);
			GUILayout.Label(transaction.RestoredAfterRestart
				? "It is saved on your PC. Nothing is sent unless you press Try again."
				: "It is saved on your PC. Press Try again to send it now, or later: it will be offered again the next time you start the game.",
				WrappedLabel());
		}
		else if (transaction.State == FlowState.Unconfirmed)
		{
			VerticalGap(6f);
			GUILayout.Label("It could not be saved for another try. You can send a new report from the game's menu.", WrappedLabel());
		}
		VerticalGap(10f);
		var previousEnabled = GUI.enabled;
		GUILayout.BeginHorizontal();
		try
		{
			if (transaction.State == FlowState.ScreenshotFailed)
			{
				if (GUILayout.Button("Send without screenshot", GUILayout.Height(30f)))
					BeginPackageAndSubmit(transaction);
				if (GUILayout.Button("Cancel report", GUILayout.Height(30f)))
					DismissTransaction(transaction);
			}
			else if (transaction.State == FlowState.Unconfirmed)
			{
				var canRetry = transaction.Outcome?.BundlePath != null && ModBugReportTransport.IsEndpoint(_cfg?.ModBugReportingEndpoint);
				GUI.enabled = previousEnabled && canRetry;
				if (GUILayout.Button("Try again", GUILayout.Height(30f)))
					BeginRetry(transaction);
				GUI.enabled = previousEnabled;
				if (GUILayout.Button(_pendingNewReportScreenPointer != IntPtr.Zero ? "New report..." : "Discard...", GUILayout.Height(30f)))
					_abandonRetryConfirmation = true;
				if (GUILayout.Button("Hide", GUILayout.Height(30f)))
					DismissTransaction(transaction);
			}
			else if (transaction.State == FlowState.Acknowledged || transaction.State == FlowState.CaptureFailed
			         || transaction.State == FlowState.Cancelled || transaction.State == FlowState.StartFailed)
			{
				if (GUILayout.Button("Close", GUILayout.Height(30f)))
					DismissTransaction(transaction);
			}
			else if (GUILayout.Button("Minimize", GUILayout.Height(30f)))
			{
				transaction.Minimized = true;
			}
			GUILayout.EndHorizontal();
		}
		finally
		{
			GUI.enabled = previousEnabled;
		}
	}

	private static void DismissTransaction(Transaction transaction)
	{
		if (!ReferenceEquals(_transaction, transaction))
			return;
		if (transaction.State == FlowState.Unconfirmed)
		{
			_abandonRetryConfirmation = false;
			_visible = false;
			return;
		}
		_transaction = null;
		_visible = _consentScreenPointer != IntPtr.Zero;
	}

	private static string StatusText(Transaction transaction)
	{
		switch (transaction.State)
		{
			case FlowState.AwaitingIterator:
			case FlowState.AwaitingIteratorStateOne:
				return "Preparing your report... You can keep playing.";
			case FlowState.CapturingScreenshot:
				return "Taking the screenshot...";
			case FlowState.PackagingAndSubmitting:
				return "Sending your report... You can keep playing.";
			case FlowState.Acknowledged:
				return "Thanks! Your report was sent.\nReference: " + ShortReference(transaction.ReportId);
			case FlowState.Unconfirmed:
				return transaction.RestoredAfterRestart
					? "A bug report from your last session was not sent."
					: "Your report could not be sent.";
			case FlowState.ScreenshotFailed:
				return "The screenshot could not be taken. Send the report without it?";
			case FlowState.CaptureFailed:
				return "Something went wrong while preparing your report. Nothing was sent.";
			case FlowState.Cancelled:
				return "Report cancelled. Nothing was sent.";
			case FlowState.StartFailed:
				return "The report could not be started. Nothing was sent.";
			default:
				return "Bug report status unavailable.";
		}
	}

	private static string CompactStatusText(Transaction transaction)
	{
		switch (transaction.State)
		{
			case FlowState.AwaitingIterator:
			case FlowState.AwaitingIteratorStateOne:
				return "Preparing bug report...";
			case FlowState.CapturingScreenshot:
				return "Taking screenshot...";
			case FlowState.PackagingAndSubmitting:
				return "Sending bug report...";
			case FlowState.Acknowledged:
				return "Bug report sent";
			case FlowState.Unconfirmed:
				return "Bug report not sent";
			case FlowState.ScreenshotFailed:
				return "Screenshot failed";
			case FlowState.Cancelled:
				return "Bug report cancelled";
			default:
				return "Bug report stopped";
		}
	}

	// First block of the report GUID: enough for a player to quote, and it matches the Drive file name prefix.
	private static string ShortReference(string reportId)
	{
		if (string.IsNullOrEmpty(reportId))
			return "-";
		var dash = reportId.IndexOf('-');
		return dash > 0 ? reportId.Substring(0, dash) : reportId;
	}

	private static void ConfirmConsent()
	{
		if (!_consentChecked || _consentScreen == null || NativePointer(_consentScreen) != _consentScreenPointer)
			return;
		var screen = _consentScreen;
		var screenPointer = _consentScreenPointer;
		var includeScreenshot = _cfg?.ModBugReportingIncludeScreenshot == true && _includeScreenshotChecked;
		var transaction = new Transaction(Guid.NewGuid().ToString("D").ToLowerInvariant(), includeScreenshot, screenPointer);
		_transaction = transaction;
		_visible = true;
		ClearConsent();
		_authorizedSubmitPointer = screenPointer;
		try
		{
			_submitMethod.Invoke(screen, null);
			if (_authorizedSubmitPointer != IntPtr.Zero)
			{
				_authorizedSubmitPointer = IntPtr.Zero;
				transaction.State = FlowState.StartFailed;
				transaction.ScreenPointer = IntPtr.Zero;
				transaction.Error = "submit_callback_not_entered";
			}
		}
		catch (Exception ex)
		{
			_authorizedSubmitPointer = IntPtr.Zero;
			transaction.State = FlowState.StartFailed;
			transaction.ScreenPointer = IntPtr.Zero;
			transaction.Error = "submit_callback_failed:" + ex.GetType().Name;
			SafeLogError("ModBugReporting: explicit Submit callback failed (" + ex.GetType().Name + ").");
		}
		finally
		{
			_authorizedSubmitPointer = IntPtr.Zero;
		}
	}

	internal static void OnHostUpdate()
	{
		try
		{
			var transaction = _transaction;
			if (_suppressOverlayForCapture && (transaction == null || transaction.State != FlowState.CapturingScreenshot))
				_suppressOverlayForCapture = false;
			if (transaction != null
			    && (transaction.State == FlowState.AwaitingIterator || transaction.State == FlowState.AwaitingIteratorStateOne)
			    && Time.realtimeSinceStartup - transaction.StartedAtRealtime >= IteratorWatchdogSeconds)
				FailCapture(transaction, null, "native_submit_iterator_timeout");
				UpdatePointerShield();
			Pump();
		}
		catch (Exception ex)
		{
			HidePointerShield();
			SafeLogError("ModBugReporting: status update failed (" + ex.GetType().Name + ").");
		}
	}

	internal static void OnHostGui()
	{
		if (!_visible || _suppressOverlayForCapture || Event.current == null)
		{
			HidePointerShield();
			return;
		}
		var previousDepth = GUI.depth;
		var previousEnabled = GUI.enabled;
		var previousMatrix = GUI.matrix;
		try
		{
			GUI.depth = -2500;
			var consent = _consentScreenPointer != IntPtr.Zero;
			var title = _abandonRetryConfirmation ? "Unsent bug report" : consent ? "Send a bug report" : "Bug report";
			var scale = UiScale();
			var windowRect = GetWindowRect(scale);
			var rect = new Rect(windowRect.x * scale, windowRect.y * scale, windowRect.width * scale, windowRect.height * scale);
			UpdatePointerShield(rect);
			GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));
			GUI.Window(WindowId, windowRect, WindowCallback, title);
		}
		catch (Exception ex)
		{
			HidePointerShield();
			SafeLogError("ModBugReporting: status UI failed (" + ex.GetType().Name + ").");
		}
		finally
		{
			GUI.matrix = previousMatrix;
			GUI.enabled = previousEnabled;
			GUI.depth = previousDepth;
		}
	}

	// The window is laid out in a 720-line virtual screen and scaled up, so it keeps the same share of the
	// screen at 1080p, 1440p and 4K instead of shrinking to a corner (never scaled below 1:1).
	private static float UiScale()
	{
		return Mathf.Max(1f, Screen.height / ReferenceScreenHeight);
	}

	// Returns the window in virtual (unscaled) GUI units for the given scale.
	private static Rect GetWindowRect(float scale)
	{
		var consent = _consentScreenPointer != IntPtr.Zero;
		var confirmingAbandon = _abandonRetryConfirmation && _transaction?.State == FlowState.Unconfirmed;
		var screenWidth = Mathf.Max(1f, Screen.width / scale);
		var screenHeight = Mathf.Max(1f, Screen.height / scale);
		var minimized = _transaction?.Minimized == true;
		var width = Mathf.Min(consent ? ConsentWindowWidth : confirmingAbandon ? 440f : minimized ? 260f : StatusWindowWidth, Mathf.Max(1f, screenWidth - 16f));
		var height = Mathf.Min(consent ? ConsentWindowHeight : confirmingAbandon ? 220f : minimized ? 72f : 230f, Mathf.Max(1f, screenHeight - 16f));
		var x = consent ? (screenWidth - width) * 0.5f : screenWidth - width - 8f;
		var y = consent ? (screenHeight - height) * 0.5f : screenHeight - height - 8f;
		return new Rect(
			Mathf.Clamp(x, 8f, Mathf.Max(8f, screenWidth - width - 8f)),
			Mathf.Clamp(y, 8f, Mathf.Max(8f, screenHeight - height - 8f)),
			width,
			height);
	}

	private static void UpdatePointerShield()
	{
		if (!_visible || _suppressOverlayForCapture)
		{
			HidePointerShield();
			return;
		}
		var scale = UiScale();
		var windowRect = GetWindowRect(scale);
		UpdatePointerShield(new Rect(windowRect.x * scale, windowRect.y * scale, windowRect.width * scale, windowRect.height * scale));
	}

	private static void UpdatePointerShield(Rect guiRect)
	{
		if (_pointerShieldImage == null || _pointerShieldCanvas == null || _pointerShieldRaycaster == null)
			return;
		_pointerShieldRaycaster.enabled = true;
		var rect = _pointerShieldImage.rectTransform;
		rect.anchorMin = new Vector2(0f, 1f);
		rect.anchorMax = new Vector2(0f, 1f);
		rect.pivot = new Vector2(0f, 1f);
		rect.anchoredPosition = new Vector2(guiRect.x, -guiRect.y);
		rect.sizeDelta = new Vector2(guiRect.width, guiRect.height);
		_pointerShieldImage.enabled = true;
	}

	private static void HidePointerShield()
	{
		try
		{
			if (_pointerShieldImage != null)
				_pointerShieldImage.enabled = false;
		}
		catch (Exception ex)
		{
			SafeLogWarning("ModBugReporting: pointer shield could not be hidden (" + ex.GetType().Name + ").");
		}
	}
}

public sealed class ModBugReportSubmissionHost : MonoBehaviour
{
	public ModBugReportSubmissionHost(IntPtr ptr) : base(ptr) { }

	private void Update() => ModBugReportSubmission.OnHostUpdate();
	private void OnGUI() => ModBugReportSubmission.OnHostGui();
}
