using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppSystem.Collections.Generic;
using OfflineUnlockMod;

internal static class PackageTests
{
	private static int _passed;
	private static int _failed;

	internal static async Task<int> Run()
	{
		await Test("capture skips deferred native screenshot and WithScreenshot clones consented PNG", CaptureAndScreenshotCopy);
		await Test("capture rejects oversized and unknown native buffers", CaptureLimits);
		await Test("bundle scrubs fields and bounds both log tails", BundleScrubbingAndLogTails);
		await Test("gzip expansion is capped before finalization", GzipExpansionIsCapped);
		await Test("refused upload retains exact retry bytes", RetryUsesRetainedZip);
		await Test("packaged bundles satisfy the shared receiver bundle contract", PackagedBundlesMatchContract);
		await Test("admission ignores failed and abandoned bundles and dedups only within 24 hours", AdmissionStateAndDedupWindow);
		await Test("local bundles are pruned by age and count with their sidecars", LocalCleanupByAgeAndCount);
		await Test("an unsent bundle is offered after restart until acknowledged or abandoned", UnsentBundleRestore);
		await Test("scrubber removes IP addresses and local Steam names", ScrubsAddressesAndSteamNames);
		Console.WriteLine("redirect package fixtures: " + _passed + " passed, " + _failed + " failed");
		return _failed;
	}

	private static async Task CaptureAndScreenshotCopy()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var args = NativeArgs("title", "description", Array.Empty<byte>(), screenshot: new object());
			var captured = ModBugReportRedirect.CaptureFromArgs(args, includeScreenshot: false);
			var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Qz8AAAAASUVORK5CYII=");
			var expectedPng = (byte[])png.Clone();
			var withScreenshot = ModBugReportRedirect.WithScreenshot(captured, png);
			Array.Clear(png, 0, png.Length);

			var outcome = await ModBugReportRedirect.PackageAndSubmitAsync(withScreenshot, "", Guid.NewGuid().ToString("D"));
			Assert(!outcome.Acknowledged && outcome.BundlePath != null, "local bundle finalizes despite offline endpoint refusal");
			Assert(outcome.Error == "invalid_endpoint", "invalid endpoint fails before network access");
			var entries = ReadZip(outcome.BundlePath);
			Assert(entries.TryGetValue("screenshot.png", out var bundledPng), "consented screenshot is included");
			Assert(expectedPng.SequenceEqual(bundledPng), "WithScreenshot owns a clone, not the caller's array");

			var config = Initialize(root);
			AssertThrows<InvalidOperationException>(() => ModBugReportRedirect.WithScreenshot(captured, new byte[4 * 1024 * 1024 + 1]), "oversized screenshot refuses attachment");
			AssertThrows<InvalidOperationException>(() => ModBugReportRedirect.WithScreenshot(captured, new byte[] { 1, 2, 3, 4, 5, 6, 7, 8 }), "non-PNG screenshot refuses attachment");
			config.ModBugReportingIncludeScreenshot = false;
			AssertThrows<InvalidOperationException>(() => ModBugReportRedirect.WithScreenshot(captured, expectedPng), "disabled screenshot config refuses attachment");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static async Task CaptureLimits()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var oversizedLog = NativeArgs("title", "description", new byte[4 * 1024 * 1024 + 1]);
			AssertThrows<InvalidOperationException>(() => ModBugReportRedirect.CaptureFromArgs(oversizedLog, false), "native log input has a hard byte cap");

			var unknownLog = NativeArgs("title", "description", new object());
			AssertThrows<InvalidOperationException>(() => ModBugReportRedirect.CaptureFromArgs(unknownLog, false), "unknown native buffer type is rejected");

