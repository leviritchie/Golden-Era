using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using OfflineUnlockMod;

internal static class Program
{
	private const string Endpoint = "https://script.google.com/macros/s/AbCdEf0123456789_abcd-ef/exec";
	private const string ReportId = "c6a74b13-76df-4833-a937-814bb198ec43";
	private const string ContentHost = "https://script.googleusercontent.com/macros/echo?user_content_key=fixture";
	private static readonly byte[] Zip = { 0x50, 0x4b, 0x03, 0x04, 0x01, 0x02, 0x03, 0x04 };
	private static int _passed;
	private static int _failed;

	private static async Task<int> Main(string[] args)
	{
		if (args.Length > 0)
			return await SubmitSynthetic(args);

		var fixtureTimer = Stopwatch.StartNew();
		await Run("synthetic archive is fixed and data-free", SyntheticArchiveIsFixedAndDataFree);
		await Run("request schema and success", RequestSchemaAndSuccess);
		await Run("unexpected acknowledgement property rejected", ExtraAcknowledgementPropertyRejected);
		await Run("duplicate acknowledgement", DuplicateAcknowledgement);
		await Run("receiver refusal", ReceiverRefusal);
		await Run("receiver error code trailing newline rejected", ReceiverErrorCodeTrailingNewlineRejected);
		await Run("acknowledgement report id mismatch", ReportIdMismatch);
		await Run("acknowledgement hash mismatch", HashMismatch);
		await Run("HTTP status rejected", HttpStatusRejected);
		await Run("content type rejected", ContentTypeRejected);
		await Run("oversized response rejected", OversizedResponseRejected);
		await Run("oversized streamed response without length rejected", OversizedStreamWithoutLengthRejected);
		await Run("allowed content redirect drops POST body", AllowedContentRedirect);
		await Run("redirect spoof rejected", RedirectSpoofRejected);
		await Run("redirect with credentials rejected", RedirectCredentialsRejected);
		await Run("timeout is unconfirmed and not retried", TimeoutIsUnconfirmed);
		await Run("invalid endpoints are rejected before network", InvalidEndpoints);
		await Run("invalid report and ZIP are rejected before network", InvalidInput);
		await Run("oversized bundle is rejected before network", OversizedBundle);
		await Run("upload timeout scales with request size and is capped", UploadTimeoutScales);
		await Run("synthetic archive satisfies the shared receiver bundle contract", SyntheticArchiveMatchesContract);
		var packageFailures = await PackageTests.Run();

		Console.WriteLine($"client fixtures: {_passed} passed, {_failed} failed");
		fixtureTimer.Stop();
		Console.WriteLine("offline fixture elapsedMs=" + fixtureTimer.ElapsedMilliseconds + " peakWorkingSetBytes=" + Process.GetCurrentProcess().PeakWorkingSet64);
		return _failed + packageFailures == 0 ? 0 : 1;
	}

	private static async Task<int> SubmitSynthetic(string[] args)
	{
		if ((args.Length != 3 && args.Length != 5)
			|| args[0] != "--submit-synthetic"
			|| args[1] != "--endpoint"
			|| args.Length == 5 && args[3] != "--report-id")
		{
			Console.Error.WriteLine("usage: --submit-synthetic --endpoint <Apps Script deployment URL> [--report-id <lowercase UUID>]");
			return 64;
		}

		var endpoint = args[2];
		var reportId = args.Length == 5 ? args[4] : Guid.NewGuid().ToString("D");
		var zip = BuildSyntheticZip(reportId);
		var sha256 = Sha256(zip);
		var timer = Stopwatch.StartNew();
		var receipt = await ModBugReportTransport.SubmitAsync(endpoint, reportId, zip);
		timer.Stop();
		Console.WriteLine(
			"synthetic-submission reportId=" + reportId
			+ " sha256=" + sha256
			+ " bytes=" + zip.Length
			+ " acknowledged=" + receipt.Acknowledged.ToString().ToLowerInvariant()
			+ " duplicate=" + receipt.Duplicate.ToString().ToLowerInvariant()
			+ " error=" + (receipt.Error ?? "none")
			+ " elapsedMs=" + timer.ElapsedMilliseconds);
		return receipt.Acknowledged ? 0 : 2;
	}

