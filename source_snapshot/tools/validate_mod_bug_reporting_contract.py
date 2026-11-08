#!/usr/bin/env python3
"""Source/static and offline-fixture gate for Google-backed mod bug-report submission.

Checks the consent-gated native workflow, bounded managed capture/transport, configured Google endpoint,
separate bounded synthetic-pilot and player-report Apps Script routes, and the fail-closed native telemetry
block. Fixtures stay bounded and offline; they do not read player reports or contact Google.

Proof tier: source/static plus offline fixtures. This does not prove Google deployment or acceptance state,
live game behavior, or user-visible submission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"

FORBIDDEN_ENDPOINT_TOKENS = (
    "unfrozen",
    "forms.gle",
    "hex.unfrozen",
    "an.prod",
    "api.prod",
)
FORBIDDEN_BROWSER_TOKENS = (
    "Process.Start",
    "Application.OpenURL",
    "OpenBrowserURL",
    "DefaultRequestHeaders.Authorization",
    "CredentialCache",
    "NetworkCredential",
    "CookieContainer",
)
# Game names that must come from GameSymbols.ModBugReporting, never from the redirect itself.
FORBIDDEN_DIRECT_SYMBOLS = (
    "HexAnalytics",
    "BhBugReportScreen",
    "Hex.UI.Reports",
    "Hex.SharedLibrary",
    '"SendReport"',
    '"Method_Private_Void_PDM_0"',
    '"vbc"',
    '"NativeMethodInfoPtr_Method_Private_Void_PDM_0"',
    '"Hex.UI.Reports.BhBugReportScreen+cul"',
    '"NativeFieldInfoPtr_field_Private_Int32_0"',
    '"NativeFieldInfoPtr_field_Public_BhBugReportScreen_0"',
    '"NativeFieldInfoPtr_field_Private_String_0"',
    '"NativeFieldInfoPtr_field_Private_String_1"',
    '"NativeFieldInfoPtr_field_Private_String_2"',
    '"NativeFieldInfoPtr_field_Private_String_3"',
    '"NativeFieldInfoPtr_field_Private_String_4"',
    '"NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Byte_0"',
    '"NativeFieldInfoPtr_field_Private_Dictionary_2_String_Il2CppStructArray_1_Byte_0"',
    '"Show"',
    "Method_Public_Static_Void_Boolean_0",
    '"SendGameMetrics"',
    '"SendTable"',
)

# Pinned abuse limits (docs/mod_bug_reporting.md, "Abuse limits"). Change them in the doc and here together.
PINNED_LIMITS = {
    "ReportCooldownSeconds": "120",
    "DailyBundleCap": "10",
    "MaxBundleBytes": "8 * 1024 * 1024",
    "BepInExLogTailBytes": "2 * 1024 * 1024",
    "NativeLogTailBytes": "256 * 1024",
    "ScreenshotMaxBytes": "4 * 1024 * 1024",
}

SHIPPED_REPORT_SETTINGS = {
    "modBugReporting": True,
    "modBugReportingEndpoint": "https://script.google.com/macros/s/<relay-deployment-id>/exec",
    "modBugReportingIncludeScreenshot": False,
    "blockNativeTelemetry": True,
}

GOOGLE_EXEC_ENDPOINT = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec$")


def validate_shipped_settings(settings: object) -> list[str]:
    if not isinstance(settings, dict):
        return ["config.json: shipping settings must be a JSON object"]
    return [
        f"config.json: shipping {key} must be {expected!r}"
        for key, expected in SHIPPED_REPORT_SETTINGS.items()
        if type(settings.get(key)) is not type(expected) or settings.get(key) != expected
    ]


def validate_google_pilot(repo: Path) -> list[str]:
    relay = repo / "tools" / "google_bug_report_relay"
    errors: list[str] = []
    try:
        manifest = json.loads((relay / "appsscript.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return ["Google pilot: Apps Script manifest must be a JSON object"]
        if manifest.get("runtimeVersion") != "V8":
            return ["Google pilot: Apps Script must use the V8 runtime"]
        if manifest.get("webapp") != {"access": "ANYONE_ANONYMOUS", "executeAs": "USER_DEPLOYING"}:
            return ["Google pilot: deployment must use anonymous access and owner execution"]
        if manifest.get("oauthScopes") != [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/script.send_mail",
        ]:
            return ["Google pilot: only the documented Drive, owner-email, and owner-alert mail scopes may be requested"]
        receiver_raw = (relay / "Code.gs").read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [f"Google pilot: cannot read Apps Script manifest/source: {exc}"]

    receiver = strip_comments(receiver_raw)
    for label, required in (
        ("synthetic fixture admission", (
            "purpose: 'synthetic-pilot'",
            "enabledProperty: 'PILOT_ACCEPTANCE_ENABLED'",
            "folderProperty: 'PILOT_PRIVATE_FOLDER_ID'",
            "ownerProperty: 'PILOT_OWNER_EMAIL'",
            "reportPrefix: 'pilot.report.'",
            "'28d8e8f21838f93dad9271c9b38481b053c8da62f7bdef8fb58f3cc27c88dbf5': 756",
            "'f1cbcbb95c1ee9cf5124b17311704000859eaf2e28df15bcb14994a2c04c49dd': 8 * 1024 * 1024",
        )),
        ("player-report route isolation and limits", (
            "purpose: 'player-report'",
            "enabledProperty: 'PRODUCT_ACCEPTANCE_ENABLED'",
            "folderProperty: 'PRODUCT_PRIVATE_FOLDER_ID'",
            "ownerProperty: 'PRODUCT_OWNER_EMAIL'",
            "reportPrefix: 'product.report.'",
            "maxBundleBytes: 8 * 1024 * 1024",
            "maxDailyReports: 40",
            "maxDailyBytes: 160 * 1024 * 1024",
            "tokenProperty: 'PRODUCT_CLIENT_TOKEN'",
            "inspectBundle: true",
            "retentionDays: 90",
            "maxRetainedReports: 1000",
            "maxRetainedBytes: 1024 * 1024 * 1024",
            "syntheticFixtures: null",
        )),
        ("bundle inspection and retention", (
            "schema: 'oe_mod_bug_report.v3'",
            "'report.json': Object.freeze({ required: true, maxBytes: 256 * 1024 })",
            "'bepinex_log_tail.txt': Object.freeze({ required: true, maxBytes: 2304 * 1024 })",
            "'payload_manifest.json': Object.freeze({ required: true, maxBytes: 256 * 1024 })",
            "'screenshot.png': Object.freeze({ required: false, maxBytes: 4 * 1024 * 1024 })",
            "Utilities.unzip(",
            "pilotReadZipDirectory_(bytes)",
            "pilotIsValidReport_(",
            "'invalid_bundle_entries'",
            "'bundle_entry_too_large'",
            "'invalid_report_json'",
            "'client_token_mismatch'",
            "'storage_budget'",
            "function pruneReports()",
            "MailApp.sendEmail(",
            "Session.getEffectiveUser()",
        )),
    ):
        for requirement in required:
            if requirement not in receiver:
                errors.append(f"Google pilot: {label} lost required contract `{requirement}`")

    setup = method_body(receiver, r"function setupPlayerReports\(\)")
    if setup is None or "pilotSetupRelay_(PRODUCT_RELAY_)" not in setup:
        errors.append("Google pilot: product setup must use its own relay properties and folder")
    setup_body = method_body(receiver, r"function pilotSetupRelay_\(relay\)")
    if setup_body is None or "properties.setProperty(relay.enabledProperty, 'false')" not in setup_body:
        errors.append("Google pilot: setup must disable its acceptance gate before verification")
    if setup_body is None or "pilotIsPrivateFolder_(folder)" not in setup_body:
        errors.append("Google pilot: setup must verify the owner-created private folder")
    if setup_body is None or not all(token in setup_body for token in ("Session.getEffectiveUser()", "folderOwnerEmail", "toLowerCase()")):
        errors.append("Google pilot: setup must bind folder ownership to the effective deploying account")
    if "if (relay.syntheticFixtures && relay.syntheticFixtures[digest] !== bytes.length)" not in receiver:
        errors.append("Google pilot: synthetic-pilot purpose must be limited to exact pinned fixture fingerprints")
    for token in (
        "if (purpose === PILOT_RELAY_.purpose) return PILOT_RELAY_;",
        "if (purpose === PRODUCT_RELAY_.purpose) return PRODUCT_RELAY_;",
        "var relay = pilotRelayForPurpose_(envelope.request.purpose);",
    ):
        if token not in receiver:
            errors.append("Google pilot: request purpose must route to only its isolated properties, ledger, and folder")
            break
    if re.search(r"maxLifetime|'lifetime_limit'", receiver):
        errors.append("Google pilot: the lifetime stop was replaced by rotation/retention; it must not return")
    inspect = method_body(receiver, r"function pilotInspectBundle_\(bytes, reportId\)")
    if inspect is None or inspect.find("pilotReadZipDirectory_(bytes)") < 0 or inspect.find("Utilities.unzip(") < 0 \
            or inspect.find("pilotReadZipDirectory_(bytes)") > inspect.find("Utilities.unzip("):
        errors.append("Google pilot: the central directory must be checked against the entry allowlist and caps before Utilities.unzip")
    try:
        contract_file = json.loads((relay / "bundle_contract.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"Google pilot: cannot read shared bundle contract: {exc}")
        contract_file = {}
    if not isinstance(contract_file, dict) or sorted((contract_file.get("entries") or {}).keys()) != sorted((
        "report.json", "bepinex_log_tail.txt", "native_log.txt", "payload_manifest.json", "screenshot.png"
    )):
        errors.append("Google pilot: bundle_contract.json must list exactly the five allowlisted entries")
    token_parse = method_body(receiver, r"function pilotParseRequest_\(request, relay, requiredToken\)")
    if token_parse is None or "(v2 && !relay.tokenProperty)" not in token_parse or "client_token_mismatch" not in token_parse:
        errors.append("Google pilot: envelope v2 client token must be route-scoped and compared when configured")
    if not re.search(r"not (?:real )?(?:security|authentication)", receiver_raw, re.I):
        errors.append("Google pilot: Code.gs header must say the shared client token is not authentication")
    if "pilotIsPrivateFile_(file)" not in receiver or "pilotStopAcceptance_(properties, relay)" not in receiver:
        errors.append("Google pilot: detected storage privacy failure must stop acceptance and withhold acknowledgement")
    if not re.search(r"state:\s*'pending'", receiver) or not re.search(r"state:\s*'committed'", receiver):
        errors.append("Google pilot: admission ledger must preserve pending and committed states")
    if errors:
        return errors

    client_tests = repo / "tools" / "mod_bug_report_client_tests" / "mod_bug_report_client_tests.csproj"
    if not client_tests.is_file():
        return [f"mod report transport: missing offline fixture project {client_tests}"]
    client_program_path = client_tests.parent / "Program.cs"
    package_tests_path = client_tests.parent / "PackageTests.cs"
    try:
        client_program = strip_comments(client_program_path.read_text(encoding="utf-8"))
        package_tests = strip_comments(package_tests_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"mod report transport: cannot read offline fixture sources: {exc}"]
    if "if (args.Length > 0)" not in client_program or "return await SubmitSynthetic(args)" not in client_program:
        errors.append("mod report transport: only non-empty CLI arguments may activate the live synthetic submit path")
    if "await PackageTests.Run()" not in client_program:
        errors.append("mod report transport: offline client run must include the ZIP packaging/retry fixtures")
    if len(re.findall(r"await Run\(", client_program)) < 21:
        errors.append("mod report transport: request/redirect/ACK fixture coverage was reduced")
    if len(re.findall(r"await Test\(", package_tests)) < 10:
        errors.append("mod report transport: capture/package/retained-retry fixture coverage was reduced")
    if errors:
        return errors

    try:
        run = subprocess.run(
            ["node", str(relay / "test_receiver.cjs")],
            cwd=repo, capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"Google pilot: cannot run required receiver fixtures: {exc}"]
    if run.returncode:
        return [f"Google pilot: receiver fixtures failed:\n{(run.stdout + run.stderr)[-6000:]}"]
    receiver_output = run.stdout + run.stderr
    receiver_summary = re.search(r"(?m)^# tests (\d+)\s*$", receiver_output)
    receiver_passed = re.search(r"(?m)^# pass (\d+)\s*$", receiver_output)
    receiver_failed = re.search(r"(?m)^# fail (\d+)\s*$", receiver_output)
    if (
        receiver_summary is None or receiver_passed is None or receiver_failed is None
        or int(receiver_summary.group(1)) < 38
        or int(receiver_passed.group(1)) != int(receiver_summary.group(1))
        or int(receiver_failed.group(1)) != 0
    ):
        return [f"Google pilot: receiver fixture summary missing, reduced, or failed:\n{receiver_output[-6000:]}"]
    try:
        probe_run = subprocess.run(
            [sys.executable, "-B", str(relay / "test_probe.py")],
            cwd=repo, capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"Google pilot: cannot run required offline probe fixtures: {exc}"]
    if probe_run.returncode:
        return [f"Google pilot: offline probe fixtures failed:\n{(probe_run.stdout + probe_run.stderr)[-6000:]}"]
    probe_output = probe_run.stdout + probe_run.stderr
    probe_summary = re.search(r"Ran (\d+) tests? in ", probe_output)
    if probe_summary is None or int(probe_summary.group(1)) < 7 or not re.search(r"(?m)^OK\s*$", probe_output):
        return [f"Google pilot: offline probe fixture summary missing, reduced, or failed:\n{probe_output[-6000:]}"]
    try:
        client_run = subprocess.run(
            ["dotnet", "run", "--project", str(client_tests), "--configuration", "Release",
             "--verbosity", "quiet", "--property:NuGetAudit=false"],
            cwd=repo, capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"mod report transport: cannot run required offline client fixtures: {exc}"]
    if client_run.returncode:
        return [f"mod report transport: offline client fixtures failed:\n{(client_run.stdout + client_run.stderr)[-6000:]}"]
    client_output = client_run.stdout + client_run.stderr
    transport_summary = re.search(r"(?m)^client fixtures: (\d+) passed, (\d+) failed\s*$", client_output)
    package_summary = re.search(r"(?m)^redirect package fixtures: (\d+) passed, (\d+) failed\s*$", client_output)
    if (
        transport_summary is None or package_summary is None
        or int(transport_summary.group(1)) < 21 or int(transport_summary.group(2)) != 0
        or int(package_summary.group(1)) < 10 or int(package_summary.group(2)) != 0
    ):
        return [f"mod report transport: client fixture summary missing, reduced, or failed:\n{client_output[-6000:]}"]
    return []


def method_body(source: str, signature_regex: str) -> str | None:
    match = re.search(signature_regex, source)
    if not match:
        return None
    start = source.find("{", match.end())
    if start < 0:
        return None
    depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char in ("\"", "'", "`"):
            index = skip_string_literal(source, index)
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    return None


def skip_string_literal(text: str, start: int) -> int:
    quote = text[start]
    verbatim = quote == '"' and (
        (start > 0 and text[start - 1] == "@")
        or (start > 1 and text[start - 2 : start] in ("@$", "$@"))
    )
    index = start + 1
    while index < len(text):
        char = text[index]
        if verbatim and char == '"' and index + 1 < len(text) and text[index + 1] == '"':
            index += 2
            continue
        if not verbatim and char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return len(text)


def strip_comments(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in ('"', "'", "`"):
            end = skip_string_literal(text, index)
            result.append(text[index:end])
            index = end
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            result.append("\n" if newline >= 0 else "")
            index = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                index = len(text)
            else:
                result.extend("\n" for line in text[index : end + 2] if line == "\n")
                index = end + 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def symbols_block(game_symbols: str) -> str | None:
    return method_body(game_symbols, r"internal static (?:partial )?class ModBugReporting\b")


def validate_transport_contract(plugin: Path) -> list[str]:
    path = plugin / "ModBugReportTransport.cs"
    if not path.is_file():
        return [f"mod report transport: missing {path}"]
    raw = path.read_text(encoding="utf-8-sig")
    source = strip_comments(raw)
    errors: list[str] = []
    for requirement, pattern in (
        ("8 MiB bundle limit", r"MaxBundleBytes\s*=\s*8\s*\*\s*1024\s*\*\s*1024"),
        ("64 KiB response limit", r"MaxResponseBytes\s*=\s*64\s*\*\s*1024"),
        ("60 second overall timeout", r"RequestTimeout\s*=\s*TimeSpan\.FromSeconds\(60\)"),
        ("300 second timeout cap", r"MaxRequestTimeout\s*=\s*TimeSpan\.FromSeconds\(300\)"),
        ("50 KiB/s upload allowance", r"UploadBytesPerSecond\s*=\s*50\s*\*\s*1024"),
        ("size-scaled timeout", r"internal static TimeSpan TimeoutFor\(long requestBytes\)"),
        ("envelope version 2", r"EnvelopeVersion\s*=\s*2"),
        ("shared client filter token", r'ClientToken\s*=\s*"[A-Za-z0-9._-]{8,128}"'),
        ("player-report purpose", r'Purpose\s*=\s*"player-report"'),
        ("Apps Script endpoint host and path allowlist", r'script\\\.google\\\.com/macros/s/.+/exec'),
        ("content redirect host allowlist", r'ContentHost\s*=\s*"script\.googleusercontent\.com"'),
        ("lowercase UUID validation", r'Guid\.TryParseExact\(reportId,\s*"D"'),
        ("SHA-256 over ZIP bytes", r"SHA256\.Create\(\).*?ComputeHash\(bytes\)"),
        ("explicit no-auto-redirect handler", r"AllowAutoRedirect\s*=\s*false"),
        ("cookie-free handler", r"UseCookies\s*=\s*false"),
        ("no default credentials", r"UseDefaultCredentials\s*=\s*false"),
        ("no preauthentication", r"PreAuthenticate\s*=\s*false"),
    ):
        if not re.search(pattern, source, re.S):
            errors.append(f"mod report transport: missing {requirement}")

    redirect_match = re.search(r"private static bool IsContentRedirect\b.*?;", source, re.S)
    redirect = redirect_match.group(0) if redirect_match else None
    if redirect is None or not all(name in redirect for name in ("MovedPermanently", "HttpStatusCode.Redirect", "SeeOther")):
        errors.append("mod report transport: only 301/302/303 content redirects may be followed")
    elif any(name in redirect for name in ("PermanentRedirect", "TemporaryRedirect")):
        errors.append("mod report transport: 307/308 must not replay the request body")
    location = method_body(source, r"private static bool TryGetAllowedContentLocation\(")
    if location is None or not all(token in location for token in (
        "IsAbsoluteUri", "UriSchemeHttps", "ContentHost", "location.Port != 443", "UserInfo", "Fragment"
    )):
        errors.append("mod report transport: redirect target must be an absolute, credential-free HTTPS content URL on the allowlisted host")
    endpoint_match = re.search(r"(?:private|internal) static bool IsEndpoint\b.*?;", source, re.S)
    endpoint = endpoint_match.group(0) if endpoint_match else None
    if endpoint is None or "EndpointPattern.IsMatch(endpoint)" not in endpoint:
        errors.append("mod report transport: configured endpoint must be strictly validated before POST")
    if source.count("client.SendAsync(") != 2:
        errors.append("mod report transport: allow at most one POST and one explicit content GET; no retry loop")
    for requirement, token in (
        ("bounded response read", "MaxResponseBytes"),
        ("matching report ID and digest acknowledgement", "TryReadReceipt(document.RootElement, reportId, expectedSha256"),
        ("explicit receiver refusal handling", "TryReadRefusal(document.RootElement, out var refused)"),
        ("success only after validated acknowledgement", "new ReportReceipt(true, reportId, null, duplicate)"),
        ("uncertain transport outcomes", "_unconfirmed"),
    ):
        if token not in source:
            errors.append(f"mod report transport: missing {requirement}")
    for forbidden in ("Authorization", "CookieContainer", "Cookie ", "DefaultRequestHeaders", "CredentialCache", "NetworkCredential"):
        if forbidden in source:
            errors.append(f"mod report transport: credential/cookie behavior is forbidden ({forbidden})")
    return errors


def validate_probe_options(relay: Path) -> list[str]:
    path = relay / "probe.py"
    if not path.is_file():
        return [f"Google probe: missing {path}"]
    source = strip_comments(path.read_text(encoding="utf-8"))
    test_path = relay / "test_probe.py"
    if not test_path.is_file():
        return [f"Google probe: missing offline option fixtures {test_path}"]
    tests = strip_comments(test_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for requirement, token in (
        ("mandatory explicit synthetic-submit flag", 'parser.add_argument("--submit-synthetic", action="store_true", required=True'),
        ("player-report envelope flag", 'parser.add_argument("--player-format", action="store_true"'),
        ("oversize refusal flag", 'parser.add_argument("--oversize", action="store_true"'),
        ("oversize generation from the fixed limit fixture", "synthetic_bundle(args.at_limit or args.oversize)"),
        ("single-byte synthetic oversize value", "bundle += b\"x\""),
        ("player-report purpose is selectable without changing fixture source", '"player-report" if args.player_format else "synthetic-pilot"'),
        ("submission bytes derive from the generated fixture", "hashlib.sha256(bundle).hexdigest()"),
    ):
        if token not in source:
            errors.append(f"Google probe: missing {requirement}")
    if "Path(" in source or ".read_bytes(" in source or "open(args." in source:
        errors.append("Google probe: option handling must not accept/read arbitrary local report files")
    for requirement, token in (
        ("safe option fixture for player-format and oversize flags", "test_player_format_and_oversize_flags_use_only_mocked_synthetic_bytes"),
        ("network submission patched out in the option fixture", 'patch.object(probe, "submit", side_effect=fake_submit)'),
        ("fixture verifies the product envelope and plus-one size", 'body["purpose"], "player-report"'),
        ("fixture verifies valid exact-limit ZIP plus one synthetic byte", "probe.MAX_BUNDLE_BYTES + 1"),
    ):
        if token not in tests:
            errors.append(f"Google probe: missing {requirement}")
    return errors


def validate_current_report_symbol_scopes(plugin: Path) -> list[str]:
    repo = plugin.parent.parent
    remap_dir = repo / "tools" / "port_current" / "remap"
    report_path = remap_dir / "current_scopes_25672315.json"
    overrides_path = remap_dir / "current_scope_overrides_25672315.json"
    generated_path = plugin / "GameSymbolsCurrent.g.cs"
    errors: list[str] = []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        generated = generated_path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        return [f"current report symbol scopes: cannot read generated scope evidence: {exc}"]

    expected = {
        "ModBugReporting.CurrentSubmitHandler": (
            ["Method_Private_Void_PDM_0"], ["Hex.UI.Reports.BhBugReportScreen"], "Method",
        ),
        "ModBugReporting.CurrentSubmitIteratorMoveNext": (
            ["MoveNext"],
            ["Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"],
            "Method",
        ),
        "ModBugReporting.CurrentScreenClose": (
            ["Close"], ["Hex.UI.Reports.BhBugReportScreen"], "Method",
        ),
        "ModBugReporting.CurrentSubmitIteratorState": (
            ["NativeFieldInfoPtr_field_Private_Int32_0", "field_Private_Int32_0"],
            ["Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"],
            "Field",
        ),
        "ModBugReporting.CurrentSubmitIteratorOwner": (
            ["NativeFieldInfoPtr_field_Public_BhBugReportScreen_0", "field_Public_BhBugReportScreen_0"],
            ["Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"],
            "Field",
        ),
        "ModBugReporting.CurrentSubmitIteratorStrings": (
            [name for index in range(5) for name in (
                f"NativeFieldInfoPtr_field_Private_String_{index}", f"field_Private_String_{index}",
            )],
            ["Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"],
            "Fields",
        ),
        "ModBugReporting.CurrentSubmitIteratorNativeLog": (
            ["NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Byte_0", "field_Private_Il2CppStructArray_1_Byte_0"],
            ["Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"],
            "Field",
        ),
        "ModBugReporting.CurrentSubmitIteratorAttachments": (
            [
                "NativeFieldInfoPtr_field_Private_Dictionary_2_String_Il2CppStructArray_1_Byte_0",
                "field_Private_Dictionary_2_String_Il2CppStructArray_1_Byte_0",
            ],
            ["Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"],
            "Field",
        ),
    }
    if report.get("schema") != "game_symbols_current_scopes.v1" or str(report.get("buildId")) != "25672315":
        return ["current report symbol scopes: report schema/build id is not the current 25672315 contract"]
    if overrides.get("schema") != "game_symbols_current_scope_overrides.v1" or str(overrides.get("buildId")) != "25672315":
        return ["current report symbol scopes: override schema/build id is not the current 25672315 contract"]

    declarations = report.get("declarations")
    override_symbols = overrides.get("symbols")
    if not isinstance(declarations, list) or not isinstance(override_symbols, dict):
        return ["current report symbol scopes: declarations or override symbols are malformed"]
    for symbol, (expected_live, expected_owners, scope_kind) in expected.items():
        matches = [item for item in declarations if isinstance(item, dict) and item.get("symbol") == symbol]
        override = override_symbols.get(symbol)
        if len(matches) != 1:
            errors.append(f"current report symbol scopes: expected exactly one report entry for {symbol}")
            continue
        item = matches[0]
        if (
            item.get("status") != "scoped"
            or item.get("live") != expected_live
            or item.get("owners") != expected_owners
            or not isinstance(item.get("override"), str)
            or not item.get("override", "").strip()
        ):
            errors.append(f"current report symbol scopes: {symbol} is refused, ownerless, or differs from its exact live pin")
        if not isinstance(override, dict) or override.get("live") != expected_live or override.get("owners") != expected_owners:
            errors.append(f"current report symbol scopes: {symbol} lacks its exact owner-checked current override")
        generated_call = f'GameSymbolScope.{scope_kind}("{symbol}"'
        if generated_call not in generated:
            errors.append(f"current report symbol scopes: generated code is missing {scope_kind} mapping for {symbol}")

    remap_path = remap_dir / "game_symbols_remap_25672315.json"
    evidence_path = remap_dir / "current_scope_evidence_25672315.json"
    try:
        remap_hash = hashlib.sha256(remap_path.read_bytes()).hexdigest().upper()
        evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest().upper()
    except OSError as exc:
        return errors + [f"current report symbol scopes: cannot hash scope inputs: {exc}"]
    if report.get("remapSha256") != remap_hash or report.get("evidenceSha256") != evidence_hash:
        errors.append("current report symbol scopes: generated report does not match its current remap/evidence inputs")
    if (
        f"Source remap: tools/port_current/remap/game_symbols_remap_25672315.json sha256 {remap_hash}" not in generated
        or f"Evidence:     tools/port_current/remap/current_scope_evidence_25672315.json sha256 {evidence_hash}" not in generated
    ):
        errors.append("current report symbol scopes: generated C# does not match its remap/evidence hashes")
    return errors


def validate_submission_surface(plugin: Path, redirect: str, game_symbols: str) -> list[str]:
    path = plugin / "ModBugReportSubmission.cs"
    if not path.is_file():
        return [f"mod report UI: missing explicit-consent submission surface {path}"]
    try:
        source = strip_comments(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return [f"mod report UI: cannot read submission surface {path}: {exc}"]
    errors: list[str] = []

    registration = method_body(source, r"internal static bool TryRegister\(")
    if registration is None:
        errors.append("mod report UI: missing TryRegister")
    else:
        for requirement, token in (
            ("current build pin", "GameBuild.Kind != GameBuildKind.Current"),
            ("protected native sink requirement", "ModBugReportRedirect.State != ModBugReportRedirect.GuardState.Redirecting"),
            ("strict transport endpoint preflight", "ModBugReportTransport.IsEndpoint(cfg.ModBugReportingEndpoint)"),
            ("Submit callback MethodSymbol through GameSymbols", "GameSymbols.ModBugReporting.CurrentSubmitHandler"),
            ("Submit native method pin through GameSymbols", "GameSymbols.ModBugReporting.CurrentSubmitHandlerNativeName"),
            ("Submit MethodInfo field pin through GameSymbols", "GameSymbols.ModBugReporting.CurrentSubmitHandlerMethodInfoFieldName"),
            ("iterator identity pin through GameSymbols", "GameSymbols.ModBugReporting.CurrentSubmitIteratorObfuscatedName"),
            ("iterator MoveNext MethodSymbol through GameSymbols", "GameSymbols.ModBugReporting.CurrentSubmitIteratorMoveNext"),
            ("screen Close MethodSymbol through GameSymbols", "GameSymbols.ModBugReporting.CurrentScreenClose"),
            ("iterator owner/state/native fields through GameSymbols", "GameSymbols.ModBugReporting.CurrentSubmitIteratorState"),
            ("Submit, MoveNext, and Close hooks", "nameof(SubmitPrefix)"),
            ("iterator MoveNext hook", "nameof(IteratorMoveNextPrefix)"),
            ("native form Close hook", "nameof(ClosePrefix)"),
        ):
            if token not in registration:
                errors.append(f"mod report UI: registration is missing {requirement}")
    field_resolver = method_body(source, r"private static bool TryResolveFieldProperty\(")
    if field_resolver is None or not all(token in field_resolver for token in (
        "symbol.NativeFieldInfoName", "nativeFieldInfo.FieldType != typeof(IntPtr)",
        "RuntimeHelpers.RunClassConstructor(owner.TypeHandle)", "nativeFieldInfo.GetValue(null)", "IntPtr.Zero"
    )):
        errors.append("mod report UI: native iterator fields must validate managed properties and initialized native metadata handles")
    if "Regex" in source or "Uri.TryCreate" in source:
        errors.append("mod report UI: endpoint syntax must be centralized in ModBugReportTransport.IsEndpoint")
    if "AccessTools.GetDeclaredMethods" in source or re.search(r"\b(?:GetMethods|GetMethod)\s*\(", source):
        errors.append("mod report UI: Submit, iterator MoveNext, and screen Close lookups must use the centralized strict GameMember resolver")

    normalized_source = re.sub(r"\s+", " ", source)
    if normalized_source.count("GameMember.FindEveryMethodByNames(") != 3:
        errors.append("mod report UI: Submit, iterator MoveNext, and screen Close must each use the strict centralized method resolver exactly once")
    for variable, symbol, error_name, shape in (
        ("submit", "CurrentSubmitHandler", "submitError", (
            "m.IsPublic", "!m.IsStatic", "!m.IsVirtual", "m.ReturnType == typeof(void)", "m.GetParameters().Length == 0",
        )),
        ("moveNext", "CurrentSubmitIteratorMoveNext", "moveNextError", (
            "m.IsPublic", "!m.IsStatic", "m.IsVirtual", "m.ReturnType == typeof(bool)", "m.GetParameters().Length == 0",
        )),
        ("close", "CurrentScreenClose", "closeError", (
            "m.IsPublic", "!m.IsStatic", "!m.IsVirtual", "m.ReturnType == typeof(void)", "m.GetParameters().Length == 0",
        )),
    ):
        call = re.search(
            rf"var {variable} = GameMember\.FindEveryMethodByNames\( .*?GameSymbols\.ModBugReporting\.{symbol}, .*?out var {error_name}\);",
            normalized_source,
        )
        if call is None or not all(token in call.group(0) for token in shape):
            errors.append(f"mod report UI: {variable} lookup must use {symbol} and enforce its exact public managed method shape")
        else:
            if not re.search(rf"if \({variable} == null \|\| {variable}\.Length != 1\)", normalized_source[call.end():]):
                errors.append(f"mod report UI: {variable} lookup must fail closed unless exactly one strict resolver match exists")
            if error_name not in normalized_source[call.end():call.end() + 400]:
                errors.append(f"mod report UI: {variable} resolver ambiguity/error must be surfaced before patching")
    if "CurrentSubmitHandlerMethodInfoFieldName" not in registration or "CurrentSubmitHandlerNativeName" not in registration or not re.search(
        r"string\.Equals\(submitNativeName, GameSymbols\.ModBugReporting\.CurrentSubmitHandlerNativeName, StringComparison\.Ordinal\)",
        normalized_source,
    ):
        errors.append("mod report UI: Submit must retain the exact centralized native vbc method-pointer preflight")

    submit = method_body(source, r"private static bool SubmitPrefix\(")
    if submit is None or not all(token in submit for token in (
        "_authorizedSubmitPointer == pointer", "_consentChecked = false", "_includeScreenshotChecked = false",
        "_visible = true", "return false;"
    )):
        errors.append("mod report UI: native Submit must pause behind a fresh, unchecked consent screen")
    consent = method_body(source, r"private static void DrawConsentContents\(")
    if consent is None or not all(token in consent for token in (
        "_consentChecked = GUILayout.Toggle", "_cfg?.ModBugReportingIncludeScreenshot == true",
        "_includeScreenshotChecked = GUILayout.Toggle", "ConfirmConsent()"
    )):
        errors.append("mod report UI: consent and optional screenshot controls must be explicit and screenshot config-gated")
    if consent is None or "Save report locally" in consent or "No Google Apps Script relay is configured" in consent:
        errors.append("mod report UI: this shipping flow requires a valid relay and must not silently offer local-only submission")
    if consent is None or not all(token in consent for token in (
        "your title, description and category, the game and mod logs, your Windows version",
        "What's not sent: files you attached", "only their names and sizes may be listed",
        "the contact details you typed", "this may miss something, so please don't type anything private"
    )):
        errors.append("mod report UI: consent must disclose included report data and the limits of text scrubbing")
    if consent is None or not all(token in consent for token in (
        "I agree to send this report to the Golden Era mod team", "private Google Drive",
        "personal details are not removed from it"
    )):
        errors.append("mod report UI: consent must name the private destination and warn that an optional screenshot may contain unsanitized private information")
    if consent is None or not all(token in consent for token in ("IP address", "90 days", "30 days")):
        errors.append("mod report UI: consent must disclose transport metadata (IP address) and the remote/local retention periods")
    confirm = method_body(source, r"private static void ConfirmConsent\(")
    if confirm is None or not all(token in confirm for token in (
        "!_consentChecked", "_cfg?.ModBugReportingIncludeScreenshot == true && _includeScreenshotChecked",
        "Guid.NewGuid().ToString(\"D\").ToLowerInvariant()", "_submitMethod.Invoke(screen, null)"
    )):
        errors.append("mod report UI: only checked consent may invoke the native Submit flow, with screenshot consent conjoined with config")

    capture = method_body(source, r"private static bool IteratorMoveNextPrefix\(")
    if capture is None or not all(token in capture for token in (
        "transaction.ScreenPointer", "state == 0", "state != 1", "GameSymbols.ModBugReporting.SendReportParameterCount",
        "CaptureFromArgs(args, includeScreenshot: false)", "TryCloseNativeForm(screen)",
        "if (transaction.IncludeScreenshot)", "CaptureScreenshotAndSubmit(transaction)",
        "BeginPackageAndSubmit(transaction)", "return false;"
    )):
        errors.append("mod report UI: pinned iterator must copy managed fields and suppress native submission after the consented capture")
    screenshot = method_body(source, r"private static IEnumerator CaptureScreenshotAndSubmit\(")
    if screenshot is None or not all(token in screenshot for token in (
        "new WaitForEndOfFrame()", "TryCaptureScreenshotPng(out var png, out var captureError)",
        "_suppressOverlayForCapture = false", "WithScreenshot", "BeginPackageAndSubmit(transaction)"
    )):
        errors.append("mod report UI: screenshot capture must occur only in the separately consented flow")
    for name, expected in (
        ("MaxScreenshotSourcePixels", "16 * 1024 * 1024"),
        ("MaxScreenshotWidth", "1280"),
        ("MaxScreenshotHeight", "720"),
    ):
        if not re.search(r"private const int " + name + r"\s*=\s*" + re.escape(expected) + r";", source):
            errors.append(f"mod report UI: screenshot source/output bound `{name} = {expected}` is missing")
    capture_png = method_body(source, r"private static bool TryCaptureScreenshotPng\(")
    if capture_png is None or not all(token in capture_png for token in (
        "MaxScreenshotSourcePixels", "MaxScreenshotWidth", "MaxScreenshotHeight",
        "Math.Floor(screenWidth * scale)", "Math.Floor(screenHeight * scale)",
        "ScreenCapture.CaptureScreenshotAsTexture()", "RenderTexture.GetTemporary(width, height",
        "Graphics.Blit(full, target)", "ReadPixels(", "ImageConversion.EncodeToPNG(scaled)",
        "ModBugReportRedirect.ScreenshotMaxBytes", "finally", "ReleaseTemporaryRenderTexture(target)",
        "DestroyTexture(full)", "DestroyTexture(scaled)", "RenderTexture.active = previousActive"
    )):
        errors.append("mod report UI: screenshot must be source-capped, GPU-downscaled, PNG-encoded by Unity, size-checked, and release every Unity object")
    if capture_png is not None and re.search(r"\b(?:for|foreach)\s*\(", capture_png):
        errors.append("mod report UI: screenshot capture must not use a CPU per-pixel loop")
    for obsolete in ("AsyncGPUReadback", "SixLabors", "ImageSharp", "EncodeToJPG"):
        if obsolete in source:
            errors.append(f"mod report UI: obsolete screenshot path `{obsolete}` is not permitted")
    host = method_body(source, r"private static void AttachHost\(")
    shield_create = method_body(source, r"private static void AttachPointerShield\(")
    shield_update = method_body(source, r"private static void UpdatePointerShield\(Rect guiRect\)")
    shield_hide = method_body(source, r"private static void HidePointerShield\(")
    host_gui = method_body(source, r"internal static void OnHostGui\(")
    if host is None or "AttachPointerShield()" not in host or shield_create is None or not all(token in shield_create for token in (
        "GraphicRaycaster", "RenderMode.ScreenSpaceOverlay", "sortingOrder = 32767", "image.raycastTarget = true", "image.enabled = false"
    )):
        errors.append("mod report UI: attach a disabled-by-default topmost UI raycast shield for the modal")
    if shield_update is None or not all(token in shield_update for token in (
        "rect.anchoredPosition = new Vector2(guiRect.x, -guiRect.y)", "rect.sizeDelta = new Vector2(guiRect.width, guiRect.height)",
        "_pointerShieldImage.enabled = true"
    )) or shield_hide is None or "_pointerShieldImage.enabled = false" not in shield_hide:
        errors.append("mod report UI: shield must track the modal bounds while visible and be disabled when hidden")
    if host_gui is None or not all(token in host_gui for token in (
        "_suppressOverlayForCapture", "HidePointerShield()", "UpdatePointerShield(rect)", "GUI.Window(WindowId"
    )):
        errors.append("mod report UI: hide the consent UI and its input shield for screenshot capture, otherwise shield the window before drawing it")
    package = method_body(source, r"private static void BeginPackageAndSubmit\(")
    if package is None or "PackageAndSubmitAsync" not in package:
        errors.append("mod report UI: accepted capture must enter the bounded background packaging path")
    retry = method_body(source, r"private static void BeginRetry\(")
    if retry is None or not all(token in retry for token in (
        "transaction.Outcome?.BundlePath", "transaction.ReportId", "RetryAndSubmitAsync"
    )):
        errors.append("mod report UI: retry must be a manual action against the retained same-ID ZIP")
    draw = method_body(source, r"private static void DrawTransactionContents\(")
    if draw is None or "Try again" not in draw or "BeginRetry(transaction)" not in draw:
        errors.append("mod report UI: retry must be explicitly user-initiated")
    if source.count("RetryAndSubmitAsync") != 1 or source.count("BeginRetry(transaction)") != 1:
        errors.append("mod report UI: retry path must not run automatically or from multiple callbacks")
    dismiss = method_body(source, r"private static void DismissTransaction\(")
    if dismiss is None:
        errors.append("mod report UI: missing transaction Hide/Dismiss behavior")
    else:
        pending_pos = dismiss.find("transaction.State == FlowState.Unconfirmed")
        hide_pos = dismiss.find("_visible = false", pending_pos + 1)
        return_pos = dismiss.find("return;", hide_pos + 1)
        clear_pos = dismiss.find("_transaction = null")
        if min(pending_pos, hide_pos, return_pos, clear_pos) < 0 or not pending_pos < hide_pos < return_pos < clear_pos:
            errors.append("mod report UI: hiding an unconfirmed report must retain its same-session retry state")
    abandon = method_body(source, r"private static void AbandonRetryAndOpenNewConsent\(")
    abandon_ui = method_body(source, r"private static void DrawAbandonRetryConfirmation\(")
    if abandon_ui is None or not all(token in abandon_ui for token in (
        "Discard this unsent report?", "It won't be offered again, now or after a restart",
        "The saved copy on your PC is not deleted right away", "Discard and start new", "Discard", "Keep it",
        "AbandonRetryAndOpenNewConsent(transaction)", "AbandonRetry(transaction)"
    )):
        errors.append("mod report UI: abandoning a retained retry must be an explicit, warned user decision")
    if abandon is None or not all(token in abandon for token in (
        "FlowState.Unconfirmed", "RecordAbandoned(transaction)", "_transaction = null", "_consentScreen = screen",
        "_consentChecked = false", "_includeScreenshotChecked = false", "NativePointer(screen) != screenPointer"
    )):
        errors.append("mod report UI: a new report may replace an unconfirmed retry only after explicit abandon and a fresh consent")
    if submit is not None and not all(token in submit for token in (
        "_pendingNewReportScreen = __instance", "_pendingNewReportScreenPointer = pointer",
        "_abandonRetryConfirmation = true", "_transaction.State == FlowState.Unconfirmed"
    )):
        errors.append("mod report UI: opening a new native report form while delivery is unconfirmed must preserve the old retry and request explicit abandonment")
    if draw is None or not all(token in draw for token in (
        "New report...", "_abandonRetryConfirmation = true", "Try again", "Hide"
    )):
        errors.append("mod report UI: an unconfirmed retry may be retried, hidden, or replaced only through an explicit confirmation")
    restore = method_body(source, r"private static void RestoreUnsentReport\(")
    if restore is None or not all(token in restore for token in (
        "ModBugReportRedirect.FindLatestUnsentReport()", "FlowState.Unconfirmed", "RestoredAfterRestart = true"
    )):
        errors.append("mod report UI: an unacknowledged bundle from an earlier session must be offered for manual retry, never sent automatically")
    if restore is not None and any(token in restore for token in ("RetryAndSubmitAsync", "BeginRetry(")):
        errors.append("mod report UI: a restored report must wait for an explicit Try again")
    pump = method_body(source, r"private static void Pump\(")
    if pump is None or not all(token in pump for token in (
        "transaction.Outcome.Acknowledged", "FlowState.Acknowledged", "FlowState.Unconfirmed"
    )):
        errors.append("mod report UI: only an acknowledged receipt may be shown as success")
    if re.search(r"\b(?:DateTime|DateTimeOffset|Stopwatch)\b|(?:FormOpenedAt|RecentFormOpen|WasFormOpenedRecently)", source):
        errors.append("mod report UI: report submission must not use a time-based origin/consent heuristic")
    for token in FORBIDDEN_DIRECT_SYMBOLS:
        if token in source:
            errors.append(f"ModBugReportSubmission.cs: game symbol {token} must be centralized in GameSymbols.ModBugReporting")
    normalized_symbols = re.sub(r"\s+", " ", game_symbols)
    if not all(token in normalized_symbols for token in (
        'CurrentSubmitHandlerNativeName = "vbc"',
        'CurrentSubmitHandlerMethodInfoFieldName = "NativeMethodInfoPtr_Method_Private_Void_PDM_0"',
        'CurrentSubmitIteratorObfuscatedName = "Hex.UI.Reports.BhBugReportScreen+cul"',
        'CurrentSubmitIteratorManagedTypeFullName = "Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique"',
        '"bugReport.submit.handler", "Method_Private_Void_PDM_0"',
        '"bugReport.submit.iterator.moveNext", "MoveNext"',
        '"bugReport.screen.close", "Close"',
        "CurrentSubmitHandler", "CurrentSubmitIteratorMoveNext", "CurrentScreenClose",
        "CurrentSubmitIteratorState", "CurrentSubmitIteratorOwner", "CurrentSubmitIteratorStrings",
        "CurrentSubmitIteratorNativeLog", "CurrentSubmitIteratorAttachments"
    )):
        errors.append("GameSymbols.ModBugReporting: missing current Submit/MoveNext/Close MethodSymbol and iterator field pin contract")

    register = method_body(redirect, r"internal static void TryRegister\(")
    if register is None:
        errors.append("ModBugReportRedirect.TryRegister: sink must be protected first and UI-registration failure must block native entry points or report unavailable")
    else:
        sink_pos = register.find("if (TryPatchSink(harmony, out var sinkError))")
        state_pos = register.find("State = GuardState.Redirecting", sink_pos + 1)
        submit_pos = register.find("ModBugReportSubmission.TryRegister(harmony, log, cfg, out var submissionError)")
        if sink_pos < 0 or state_pos < 0 or submit_pos < 0 or not sink_pos < state_pos < submit_pos:
            errors.append("ModBugReportRedirect.TryRegister: protect the native sink and enter Redirecting before resolving the Submit UI")
        if not all(token in register for token in (
            "TryBlockEntryPoints", "GuardState.SubmissionUnavailable", "GuardState.EntryPointsBlocked",
            "native sink remains blocked", "no report upload is available"
        )):
            errors.append("ModBugReportRedirect.TryRegister: UI-registration failure must block native entry points or explicitly report submission unavailable")
    return errors


def validate(repo: Path) -> list[str]:
    errors: list[str] = []
    plugin = repo / PLUGIN_DIR
    redirect_path = plugin / "ModBugReportRedirect.cs"
    if not redirect_path.is_file():
        return [f"missing {redirect_path}"]
    redirect_raw = redirect_path.read_text(encoding="utf-8-sig")
    redirect = strip_comments(redirect_raw)
    submission_path = plugin / "ModBugReportSubmission.cs"
    submission_raw = submission_path.read_text(encoding="utf-8-sig") if submission_path.is_file() else ""
    submission = strip_comments(submission_raw)
    telemetry_path = plugin / "NativeTelemetryBlock.cs"
    if not telemetry_path.is_file():
        return [f"missing {telemetry_path}"]
    telemetry_raw = telemetry_path.read_text(encoding="utf-8-sig")
    telemetry = strip_comments(telemetry_raw)
    transport_path = plugin / "ModBugReportTransport.cs"
    transport_raw = transport_path.read_text(encoding="utf-8-sig") if transport_path.is_file() else ""
    errors.extend(validate_transport_contract(plugin))

    game_symbols = (plugin / "GameSymbols.cs").read_text(encoding="utf-8-sig")
    block = symbols_block(game_symbols)
    if block is None:
        errors.append("GameSymbols.cs: missing `internal static class ModBugReporting` block")
        block = ""

    # 1. No developer endpoint anywhere in the reporting path (comments included: a pasted URL is still a leak risk).
    for label, text in (
        ("ModBugReportRedirect.cs", redirect_raw),
        ("ModBugReportSubmission.cs", submission_raw),
        ("NativeTelemetryBlock.cs", telemetry_raw),
        ("ModBugReportTransport.cs", transport_raw),
        ("GameSymbols.ModBugReporting", block),
    ):
        lowered = text.lower()
        for token in FORBIDDEN_ENDPOINT_TOKENS:
            if token in lowered:
                errors.append(f"{label}: game-developer endpoint token '{token}' in the reporting path")
    for label, text in (
        ("ModBugReportRedirect.cs", redirect),
        ("ModBugReportSubmission.cs", submission),
        ("NativeTelemetryBlock.cs", telemetry),
    ):
        for token in FORBIDDEN_BROWSER_TOKENS:
            if token in text:
                errors.append(f"{label}: browser/auth API '{token}' used; delivery must be explicit and managed")
        for token in ("WebClient", "WebRequest", "UnityWebRequest", "TcpClient", "Socket", "GrpcChannel", "MagicOnion", "SmtpClient"):
            if re.search(r"\b" + re.escape(token) + r"\b", text):
                errors.append(f"{label}: unsupported network API '{token}' used")
    guard_path = plugin / "NativeAnalyticsHostGuard.cs"
    guard_raw = guard_path.read_text(encoding="utf-8-sig") if guard_path.is_file() else ""
    guard = strip_comments(guard_raw)
    if not guard:
        errors.append(f"missing {guard_path}: the independent analytics host guard")
    else:
        host_literals = re.findall(r'"([^"\n]*)"', guard)
        developer_hosts = [lit for lit in host_literals if any(token in lit.lower() for token in FORBIDDEN_ENDPOINT_TOKENS)]
        if developer_hosts != ["an.prod.hex.unfrozen.app"]:
            errors.append("NativeAnalyticsHostGuard.cs: must name exactly one developer host, the analytics host, as BlockedHost")
        urls = re.findall(r'"https?://[^"]*"', guard)
        if urls != ['"https://127.0.0.1:9/"']:
            errors.append("NativeAnalyticsHostGuard.cs: the only URL literal may be the closed local sink https://127.0.0.1:9/")
        for token in ("typeof(Grpc.Net.Client.GrpcChannel).GetConstructor(", "typeof(Il2CppSystem.Uri)",
                      "typeof(Grpc.Net.Client.GrpcChannelOptions)", "nameof(ChannelPrefix)", "BlockNativeTelemetry",
                      "Priority.First"):
            if token not in guard:
                errors.append(f"NativeAnalyticsHostGuard.cs: missing `{token}`")
        channel_prefix = method_body(guard, r"private static void ChannelPrefix\(ref Il2CppSystem\.Uri address\)")
        if channel_prefix is None or not all(token in channel_prefix for token in (
            "IsBlockedHost(address.Host)", "address = new Il2CppSystem.Uri(SinkAddress)", "catch"
        )):
            errors.append("NativeAnalyticsHostGuard.ChannelPrefix: must swap only the analytics host for the local sink, inside try/catch")
        if re.search(r"\bthrow\b", guard):
            errors.append("NativeAnalyticsHostGuard.cs: must not throw (it runs in Plugin.Load and in native call paths)")
        warning = method_body(guard, r"internal static string StateWarning\(")
        if warning is None or not all(token in warning for token in (
            "GuardState.Redirecting", "GuardState.EntryPointsBlocked", "GuardState.SubmissionUnavailable",
            "GuardState.Unprotected", "return null;"
        )):
            errors.append("NativeAnalyticsHostGuard.StateWarning: every non-Redirecting state must produce an on-screen notice")
        if "ModBugReportWarningHost.Show(message)" not in guard or 'GUILayout.Button("Dismiss"' not in guard:
            errors.append("NativeAnalyticsHostGuard.cs: the state notice must be shown on screen and be dismissible")
    if "internal static bool ReportSinkBlocked" not in telemetry:
        errors.append("NativeTelemetryBlock.cs: must expose ReportSinkBlocked for the state notice")
    if re.search(r'"https?://', telemetry_raw):
        errors.append("NativeTelemetryBlock.cs: URL literal present; the telemetry block builds no URL")
    if "github.com" in redirect.lower() or "modBugReportingIssueRepo" in redirect:
        errors.append("ModBugReportRedirect.cs: manual GitHub issue fallback is not part of this Google submission path")
    if re.search(r'"https?://', redirect_raw):
        errors.append("ModBugReportRedirect.cs: browser destination URL literal is not permitted")
    if "http://" in redirect_raw:
        errors.append("ModBugReportRedirect.cs: plain http:// literal present")

    # 2. The sink prefix blocks unconditionally.
    prefix = method_body(redirect, r"private static bool SendReportPrefix\(\)")
    if prefix is None:
        errors.append("ModBugReportRedirect.cs: missing `private static bool SendReportPrefix()`")
    else:
        if "return true" in prefix:
            errors.append("SendReportPrefix: contains `return true`; the native send must never run")
        if not re.search(r"return false;\s*}\s*$", prefix):
            errors.append("SendReportPrefix: must end with `return false;`")
        if "try" not in prefix or "catch" not in prefix:
            errors.append("SendReportPrefix: body must be wrapped in try/catch so logging cannot break the fail-closed sink")
        if "throw" in prefix:
            errors.append("SendReportPrefix: must not throw")
        if any(token in prefix for token in ("CaptureFromArgs", "PackageAndSubmitAsync", "RetryAndSubmitAsync", "ModBugReportTransport")):
            errors.append("SendReportPrefix: native sink must not capture or upload reports; submission requires explicit UI consent")
    if not re.search(r"nameof\(SendReportPrefix\)", redirect):
        errors.append("ModBugReportRedirect.cs: SendReportPrefix is never patched")

    # 3. Fail closed.
    register = method_body(redirect, r"internal static void TryRegister\(")
    if register is None:
        errors.append("ModBugReportRedirect.cs: missing TryRegister")
    else:
        if "TryBlockEntryPoints" not in register:
            errors.append("TryRegister: sink failure must fall to TryBlockEntryPoints (fail closed)")
        if "GuardState.Unprotected" not in register or "LogError" not in register:
            errors.append("TryRegister: total patch failure must set GuardState.Unprotected and log at error level")
        sink_pos = register.find("TryPatchSink")
        block_pos = register.find("TryBlockEntryPoints")
        if sink_pos < 0 or block_pos < 0 or block_pos < sink_pos:
            errors.append("TryRegister: must try the sink first and block entry points only after it fails")
    block_prefix = method_body(redirect, r"private static bool BlockPrefix\(")
    if block_prefix is None or "return true" in block_prefix or "return false" not in block_prefix:
        errors.append("BlockPrefix: must exist and always return false")
    block_entry = method_body(redirect, r"private static bool TryBlockEntryPoints\(")
    if block_entry is None or block_entry.count("nameof(BlockPrefix)") < 1 or block_entry.count("harmony.Patch(") < 2:
        errors.append("TryBlockEntryPoints: must patch both the form opener and the desync auto-send with BlockPrefix")

    # 4. Symbols through GameSymbols.
    for label, text in (
        ("ModBugReportRedirect.cs", redirect),
        ("ModBugReportSubmission.cs", submission),
        ("NativeTelemetryBlock.cs", telemetry),
    ):
        for token in FORBIDDEN_DIRECT_SYMBOLS:
            if token in text:
                errors.append(f"{label}: game symbol {token} named directly; route it through GameSymbols.ModBugReporting")
    for needed in ("SendReportOwnerTypeHints", "SendReportMethodName", "ScreenTypeHints", "ScreenShowMethodName", "ScreenStaticAutoSend"):
        if needed not in block:
            errors.append(f"GameSymbols.ModBugReporting: missing {needed}")
        if f"GameSymbols.ModBugReporting.{needed}" not in redirect:
            errors.append(f"ModBugReportRedirect.cs: does not use GameSymbols.ModBugReporting.{needed}")

    # 5. Pin the shipping Google endpoint and ensure user-configurable layers retain it.
    settings: object = {}
    try:
        settings = json.loads((plugin / "config.json").read_text(encoding="utf-8-sig"))
        errors.extend(validate_shipped_settings(settings))
    except (OSError, ValueError) as exc:
        errors.append(f"config.json: cannot read shipping settings: {exc}")
    config = (plugin / "LauncherConfig.cs").read_text(encoding="utf-8-sig")
    if not re.search(r"public bool ModBugReporting = true;", config):
        errors.append("LauncherConfig.cs: `public bool ModBugReporting = true;` not found")
    if not re.search(r'ReadBool\(json,\s*"modBugReporting",\s*true\)', config):
        errors.append("LauncherConfig.cs: modBugReporting must be read with default true")
    if not re.search(r"public bool BlockNativeTelemetry = true;", config):
        errors.append("LauncherConfig.cs: `public bool BlockNativeTelemetry = true;` not found")
    if not re.search(r'ReadBool\(json,\s*"blockNativeTelemetry",\s*true\)', config):
        errors.append("LauncherConfig.cs: blockNativeTelemetry must be read with default true")
    if 'KeyPresent(jsonB, "blockNativeTelemetry")' not in config:
        errors.append("LauncherConfig.cs: blockNativeTelemetry is not merged across config files")
    if not re.search(r'public string ModBugReportingEndpoint = "";', config):
        errors.append('LauncherConfig.cs: ModBugReportingEndpoint must default to empty')
    if not re.search(r'ReadString\(json,\s*"modBugReportingEndpoint",\s*""\)', config):
        errors.append('LauncherConfig.cs: modBugReportingEndpoint must be read with default ""')
    for key, assignment in (
        ("modBugReporting", "a.ModBugReporting = b.ModBugReporting;"),
        ("modBugReportingEndpoint", "a.ModBugReportingEndpoint = b.ModBugReportingEndpoint;"),
        ("modBugReportingIncludeScreenshot", "a.ModBugReportingIncludeScreenshot = b.ModBugReportingIncludeScreenshot;"),
        ("blockNativeTelemetry", "a.BlockNativeTelemetry = b.BlockNativeTelemetry;"),
    ):
        if f'KeyPresent(jsonB, "{key}")' not in config or assignment not in config:
            errors.append(f"LauncherConfig.cs: {key} is not merged from the overriding config layer")
    configured_endpoint = settings.get("modBugReportingEndpoint", "") if isinstance(settings, dict) else ""
    if not GOOGLE_EXEC_ENDPOINT.fullmatch(str(configured_endpoint)):
        errors.append("config.json: modBugReportingEndpoint must be an observed /exec URL on script.google.com")
    if "modBugReportingIssueRepo" in settings or "modBugReportingIssueRepo" in config:
        errors.append("config.json / LauncherConfig.cs: obsolete GitHub browser destination is still configured")
    if not re.search(r"public bool ModBugReportingIncludeScreenshot = false;", config):
        errors.append("LauncherConfig.cs: ModBugReportingIncludeScreenshot must default to false (opt-in)")
    if not re.search(r'ReadBool\(json,\s*"modBugReportingIncludeScreenshot",\s*false\)', config):
        errors.append("LauncherConfig.cs: modBugReportingIncludeScreenshot must be read with default false")

    # 5b. Abuse limits.
    for name, value in PINNED_LIMITS.items():
        if not re.search(r"internal const int " + name + r"\s*=\s*" + re.escape(value) + r";", redirect):
            errors.append(f"ModBugReportRedirect.cs: abuse limit `internal const int {name} = {value};` not found")
    build_bundle = method_body(redirect, r"private static BundleBuildResult BuildFinalBundle\(")
    if build_bundle is None:
        errors.append("ModBugReportRedirect.cs: missing bounded BuildFinalBundle")
    else:
        admit = build_bundle.find("AdmissionRefusal(")
        opened = build_bundle.find("ZipFile.Open(")
        if admit < 0 or opened < 0 or admit > opened:
            errors.append("BuildFinalBundle: AdmissionRefusal (dedup, cooldown, daily cap) must run before the zip is opened")
        if "MaxBundleBytes" not in build_bundle or "FileInfo(temporaryPath).Length" not in build_bundle:
            errors.append("BuildFinalBundle: the package must be size-checked against MaxBundleBytes")
        if "File.Move(temporaryPath, path)" not in build_bundle or "WriteRetryMetadata" not in build_bundle:
            errors.append("BuildFinalBundle: finalized bundle and integrity sidecar must be retained for explicit retry")
        if "ReportHash(" not in build_bundle:
            errors.append("BuildFinalBundle: report content hash must key dedup/admission")
    capture = method_body(redirect, r"internal static CaptureData CaptureFromArgs\(")
    if capture is None:
        errors.append("ModBugReportRedirect.cs: missing bounded managed CaptureFromArgs")
    else:
        if "_mainThreadId" not in capture or "ManagedThreadId" not in capture:
            errors.append("CaptureFromArgs: native values must be copied on the Unity main thread")
        if "includeScreenshot && screenshotAllowed" not in capture:
            errors.append("CaptureFromArgs: screenshot requires both player consent and the config setting")
        if "ScreenshotMaxBytes" not in capture or "NativeLogInputMaxBytes" not in capture:
            errors.append("CaptureFromArgs: screenshot and native log inputs must be bounded before worker packaging")
    with_screenshot = method_body(redirect, r"internal static CaptureData WithScreenshot\(")
    if with_screenshot is None or not all(token in with_screenshot for token in (
        "ModBugReportingIncludeScreenshot", "ScreenshotMaxBytes", "HasPngSignature(png)", "(byte[])png.Clone()"
    )):
        errors.append("WithScreenshot: optional screenshot must require config, size/signature checks, and an owned byte copy")
    if any(token in redirect for token in ("FormOpenedAt", "FormOpenTimestamp", "WasFormOpenedRecently", "RecentFormOpen")):
        errors.append("ModBugReportRedirect.cs: report origin must come from the explicit native Submit path, not a form-open time heuristic")
    package = method_body(redirect, r"internal static Task<ReportOutcome> PackageAndSubmitAsync\(")
    if package is None or "Task.Run(" not in package or "PackageAndSubmitCoreAsync" not in package:
        errors.append("PackageAndSubmitAsync: package and network work must be scheduled off the Unity thread")
    retry = method_body(redirect, r"internal static Task<ReportOutcome> RetryAndSubmitAsync\(")
    if retry is None or "SubmitExistingCoreAsync" not in retry or "Task.Run(" not in retry:
        errors.append("RetryAndSubmitAsync: retry must be an explicit off-thread action for an existing report ID")
    retry_core = method_body(redirect, r"private static async Task<ReportOutcome> SubmitExistingCoreAsync\(")
    if retry_core is None or "ReadRetryBundle(reportId)" not in retry_core or "BuildFinalBundle" in retry_core:
        errors.append("SubmitExistingCoreAsync: same-ID retry must verify and submit the existing ZIP without recapturing or repackaging")
    if retry_core is not None and "File.Delete" in retry_core:
        errors.append("SubmitExistingCoreAsync: failed or uncertain upload must not delete the local ZIP")
    read_retry = method_body(redirect, r"private static BundleBuildResult ReadRetryBundle\(")
    if read_retry is None or not all(token in read_retry for token in (
        "MaxBundleBytes", "metadata.ReportId", "metadata.BundleSha256", "Sha256(bytes)"
    )):
        errors.append("ReadRetryBundle: explicit retry must validate size and SHA-256 before resubmission")
    package_core = method_body(redirect, r"private static async Task<ReportOutcome> PackageAndSubmitCoreAsync\(")
    if package_core is None or "RecordOutcomeState(OutcomeFromReceipt(receipt, reportId, bundlePath))" not in package_core:
        errors.append("PackageAndSubmitCoreAsync: refusal and uncertain acknowledgement must retain the finalized local ZIP")
    receipt_outcome = method_body(redirect, r"private static ReportOutcome OutcomeFromReceipt\(")
    if receipt_outcome is None or not all(token in receipt_outcome for token in (
        "FailedOutcome(reportId, \"empty_transport_receipt_unconfirmed\", bundlePath)",
        "FailedOutcome(reportId, \"acknowledgement_id_mismatch_unconfirmed\", bundlePath)",
        "new ReportOutcome(receipt.Acknowledged, reportId, error, bundlePath, receipt.Duplicate)"
    )):
        errors.append("OutcomeFromReceipt: local finalized ZIP must remain attached to refused, mismatched, and uncertain outcomes for explicit retry")
    admission = method_body(redirect, r"private static string AdmissionRefusal\(")
    if admission is None:
        errors.append("ModBugReportRedirect.cs: missing AdmissionRefusal")
    else:
        for needle, why in (
            ("duplicate", "dedup of an identical report"),
            ("ReportCooldownSeconds", "cooldown"),
            ("DailyBundleCap", "daily cap"),
        ):
            if needle not in admission:
                errors.append(f"AdmissionRefusal: {why} is not applied")
    if admission is not None and not all(token in admission for token in ("CountsForAdmission(", "DuplicateWindowHours")):
        errors.append("AdmissionRefusal: failed/abandoned bundles must not count, and dedup must be limited to DuplicateWindowHours")
    for name, value in (("LocalBundleRetentionDays", "30"), ("LocalBundleMaxCount", "50"), ("DuplicateWindowHours", "24")):
        if not re.search(r"(?:internal|private) const int " + name + r"\s*=\s*" + value + r";", redirect):
            errors.append(f"ModBugReportRedirect.cs: `{name} = {value}` not found")
    cleanup = method_body(redirect, r"private static void CleanupLocalBundlesLocked\(")
    if cleanup is None or not all(token in cleanup for token in ("LocalBundleRetentionDays", "LocalBundleMaxCount", "ActiveReports")):
        errors.append("ModBugReportRedirect.cs: local bundles must be pruned by age and count, never an active report")
    tail = method_body(redirect, r"private static string ReadBepInExLogTail\(")
    if tail is None or "BepInExLogTailBytes" not in tail or "truncated" not in tail:
        errors.append("ReadBepInExLogTail: must cut to BepInExLogTailBytes and mark the truncation")

    # 6. PII scrub coverage.
    scrubber = method_body(redirect, r"internal static string Scrub\(")
    if scrubber is None:
        errors.append("ModBugReportRedirect.cs: missing Scrubber.Scrub")
    else:
        for needle in ("UserProfilePath", "SteamId64", "SteamId2", "SteamId3", "Email", "Environment.UserName", "Environment.MachineName",
                       "IPv4.Replace", "IPv6.Replace", "SteamNameRegex()"):
            if needle not in scrubber:
                errors.append(f"Scrubber.Scrub: does not apply {needle}")
    if "7656119" not in redirect or "Users" not in redirect:
        errors.append("Scrubber: SteamID64 prefix or Users path pattern missing")

    # 7. Telemetry block.
    for needed in (
        "SendGameMetricsMethodName",
        "SendGameMetricsParameterCount",
        "SendTableMethodName",
        "SendTableParameterCount",
    ):
        if needed not in block:
            errors.append(f"GameSymbols.ModBugReporting: missing {needed}")
        if f"GameSymbols.ModBugReporting.{needed}" not in telemetry:
            errors.append(f"NativeTelemetryBlock.cs: does not use GameSymbols.ModBugReporting.{needed}")
    if "GameSymbols.ModBugReporting.ScreenStaticAutoSend" not in telemetry:
        errors.append("NativeTelemetryBlock.cs: the desync auto-report launcher is not blocked")
    # Supported builds may expose multiple desync launchers; first-match lookup can leave one unblocked.
    # Every consumer binds and patches all launchers discovered through the centralized symbol contract.
    for label, text in (("ModBugReportRedirect.cs", redirect), ("NativeTelemetryBlock.cs", telemetry)):
        if re.search(r"FindFirstMethodByNames\([^;]*ScreenStaticAutoSend", text, re.S):
            errors.append(f"{label}: ScreenStaticAutoSend looked up first-match; bind every launcher (FindAutoSendLaunchers)")
        if not re.search(r"FindAutoSendLaunchers\([^;]*GameSymbols\.ModBugReporting\.ScreenStaticAutoSend", text, re.S):
            errors.append(f"{label}: desync auto-send launchers must be bound through FindAutoSendLaunchers")
        if not re.search(r"foreach \(var launcher in launchers\)\s*harmony\.Patch\(launcher", text):
            errors.append(f"{label}: every bound desync auto-send launcher must be patched")
    finder = method_body(redirect, r"internal static MethodInfo\[\] FindAutoSendLaunchers\(")
    if finder is None or "GameMember.FindEveryMethodByNames" not in finder:
        errors.append("ModBugReportRedirect.FindAutoSendLaunchers: must require every launcher (GameMember.FindEveryMethodByNames)")
    for prefix_name in ("SendGameMetricsPrefix", "SendTablePrefix", "AutoReportPrefix", "SendReportPrefix"):
        body = method_body(telemetry, r"private static bool " + prefix_name + r"\(")
        if body is None:
            errors.append(f"NativeTelemetryBlock.cs: missing `private static bool {prefix_name}(`")
            continue
        if "return true" in body or not re.search(r"return false;\s*}\s*$", body) or "throw" in body:
            errors.append(f"NativeTelemetryBlock.{prefix_name}: must end with `return false;`, never return true or throw")
        if f"nameof({prefix_name})" not in telemetry:
            errors.append(f"NativeTelemetryBlock.cs: {prefix_name} is never patched")
    table = method_body(telemetry, r"private static bool SendTablePrefix\(")
    if table is not None and ("__result" not in table or "SetResult(true)" not in table or "catch" not in table):
        errors.append("NativeTelemetryBlock.SendTablePrefix: must answer with a completed true task inside try/catch")
    tele_register = method_body(telemetry, r"internal static void TryRegister\(")
    if tele_register is None:
        errors.append("NativeTelemetryBlock.cs: missing TryRegister")
    else:
        if "BlockNativeTelemetry" not in tele_register:
            errors.append("NativeTelemetryBlock.TryRegister: must be gated on cfg.BlockNativeTelemetry")
        if "catch" not in tele_register or "LogError" not in tele_register or "NOT BLOCKED" not in tele_register:
            errors.append("NativeTelemetryBlock.TryRegister: unbound hooks must be logged at error level as NOT BLOCKED, inside try/catch")
        if "GuardState.Redirecting" not in tele_register:
            errors.append("NativeTelemetryBlock.TryRegister: must leave SendReport to the redirect when it is redirecting")
    if re.search(r"\bthrow\b", telemetry):
        errors.append("NativeTelemetryBlock.cs: must not throw (it runs in Plugin.Load and in native call paths)")

    # 8. Registered from Plugin.Load, redirect first.
    plugin_cs = (plugin / "Plugin.cs").read_text(encoding="utf-8-sig")
    load = method_body(plugin_cs, r"public override void Load\(\)")
    redirect_call = "ModBugReportRedirect.TryRegister(_harmony, Log, cfg);"
    telemetry_call = "NativeTelemetryBlock.TryRegister(_harmony, Log, cfg);"
    if load is None or redirect_call not in load:
        errors.append("Plugin.Load: must call ModBugReportRedirect.TryRegister(_harmony, Log, cfg)")
    elif telemetry_call not in load or load.find(telemetry_call) < load.find(redirect_call):
        errors.append("Plugin.Load: must call NativeTelemetryBlock.TryRegister(_harmony, Log, cfg) after the redirect")
    else:
        guard_call = "NativeAnalyticsHostGuard.TryRegister(_harmony, Log, cfg);"
        notice_call = "NativeAnalyticsHostGuard.ShowStateWarningIfNeeded(cfg);"
        if not (load.find(telemetry_call) < load.find(guard_call) < load.find(notice_call)) or load.find(guard_call) < 0:
            errors.append("Plugin.Load: must register the analytics host guard, then the state notice, after the telemetry block")

    # 9. The doc keeps a supervised reference checklist; it is not a shipping proof claim.
    doc = repo / "docs" / "mod_bug_reporting.md"
    doc_text = doc.read_text(encoding="utf-8-sig") if doc.is_file() else ""
    if not re.search(r"^## Supervised test\s*$", doc_text, flags=re.M):
        errors.append("docs/mod_bug_reporting.md: missing the `## Supervised test` reference section")
    for required in (
        "## Submission Contract",
        "A recent form-open timestamp is not submission consent.",
        "A locally finalized ZIP is not remote success.",
        "The player must explicitly consent",
        "ordinary no-argument tests remain offline",
    ):
        if required not in doc_text:
            errors.append(f"docs/mod_bug_reporting.md: missing submission/proof boundary `{required}`")

    errors.extend(validate_submission_surface(plugin, redirect, block))
    errors.extend(validate_current_report_symbol_scopes(plugin))
    errors.extend(validate_probe_options(repo / "tools" / "google_bug_report_relay"))
    errors.extend(validate_google_pilot(repo))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate(args.repo_root.resolve())
    if errors:
        for error in errors:
            print(f"mod bug reporting contract: {error}", file=sys.stderr)
        return 1
    print("mod bug reporting contract: OK (source/static + offline fixtures; gate made no cloud or game calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