			var wrongThread = Task.Run(() => ModBugReportRedirect.CaptureFromArgs(NativeArgs("title", "description", Array.Empty<byte>()), false));
			await AssertThrowsAsync<InvalidOperationException>(wrongThread, "IL2CPP capture is main-thread-only");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static async Task BundleScrubbingAndLogTails()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var user = Environment.UserName;
			var jsonField = typeof(ModBugReportRedirect).GetMethod("JsonField", BindingFlags.Static | BindingFlags.NonPublic);
			Assert(jsonField != null, "private JSON serializer is available to fixture");
			var serializedField = new StringBuilder();
			jsonField.Invoke(null, new object[] { serializedField, user, user, true, true });
			var scrubbedUser = user.Length >= 3 ? "<user>" : user;
			Assert(
				serializedField.ToString().Contains("\"" + user + "\": \"" + scrubbedUser + "\"", StringComparison.Ordinal),
				"a key equal to the current username remains literal while its value is scrubbed");
			var trustedField = new StringBuilder();
			jsonField.Invoke(null, new object[] { trustedField, "source", user, true, false });
			Assert(trustedField.ToString().Contains("\"source\": \"" + user + "\"", StringComparison.Ordinal), "trusted metadata bypasses PII scrubbing");
			var userTextField = new StringBuilder();
			jsonField.Invoke(null, new object[] { userTextField, "title", user, true, true });
			Assert(userTextField.ToString().Contains("\"title\": \"" + scrubbedUser + "\"", StringComparison.Ordinal), "user text remains scrubbed under an explicit trusted-field exception");

			var pluginDir = Path.Combine(Paths.PluginPath, "OfflineUnlockMod");
			Directory.CreateDirectory(Path.Combine(pluginDir, user));
			File.WriteAllText(Path.Combine(pluginDir, user, "manifest.json"), "fixture manifest");
			var bepInExLog = new string('b', ModBugReportRedirect.BepInExLogTailBytes + 32) + " user@example.com";
			File.WriteAllText(Path.Combine(Paths.BepInExRootPath, "LogOutput.log"), bepInExLog);

			var nativeLog = Encoding.UTF8.GetBytes(new string('n', ModBugReportRedirect.NativeLogTailBytes + 32));
			var attachmentName = "report-" + user + " foo@example.com";
			var attachments = new Dictionary<string, Il2CppStructArray<byte>>
			{
				{ attachmentName, new Il2CppStructArray<byte>(new byte[7]) },
			};
			var capture = ModBugReportRedirect.CaptureFromArgs(
				NativeArgs(user, "report user@example.com STEAM_0:1:42", nativeLog, gameId: "game-" + user, attachments: attachments),
				includeScreenshot: false);
			var outcome = await ModBugReportRedirect.PackageAndSubmitAsync(capture, "", Guid.NewGuid().ToString("D"));
			Assert(outcome.BundlePath != null, "ZIP finalized before refusal");
			var entries = ReadZip(outcome.BundlePath);
			var report = Encoding.UTF8.GetString(entries["report.json"]);
			Assert(report.Contains("\"title\": \"<user>\"", StringComparison.Ordinal), "user-name title value is scrubbed without renaming the schema key");
			Assert(report.Contains("\"os\": ", StringComparison.Ordinal), "fixed OS schema key remains stable");
			Assert(!report.Contains("user@example.com", StringComparison.OrdinalIgnoreCase), "contact e-mail in text is scrubbed");
			Assert(!report.Contains("STEAM_0:1:42", StringComparison.Ordinal), "Steam identity in text is scrubbed");
			Assert(!report.Contains(attachmentName, StringComparison.OrdinalIgnoreCase), "raw attachment name is scrubbed");
			Assert(report.Contains("\"nativeAttachmentsOmitted\": \"report-<user> <email> (7 bytes)\"", StringComparison.Ordinal), "attachment summary keeps size after PII scrubbing");