	private static Task UploadTimeoutScales()
	{
		Assert(ModBugReportTransport.TimeoutFor(0) == TimeSpan.FromSeconds(60), "base timeout");
		Assert(ModBugReportTransport.TimeoutFor(50 * 1024 * 30) == TimeSpan.FromSeconds(90), "50 KiB/s allowance");
		Assert(ModBugReportTransport.TimeoutFor(64L * 1024 * 1024) == TimeSpan.FromSeconds(300), "300 s cap");
		var largest = ModBugReportTransport.TimeoutFor(ModBugReportTransport.EstimatedRequestBytes(new byte[ModBugReportTransport.MaxBundleBytes]));
		Assert(largest > TimeSpan.FromSeconds(240) && largest <= TimeSpan.FromSeconds(300), "8 MiB bundle allowance");
		return Task.CompletedTask;
	}

	private static Task SyntheticArchiveMatchesContract()
	{
		var contract = PackageTests.LoadBundleContract();
		var zip = BuildSyntheticZip(ReportId);
		PackageTests.AssertContractBundle(contract, zip, ReportId, "synthetic");
		return Task.CompletedTask;
	}

	private static Task SyntheticArchiveIsFixedAndDataFree()
	{
		var first = BuildSyntheticZip(ReportId);
		var second = BuildSyntheticZip(ReportId);
		Assert(first.AsSpan().SequenceEqual(second), "stable bytes for repeat-id testing");
		using var stream = new MemoryStream(first, writable: false);
		using var archive = new ZipArchive(stream, ZipArchiveMode.Read);
		Assert(archive.Entries.Count == 5, "synthetic entries");
		foreach (var entry in archive.Entries)
			Assert(entry.LastWriteTime.DateTime == new DateTime(1980, 1, 1, 0, 0, 0), "fixed ZIP timestamp");
		Assert(archive.GetEntry("screenshot.png") != null, "synthetic screenshot entry");
		Assert(archive.GetEntry("bepinex_log_tail.txt") != null, "synthetic log entry");
		return Task.CompletedTask;
	}

