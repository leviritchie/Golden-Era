using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace OfflineUnlockMod;

/// <summary>
/// Owns the native SendReport fail-closed sink and the managed report capture/package boundary.
///
/// The sink always suppresses native uploads, including automatic desync reports. Only the explicit mod-owned
/// submission flow may call CaptureFromArgs; that method copies capped data on the Unity thread, then the worker
/// scrubs it, writes a durable ZIP, and submits it to the configured relay. A finalized ZIP is retained on every
/// transport refusal, timeout, cancellation, or acknowledgement mismatch. Explicit retry verifies and reuses the
/// same ZIP bytes and report ID. Screenshots require both the player's choice and configuration permission.
/// Each finalized ZIP gets a small <c>.state</c> sidecar (acknowledged / unconfirmed / failed / abandoned) so
/// admission limits ignore failed or abandoned attempts and a not-yet-acknowledged report can be offered for
/// explicit retry after a restart. Local bundles are pruned by age and count.
///
/// Fail closed: if the sink cannot be patched, the native report opener and desync auto-send launchers are blocked.
/// Source/fixture, test-build, installed-payload and synthetic player-receiver proof are recorded in
/// docs/mod_bug_reporting.md. Native UI and gameplay behavior still require separate runtime verification.
/// </summary>
internal static class ModBugReportRedirect
{
	internal enum GuardState
	{
		Off,
		Redirecting,
		EntryPointsBlocked,
		SubmissionUnavailable,
		Unprotected,
	}

	private const string BundleFolderName = "mod_bug_reports";
	private const string BundleSchema = "oe_mod_bug_report.v3";

	// Abuse limits (docs/mod_bug_reporting.md, "Abuse limits"). Pinned by tools/validate_mod_bug_reporting_contract.py.
	internal const int ReportCooldownSeconds = 120;
	internal const int DailyBundleCap = 10;
	internal const int MaxBundleBytes = 8 * 1024 * 1024;
	internal const int BepInExLogTailBytes = 2 * 1024 * 1024;
	internal const int NativeLogTailBytes = 256 * 1024;
	internal const int ScreenshotMaxBytes = 4 * 1024 * 1024;
	private const int NativeLogInputMaxBytes = 4 * 1024 * 1024;
	private const int NativeLogInflatedMaxBytes = 16 * 1024 * 1024;
	private const int MaxAttachmentEntries = 64;
	private const int MaxAttachmentNameChars = 256;
	private const int MaxManifestFiles = 256;
	private const int MaxManifestFileBytes = 1024 * 1024;
	private const int MaxPluginAssemblyBytes = 32 * 1024 * 1024;
	private const int MaxTitleChars = 512;
	private const int MaxDescriptionChars = 16384;
	private const int MaxContactChars = 512;
	private const int MaxCategoryChars = 256;
	private const int MaxTagChars = 256;
	private const int MaxGameIdChars = 256;
	private const int ReportHashChars = 16;
	// Local retention and admission windows (docs/mod_bug_reporting.md, "Bundle And Limits").
	internal const int LocalBundleRetentionDays = 30;
	internal const int LocalBundleMaxCount = 50;
	internal const int DuplicateWindowHours = 24;
	internal const int RestoreUnsentMaxAgeDays = 7;
	private const int MaxStateFileBytes = 256;
	private const string StateAcknowledged = "acknowledged";
	private const string StateAbandoned = "abandoned";
	private const string StateUnconfirmedPrefix = "unconfirmed:";
	private const string StateFailedPrefix = "failed:";
	private static readonly Regex BundleNamePattern = new(
		@"^oe-mod-report-(\d{8}-\d{6})(?:-([0-9a-f]{16}))?(?:-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))?\.zip$",
		RegexOptions.IgnoreCase);

	private static ManualLogSource _log;
	private static LauncherConfig _cfg;
	private static int _mainThreadId;
	private static int _sinkBlockWarningWritten;
	private static readonly object BundleGate = new();
	private static readonly object ActiveReportsGate = new();
	private static readonly HashSet<string> ActiveReports = new(StringComparer.Ordinal);

	internal static GuardState State { get; private set; } = GuardState.Off;

	internal static void TryRegister(Harmony harmony, ManualLogSource log, LauncherConfig cfg)
	{
		_log = log;
		_cfg = cfg;
		_mainThreadId = Thread.CurrentThread.ManagedThreadId;
		if (cfg == null || !cfg.ModBugReporting)
		{
			State = GuardState.Off;
			log?.LogWarning(
				"ModBugReporting: off (modBugReporting=false). The native bug report sink is not blocked here; it reaches "
				+ "the game developer's analytics service unless blockNativeTelemetry blocks it.");
			return;
		}

		if (TryPatchSink(harmony, out var sinkError))
		{
			State = GuardState.Redirecting;
			TryCleanupLocalBundles();
			if (ModBugReportSubmission.TryRegister(harmony, log, cfg, out var submissionError))
			{
				log?.LogInfo(
					"ModBugReporting: native SendReport sink is blocked; explicit Submit uses the configured anonymous Google endpoint. "
					+ "A matching receiver acknowledgement is required for success. Local bundles are retained under "
					+ Scrubber.Scrub(BundleDirectory()) + " (limits: cooldown " + ReportCooldownSeconds + " s, "
					+ DailyBundleCap + " per UTC day, identical reports deduplicated, bundle cap "
					+ (MaxBundleBytes / (1024 * 1024)) + " MiB). Unowned native reports are discarded.");
				return;
			}

			log?.LogError("ModBugReporting: native sink is protected, but explicit Submit integration failed ("
				+ Scrubber.Scrub(submissionError ?? "unknown") + "). Blocking native report entry points; no report upload is available.");
			if (TryBlockEntryPoints(harmony, out var entryError))
			{
				State = GuardState.EntryPointsBlocked;
				return;
			}
			// The sink still prevents native delivery; never label this branch unprotected or connected.
			State = GuardState.SubmissionUnavailable;
			log?.LogError("ModBugReporting: report entry-point blocking also failed ("
				+ Scrubber.Scrub(entryError ?? "unknown") + "); the native sink remains blocked, but the form may still open.");
			return;
		}

		log?.LogError("ModBugReporting: report sink hook failed (" + sinkError + "). Failing closed: blocking native report entry points.");
		if (TryBlockEntryPoints(harmony, out var blockError))
		{
			State = GuardState.EntryPointsBlocked;
			log?.LogWarning("ModBugReporting: native bug report entry points blocked; the report buttons do nothing.");
			return;
		}

		State = GuardState.Unprotected;
		log?.LogError(
			"ModBugReporting: UNPROTECTED. Neither the report sink nor the report entry points could be patched ("
			+ blockError + "). Native bug reports may still reach the game developer.");
	}