			var manifest = Encoding.UTF8.GetString(entries["payload_manifest.json"]);
			Assert(!manifest.Contains(user, StringComparison.OrdinalIgnoreCase), "dynamic manifest key does not expose the OS username");
			Assert(manifest.Contains("<user>/manifest.json", StringComparison.Ordinal), "dynamic manifest key is scrubbed at its callsite");
			var bepinexTail = Encoding.UTF8.GetString(entries["bepinex_log_tail.txt"]);
			Assert(bepinexTail.Contains("[truncated: last ", StringComparison.Ordinal), "BepInEx log reports bounded tail truncation");
			Assert(!bepinexTail.Contains("user@example.com", StringComparison.OrdinalIgnoreCase), "BepInEx log tail is scrubbed");
			var nativeTail = Encoding.UTF8.GetString(entries["native_log.txt"]);
			Assert(nativeTail.Contains("[truncated: last ", StringComparison.Ordinal), "native log is reduced to bounded tail");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static async Task GzipExpansionIsCapped()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var expanded = new byte[16 * 1024 * 1024 + 1];
			byte[] compressed;
			using (var output = new MemoryStream())
			{
				using (var gzip = new GZipStream(output, CompressionMode.Compress, leaveOpen: true))
					gzip.Write(expanded, 0, expanded.Length);
				compressed = output.ToArray();
			}
			var capture = ModBugReportRedirect.CaptureFromArgs(NativeArgs("title", "description", compressed), false);
			var outcome = await ModBugReportRedirect.PackageAndSubmitAsync(capture, "", Guid.NewGuid().ToString("D"));
			Assert(outcome.Error == "native_log_invalid", "gzip expansion cap yields a clear local failure code");
			Assert(outcome.BundlePath == null, "oversized decompressed log never produces a finalized ZIP");
			Assert(!Directory.EnumerateFiles(ModBugReportRedirect.BundleDirectory(), "*.zip").Any(), "no oversized-log bundle reaches disk as final ZIP");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static async Task RetryUsesRetainedZip()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var capture = ModBugReportRedirect.CaptureFromArgs(NativeArgs("retry title", "retry description", Array.Empty<byte>()), false);
			var reportId = Guid.NewGuid().ToString("D");
			var first = await ModBugReportRedirect.PackageAndSubmitAsync(capture, "", reportId);
			Assert(!first.Acknowledged && first.BundlePath != null, "refusal retains the finalized ZIP");
			var before = File.ReadAllBytes(first.BundlePath);
			var beforeHash = Sha256(before);
			var sidecar = first.BundlePath + ".retry";
			Assert(File.Exists(sidecar), "final ZIP has durable retry metadata");
			Assert(!File.ReadAllText(sidecar).Contains("retry title", StringComparison.Ordinal), "retry metadata stores no report text");

			var retry = await ModBugReportRedirect.RetryAndSubmitAsync("", reportId);
			var after = File.ReadAllBytes(first.BundlePath);
			Assert(!retry.Acknowledged && retry.BundlePath == first.BundlePath, "retry returns the retained bundle path on refusal");
			Assert(beforeHash == Sha256(after) && before.SequenceEqual(after), "retry leaves the exact ZIP bytes unchanged");

			File.AppendAllText(sidecar, "tampered");
			var tampered = await ModBugReportRedirect.RetryAndSubmitAsync("", reportId);
			Assert(!tampered.Acknowledged && tampered.Error == "retry_metadata_invalid", "tampered retry metadata refuses upload");
			Assert(File.Exists(first.BundlePath), "integrity failure retains the original ZIP for inspection");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static async Task PackagedBundlesMatchContract()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var contract = LoadBundleContract();
			var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Qz8AAAAASUVORK5CYII=");
			// IL2CPP capture is main-thread-only; take every snapshot before the first await.
			var plainCapture = ModBugReportRedirect.CaptureFromArgs(NativeArgs("plain", "no screenshot", Encoding.UTF8.GetBytes("native line\n")), false);
			var withShot = ModBugReportRedirect.WithScreenshot(
				ModBugReportRedirect.CaptureFromArgs(NativeArgs("shot", "with screenshot", Array.Empty<byte>()), false), png);
			var plainId = Guid.NewGuid().ToString("D");
			var plain = await ModBugReportRedirect.PackageAndSubmitAsync(plainCapture, "", plainId);
			Assert(plain.BundlePath != null, "plain bundle finalized");
			AssertContractBundle(contract, File.ReadAllBytes(plain.BundlePath), plainId, "plain");