	// Synthetic, contract-shaped bundle: the player route inspects entries and report.json against the request ID.
	private static byte[] BuildSyntheticZip(string reportId)
	{
		using var stream = new MemoryStream();
		using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: true))
		{
			AddSyntheticEntry(archive, "report.json", Encoding.UTF8.GetBytes(
				"{\"schema\":\"oe_mod_bug_report.v3\",\"createdUtc\":\"2026-01-01T00:00:00.0000000Z\",\"reportId\":\"" + reportId + "\","
				+ "\"source\":\"native_form\",\"reportHash\":\"" + new string('0', 64) + "\",\"pluginVersion\":\"synthetic\","
				+ "\"title\":\"Synthetic relay test\",\"description\":\"Fixed test fixture; contains no player data.\","
				+ "\"category\":\"synthetic\",\"tag\":\"synthetic\",\"gameId\":\"synthetic\",\"contactProvided\":\"false\","
				+ "\"os\":\"synthetic\",\"nativeAttachmentsOmitted\":\"none\",\"screenshot\":\"included\","
				+ "\"limits\":\"synthetic\",\"scrubbing\":\"synthetic\"}\n"));
			AddSyntheticEntry(archive, "bepinex_log_tail.txt", Encoding.UTF8.GetBytes("SYNTHETIC fixture log; no machine or player data.\n"));
			AddSyntheticEntry(archive, "native_log.txt", Encoding.UTF8.GetBytes("SYNTHETIC native log entry.\n"));
			AddSyntheticEntry(archive, "payload_manifest.json", Encoding.UTF8.GetBytes("{\"source\":\"synthetic_fixture\"}\n"));
			AddSyntheticEntry(
				archive,
				"screenshot.png",
				Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Qz8AAAAASUVORK5CYII="));
		}
		return stream.ToArray();
	}

	private static void AddSyntheticEntry(ZipArchive archive, string name, byte[] bytes)
	{
		var entry = archive.CreateEntry(name, CompressionLevel.Optimal);
		entry.LastWriteTime = new DateTimeOffset(1980, 1, 1, 0, 0, 0, TimeSpan.Zero);
		using var output = entry.Open();
		output.Write(bytes, 0, bytes.Length);
	}

	private static async Task RequestSchemaAndSuccess()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, SuccessJson(ReportId, Sha256(Zip), false))));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(result.Acknowledged && !result.Duplicate && result.ReportId == ReportId && result.Error == null, "success receipt");
		Assert(handler.Requests.Count == 1, "one POST");
		var request = handler.Requests[0];
		Assert(request.Method == "POST" && request.Uri == Endpoint, "POST URL");
		Assert(request.Authorization == null && request.Cookie == null, "no auth or cookies");
		using var document = JsonDocument.Parse(request.Body);
		var root = document.RootElement;
		AssertPropertyNames(root, "version", "purpose", "reportId", "clientToken", "sha256", "bundleBase64");
		Assert(root.GetProperty("version").GetInt32() == 2, "version");
		Assert(root.GetProperty("clientToken").GetString() == ModBugReportTransport.ClientToken, "shared filter token");
		Assert(root.GetProperty("purpose").GetString() == "player-report", "purpose");
		Assert(root.GetProperty("reportId").GetString() == ReportId, "request id");
		Assert(root.GetProperty("sha256").GetString() == Sha256(Zip), "exact ZIP SHA-256");
		Assert(Convert.FromBase64String(root.GetProperty("bundleBase64").GetString()).AsSpan().SequenceEqual(Zip), "exact ZIP bytes");
	}

	private static async Task DuplicateAcknowledgement()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, SuccessJson(ReportId, Sha256(Zip), true))));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(result.Acknowledged && result.Duplicate, "duplicate acknowledgement accepted");
	}

	private static async Task ExtraAcknowledgementPropertyRejected()
	{
		var json = SuccessJson(ReportId, Sha256(Zip), false);
		json = json.Substring(0, json.Length - 1) + ",\"extra\":\"ignored\"}";
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, json)));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "ack_mismatch_unconfirmed", "extra acknowledgement data is rejected");
	}

	private static async Task ReceiverRefusal()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, "{\"ok\":false,\"error\":\"disabled\"}")));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "receiver_refused:disabled", "refusal not acknowledged");
	}

	private static async Task ReceiverErrorCodeTrailingNewlineRejected()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, "{\"ok\":false,\"error\":\"disabled\\n\"}")));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "ack_mismatch_unconfirmed", "error code is not accepted with trailing newline");
	}

	private static async Task ReportIdMismatch()
	{
		var wrongId = "8324303a-aea5-4aa4-8c02-32045bb5e37c";
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, SuccessJson(wrongId, Sha256(Zip), false))));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "ack_mismatch_unconfirmed", "mismatched id is not acknowledged");
	}

	private static async Task HashMismatch()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.OK, SuccessJson(ReportId, new string('0', 64), false))));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "ack_mismatch_unconfirmed", "mismatched hash is not acknowledged");
	}

	private static async Task HttpStatusRejected()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(JsonResponse(HttpStatusCode.InternalServerError, SuccessJson(ReportId, Sha256(Zip), false))));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "http_status_unconfirmed", "HTTP non-200 is unconfirmed");
	}

	private static async Task ContentTypeRejected()
	{
		var handler = new QueueHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
		{
			Content = new StringContent(SuccessJson(ReportId, Sha256(Zip)), Encoding.UTF8, "text/plain"),
		}));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "content_type_unconfirmed", "non-JSON content is not acknowledged");
	}

	private static async Task OversizedResponseRejected()
	{
		var content = new ByteArrayContent(new byte[ModBugReportTransport.MaxResponseBytes + 1]);
		content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
		var handler = new QueueHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content }));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "response_too_large_unconfirmed", "oversized response refused");
	}

	private static async Task OversizedStreamWithoutLengthRejected()
	{
		var content = new StreamContent(new RepeatingStream(ModBugReportTransport.MaxResponseBytes + 1));
		content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
		Assert(content.Headers.ContentLength == null, "fixture has no Content-Length");
		var handler = new QueueHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content }));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "response_too_large_unconfirmed", "stream cap enforced without a length header");
	}

	private static async Task AllowedContentRedirect()
	{
		var handler = new QueueHandler((request, index) =>
		{
			if (index == 0)
			{
				var redirect = new HttpResponseMessage(HttpStatusCode.SeeOther);
				redirect.Headers.Location = new Uri(ContentHost);
				return Task.FromResult(redirect);
			}
			return Task.FromResult(JsonResponse(HttpStatusCode.OK, SuccessJson(ReportId, Sha256(Zip), false)));
		});
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(result.Acknowledged, "redirected response acknowledged");
		Assert(handler.Requests.Count == 2, "exactly one redirect GET");
		Assert(handler.Requests[0].Method == "POST" && handler.Requests[1].Method == "GET", "POST converted to GET");
		Assert(handler.Requests[1].Body.Length == 0 && handler.Requests[1].Uri == ContentHost, "redirect drops POST body");
		Assert(handler.Requests[1].Authorization == null && handler.Requests[1].Cookie == null, "redirect has no credentials");
	}

	private static async Task RedirectSpoofRejected()
	{
		var handler = new QueueHandler((_, _) =>
		{
			var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
			redirect.Headers.Location = new Uri("https://script.googleusercontent.com.attacker.invalid/macros/echo");
			return Task.FromResult(redirect);
		});
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "redirect_unconfirmed", "spoofed host is rejected");
		Assert(handler.Requests.Count == 1, "no request to spoofed host");
	}

	private static async Task RedirectCredentialsRejected()
	{
		var handler = new QueueHandler((_, _) =>
		{
			var redirect = new HttpResponseMessage(HttpStatusCode.MovedPermanently);
			redirect.Headers.Location = new Uri("https://<email>/macros/echo");
			return Task.FromResult(redirect);
		});
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, Zip, handler);
		Assert(!result.Acknowledged && result.Error == "redirect_unconfirmed", "userinfo redirect is rejected");
		Assert(handler.Requests.Count == 1, "credential redirect not followed");
	}

	private static async Task TimeoutIsUnconfirmed()
	{
		var handler = new QueueHandler(async (_, _, token) =>
		{
			await Task.Delay(Timeout.Infinite, token);
			return JsonResponse(HttpStatusCode.OK, SuccessJson(ReportId, Sha256(Zip), false));
		});
		var result = await ModBugReportTransport.SubmitAsync(
			Endpoint,
			ReportId,
			Zip,
			handler,
			TimeSpan.FromMilliseconds(40));
		Assert(!result.Acknowledged && result.Error == "timeout_unconfirmed", "timeout is not a failed-upload claim");
		Assert(handler.Requests.Count == 1, "no retry after timeout");
	}

	private static async Task InvalidEndpoints()
	{
		var invalid = new[]
		{
			"http://script.google.com/macros/s/AbCdEf0123456789_abcd-ef/exec",
			"https://<email>/macros/s/AbCdEf0123456789_abcd-ef/exec",
			"https://script.google.com:444/macros/s/AbCdEf0123456789_abcd-ef/exec",
			Endpoint + "?x=1",
			Endpoint + "#fragment",
			Endpoint + "\n",
			Endpoint + "\r\n",
			"https://script.google.com.evil.invalid/macros/s/AbCdEf0123456789_abcd-ef/exec",
		};
		foreach (var endpoint in invalid)
		{
			var handler = new QueueHandler((_, _) => throw new InvalidOperationException("must not send"));
			var result = await ModBugReportTransport.SubmitAsync(endpoint, ReportId, Zip, handler);
			Assert(!result.Acknowledged && result.Error == "invalid_endpoint", "invalid endpoint rejected");
			Assert(handler.Requests.Count == 0, "invalid endpoint made no request");
		}
	}

	private static async Task InvalidInput()
	{
		var badIdHandler = new QueueHandler((_, _) => throw new InvalidOperationException("must not send"));
		var badId = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId.ToUpperInvariant(), Zip, badIdHandler);
		Assert(!badId.Acknowledged && badId.Error == "invalid_report_id" && badIdHandler.Requests.Count == 0, "uppercase id rejected");

		var badZipHandler = new QueueHandler((_, _) => throw new InvalidOperationException("must not send"));
		var badZip = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, new byte[] { 1, 2, 3, 4 }, badZipHandler);
		Assert(!badZip.Acknowledged && badZip.Error == "invalid_zip" && badZipHandler.Requests.Count == 0, "invalid ZIP signature rejected");
	}

	private static async Task OversizedBundle()
	{
		var bytes = new byte[ModBugReportTransport.MaxBundleBytes + 1];
		bytes[0] = 0x50;
		bytes[1] = 0x4b;
		bytes[2] = 0x03;
		bytes[3] = 0x04;
		var handler = new QueueHandler((_, _) => throw new InvalidOperationException("must not send"));
		var result = await ModBugReportTransport.SubmitAsync(Endpoint, ReportId, bytes, handler);
		Assert(!result.Acknowledged && result.Error == "bundle_too_large" && handler.Requests.Count == 0, "oversized ZIP rejected before encoding");
	}

	private static HttpResponseMessage JsonResponse(HttpStatusCode status, string json)
		=> new(status) { Content = new StringContent(json, Encoding.UTF8, "application/json") };

	private static string SuccessJson(string reportId, string sha256, bool duplicate = false)
		=> "{\"ok\":true,\"reportId\":\"" + reportId + "\",\"sha256\":\"" + sha256 + "\",\"duplicate\":"
			+ duplicate.ToString().ToLowerInvariant() + "}";

	private static string Sha256(byte[] bytes)
	{
		using var sha = SHA256.Create();
		var digest = sha.ComputeHash(bytes);
		var result = new StringBuilder(digest.Length * 2);
		foreach (var value in digest)
			result.Append(value.ToString("x2"));
		return result.ToString();
	}

	private static void AssertPropertyNames(JsonElement element, params string[] expected)
	{
		Assert(element.ValueKind == JsonValueKind.Object, "request is a JSON object");
		var names = new List<string>();
		foreach (var property in element.EnumerateObject())
			names.Add(property.Name);
		Assert(names.Count == expected.Length, "exact request property count");
		for (var i = 0; i < expected.Length; i++)
			Assert(names[i] == expected[i], "request property " + expected[i]);
	}

	private static void Assert(bool condition, string message)
	{
		if (!condition)
			throw new InvalidOperationException(message);
	}

	private static async Task Run(string name, Func<Task> test)
	{
		try
		{
			await test();
			_passed++;
			Console.WriteLine("PASS " + name);
		}
		catch (Exception ex)
		{
			_failed++;
			Console.Error.WriteLine("FAIL " + name + ": " + ex.Message);
		}
	}

	private sealed class QueueHandler : HttpMessageHandler
	{
		private readonly Func<HttpRequestMessage, int, CancellationToken, Task<HttpResponseMessage>> _respond;
		internal readonly List<SeenRequest> Requests = new();

		internal QueueHandler(Func<HttpRequestMessage, int, Task<HttpResponseMessage>> respond)
			: this((request, index, _) => respond(request, index))
		{
		}

		internal QueueHandler(Func<HttpRequestMessage, int, CancellationToken, Task<HttpResponseMessage>> respond)
		{
			_respond = respond;
		}

		protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
		{
			var body = request.Content == null ? Array.Empty<byte>() : await request.Content.ReadAsByteArrayAsync(cancellationToken);
			Requests.Add(new SeenRequest(
				request.Method.Method,
				request.RequestUri.AbsoluteUri,
				request.Headers.Authorization?.ToString(),
				request.Headers.Contains("Cookie") ? string.Join(";", request.Headers.GetValues("Cookie")) : null,
				body));
			return await _respond(request, Requests.Count - 1, cancellationToken);
		}
	}

	private sealed class SeenRequest
	{
		internal string Method { get; }
		internal string Uri { get; }
		internal string Authorization { get; }
		internal string Cookie { get; }
		internal byte[] Body { get; }

		internal SeenRequest(string method, string uri, string authorization, string cookie, byte[] body)
		{
			Method = method;
			Uri = uri;
			Authorization = authorization;
			Cookie = cookie;
			Body = body;
		}
	}

	private sealed class RepeatingStream : Stream
	{
		private int _remaining;

		internal RepeatingStream(int length) => _remaining = length;
		public override bool CanRead => true;
		public override bool CanSeek => false;
		public override bool CanWrite => false;
		public override long Length => throw new NotSupportedException();
		public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
		public override void Flush() { }
		public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
		public override void SetLength(long value) => throw new NotSupportedException();
		public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

		public override int Read(byte[] buffer, int offset, int count)
		{
			var read = Math.Min(count, _remaining);
			Array.Clear(buffer, offset, read);
			_remaining -= read;
			return read;
		}

		public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken)
		{
			cancellationToken.ThrowIfCancellationRequested();
			return Task.FromResult(Read(buffer, offset, count));
		}
	}
}
