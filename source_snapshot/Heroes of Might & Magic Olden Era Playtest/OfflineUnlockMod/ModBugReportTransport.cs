using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace OfflineUnlockMod;

internal static class ModBugReportTransport
{
	internal const int MaxBundleBytes = 8 * 1024 * 1024;
	internal const int MaxResponseBytes = 64 * 1024;
	internal static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(60);
	// Upload allowance on top of RequestTimeout for slow links, capped so a stalled upload still ends.
	internal const int UploadBytesPerSecond = 50 * 1024;
	internal static readonly TimeSpan MaxRequestTimeout = TimeSpan.FromSeconds(300);
	// Envelope v2 shared filter token, mirrored by the receiver's PRODUCT_CLIENT_TOKEN and probe.py.
	// It ships in every public build, so it only filters drive-by scanners; it is not authentication.
	internal const string ClientToken = "golden-era-mod-report-1";
	internal const int EnvelopeVersion = 2;

	private const int MaxRequestBytes = 12 * 1024 * 1024;
	private const string Purpose = "player-report";
	private const string AppsScriptHost = "script.google.com";
	private const string ContentHost = "script.googleusercontent.com";
	private static readonly Regex EndpointPattern = new(
		@"\Ahttps://script\.google\.com/macros/s/[A-Za-z0-9_-]{10,200}/exec\z",
		RegexOptions.CultureInvariant | RegexOptions.Compiled);
	private static readonly Regex ErrorCodePattern = new(
		@"\A[a-z][a-z0-9_]{0,63}\z",
		RegexOptions.CultureInvariant | RegexOptions.Compiled);
	private static readonly JsonDocumentOptions ResponseJsonOptions = new()
	{
		AllowTrailingCommas = false,
		CommentHandling = JsonCommentHandling.Disallow,
		MaxDepth = 4,
	};

	internal sealed class ReportReceipt
	{
		internal bool Acknowledged { get; }
		internal string ReportId { get; }
		internal string Error { get; }
		internal bool Duplicate { get; }

		internal ReportReceipt(bool acknowledged, string reportId, string error, bool duplicate)
		{
			Acknowledged = acknowledged;
			ReportId = reportId;
			Error = error;
			Duplicate = duplicate;
		}
	}

	internal static Task<ReportReceipt> SubmitAsync(
		string endpoint,
		string reportId,
		byte[] zip,
		CancellationToken cancellationToken = default)
	{
		HttpMessageHandler handler;
		try
		{
			handler = new HttpClientHandler
			{
				AllowAutoRedirect = false,
				UseCookies = false,
				UseDefaultCredentials = false,
				PreAuthenticate = false,
			};
		}
		catch
		{
			return Task.FromResult(Failed(reportId, "transport_unconfirmed"));
		}

		return SubmitAsync(endpoint, reportId, zip, handler, TimeoutFor(EstimatedRequestBytes(zip)), cancellationToken);
	}

	/// <summary>60 s plus the upload time at 50 KiB/s for the request body, capped at 300 s.</summary>
	internal static TimeSpan TimeoutFor(long requestBytes)
	{
		var seconds = RequestTimeout.TotalSeconds + Math.Max(0L, requestBytes) / (double)UploadBytesPerSecond;
		return TimeSpan.FromSeconds(Math.Min(seconds, MaxRequestTimeout.TotalSeconds));
	}

	// Base64 body plus a fixed allowance for the JSON envelope fields.
	internal static long EstimatedRequestBytes(byte[] zip)
		=> zip == null ? 0 : (zip.LongLength + 2) / 3 * 4 + 512;

	// Handler ownership transfers to this method. The timeout overload is for deterministic offline fixtures.
	internal static Task<ReportReceipt> SubmitAsync(
		string endpoint,
		string reportId,
		byte[] zip,
		HttpMessageHandler handler,
		CancellationToken cancellationToken = default)
		=> SubmitAsync(endpoint, reportId, zip, handler, TimeoutFor(EstimatedRequestBytes(zip)), cancellationToken);