			MakeBundlesOld(ModBugReportRedirect.BundleDirectory(), TimeSpan.FromMinutes(10));
			var shotId = Guid.NewGuid().ToString("D");
			var shot = await ModBugReportRedirect.PackageAndSubmitAsync(withShot, "", shotId);
			Assert(shot.BundlePath != null, "screenshot bundle finalized");
			AssertContractBundle(contract, File.ReadAllBytes(shot.BundlePath), shotId, "screenshot");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static async Task AdmissionStateAndDedupWindow()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var dir = ModBugReportRedirect.BundleDirectory();
			// IL2CPP capture is main-thread-only; take every snapshot before the first await.
			var sames = new System.Collections.Generic.Queue<ModBugReportRedirect.CaptureData>(Enumerable.Range(0, 6)
				.Select(_ => ModBugReportRedirect.CaptureFromArgs(NativeArgs("same title", "same text", Array.Empty<byte>()), false)).ToList());
			var otherCapture = ModBugReportRedirect.CaptureFromArgs(NativeArgs("other", "other text", Array.Empty<byte>()), false);
			ModBugReportRedirect.CaptureData Same() => sames.Dequeue();

			var first = await ModBugReportRedirect.PackageAndSubmitAsync(Same(), "", Guid.NewGuid().ToString("D"));
			Assert(first.BundlePath != null && first.Error == "invalid_endpoint", "first attempt finalizes then fails locally");
			Assert(ModBugReportRedirect.ReadBundleState(first.BundlePath) == "failed:invalid_endpoint", "definite failure is recorded");

			var second = await ModBugReportRedirect.PackageAndSubmitAsync(Same(), "", Guid.NewGuid().ToString("D"));
			Assert(second.BundlePath != null, "a failed bundle neither dedups nor starts the cooldown");

			File.WriteAllText(second.BundlePath + ".state", "acknowledged\n");
			var duplicate = await ModBugReportRedirect.PackageAndSubmitAsync(Same(), "", Guid.NewGuid().ToString("D"));
			Assert(duplicate.Error == "package_refused:duplicate_report" && duplicate.BundlePath == null, "acknowledged identical report dedups");

			var other = await ModBugReportRedirect.PackageAndSubmitAsync(otherCapture, "", Guid.NewGuid().ToString("D"));
			Assert(other.Error == "package_refused:cooldown_active", "acknowledged bundle starts the cooldown");

			MakeBundlesOld(dir, TimeSpan.FromHours(25));
			var later = await ModBugReportRedirect.PackageAndSubmitAsync(Same(), "", Guid.NewGuid().ToString("D"));
			Assert(later.BundlePath != null, "identical report is admitted again after the 24 hour window");

			File.WriteAllText(later.BundlePath + ".state", "abandoned\n");
			var afterAbandon = await ModBugReportRedirect.PackageAndSubmitAsync(Same(), "", Guid.NewGuid().ToString("D"));
			Assert(afterAbandon.BundlePath != null, "an abandoned bundle does not dedup or start the cooldown");