	private static bool TryPatchSink(Harmony harmony, out string error)
	{
		error = null;
		try
		{
			var owner = GameMember.FindTypeFromHints(
				"bugReport.analytics.owner",
				GameSymbols.ModBugReporting.SendReportOwnerTypeHints);
			if (owner == null)
			{
				error = "sink owner type not found";
				return false;
			}

			var candidates = AccessTools.GetDeclaredMethods(owner)
				.Where(m => m.IsStatic
				            && m.Name == GameSymbols.ModBugReporting.SendReportMethodName
				            && m.GetParameters().Length == GameSymbols.ModBugReporting.SendReportParameterCount)
				.ToArray();
			if (candidates.Length != 1)
			{
				error = "expected exactly one static " + GameSymbols.ModBugReporting.SendReportMethodName + " with "
				        + GameSymbols.ModBugReporting.SendReportParameterCount + " parameters on " + owner.FullName
				        + ", found " + candidates.Length;
				return false;
			}

			harmony.Patch(
				candidates[0],
				prefix: new HarmonyMethod(typeof(ModBugReportRedirect), nameof(SendReportPrefix)) { priority = Priority.First });
			return true;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryBlockEntryPoints(Harmony harmony, out string error)
	{
		error = null;
		try
		{
			var show = FindScreenShow(out error);
			if (show == null)
				return false;
			var screen = show.DeclaringType;
			var launchers = FindAutoSendLaunchers(screen, GameSymbols.ModBugReporting.ScreenStaticAutoSend, out var launcherError);
			if (launchers == null)
			{
				error = "desync auto-send launcher not found on " + screen.FullName + " (" + launcherError + ")";
				return false;
			}

			var block = new HarmonyMethod(typeof(ModBugReportRedirect), nameof(BlockPrefix)) { priority = Priority.First };
			harmony.Patch(show, prefix: block);
			foreach (var launcher in launchers)
				harmony.Patch(launcher, prefix: block);
			return true;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	/// <summary>
	/// The desync auto-send launchers (static, void, no form): one <c>void(bool)</c> on Golden Era, two parameterless
	/// ones on build 25061458 (the generated scope splits the symbol; docs/mod_bug_reporting.md). Each hint of the
	/// symbol is a required launcher, not an alias, so every one must bind or the result is null with the reason.
	/// </summary>
	internal static MethodInfo[] FindAutoSendLaunchers(Type screen, GameSymbols.MethodSymbol launcherSymbol, out string error)
	{
		return GameMember.FindEveryMethodByNames(screen, launcherSymbol, IsAutoSendLauncherShape, out error);
	}

	private static bool IsAutoSendLauncherShape(MethodInfo m)
	{
		if (m == null || !m.IsStatic || m.ReturnType != typeof(void))
			return false;
		var ps = m.GetParameters();
		return ps.Length == 0 || (ps.Length == 1 && ps[0].ParameterType == typeof(bool));
	}

	private static MethodInfo FindScreenShow(out string error)
	{
		error = null;
		var screen = GameMember.FindTypeFromHints("bugReport.screen", GameSymbols.ModBugReporting.ScreenTypeHints);
		if (screen == null)
		{
			error = "bug report screen type not found";
			return null;
		}

		var show = AccessTools.GetDeclaredMethods(screen)
			.FirstOrDefault(m => m.IsStatic
			                     && m.Name == GameSymbols.ModBugReporting.ScreenShowMethodName
			                     && m.GetParameters().Length == GameSymbols.ModBugReporting.ScreenShowParameterCount);
		if (show == null)
			error = "static " + GameSymbols.ModBugReporting.ScreenShowMethodName + " not found on " + screen.FullName;
		return show;
	}

	/// <summary>Blocks every native send; only the mod-owned submit flow may capture and upload a report.</summary>
	private static bool SendReportPrefix()
	{
		try
		{
			if (Interlocked.Exchange(ref _sinkBlockWarningWritten, 1) == 0)
				_log?.LogWarning("ModBugReporting: unowned native SendReport call blocked; no report was captured or uploaded.");
		}
		catch
		{
			// The Harmony prefix must remain fail-closed even if logging fails.
		}
		return false;
	}

	private static bool BlockPrefix()
	{
		try
		{
			_log?.LogWarning("ModBugReporting: native bug report entry point blocked (fail-closed mode).");
		}
		catch
		{
			// A logging failure must not allow the native form or auto-send launcher to run.
		}
		return false;
	}

	internal static string BundleDirectory() => Path.Combine(Paths.BepInExRootPath, BundleFolderName);

	private static void SafeLogError(string message)
	{
		try { _log?.LogError(message); }
		catch { }
	}

	internal sealed class CaptureData
	{
		internal readonly string _title;
		internal readonly string _description;
		internal readonly string _contact;
		internal readonly string _category;
		internal readonly string _tag;
		internal readonly byte[] _nativeLog;
		internal readonly string _attachments;
		internal readonly byte[] _screenshot;
		internal readonly string _gameId;
		internal readonly bool _includeScreenshot;
		internal readonly string _screenshotOmissionReason;

		internal CaptureData(
			string title,
			string description,
			string contact,
			string category,
			string tag,
			byte[] nativeLog,
			string attachments,
			byte[] screenshot,
			string gameId,
			bool includeScreenshot,
			string screenshotOmissionReason)
		{
			_title = title;
			_description = description;
			_contact = contact;
			_category = category;
			_tag = tag;
			_nativeLog = nativeLog;
			_attachments = attachments;
			_screenshot = screenshot;
			_gameId = gameId;
			_includeScreenshot = includeScreenshot;
			_screenshotOmissionReason = screenshotOmissionReason;
		}
	}

	internal sealed class ReportOutcome
	{
		internal bool Acknowledged { get; }
		internal string ReportId { get; }
		internal string Error { get; }
		internal string BundlePath { get; }
		internal bool Duplicate { get; }

		internal ReportOutcome(bool acknowledged, string reportId, string error, string bundlePath, bool duplicate)
		{
			Acknowledged = acknowledged;
			ReportId = reportId;
			Error = error;
			BundlePath = bundlePath;
			Duplicate = duplicate;
		}
	}

	private sealed class BundleBuildResult
	{
		internal string BundlePath { get; }
		internal byte[] ZipBytes { get; }
		internal string Error { get; }
		internal bool Success => BundlePath != null && ZipBytes != null && Error == null;

		internal BundleBuildResult(string bundlePath, byte[] zipBytes, string error)
		{
			BundlePath = bundlePath;
			ZipBytes = zipBytes;
			Error = error;
		}
	}

	private sealed class RetryMetadata
	{
		internal string ReportId { get; }
		internal string BundleSha256 { get; }

		internal RetryMetadata(string reportId, string bundleSha256)
		{
			ReportId = reportId;
			BundleSha256 = bundleSha256;
		}
	}

	/// <summary>Copies only bounded managed values; callers must invoke this from the native UI thread.</summary>
	internal static CaptureData CaptureFromArgs(object[] args, bool includeScreenshot)
	{
		if (_mainThreadId == 0 || Thread.CurrentThread.ManagedThreadId != _mainThreadId)
			throw new InvalidOperationException("Bug report capture must copy IL2CPP values on the Unity main thread.");
		if (State != GuardState.Redirecting)
			throw new InvalidOperationException("Bug report capture is unavailable because the native send sink is not protected.");
		if (args == null || args.Length != GameSymbols.ModBugReporting.SendReportParameterCount)
			throw new InvalidOperationException("Bug report capture expected exactly " + GameSymbols.ModBugReporting.SendReportParameterCount + " native arguments.");

		var title = CaptureText(args[0], "title", MaxTitleChars);
		var description = CaptureText(args[1], "description", MaxDescriptionChars);
		var contact = CaptureText(args[2], "contact", MaxContactChars);
		var category = CaptureText(args[3], "category", MaxCategoryChars);
		var tag = CaptureText(args[4], "tag", MaxTagChars);
		var nativeLog = CaptureBytes(args[5], "native log", NativeLogInputMaxBytes);
		var attachments = CaptureAttachmentSummary(args[6]);
		var screenshotAllowed = _cfg?.ModBugReportingIncludeScreenshot == true;
		var captureScreenshot = includeScreenshot && screenshotAllowed;
		var screenshot = captureScreenshot ? CaptureBytes(args[7], "screenshot", ScreenshotMaxBytes) : Array.Empty<byte>();
		var gameId = CaptureText(args[8], "game id", MaxGameIdChars);
		var omissionReason = !includeScreenshot
			? "omitted (player declined)"
			: !screenshotAllowed ? "omitted (disabled by configuration)" : null;
		return new CaptureData(title, description, contact, category, tag, nativeLog, attachments, screenshot, gameId, captureScreenshot, omissionReason);
	}

	/// <summary>Returns a new snapshot containing a consented, validated managed PNG without retaining native objects.</summary>
	internal static CaptureData WithScreenshot(CaptureData capture, byte[] png)
	{
		if (capture == null)
			throw new ArgumentNullException(nameof(capture));
		if (_mainThreadId == 0 || Thread.CurrentThread.ManagedThreadId != _mainThreadId)
			throw new InvalidOperationException("Screenshot attachment must be finalized on the Unity main thread.");
		if (State != GuardState.Redirecting)
			throw new InvalidOperationException("Screenshot attachment is unavailable because the native send sink is not protected.");
		if (_cfg?.ModBugReportingIncludeScreenshot != true)
			throw new InvalidOperationException("Screenshot attachment is disabled by modBugReportingIncludeScreenshot.");
		if (png == null || png.Length == 0)
			throw new InvalidOperationException("Screenshot attachment is empty.");
		if (png.Length > ScreenshotMaxBytes)
			throw new InvalidOperationException("Screenshot attachment exceeds the " + ScreenshotMaxBytes + " byte limit.");
		if (!HasPngSignature(png))
			throw new InvalidOperationException("Screenshot attachment is not a PNG image.");

		return new CaptureData(
			capture._title,
			capture._description,
			capture._contact,
			capture._category,
			capture._tag,
			capture._nativeLog,
			capture._attachments,
			(byte[])png.Clone(),
			capture._gameId,
			includeScreenshot: true,
			screenshotOmissionReason: null);
	}

	/// <summary>Packages and submits one explicit user report. ZIP construction and network I/O stay off the Unity thread.</summary>
	internal static Task<ReportOutcome> PackageAndSubmitAsync(
		CaptureData capture,
		string endpoint,
		string reportId,
		CancellationToken cancellationToken = default)
	{
		if (capture == null)
			return Task.FromResult(FailedOutcome(reportId, "capture_missing", null));
		if (!TryNormalizeReportId(reportId, out var normalizedId))
			return Task.FromResult(FailedOutcome(reportId, "invalid_report_id", null));
		if (!TryBeginReport(normalizedId))
			return Task.FromResult(FailedOutcome(normalizedId, "report_already_in_progress", null));
		return Task.Run(() => PackageAndSubmitCoreAsync(capture, endpoint, normalizedId, cancellationToken));
	}

	/// <summary>Explicit retry: verifies and sends the existing finalized ZIP without recapture, repackaging or rate accounting.</summary>
	internal static Task<ReportOutcome> RetryAndSubmitAsync(
		string endpoint,
		string reportId,
		CancellationToken cancellationToken = default)
	{
		if (!TryNormalizeReportId(reportId, out var normalizedId))
			return Task.FromResult(FailedOutcome(reportId, "invalid_report_id", null));
		if (!TryBeginReport(normalizedId))
			return Task.FromResult(FailedOutcome(normalizedId, "report_already_in_progress", null));
		return Task.Run(() => SubmitExistingCoreAsync(endpoint, normalizedId, cancellationToken));
	}

	private static async Task<ReportOutcome> PackageAndSubmitCoreAsync(
		CaptureData capture,
		string endpoint,
		string reportId,
		CancellationToken cancellationToken)
	{
		string bundlePath = null;
		var uploadStarted = false;
		try
		{
			var built = BuildFinalBundle(capture, reportId, cancellationToken);
			bundlePath = built.BundlePath;
			if (!built.Success)
				return RecordOutcomeState(FailedOutcome(reportId, built.Error ?? "package_failed", bundlePath));
			if (cancellationToken.IsCancellationRequested)
				return RecordOutcomeState(FailedOutcome(reportId, "cancelled_before_upload", bundlePath));

			uploadStarted = true;
			var receipt = await ModBugReportTransport.SubmitAsync(endpoint, reportId, built.ZipBytes, cancellationToken).ConfigureAwait(false);
			return RecordOutcomeState(OutcomeFromReceipt(receipt, reportId, bundlePath));
		}
		catch (OperationCanceledException)
		{
			return RecordOutcomeState(FailedOutcome(reportId, uploadStarted ? "cancelled_unconfirmed" : "package_cancelled", bundlePath));
		}
		catch (InvalidDataException) when (!uploadStarted)
		{
			SafeLogError("ModBugReporting: native log data is invalid or exceeds the decompression limit; no bundle was submitted.");
			return FailedOutcome(reportId, "native_log_invalid", bundlePath);
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: " + (uploadStarted ? "submit" : "package") + " failed (" + ex.GetType().Name + "); the native sink remains blocked.");
			return RecordOutcomeState(FailedOutcome(reportId, uploadStarted ? "submit_unconfirmed" : "package_failed", bundlePath));
		}
		finally
		{
			EndReport(reportId);
		}
	}

	private static async Task<ReportOutcome> SubmitExistingCoreAsync(string endpoint, string reportId, CancellationToken cancellationToken)
	{
		string bundlePath = null;
		var uploadStarted = false;
		try
		{
			var existing = ReadRetryBundle(reportId);
			bundlePath = existing.BundlePath;
			if (existing.Error != null)
				return RecordOutcomeState(FailedOutcome(reportId, existing.Error, bundlePath));
			if (cancellationToken.IsCancellationRequested)
				return RecordOutcomeState(FailedOutcome(reportId, "cancelled_before_upload", bundlePath));

			uploadStarted = true;
			var receipt = await ModBugReportTransport.SubmitAsync(endpoint, reportId, existing.ZipBytes, cancellationToken).ConfigureAwait(false);
			return RecordOutcomeState(OutcomeFromReceipt(receipt, reportId, bundlePath));
		}
		catch (OperationCanceledException)
		{
			return RecordOutcomeState(FailedOutcome(reportId, uploadStarted ? "cancelled_unconfirmed" : "retry_cancelled", bundlePath));
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: explicit retry " + (uploadStarted ? "submit" : "verification") + " failed (" + ex.GetType().Name + "); the finalized bundle was retained.");
			return RecordOutcomeState(FailedOutcome(reportId, uploadStarted ? "retry_unconfirmed" : "retry_verification_failed", bundlePath));
		}
		finally
		{
			EndReport(reportId);
		}
	}

	private static BundleBuildResult BuildFinalBundle(CaptureData capture, string reportId, CancellationToken cancellationToken)
	{
		lock (BundleGate)
		{
			var dir = BundleDirectory();
			Directory.CreateDirectory(dir);
			var now = DateTime.UtcNow;
			CleanupLocalBundlesLocked(dir, now);
			if (FindBundlesByReportId(dir, reportId).Length != 0)
				return new BundleBuildResult(null, null, "report_id_exists_use_explicit_retry");

			if (cancellationToken.IsCancellationRequested)
				return new BundleBuildResult(null, null, "cancelled_before_package");

			var reportHash = ReportHash("native_form", Scrubber.Scrub(capture._title), Scrubber.Scrub(capture._description),
				Scrubber.Scrub(capture._category), Scrubber.Scrub(capture._tag));
			var refusal = AdmissionRefusal(dir, reportHash, now);
			if (refusal != null)
				return new BundleBuildResult(null, null, "package_refused:" + refusal);

			var fileName = "oe-mod-report-" + now.ToString("yyyyMMdd-HHmmss") + "-" + reportHash.Substring(0, ReportHashChars) + "-" + reportId + ".zip";
			var path = Path.Combine(dir, fileName);
			var temporaryPath = path + ".tmp-" + Guid.NewGuid().ToString("N");
			var screenshotNote = !capture._includeScreenshot
				? capture._screenshotOmissionReason
				: capture._screenshot.Length == 0 ? "none" : "included";

			try
			{
				using (var zip = ZipFile.Open(temporaryPath, ZipArchiveMode.Create))
				{
					var report = BuildReportJson(
						reportId,
						capture._title,
						capture._description,
						capture._contact,
						capture._category,
						capture._tag,
						capture._attachments,
						screenshotNote,
						capture._gameId,
						"native_form",
						reportHash,
						now);
					AddText(zip, "report.json", report);
					AddText(zip, "bepinex_log_tail.txt", Scrubber.Scrub(ReadBepInExLogTail()));
					var nativeText = NativeLogText(capture._nativeLog);
					if (nativeText != null)
						AddText(zip, "native_log.txt", Scrubber.Scrub(nativeText));
					AddText(zip, "payload_manifest.json", PayloadManifest());
					if (screenshotNote == "included")
					{
						// The receiver accepts only screenshot.png (tools/google_bug_report_relay/bundle_contract.json).
						if (!HasPngSignature(capture._screenshot))
							return new BundleBuildResult(null, null, "screenshot_not_png");
						AddBytes(zip, "screenshot.png", capture._screenshot);
					}
				}

				var size = new FileInfo(temporaryPath).Length;
				if (size > MaxBundleBytes)
					return new BundleBuildResult(null, null, "bundle_too_large");
				if (cancellationToken.IsCancellationRequested)
					return new BundleBuildResult(null, null, "cancelled_before_finalize");
				if (File.Exists(path))
					return new BundleBuildResult(null, null, "bundle_path_collision");

				File.Move(temporaryPath, path);
				try
				{
					var bundleHash = Sha256File(path, MaxBundleBytes);
					WriteRetryMetadata(path, reportId, bundleHash);
					var zipBytes = File.ReadAllBytes(path);
					if (!string.Equals(Sha256(zipBytes), bundleHash, StringComparison.Ordinal))
						return new BundleBuildResult(path, null, "bundle_integrity_mismatch_unconfirmed");
					return new BundleBuildResult(path, zipBytes, null);
				}
				catch (Exception ex)
				{
					SafeLogError("ModBugReporting: finalized local bundle could not be prepared for upload (" + ex.GetType().Name + "); it was retained.");
					return new BundleBuildResult(path, null, "finalized_bundle_unavailable");
				}
			}
			catch
			{
				if (File.Exists(temporaryPath))
					File.Delete(temporaryPath);
				throw;
			}
			finally
			{
				if (File.Exists(temporaryPath))
					File.Delete(temporaryPath);
			}
		}
	}

	private static string BuildReportJson(
		string reportId,
		string title,
		string description,
		string contact,
		string category,
		string tag,
		string attachments,
		string screenshotNote,
		string gameId,
		string source,
		string reportHash,
		DateTime now)
	{
		var report = new StringBuilder();
		report.Append("{\n");
		JsonField(report, "schema", BundleSchema, scrubValue: false);
		JsonField(report, "createdUtc", now.ToString("o"), scrubValue: false);
		JsonField(report, "reportId", reportId, scrubValue: false);
		JsonField(report, "source", source, scrubValue: false);
		JsonField(report, "reportHash", reportHash, scrubValue: false);
		JsonField(report, "pluginVersion", Plugin.PluginVersion, scrubValue: false);
		JsonField(report, "title", title);
		JsonField(report, "description", description);
		JsonField(report, "category", category);
		JsonField(report, "tag", tag);
		JsonField(report, "gameId", gameId);
		JsonField(report, "contactProvided", string.IsNullOrWhiteSpace(contact) ? "false" : "true", scrubValue: false);
		JsonField(report, "os", Environment.OSVersion.VersionString);
		JsonField(report, "nativeAttachmentsOmitted", attachments);
		JsonField(report, "screenshot", screenshotNote, scrubValue: false);
		JsonField(
			report,
			"limits",
			"log tails " + BepInExLogTailBytes + " / " + NativeLogTailBytes + " bytes, screenshot " + ScreenshotMaxBytes
			+ " bytes, bundle " + MaxBundleBytes + " bytes",
			scrubValue: false);
		JsonField(report, "scrubbing", "user profile paths, user and machine names, Steam ids and Steam account/persona names, e-mail and IP addresses replaced", last: true, scrubValue: false);
		report.Append("}\n");
		return report.ToString();
	}

	/// <summary>Content hash of what the player wrote; identical reports get the same hash.</summary>
	private static string ReportHash(string source, string title, string description, string category, string tag)
	{
		var text = string.Join("\n", source, (title ?? "").Trim(), (description ?? "").Trim(), category ?? "", tag ?? "");
		using var sha = SHA256.Create();
		return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(text))).Replace("-", "").ToLowerInvariant();
	}

	/// <summary>
	/// Applies the dedup, cooldown and daily cap against the bundles already on disk, so the limits survive a restart.
	/// Returns null when the report may be bundled, otherwise the reason it is refused.
	/// </summary>
	private static string AdmissionRefusal(string dir, string reportHash, DateTime nowUtc)
	{
		var shortHash = reportHash.Substring(0, ReportHashChars);
		var today = nowUtc.ToString("yyyyMMdd");
		var newest = DateTime.MinValue;
		var todayCount = 0;
		var duplicateCutoff = nowUtc.AddHours(-DuplicateWindowHours);
		foreach (var file in Directory.GetFiles(dir, "oe-mod-report-*.zip"))
		{
			var match = BundleNamePattern.Match(Path.GetFileName(file));
			if (!match.Success || !TryParseBundleStamp(match, out var stamp))
				continue;
			// Failed and abandoned attempts never reached the receiver as accepted reports; they do not count.
			if (!CountsForAdmission(ReadBundleState(file)))
				continue;
			if (match.Groups[2].Success && stamp >= duplicateCutoff
			    && string.Equals(match.Groups[2].Value, shortHash, StringComparison.OrdinalIgnoreCase))
				return "duplicate_report";
			if (stamp > newest)
				newest = stamp;
			if (match.Groups[1].Value.StartsWith(today, StringComparison.Ordinal))
				todayCount++;
		}

		var sinceLast = nowUtc - newest;
		if (sinceLast < TimeSpan.FromSeconds(ReportCooldownSeconds))
			return "cooldown_active";
		if (todayCount >= DailyBundleCap)
			return "daily_cap_reached";
		return null;
	}

	private static bool TryParseBundleStamp(Match match, out DateTime stamp)
		=> DateTime.TryParseExact(
			match.Groups[1].Value,
			"yyyyMMdd-HHmmss",
			System.Globalization.CultureInfo.InvariantCulture,
			System.Globalization.DateTimeStyles.AssumeUniversal | System.Globalization.DateTimeStyles.AdjustToUniversal,
			out stamp);

	private static bool CountsForAdmission(string state)
		=> state == null || state == StateAcknowledged || state.StartsWith(StateUnconfirmedPrefix, StringComparison.Ordinal);

	private static string StatePath(string bundlePath) => bundlePath + ".state";

	/// <summary>Null when no readable state exists (in flight, or interrupted before the receipt).</summary>
	internal static string ReadBundleState(string bundlePath)
	{
		try
		{
			var path = StatePath(bundlePath);
			var info = new FileInfo(path);
			if (!info.Exists || info.Length > MaxStateFileBytes)
				return null;
			var value = File.ReadAllText(path, Encoding.ASCII).Trim();
			if (value == StateAcknowledged || value == StateAbandoned
			    || value.StartsWith(StateUnconfirmedPrefix, StringComparison.Ordinal)
			    || value.StartsWith(StateFailedPrefix, StringComparison.Ordinal))
				return value;
			return null;
		}
		catch
		{
			return null;
		}
	}

	private static void WriteBundleState(string bundlePath, string state)
	{
		var safe = new StringBuilder(state.Length);
		foreach (var c in state)
		{
			if (safe.Length >= 128)
				break;
			safe.Append(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == ':' ? c : '_');
		}
		File.WriteAllText(StatePath(bundlePath), safe + "\n", Encoding.ASCII);
	}

	private static ReportOutcome RecordOutcomeState(ReportOutcome outcome)
	{
		if (outcome?.BundlePath == null || !File.Exists(outcome.BundlePath))
			return outcome;
		try
		{
			var error = outcome.Error ?? "unknown";
			var state = outcome.Acknowledged
				? StateAcknowledged
				: error.IndexOf("unconfirmed", StringComparison.Ordinal) >= 0
					? StateUnconfirmedPrefix + error
					: StateFailedPrefix + error;
			lock (BundleGate)
				WriteBundleState(outcome.BundlePath, state);
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: local report state could not be recorded (" + ex.GetType().Name + ").");
		}
		return outcome;
	}

	/// <summary>Explicit player abandonment: the bundle stays on disk until pruned but is no longer offered for retry.</summary>
	internal static bool MarkAbandoned(string reportId)
	{
		if (!TryNormalizeReportId(reportId, out var normalized))
			return false;
		lock (ActiveReportsGate)
		{
			if (ActiveReports.Contains(normalized))
				return false;
		}
		try
		{
			lock (BundleGate)
			{
				var matches = FindBundlesByReportId(BundleDirectory(), normalized);
				foreach (var match in matches)
					WriteBundleState(match, StateAbandoned);
				return matches.Length != 0;
			}
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: abandoned state could not be recorded (" + ex.GetType().Name + ").");
			return false;
		}
	}

	/// <summary>
	/// The newest finalized bundle from the last <see cref="RestoreUnsentMaxAgeDays"/> days that was never acknowledged
	/// or abandoned and still has valid retry metadata, so the player can explicitly retry it after a restart.
	/// </summary>
	internal static ReportOutcome FindLatestUnsentReport()
	{
		try
		{
			var dir = BundleDirectory();
			if (!Directory.Exists(dir))
				return null;
			var cutoff = DateTime.UtcNow.AddDays(-RestoreUnsentMaxAgeDays);
			string bestPath = null;
			string bestId = null;
			string bestState = null;
			var bestStamp = DateTime.MinValue;
			lock (BundleGate)
			{
				foreach (var file in Directory.GetFiles(dir, "oe-mod-report-*.zip"))
				{
					var match = BundleNamePattern.Match(Path.GetFileName(file));
					if (!match.Success || !match.Groups[3].Success || !TryParseBundleStamp(match, out var stamp)
					    || stamp < cutoff || stamp <= bestStamp)
						continue;
					var state = ReadBundleState(file);
					if (state == StateAcknowledged || state == StateAbandoned)
						continue;
					var metadata = ReadRetryMetadata(RetryMetadataPath(file));
					if (metadata == null || !string.Equals(metadata.ReportId, match.Groups[3].Value.ToLowerInvariant(), StringComparison.Ordinal))
						continue;
					bestPath = file;
					bestId = metadata.ReportId;
					bestState = state;
					bestStamp = stamp;
				}
			}
			if (bestPath == null)
				return null;
			var error = bestState == null
				? "not_acknowledged_before_restart"
				: bestState.Substring(bestState.IndexOf(':') + 1);
			return new ReportOutcome(false, bestId, error, bestPath, false);
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: unsent report scan failed (" + ex.GetType().Name + ").");
			return null;
		}
	}

	private static void TryCleanupLocalBundles()
	{
		try
		{
			var dir = BundleDirectory();
			if (!Directory.Exists(dir))
				return;
			lock (BundleGate)
				CleanupLocalBundlesLocked(dir, DateTime.UtcNow);
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: local report cleanup failed (" + ex.GetType().Name + ").");
		}
	}

	/// <summary>Fixture hook for the local retention policy; production calls it at startup and before packaging.</summary>
	internal static void CleanupLocalBundles(DateTime nowUtc)
	{
		var dir = BundleDirectory();
		if (!Directory.Exists(dir))
			return;
		lock (BundleGate)
			CleanupLocalBundlesLocked(dir, nowUtc);
	}

	// Deletes finalized bundles (with their sidecars) older than LocalBundleRetentionDays or beyond the newest
	// LocalBundleMaxCount, orphaned sidecars, and abandoned temporary files. In-flight reports are never touched.
	private static void CleanupLocalBundlesLocked(string dir, DateTime nowUtc)
	{
		var cutoff = nowUtc.AddDays(-LocalBundleRetentionDays);
		var bundles = new List<(string Path, DateTime Stamp, string Id)>();
		foreach (var file in Directory.GetFiles(dir, "oe-mod-report-*.zip"))
		{
			var match = BundleNamePattern.Match(Path.GetFileName(file));
			if (match.Success && TryParseBundleStamp(match, out var stamp))
				bundles.Add((file, stamp, match.Groups[3].Success ? match.Groups[3].Value.ToLowerInvariant() : null));
		}
		bundles.Sort((a, b) =>
		{
			var byStamp = b.Stamp.CompareTo(a.Stamp);
			return byStamp != 0 ? byStamp : string.CompareOrdinal(b.Path, a.Path);
		});
		for (var i = 0; i < bundles.Count; i++)
		{
			var bundle = bundles[i];
			if (i < LocalBundleMaxCount && bundle.Stamp >= cutoff)
				continue;
			if (bundle.Id != null)
			{
				lock (ActiveReportsGate)
				{
					if (ActiveReports.Contains(bundle.Id))
						continue;
				}
			}
			TryDelete(bundle.Path);
			TryDelete(RetryMetadataPath(bundle.Path));
			TryDelete(StatePath(bundle.Path));
		}

		foreach (var sidecar in Directory.GetFiles(dir, "oe-mod-report-*.zip.*"))
		{
			var name = Path.GetFileName(sidecar);
			if (name.EndsWith(".zip.retry", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".zip.state", StringComparison.OrdinalIgnoreCase))
			{
				if (!File.Exists(sidecar.Substring(0, sidecar.LastIndexOf('.'))))
					TryDelete(sidecar);
			}
			else if (name.IndexOf(".tmp-", StringComparison.OrdinalIgnoreCase) >= 0
			         && File.GetLastWriteTimeUtc(sidecar) < nowUtc.AddHours(-1))
			{
				TryDelete(sidecar);
			}
		}
	}

	private static void TryDelete(string path)
	{
		try
		{
			if (File.Exists(path))
				File.Delete(path);
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: local report file could not be pruned (" + ex.GetType().Name + ").");
		}
	}

	private static bool TryNormalizeReportId(string reportId, out string normalized)
	{
		normalized = null;
		if (!Guid.TryParseExact(reportId, "D", out var guid))
			return false;
		normalized = guid.ToString("D").ToLowerInvariant();
		return string.Equals(reportId, normalized, StringComparison.Ordinal);
	}

	private static bool TryBeginReport(string reportId)
	{
		lock (ActiveReportsGate)
			return ActiveReports.Add(reportId);
	}

	private static void EndReport(string reportId)
	{
		lock (ActiveReportsGate)
			ActiveReports.Remove(reportId);
	}

	private static ReportOutcome FailedOutcome(string reportId, string error, string bundlePath)
		=> new(false, reportId, error, bundlePath, false);

	private static ReportOutcome OutcomeFromReceipt(ModBugReportTransport.ReportReceipt receipt, string reportId, string bundlePath)
	{
		if (receipt == null)
			return FailedOutcome(reportId, "empty_transport_receipt_unconfirmed", bundlePath);
		if (!string.Equals(receipt.ReportId, reportId, StringComparison.Ordinal))
			return FailedOutcome(reportId, "acknowledgement_id_mismatch_unconfirmed", bundlePath);
		var error = receipt.Acknowledged ? receipt.Error : receipt.Error ?? "submission_unconfirmed";
		return new ReportOutcome(receipt.Acknowledged, reportId, error, bundlePath, receipt.Duplicate);
	}

	private static BundleBuildResult ReadRetryBundle(string reportId)
	{
		var dir = BundleDirectory();
		var matches = FindBundlesByReportId(dir, reportId);
		if (matches.Length == 0)
			return new BundleBuildResult(null, null, "retry_bundle_not_found");
		if (matches.Length != 1)
			return new BundleBuildResult(null, null, "retry_bundle_ambiguous");

		var path = matches[0];
		try
		{
			var metadata = ReadRetryMetadata(path + ".retry");
			if (metadata == null || !string.Equals(metadata.ReportId, reportId, StringComparison.Ordinal))
				return new BundleBuildResult(path, null, "retry_metadata_invalid");

			var size = new FileInfo(path).Length;
			if (size < 4 || size > MaxBundleBytes)
				return new BundleBuildResult(path, null, "retry_bundle_size_invalid");
			var actualHash = Sha256File(path, MaxBundleBytes);
			if (!string.Equals(actualHash, metadata.BundleSha256, StringComparison.Ordinal))
				return new BundleBuildResult(path, null, "retry_bundle_integrity_mismatch");

			var bytes = File.ReadAllBytes(path);
			if (!string.Equals(Sha256(bytes), metadata.BundleSha256, StringComparison.Ordinal))
				return new BundleBuildResult(path, null, "retry_bundle_integrity_mismatch");
			return new BundleBuildResult(path, bytes, null);
		}
		catch (Exception ex)
		{
			SafeLogError("ModBugReporting: explicit retry bundle verification failed (" + ex.GetType().Name + "); the file was retained.");
			return new BundleBuildResult(path, null, "retry_bundle_verification_failed");
		}
	}

	private static string[] FindBundlesByReportId(string directory, string reportId)
	{
		if (!Directory.Exists(directory))
			return Array.Empty<string>();
		return Directory.GetFiles(directory, "oe-mod-report-*.zip")
			.Where(path =>
			{
				var match = BundleNamePattern.Match(Path.GetFileName(path));
				return match.Success && match.Groups[3].Success
				       && string.Equals(match.Groups[3].Value, reportId, StringComparison.OrdinalIgnoreCase);
			})
			.ToArray();
	}

	private static string Hex(byte[] bytes)
		=> BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();

	private static string RetryMetadataPath(string bundlePath) => bundlePath + ".retry";

	private static void WriteRetryMetadata(string bundlePath, string reportId, string bundleSha256)
	{
		var path = RetryMetadataPath(bundlePath);
		var temporaryPath = path + ".tmp-" + Guid.NewGuid().ToString("N");
		var contents = string.Join("\n", "oe_mod_bug_report_retry.v1", reportId, bundleSha256) + "\n";
		try
		{
			File.WriteAllText(temporaryPath, contents, Encoding.ASCII);
			if (File.Exists(path))
				throw new IOException("Retry metadata already exists for a new report id.");
			File.Move(temporaryPath, path);
		}
		finally
		{
			if (File.Exists(temporaryPath))
				File.Delete(temporaryPath);
		}
	}

	private static RetryMetadata ReadRetryMetadata(string path)
	{
		if (!File.Exists(path))
			return null;
		var lines = File.ReadAllLines(path, Encoding.ASCII);
		if (lines.Length != 3 || lines[0] != "oe_mod_bug_report_retry.v1"
		    || !TryNormalizeReportId(lines[1], out var reportId)
		    || !IsSha256(lines[2]))
			return null;
		return new RetryMetadata(reportId, lines[2]);
	}

	private static bool IsSha256(string value)
		=> value != null && value.Length == 64 && value.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f');

	private static string CaptureText(object value, string field, int maxChars)
	{
		if (value == null)
			return "";
		if (!(value is string text))
			throw new InvalidOperationException("Bug report " + field + " has an unexpected runtime type.");
		if (text.Length > maxChars)
			throw new InvalidOperationException("Bug report " + field + " exceeds the " + maxChars + " character capture limit.");
		return text;
	}

	private static byte[] CaptureBytes(object value, string field, int maxBytes)
	{
		if (value == null)
			return Array.Empty<byte>();
		try
		{
			if (value is byte[] managed)
			{
				if (managed.Length > maxBytes)
					throw new InvalidOperationException("Bug report " + field + " exceeds the " + maxBytes + " byte capture limit.");
				return (byte[])managed.Clone();
			}
			if (value is Il2CppStructArray<byte> il2cpp)
			{
				if (il2cpp.Length > maxBytes)
					throw new InvalidOperationException("Bug report " + field + " exceeds the " + maxBytes + " byte capture limit.");
				var copy = il2cpp.ToArray();
				if (copy == null || copy.Length != il2cpp.Length)
					throw new InvalidOperationException("Bug report " + field + " copy length did not match the native buffer.");
				return copy;
			}
			throw new InvalidOperationException("Bug report " + field + " has an unsupported native buffer type.");
		}
		catch (InvalidOperationException)
		{
			throw;
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException("Bug report " + field + " could not be copied from the native buffer (" + ex.GetType().Name + ").", ex);
		}
	}

	private static string CaptureAttachmentSummary(object value)
	{
		if (value == null)
			return "none";
		if (!(value is Il2CppSystem.Collections.Generic.Dictionary<string, Il2CppStructArray<byte>> dict))
			throw new InvalidOperationException("Bug report attachments have an unsupported native dictionary type.");
		if (dict.Count > MaxAttachmentEntries)
			throw new InvalidOperationException("Bug report attachment count exceeds the " + MaxAttachmentEntries + " entry capture limit.");

		var parts = new List<string>(dict.Count);
		foreach (var entry in dict)
		{
			if (entry.Key == null || entry.Key.Length > MaxAttachmentNameChars)
				throw new InvalidOperationException("Bug report attachment name is null or exceeds the " + MaxAttachmentNameChars + " character capture limit.");
			parts.Add(entry.Key + " (" + (entry.Value?.Length ?? 0).ToString(System.Globalization.CultureInfo.InvariantCulture) + " bytes)");
		}
		return parts.Count == 0 ? "none" : string.Join("; ", parts);
	}

	private static string NativeLogText(byte[] bytes)
	{
		if (bytes == null || bytes.Length == 0)
			return null;
		var compressed = bytes.Length > 2 && bytes[0] == 0x1f && bytes[1] == 0x8b;
		long totalBytes;
		var tail = compressed ? ReadGzipTail(bytes, out totalBytes) : ReadByteTail(bytes, out totalBytes);
		var text = Encoding.UTF8.GetString(tail);
		if (totalBytes > tail.Length)
			text = "[truncated: last " + tail.Length + " of " + totalBytes + " bytes]\n" + text;
		var control = text.Count(c => c < 0x20 && c != '\n' && c != '\r' && c != '\t');
		return control > text.Length / 100 ? null : text;
	}

	private static byte[] ReadByteTail(byte[] bytes, out long totalBytes)
	{
		totalBytes = bytes.Length;
		var length = Math.Min(bytes.Length, NativeLogTailBytes);
		var tail = new byte[length];
		Buffer.BlockCopy(bytes, bytes.Length - length, tail, 0, length);
		return tail;
	}

	private static byte[] ReadGzipTail(byte[] bytes, out long totalBytes)
	{
		var ring = new byte[NativeLogTailBytes];
		var chunk = new byte[8192];
		totalBytes = 0;
		using (var input = new MemoryStream(bytes, writable: false))
		using (var gzip = new GZipStream(input, CompressionMode.Decompress))
		{
			while (true)
			{
				var read = gzip.Read(chunk, 0, chunk.Length);
				if (read == 0)
					break;
				if (totalBytes + read > NativeLogInflatedMaxBytes)
					throw new InvalidDataException("Native log expands beyond the " + NativeLogInflatedMaxBytes + " byte decompression limit.");
				var destination = (int)(totalBytes % NativeLogTailBytes);
				var firstChunk = Math.Min(read, NativeLogTailBytes - destination);
				Buffer.BlockCopy(chunk, 0, ring, destination, firstChunk);
				if (firstChunk < read)
					Buffer.BlockCopy(chunk, firstChunk, ring, 0, read - firstChunk);
				totalBytes += read;
			}
		}

		var length = (int)Math.Min(totalBytes, NativeLogTailBytes);
		var tail = new byte[length];
		var start = (int)((totalBytes - length) % NativeLogTailBytes);
		var firstLength = Math.Min(length, NativeLogTailBytes - start);
		Buffer.BlockCopy(ring, start, tail, 0, firstLength);
		if (firstLength < length)
			Buffer.BlockCopy(ring, 0, tail, firstLength, length - firstLength);
		return tail;
	}

	private static string ReadBepInExLogTail()
	{
		var path = Path.Combine(Paths.BepInExRootPath, "LogOutput.log");
		if (!File.Exists(path))
			return "(LogOutput.log not found)";
		using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
		var length = fs.Length;
		var start = Math.Max(0, length - BepInExLogTailBytes);
		var remaining = (int)(length - start);
		fs.Seek(start, SeekOrigin.Begin);
		var bytes = new byte[remaining];
		var offset = 0;
		while (offset < bytes.Length)
		{
			var read = fs.Read(bytes, offset, bytes.Length - offset);
			if (read == 0)
				break;
			offset += read;
		}
		var text = Encoding.UTF8.GetString(bytes, 0, offset);
		return start > 0 ? "[truncated: last " + offset + " of " + length + " bytes]\n" + text : text;
	}

	private static string PayloadManifest()
	{
		var sb = new StringBuilder();
		sb.Append("{\n");
		var pluginDir = Path.Combine(Paths.PluginPath, "OfflineUnlockMod");
		JsonField(sb, "pluginVersion", Plugin.PluginVersion, scrubValue: false);
		JsonField(sb, "OfflineUnlockMod.dll", Sha256File(Path.Combine(pluginDir, "OfflineUnlockMod.dll"), MaxPluginAssemblyBytes), scrubValue: false);
		if (Directory.Exists(pluginDir))
		{
			var manifests = Directory.EnumerateDirectories(pluginDir).Take(MaxManifestFiles + 1).OrderBy(d => d, StringComparer.Ordinal).ToArray();
			if (manifests.Length > MaxManifestFiles)
				throw new InvalidOperationException("Plugin manifest count exceeds the " + MaxManifestFiles + " file capture limit.");
			foreach (var manifest in manifests)
			{
				var file = Path.Combine(manifest, "manifest.json");
				if (File.Exists(file))
					JsonField(sb, Scrubber.Scrub(Path.GetFileName(manifest) + "/manifest.json"), Sha256File(file, MaxManifestFileBytes), scrubValue: false);
			}
		}

		var core = Path.Combine(Paths.GameRootPath, "HeroesOldenEra_Data", "StreamingAssets", "Core.zip");
		var coreInfo = new FileInfo(core);
		JsonField(
			sb,
			"Core.zip",
			coreInfo.Exists ? coreInfo.Length + " bytes, modified " + coreInfo.LastWriteTimeUtc.ToString("o") : "missing",
			last: true,
			scrubValue: false);
		sb.Append("}\n");
		return sb.ToString();
	}

	private static string Sha256File(string path, long maxBytes)
	{
		if (!File.Exists(path))
			return "missing";
		using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
		using var sha = SHA256.Create();
		var buffer = new byte[64 * 1024];
		long total = 0;
		int read;
		while ((read = fs.Read(buffer, 0, buffer.Length)) > 0)
		{
			total += read;
			if (total > maxBytes)
				throw new InvalidOperationException("File exceeds the " + maxBytes + " byte hashing limit: " + Scrubber.Scrub(path));
			sha.TransformBlock(buffer, 0, read, buffer, 0);
		}
		sha.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
		return Hex(sha.Hash);
	}

	private static string Sha256(byte[] bytes)
	{
		using var sha = SHA256.Create();
		return Hex(sha.ComputeHash(bytes));
	}

	private static bool HasPngSignature(byte[] bytes)
		=> bytes != null && bytes.Length >= 8
		   && bytes[0] == 0x89 && bytes[1] == 0x50 && bytes[2] == 0x4e && bytes[3] == 0x47
		   && bytes[4] == 0x0d && bytes[5] == 0x0a && bytes[6] == 0x1a && bytes[7] == 0x0a;

	private static void AddText(ZipArchive zip, string name, string text) => AddBytes(zip, name, Encoding.UTF8.GetBytes(text ?? ""));

	private static void AddBytes(ZipArchive zip, string name, byte[] bytes)
	{
		var entry = zip.CreateEntry(name, CompressionLevel.Optimal);
		using var s = entry.Open();
		s.Write(bytes, 0, bytes.Length);
	}

	private static void JsonField(StringBuilder sb, string key, string value, bool last = false, bool scrubValue = true)
	{
		// Schema keys are stable; callers scrub dynamic manifest names, and user-controlled values default to scrubbed.
		var safeValue = value ?? "";
		if (scrubValue)
			safeValue = Scrubber.Scrub(safeValue);
		sb.Append("  \"").Append(JsonEscape(key)).Append("\": \"").Append(JsonEscape(safeValue)).Append('"');
		sb.Append(last ? "\n" : ",\n");
	}

	private static string JsonEscape(string s)
	{
		var sb = new StringBuilder(s.Length + 8);
		foreach (var c in s)
		{
			switch (c)
			{
				case '"': sb.Append("\\\""); break;
				case '\\': sb.Append("\\\\"); break;
				case '\n': sb.Append("\\n"); break;
				case '\r': sb.Append("\\r"); break;
				case '\t': sb.Append("\\t"); break;
				default:
					if (c < 0x20)
						sb.Append("\\u").Append(((int)c).ToString("x4"));
					else
						sb.Append(c);
					break;
			}
		}

		return sb.ToString();
	}

	/// <summary>PII scrubbing applied to every text that goes into a report bundle.</summary>
	internal static class Scrubber
	{
		private static readonly Regex UserProfilePath = new(
			@"(?i)([A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)[^\\/:*?""<>|\r\n]+",
			RegexOptions.Compiled);
		private static readonly Regex UnixHomePath = new(@"(/(?:home|Users)/)[^/\s]+", RegexOptions.Compiled);
		private static readonly Regex SteamId64 = new(@"\b7656119\d{10}\b", RegexOptions.Compiled);
		private static readonly Regex SteamId2 = new(@"\bSTEAM_[0-5]:[01]:\d+\b", RegexOptions.Compiled);
		private static readonly Regex SteamId3 = new(@"\[U:1:\d+\]", RegexOptions.Compiled);
		private static readonly Regex Email = new(@"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", RegexOptions.Compiled);
		private static readonly Regex IPv4 = new(
			@"(?<![0-9.])(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?![0-9]|\.[0-9])",
			RegexOptions.Compiled | RegexOptions.CultureInvariant);
		// Full eight-group or "::"-compressed forms; a match must contain a digit so C++/IL2CPP "Type::Method" text survives.
		private static readonly Regex IPv6 = new(
			@"(?<![0-9A-Fa-f:])(?:(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|(?:[0-9A-Fa-f]{1,4}:){1,7}:(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?|::[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})(?![0-9A-Fa-f:])",
			RegexOptions.Compiled | RegexOptions.CultureInvariant);
		private static readonly Regex SteamLoginName = new(
			@"""(?:PersonaName|AccountName)""\s+""((?:[^""\\\r\n]|\\.){1,128})""",
			RegexOptions.Compiled | RegexOptions.CultureInvariant);
		private static readonly object SteamNamesGate = new();
		private static bool _steamNamesLoaded;
		private static Regex _steamNameRegex;
		private const int MaxSteamLoginFileBytes = 1024 * 1024;
		private const int MaxSteamNames = 32;

		/// <summary>Fixture hook: replaces the Steam login names read from this machine.</summary>
		internal static string[] SteamNamesOverride
		{
			set
			{
				var built = BuildSteamNameRegex(value ?? Array.Empty<string>());
				lock (SteamNamesGate)
				{
					_steamNameRegex = built;
					_steamNamesLoaded = true;
				}
			}
		}

		private static Regex SteamNameRegex()
		{
			lock (SteamNamesGate)
			{
				if (!_steamNamesLoaded)
				{
					_steamNameRegex = BuildSteamNameRegex(ReadSteamLoginNames());
					_steamNamesLoaded = true;
				}
				return _steamNameRegex;
			}
		}

		internal static string Scrub(string text)
		{
			if (string.IsNullOrEmpty(text))
				return text ?? "";
			var s = UserProfilePath.Replace(text, "$1<user>");
			s = UnixHomePath.Replace(s, "$1<user>");
			s = SteamId64.Replace(s, "<steamid64>");
			s = SteamId2.Replace(s, "<steamid>");
			s = SteamId3.Replace(s, "<steamid3>");
			s = Email.Replace(s, "<email>");
			s = IPv4.Replace(s, m => IsNonIdentifyingIPv4(m.Value) ? m.Value : "<ip>");
			s = IPv6.Replace(s, m => m.Value == "::1" || !m.Value.Any(char.IsDigit) ? m.Value : "<ip>");
			var steamNames = SteamNameRegex();
			if (steamNames != null)
				s = steamNames.Replace(s, "<steam-name>");
			s = ReplaceWord(s, SafeEnv(() => Environment.UserName), "<user>");
			s = ReplaceWord(s, SafeEnv(() => Environment.MachineName), "<machine>");
			return s;
		}

		private static bool IsNonIdentifyingIPv4(string value)
			=> value == "0.0.0.0" || value == "127.0.0.1" || value == "255.255.255.255";

		// Steam account and persona names from the local loginusers.vdf, read once without interop or network.
		private static Regex BuildSteamNameRegex(string[] source)
		{
			try
			{
				var names = source
					.Where(n => !string.IsNullOrWhiteSpace(n) && n.Trim().Length >= 3)
					.Select(n => n.Trim())
					.Distinct(StringComparer.OrdinalIgnoreCase)
					.OrderByDescending(n => n.Length)
					.Take(MaxSteamNames)
					.ToArray();
				if (names.Length == 0)
					return null;
				return new Regex(
					@"(?<![A-Za-z0-9])(?:" + string.Join("|", names.Select(Regex.Escape)) + @")(?![A-Za-z0-9])",
					RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
			}
			catch
			{
				return null;
			}
		}

		private static string[] ReadSteamLoginNames()
		{
			foreach (var root in SteamRootCandidates())
			{
				try
				{
					var path = Path.Combine(root, "config", "loginusers.vdf");
					var info = new FileInfo(path);
					if (!info.Exists || info.Length > MaxSteamLoginFileBytes)
						continue;
					var text = File.ReadAllText(path, Encoding.UTF8);
					return SteamLoginName.Matches(text).Cast<Match>()
						.Select(m => m.Groups[1].Value.Replace("\\\"", "\"").Replace("\\\\", "\\"))
						.ToArray();
				}
				catch
				{
					// Unreadable candidates are skipped; scrubbing continues without Steam names.
				}
			}
			return Array.Empty<string>();
		}

		private static IEnumerable<string> SteamRootCandidates()
		{
			var roots = new List<string>();
			var programFilesX86 = SafeEnv(() => Environment.GetEnvironmentVariable("ProgramFiles(x86)"));
			var programFiles = SafeEnv(() => Environment.GetEnvironmentVariable("ProgramFiles"));
			if (!string.IsNullOrEmpty(programFilesX86))
				roots.Add(Path.Combine(programFilesX86, "Steam"));
			if (!string.IsNullOrEmpty(programFiles))
				roots.Add(Path.Combine(programFiles, "Steam"));
			// The game lives in <library>/steamapps/common/<game>; the primary library is the Steam install root.
			var gameRoot = SafeEnv(() => Paths.GameRootPath);
			try
			{
				for (var dir = string.IsNullOrEmpty(gameRoot) ? null : new DirectoryInfo(gameRoot); dir != null; dir = dir.Parent)
				{
					if (string.Equals(dir.Name, "steamapps", StringComparison.OrdinalIgnoreCase) && dir.Parent != null)
					{
						roots.Add(dir.Parent.FullName);
						break;
					}
				}
			}
			catch
			{
				// Path probing is best effort.
			}
			return roots.Distinct(StringComparer.OrdinalIgnoreCase);
		}

		private static string SafeEnv(Func<string> read)
		{
			try { return read(); }
			catch { return null; }
		}

		private static string ReplaceWord(string text, string word, string replacement)
		{
			if (string.IsNullOrWhiteSpace(word) || word.Length < 3)
				return text;
			return Regex.Replace(text, @"(?<![A-Za-z0-9])" + Regex.Escape(word) + @"(?![A-Za-z0-9])", replacement, RegexOptions.IgnoreCase);
		}
	}
}