	internal static async Task<ReportReceipt> SubmitAsync(
		string endpoint,
		string reportId,
		byte[] zip,
		HttpMessageHandler handler,
		TimeSpan overallTimeout,
		CancellationToken cancellationToken = default)
	{
		if (handler == null)
			return Failed(reportId, "invalid_transport");

		using (handler)
		using (var client = new HttpClient(handler, disposeHandler: false) { Timeout = Timeout.InfiniteTimeSpan })
		{
			if (!IsEndpoint(endpoint))
				return Failed(reportId, "invalid_endpoint");
			if (!IsLowercaseGuid(reportId))
				return Failed(reportId, "invalid_report_id");
			if (zip == null || zip.Length < 4 || !HasZipLocalHeader(zip))
				return Failed(reportId, "invalid_zip");
			if (zip.Length > MaxBundleBytes)
				return Failed(reportId, "bundle_too_large");
			if (overallTimeout <= TimeSpan.Zero)
				return Failed(reportId, "invalid_timeout");

			var sha256 = Sha256(zip);
			var requestBody = JsonSerializer.SerializeToUtf8Bytes(new RelayRequest
			{
				Version = EnvelopeVersion,
				Purpose = Purpose,
				ReportId = reportId,
				ClientToken = ClientToken,
				Sha256 = sha256,
				BundleBase64 = Convert.ToBase64String(zip),
			});
			if (requestBody.Length > MaxRequestBytes)
				return Failed(reportId, "request_too_large");

			using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken))
			{
				timeout.CancelAfter(overallTimeout);
				try
				{
					using (var request = new HttpRequestMessage(HttpMethod.Post, endpoint))
					{
						request.Content = new ByteArrayContent(requestBody);
						request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
						using (var response = await client.SendAsync(
							request,
						HttpCompletionOption.ResponseHeadersRead,
						 timeout.Token).ConfigureAwait(false))
						{
							if (IsContentRedirect(response.StatusCode))
							{
								if (!TryGetAllowedContentLocation(response, out var contentUri))
									return Failed(reportId, "redirect_unconfirmed");

								using (var follow = new HttpRequestMessage(HttpMethod.Get, contentUri))
								using (var final = await client.SendAsync(
									follow,
									HttpCompletionOption.ResponseHeadersRead,
									timeout.Token).ConfigureAwait(false))
								{
									return await ReadReceiptAsync(final, reportId, sha256, timeout.Token).ConfigureAwait(false);
								}
							}

							return await ReadReceiptAsync(response, reportId, sha256, timeout.Token).ConfigureAwait(false);
						}
					}
				}
				catch (OperationCanceledException)
				{
					return Failed(reportId, cancellationToken.IsCancellationRequested
						? "cancelled_unconfirmed"
						: "timeout_unconfirmed");
				}
				catch (Exception)
				{
					return Failed(reportId, "transport_unconfirmed");
				}
			}
		}
	}

	private static async Task<ReportReceipt> ReadReceiptAsync(
		HttpResponseMessage response,
		string reportId,
		string expectedSha256,
		CancellationToken cancellationToken)
	{
		if (response.StatusCode != HttpStatusCode.OK)
			return Failed(reportId, "http_status_unconfirmed");
		if (!string.Equals(response.Content?.Headers.ContentType?.MediaType, "application/json", StringComparison.OrdinalIgnoreCase))
			return Failed(reportId, "content_type_unconfirmed");
		if (response.Content.Headers.ContentLength > MaxResponseBytes)
			return Failed(reportId, "response_too_large_unconfirmed");

		var bytes = await ReadBoundedAsync(response.Content, cancellationToken).ConfigureAwait(false);
		if (bytes == null)
			return Failed(reportId, "response_too_large_unconfirmed");

		try
		{
			using (var document = JsonDocument.Parse(bytes, ResponseJsonOptions))
			{
				if (TryReadRefusal(document.RootElement, out var refused))
					return Failed(reportId, "receiver_refused:" + refused);
				if (!TryReadReceipt(document.RootElement, reportId, expectedSha256, out var duplicate))
					return Failed(reportId, "ack_mismatch_unconfirmed");
				return new ReportReceipt(true, reportId, null, duplicate);
			}
		}
		catch (JsonException)
		{
			return Failed(reportId, "invalid_ack_unconfirmed");
		}
	}

	private static async Task<byte[]> ReadBoundedAsync(HttpContent content, CancellationToken cancellationToken)
	{
		if (content == null)
			return null;

		using (var stream = await content.ReadAsStreamAsync().ConfigureAwait(false))
		using (var buffer = new MemoryStream())
		{
			var chunk = new byte[8192];
			while (true)
			{
				var read = await stream.ReadAsync(chunk, 0, chunk.Length, cancellationToken).ConfigureAwait(false);
				if (read == 0)
					return buffer.ToArray();
				if (buffer.Length + read > MaxResponseBytes)
					return null;
				buffer.Write(chunk, 0, read);
			}
		}
	}

	private static bool TryReadReceipt(JsonElement root, string reportId, string sha256, out bool duplicate)
	{
		duplicate = false;
		if (!HasExactProperties(root, "ok", "reportId", "sha256", "duplicate"))
			return false;
		if (!root.TryGetProperty("ok", out var ok) || ok.ValueKind != JsonValueKind.True)
			return false;
		if (!root.TryGetProperty("reportId", out var id) || id.ValueKind != JsonValueKind.String
			|| !string.Equals(id.GetString(), reportId, StringComparison.Ordinal))
			return false;
		if (!root.TryGetProperty("sha256", out var digest) || digest.ValueKind != JsonValueKind.String
			|| !string.Equals(digest.GetString(), sha256, StringComparison.Ordinal))
			return false;
		if (!root.TryGetProperty("duplicate", out var duplicateElement)
			|| duplicateElement.ValueKind != JsonValueKind.True && duplicateElement.ValueKind != JsonValueKind.False)
			return false;
		duplicate = duplicateElement.GetBoolean();
		return true;
	}

	private static bool TryReadRefusal(JsonElement root, out string code)
	{
		code = null;
		if (!HasExactProperties(root, "ok", "error")
			|| !root.TryGetProperty("ok", out var ok)
			|| ok.ValueKind != JsonValueKind.False
			|| !root.TryGetProperty("error", out var error)
			|| error.ValueKind != JsonValueKind.String)
			return false;

		var value = error.GetString();
		if (string.IsNullOrEmpty(value) || !ErrorCodePattern.IsMatch(value))
			return false;
		code = value;
		return true;
	}

	private static bool HasExactProperties(JsonElement root, params string[] expected)
	{
		if (root.ValueKind != JsonValueKind.Object)
			return false;
		var seen = 0;
		foreach (var property in root.EnumerateObject())
		{
			var found = false;
			foreach (var name in expected)
			{
				if (!string.Equals(property.Name, name, StringComparison.Ordinal))
					continue;
				found = true;
				break;
			}
			if (!found || ++seen > expected.Length)
				return false;
		}
		return seen == expected.Length;
	}

	private static bool IsContentRedirect(HttpStatusCode status)
		=> status == HttpStatusCode.MovedPermanently || status == HttpStatusCode.Redirect || status == HttpStatusCode.SeeOther;

	private static bool TryGetAllowedContentLocation(HttpResponseMessage response, out Uri uri)
	{
		uri = null;
		var location = response.Headers.Location;
		if (location == null || !location.IsAbsoluteUri
			|| !string.Equals(location.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase)
			|| !string.Equals(location.Host, ContentHost, StringComparison.OrdinalIgnoreCase)
			|| location.Port != 443
			|| !string.IsNullOrEmpty(location.UserInfo)
			|| !string.IsNullOrEmpty(location.Fragment))
			return false;
		uri = location;
		return true;
	}

	internal static bool IsEndpoint(string endpoint)
		=> !string.IsNullOrEmpty(endpoint) && EndpointPattern.IsMatch(endpoint);

	private static bool IsLowercaseGuid(string reportId)
		=> Guid.TryParseExact(reportId, "D", out var parsed)
			&& string.Equals(parsed.ToString("D"), reportId, StringComparison.Ordinal);

	private static bool HasZipLocalHeader(byte[] zip)
		=> zip[0] == (byte)'P' && zip[1] == (byte)'K' && zip[2] == 0x03 && zip[3] == 0x04;

	private static string Sha256(byte[] bytes)
	{
		using (var sha = SHA256.Create())
		{
			var digest = sha.ComputeHash(bytes);
			var result = new char[digest.Length * 2];
			const string hex = "0123456789abcdef";
			for (var i = 0; i < digest.Length; i++)
			{
				result[i * 2] = hex[digest[i] >> 4];
				result[i * 2 + 1] = hex[digest[i] & 0x0f];
			}
			return new string(result);
		}
	}

	private static ReportReceipt Failed(string reportId, string error)
		=> new(false, reportId, error, false);

	private sealed class RelayRequest
	{
		[JsonPropertyName("version")]
		public int Version { get; set; }

		[JsonPropertyName("purpose")]
		public string Purpose { get; set; }

		[JsonPropertyName("reportId")]
		public string ReportId { get; set; }

		[JsonPropertyName("clientToken")]
		public string ClientToken { get; set; }

		[JsonPropertyName("sha256")]
		public string Sha256 { get; set; }

		[JsonPropertyName("bundleBase64")]
		public string BundleBase64 { get; set; }
	}
}