			// Daily cap counts only bundles that may have reached the receiver.
			var cap = CreateRoot();
			try
			{
				Initialize(cap);
				var capSame = ModBugReportRedirect.CaptureFromArgs(NativeArgs("same title", "same text", Array.Empty<byte>()), false);
				var capOther = ModBugReportRedirect.CaptureFromArgs(NativeArgs("cap", "cap text", Array.Empty<byte>()), false);
				var capDir = ModBugReportRedirect.BundleDirectory();
				Directory.CreateDirectory(capDir);
				var now = DateTime.UtcNow;
				if (now.TimeOfDay > TimeSpan.FromMinutes(30))
				{
					for (var i = 0; i < ModBugReportRedirect.DailyBundleCap; i++)
					{
						var path = FakeBundle(capDir, now.Date.AddMinutes(i), i);
						File.WriteAllText(path + ".state", "failed:invalid_endpoint\n");
					}
					var admitted = await ModBugReportRedirect.PackageAndSubmitAsync(capSame, "", Guid.NewGuid().ToString("D"));
					Assert(admitted.BundlePath != null, "failed bundles do not consume the daily cap");
					File.WriteAllText(admitted.BundlePath + ".state", "unconfirmed:timeout_unconfirmed\n");
					MakeBundlesOld(capDir, TimeSpan.FromMinutes(5));
					for (var i = 0; i < ModBugReportRedirect.DailyBundleCap; i++)
						File.WriteAllText(Directory.GetFiles(capDir, "*.zip").OrderBy(f => f, StringComparer.Ordinal).ElementAt(i) + ".state", "acknowledged\n");
					var capped = await ModBugReportRedirect.PackageAndSubmitAsync(capOther, "", Guid.NewGuid().ToString("D"));
					Assert(capped.Error == "package_refused:daily_cap_reached", "acknowledged and unconfirmed bundles consume the daily cap");
				}
			}
			finally
			{
				DeleteRoot(cap);
			}
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static Task LocalCleanupByAgeAndCount()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			var dir = ModBugReportRedirect.BundleDirectory();
			Directory.CreateDirectory(dir);
			var now = DateTime.UtcNow;
			var old = new System.Collections.Generic.List<string>();
			for (var i = 0; i < 3; i++)
				old.Add(FakeBundle(dir, now.AddDays(-(ModBugReportRedirect.LocalBundleRetentionDays + 1 + i)), 100 + i));
			var fresh = new System.Collections.Generic.List<string>();
			for (var i = 0; i < ModBugReportRedirect.LocalBundleMaxCount + 5; i++)
				fresh.Add(FakeBundle(dir, now.AddMinutes(-(10 + i)), i));
			var orphan = Path.Combine(dir, "oe-mod-report-20260101-000000-0000000000000000-" + Guid.NewGuid().ToString("D") + ".zip.retry");
			File.WriteAllText(orphan, "orphan");
			var oldTemp = Path.Combine(dir, "oe-mod-report-20260101-000000.zip.tmp-" + Guid.NewGuid().ToString("N"));
			File.WriteAllText(oldTemp, "partial");
			File.SetLastWriteTimeUtc(oldTemp, now.AddHours(-2));
			var newTemp = Path.Combine(dir, "oe-mod-report-20260102-000000.zip.tmp-" + Guid.NewGuid().ToString("N"));
			File.WriteAllText(newTemp, "partial");

			ModBugReportRedirect.CleanupLocalBundles(now);

			Assert(old.All(p => !File.Exists(p) && !File.Exists(p + ".retry") && !File.Exists(p + ".state")), "aged bundles and sidecars are deleted");
			Assert(fresh.Take(ModBugReportRedirect.LocalBundleMaxCount).All(File.Exists), "newest bundles are kept");
			Assert(fresh.Skip(ModBugReportRedirect.LocalBundleMaxCount).All(p => !File.Exists(p) && !File.Exists(p + ".retry")), "bundles beyond the count cap are deleted");
			Assert(!File.Exists(orphan), "orphaned sidecars are deleted");
			Assert(!File.Exists(oldTemp) && File.Exists(newTemp), "only stale temporary files are deleted");
			Assert(Directory.GetFiles(dir, "*.zip").Length == ModBugReportRedirect.LocalBundleMaxCount, "bounded bundle count");
		}
		finally
		{
			DeleteRoot(root);
		}
		return Task.CompletedTask;
	}

	private static async Task UnsentBundleRestore()
	{
		var root = CreateRoot();
		try
		{
			Initialize(root);
			Assert(ModBugReportRedirect.FindLatestUnsentReport() == null, "no bundle, nothing to restore");
			var reportId = Guid.NewGuid().ToString("D");
			var refused = await ModBugReportRedirect.PackageAndSubmitAsync(
				ModBugReportRedirect.CaptureFromArgs(NativeArgs("restore", "restore text", Array.Empty<byte>()), false), "", reportId);
			Assert(refused.BundlePath != null, "bundle finalized");

			var restored = ModBugReportRedirect.FindLatestUnsentReport();
			Assert(restored != null && restored.ReportId == reportId && restored.BundlePath == refused.BundlePath
			       && !restored.Acknowledged && restored.Error == "invalid_endpoint", "unsent bundle is offered with its last error");
			var retry = await ModBugReportRedirect.RetryAndSubmitAsync("", restored.ReportId);
			Assert(retry.BundlePath == refused.BundlePath && retry.Error == "invalid_endpoint", "restored report retries the exact retained bundle");

			File.Delete(refused.BundlePath + ".state");
			Assert(ModBugReportRedirect.FindLatestUnsentReport()?.Error == "not_acknowledged_before_restart", "interrupted bundle without state is offered");

			Assert(ModBugReportRedirect.MarkAbandoned(reportId), "abandon records state");
			Assert(ModBugReportRedirect.ReadBundleState(refused.BundlePath) == "abandoned", "abandoned state persisted");
			Assert(ModBugReportRedirect.FindLatestUnsentReport() == null, "abandoned bundle is not offered");
			Assert(File.Exists(refused.BundlePath), "abandon does not delete the local bundle");

			File.WriteAllText(refused.BundlePath + ".state", "acknowledged\n");
			Assert(ModBugReportRedirect.FindLatestUnsentReport() == null, "acknowledged bundle is not offered");
		}
		finally
		{
			DeleteRoot(root);
		}
	}

	private static Task ScrubsAddressesAndSteamNames()
	{
		ModBugReportRedirect.Scrubber.SteamNamesOverride = new[] { "PersonaFixture", "acct_fixture", "ab" };
		var text = "peer 203.0.113.7:27015 lan 192.168.1.20 v6 2001:db8::8a2e:370:7334 full fe80:0:0:0:200:f8ff:fe21:67cf "
			+ "loopback 127.0.0.1 ::1 any 0.0.0.0 version 10.0.26200.0 time 12:34:56 Type::Method dead::beef "
			+ "player PersonaFixture logged in as ACCT_FIXTURE; ab stays";
		var scrubbed = ModBugReportRedirect.Scrubber.Scrub(text);
		foreach (var leaked in new[] { "203.0.113.7", "192.168.1.20", "2001:db8", "fe80:0", "PersonaFixture", "ACCT_FIXTURE" })
			Assert(!scrubbed.Contains(leaked, StringComparison.OrdinalIgnoreCase), "scrubbed " + leaked);
		foreach (var kept in new[] { "127.0.0.1", " ::1 ", "0.0.0.0", "10.0.26200.0", "12:34:56", "Type::Method", "dead::beef", "ab stays", ":27015" })
			Assert(scrubbed.Contains(kept, StringComparison.Ordinal), "kept " + kept);
		Assert(scrubbed.Contains("<steam-name> logged in as <steam-name>", StringComparison.Ordinal), "Steam names replaced");
		return Task.CompletedTask;
	}

	internal static JsonElement LoadBundleContract()
	{
		for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
		{
			var path = Path.Combine(dir.FullName, "tools", "google_bug_report_relay", "bundle_contract.json");
			if (File.Exists(path))
				return JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone();
		}
		throw new InvalidOperationException("tools/google_bug_report_relay/bundle_contract.json not found above the fixture binary");
	}

	// Mirrors the receiver's pilotInspectBundle_ rules so client packaging and server admission cannot drift apart.
	internal static void AssertContractBundle(JsonElement contract, byte[] zipBytes, string reportId, string label)
	{
		using var archive = new ZipArchive(new MemoryStream(zipBytes, writable: false), ZipArchiveMode.Read);
		var rules = contract.GetProperty("entries");
		var names = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
		Assert(archive.Entries.Count <= contract.GetProperty("maxEntries").GetInt32(), label + ": entry count");
		var contents = new System.Collections.Generic.Dictionary<string, byte[]>(StringComparer.Ordinal);
		foreach (var entry in archive.Entries)
		{
			Assert(rules.TryGetProperty(entry.FullName, out var rule), label + ": unexpected entry " + entry.FullName);
			Assert(names.Add(entry.FullName), label + ": duplicate entry " + entry.FullName);
			Assert(entry.Length <= rule.GetProperty("maxBytes").GetInt64(), label + ": entry over cap " + entry.FullName);
			using var stream = entry.Open();
			using var copy = new MemoryStream();
			stream.CopyTo(copy);
			contents[entry.FullName] = copy.ToArray();
		}
		foreach (var rule in rules.EnumerateObject())
			Assert(!rule.Value.GetProperty("required").GetBoolean() || names.Contains(rule.Name), label + ": missing " + rule.Name);

		using var report = JsonDocument.Parse(contents["report.json"]);
		var fields = contract.GetProperty("reportFields");
		var expectedKeys = fields.EnumerateObject().Select(f => f.Name).OrderBy(n => n, StringComparer.Ordinal).ToArray();
		var actualKeys = report.RootElement.EnumerateObject().Select(f => f.Name).OrderBy(n => n, StringComparer.Ordinal).ToArray();
		Assert(expectedKeys.SequenceEqual(actualKeys), label + ": report.json keys " + string.Join(",", actualKeys));
		foreach (var field in report.RootElement.EnumerateObject())
		{
			Assert(field.Value.ValueKind == JsonValueKind.String, label + ": string field " + field.Name);
			Assert(field.Value.GetString().Length <= fields.GetProperty(field.Name).GetInt32(), label + ": field cap " + field.Name);
		}
		var root = report.RootElement;
		Assert(root.GetProperty("schema").GetString() == contract.GetProperty("schema").GetString(), label + ": schema");
		Assert(root.GetProperty("reportId").GetString() == reportId, label + ": report id");
		Assert(root.GetProperty("source").GetString() == "native_form", label + ": source");
		Assert(System.Text.RegularExpressions.Regex.IsMatch(root.GetProperty("reportHash").GetString(), "^[0-9a-f]{64}$"), label + ": report hash");
		Assert(System.Text.RegularExpressions.Regex.IsMatch(root.GetProperty("createdUtc").GetString(), @"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z$"), label + ": createdUtc");
		var screenshot = root.GetProperty("screenshot").GetString();
		Assert(contract.GetProperty("screenshotValues").EnumerateArray().Any(v => v.GetString() == screenshot), label + ": screenshot value");
		Assert((screenshot == "included") == names.Contains("screenshot.png"), label + ": screenshot entry matches report.json");
		if (names.Contains("screenshot.png"))
			Assert(contents["screenshot.png"].Take(8).SequenceEqual(new byte[] { 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a }), label + ": PNG signature");
		using var manifest = JsonDocument.Parse(contents["payload_manifest.json"]);
		Assert(manifest.RootElement.ValueKind == JsonValueKind.Object, label + ": manifest object");
		Assert(manifest.RootElement.EnumerateObject().All(p => p.Value.ValueKind == JsonValueKind.String), label + ": manifest string values");
	}

	private static string FakeBundle(string dir, DateTime stampUtc, int index)
	{
		var reportId = Guid.NewGuid().ToString("D");
		var path = Path.Combine(dir, "oe-mod-report-" + stampUtc.ToString("yyyyMMdd-HHmmss") + "-" + index.ToString("x16") + "-" + reportId + ".zip");
		File.WriteAllBytes(path, new byte[] { 0x50, 0x4b, 0x05, 0x06 });
		File.WriteAllText(path + ".retry", "oe_mod_bug_report_retry.v1\n" + reportId + "\n" + new string('0', 64) + "\n");
		return path;
	}

	// Renames every bundle (and sidecars) so its name timestamp is the given age; admission reads names, not mtimes.
	private static void MakeBundlesOld(string dir, TimeSpan age)
	{
		var stamp = DateTime.UtcNow - age;
		var pattern = new System.Text.RegularExpressions.Regex(@"^oe-mod-report-\d{8}-\d{6}(-.*\.zip)$");
		var counter = 0;
		foreach (var path in Directory.GetFiles(dir, "*.zip"))
		{
			var match = pattern.Match(Path.GetFileName(path));
			if (!match.Success)
				continue;
			var target = Path.Combine(dir, "oe-mod-report-" + stamp.AddSeconds(-counter++).ToString("yyyyMMdd-HHmmss") + match.Groups[1].Value);
			foreach (var suffix in new[] { "", ".retry", ".state" })
			{
				if (File.Exists(path + suffix))
					File.Move(path + suffix, target + suffix);
			}
		}
	}

	private static LauncherConfig Initialize(string root)
	{
		Directory.CreateDirectory(root);
		Paths.BepInExRootPath = Path.Combine(root, "BepInEx");
		Paths.PluginPath = Path.Combine(root, "plugins");
		Paths.GameRootPath = Path.Combine(root, "game");
		Directory.CreateDirectory(Paths.BepInExRootPath);
		Directory.CreateDirectory(Paths.PluginPath);
		Directory.CreateDirectory(Paths.GameRootPath);
		var config = new LauncherConfig { ModBugReporting = true, ModBugReportingIncludeScreenshot = true };
		ModBugReportRedirect.TryRegister(new Harmony(), new ManualLogSource(), config);
		return config;
	}

	private static object[] NativeArgs(
		string title,
		string description,
		object nativeLog,
		object screenshot = null,
		string gameId = "fixture-game",
		Dictionary<string, Il2CppStructArray<byte>> attachments = null)
		=> new object[]
		{
			title,
			description,
			"",
			"fixture-category",
			"fixture-tag",
			nativeLog,
			attachments ?? new Dictionary<string, Il2CppStructArray<byte>>(),
			screenshot,
			gameId,
		};

	private static System.Collections.Generic.Dictionary<string, byte[]> ReadZip(string path)
	{
		using var stream = File.OpenRead(path);
		using var zip = new ZipArchive(stream, ZipArchiveMode.Read);
		var entries = new System.Collections.Generic.Dictionary<string, byte[]>(StringComparer.Ordinal);
		foreach (var entry in zip.Entries)
		{
			using var entryStream = entry.Open();
			using var copy = new MemoryStream();
			entryStream.CopyTo(copy);
			entries.Add(entry.FullName, copy.ToArray());
		}
		return entries;
	}

	private static string CreateRoot() => Path.Combine(Path.GetTempPath(), "oe-report-package-fixture-" + Guid.NewGuid().ToString("N"));

	private static void DeleteRoot(string root)
	{
		if (Directory.Exists(root))
			Directory.Delete(root, recursive: true);
	}

	private static string Sha256(byte[] bytes)
	{
		using var sha = System.Security.Cryptography.SHA256.Create();
		return Convert.ToHexString(sha.ComputeHash(bytes));
	}

	private static async Task Test(string name, Func<Task> test)
	{
		try
		{
			await test();
			_passed++;
			Console.WriteLine("PASS redirect: " + name);
		}
		catch (Exception ex)
		{
			_failed++;
			Console.Error.WriteLine("FAIL redirect: " + name + ": " + ex.Message);
		}
	}

	private static void Assert(bool condition, string message)
	{
		if (!condition)
			throw new InvalidOperationException(message);
	}

	private static void AssertThrows<T>(Action action, string message) where T : Exception
	{
		try { action(); }
		catch (T) { return; }
		throw new InvalidOperationException(message);
	}

	private static async Task AssertThrowsAsync<T>(Task task, string message) where T : Exception
	{
		try { await task; }
		catch (T) { return; }
		throw new InvalidOperationException(message);
	}
}
