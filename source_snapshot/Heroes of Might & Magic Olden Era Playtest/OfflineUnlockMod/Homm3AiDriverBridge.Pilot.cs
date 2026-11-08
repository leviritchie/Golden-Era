using System;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

internal static partial class Homm3AiDriverBridge
{
	private const string PilotGrepKey = "HOMM3_AI_PILOT";
	private const int InputKeyDown = 0x0000;
	private const int InputKeyUp = 0x0002;
	private const int InputMouse = 0;
	private const uint MouseEventLeftDown = 0x0002;
	private const uint MouseEventLeftUp = 0x0004;

	internal static string BuildPilotKeyResponse(string id, string requestJson)
	{
		var key = ReadString(requestJson, "key");
		var phase = ReadString(requestJson, "phase") ?? "tap";
		if (string.IsNullOrWhiteSpace(key))
			return ErrorResponse(id, "bad_request", "pilot_key requires key (virtual-key name such as Escape, Return, A, F1).");
		if (!TryResolveVirtualKey(key, out var vk, out var resolveError))
			return ErrorResponse(id, "unsupported_key", resolveError ?? "Unsupported key.");
		if (!string.Equals(phase, "tap", StringComparison.Ordinal)
		    && !string.Equals(phase, "down", StringComparison.Ordinal)
		    && !string.Equals(phase, "up", StringComparison.Ordinal))
			return ErrorResponse(id, "bad_request", "pilot_key phase must be tap, down, or up.");

		if (!TryFocusGameWindow(out var focusError))
			return ErrorResponse(id, "pilot_focus_failed", focusError ?? "Could not focus the game window.");
		// One route: Win32 SendInput keyboard events (human-parity OS injection).
		if (!TrySendVirtualKey(vk, phase, out var sendError))
			return ErrorResponse(id, "pilot_key_failed", sendError ?? "SendInput keyboard injection failed.");

		_log?.LogWarning(PilotGrepKey + " pilot_key key=" + key + " vk=" + vk.ToString("X2", CultureInfo.InvariantCulture) + " phase=" + phase);
		var hover = BuildHoverSnapshotJson(writeEventFile: false);
		return OkResponse(id,
			"\"command\":\"pilot_key\","
			+ "\"route\":\"win32_sendinput_key\","
			+ "\"proof\":\"source-prepared\","
			+ "\"key\":\"" + EscapeJson(key) + "\","
			+ "\"virtualKey\":" + vk.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"phase\":\"" + EscapeJson(phase) + "\","
			+ "\"frame\":" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "")) + "\","
			+ "\"postHover\":" + hover);
	}

	internal static string BuildPilotPointerMoveResponse(string id, string requestJson)
	{
		if (!TryReadScreenPoint(requestJson, out var x, out var y, out var pointError))
			return ErrorResponse(id, "bad_request", pointError ?? "pilot_pointer_move requires numeric x and y screen coordinates.");
		if (!TryFocusGameWindow(out var focusError))
			return ErrorResponse(id, "pilot_focus_failed", focusError ?? "Could not focus the game window.");
		if (!TrySetCursorScreenPoint(x, y, out var moveError))
			return ErrorResponse(id, "pilot_pointer_move_failed", moveError ?? "SetCursorPos failed.");

		_log?.LogWarning(PilotGrepKey + " pilot_pointer_move x=" + x.ToString("0.###", CultureInfo.InvariantCulture) + " y=" + y.ToString("0.###", CultureInfo.InvariantCulture));
		var hover = BuildHoverSnapshotJson(writeEventFile: true);
		return OkResponse(id,
			"\"command\":\"pilot_pointer_move\","
			+ "\"route\":\"win32_setcursorpos\","
			+ "\"proof\":\"source-prepared\","
			+ "\"x\":" + x.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"y\":" + y.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"frame\":" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "")) + "\","
			+ "\"postHover\":" + hover);
	}

	private static int _pendingMouseUpFrame = int.MinValue;
	private static bool _pendingMouseUp;

	internal static void TickPilotInput()
	{
		if (!_pendingMouseUp)
			return;
		if (Time.frameCount < _pendingMouseUpFrame)
			return;
		_pendingMouseUp = false;
		_pendingMouseUpFrame = int.MinValue;
		if (!TrySendMouseButton(up: true, out var upError))
			_log?.LogWarning(PilotGrepKey + " deferred mouse-up failed: " + upError);
		else
			_log?.LogWarning(PilotGrepKey + " deferred mouse-up frame=" + Time.frameCount.ToString(CultureInfo.InvariantCulture));
	}

	internal static string BuildPilotClickResponse(string id, string requestJson)
	{
		if (!TryReadScreenPoint(requestJson, out var x, out var y, out var pointError))
			return ErrorResponse(id, "bad_request", pointError ?? "pilot_click requires numeric x and y screen coordinates.");
		var button = ReadString(requestJson, "button") ?? "left";
		if (!string.Equals(button, "left", StringComparison.Ordinal))
			return ErrorResponse(id, "unsupported_button", "pilot_click currently exposes only button=left. RMB remains absent until proven.");

		// Human-parity route: focus, SetCursorPos, mouse-down now, mouse-up next frame.
		// Spanning frames lets Unity Input System / world Update see a real press duration.
		if (!TryFocusGameWindow(out var focusError))
			return ErrorResponse(id, "pilot_focus_failed", focusError ?? "Could not focus the game window.");
		if (!TrySetCursorScreenPoint(x, y, out var moveError))
			return ErrorResponse(id, "pilot_click_failed", moveError ?? "SetCursorPos failed before click.");
		if (!TrySendMouseButton(up: false, out var downError))
			return ErrorResponse(id, "pilot_click_failed", downError ?? "SendInput mouse-down failed.");

		_pendingMouseUp = true;
		_pendingMouseUpFrame = Time.frameCount + 1;

		_log?.LogWarning(PilotGrepKey + " pilot_click x=" + x.ToString("0.###", CultureInfo.InvariantCulture)
			+ " y=" + y.ToString("0.###", CultureInfo.InvariantCulture)
			+ " route=win32_sendinput_mouse_deferred sizeofNativeInput="
			+ Marshal.SizeOf<NativeInput>().ToString(CultureInfo.InvariantCulture));
		var hover = BuildHoverSnapshotJson(writeEventFile: true);
		return OkResponse(id,
			"\"command\":\"pilot_click\","
			+ "\"route\":\"win32_sendinput_mouse_deferred\","
			+ "\"proof\":\"source-prepared\","
			+ "\"x\":" + x.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"y\":" + y.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"button\":\"left\","
			+ "\"mouseUpFrame\":" + _pendingMouseUpFrame.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"nativeInputBytes\":" + Marshal.SizeOf<NativeInput>().ToString(CultureInfo.InvariantCulture) + ","
			+ "\"frame\":" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "")) + "\","
			+ "\"postHover\":" + hover);
	}

	private static bool TryReadScreenPoint(string requestJson, out float x, out float y, out string error)
	{
		x = 0f;
		y = 0f;
		error = null;
		if (!TryReadFloat(requestJson, "x", out x) || !TryReadFloat(requestJson, "y", out y))
		{
			error = "Missing or non-numeric x/y.";
			return false;
		}
		if (x < 0 || y < 0 || x > Screen.width || y > Screen.height)
		{
			error = "Screen point out of bounds for current game window ("
				+ Screen.width.ToString(CultureInfo.InvariantCulture) + "x"
				+ Screen.height.ToString(CultureInfo.InvariantCulture) + ").";
			return false;
		}
		return true;
	}

	private static bool TryReadFloat(string json, string key, out float value)
	{
		value = 0f;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return false;
		var match = System.Text.RegularExpressions.Regex.Match(
			json,
			"\\\"" + System.Text.RegularExpressions.Regex.Escape(key) + "\\\"\\s*:\\s*(?<v>-?\\d+(?:\\.\\d+)?)");
		return match.Success && float.TryParse(match.Groups["v"].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
	}

	private static bool TryResolveVirtualKey(string key, out byte vk, out string error)
	{
		vk = 0;
		error = null;
		var normalized = (key ?? "").Trim();
		if (normalized.Length == 1)
		{
			var c = char.ToUpperInvariant(normalized[0]);
			if (c >= 'A' && c <= 'Z')
			{
				vk = (byte)c;
				return true;
			}
			if (c >= '0' && c <= '9')
			{
				vk = (byte)c;
				return true;
			}
		}
		switch (normalized.ToLowerInvariant())
		{
			case "escape":
			case "esc":
				vk = 0x1B;
				return true;
			case "return":
			case "enter":
				vk = 0x0D;
				return true;
			case "space":
				vk = 0x20;
				return true;
			case "tab":
				vk = 0x09;
				return true;
			case "backspace":
				vk = 0x08;
				return true;
			case "left":
				vk = 0x25;
				return true;
			case "up":
				vk = 0x26;
				return true;
			case "right":
				vk = 0x27;
				return true;
			case "down":
				vk = 0x28;
				return true;
			case "f1":
				vk = 0x70;
				return true;
			case "f2":
				vk = 0x71;
				return true;
			case "f3":
				vk = 0x72;
				return true;
			case "f4":
				vk = 0x73;
				return true;
			case "f5":
				vk = 0x74;
				return true;
			case "w":
				vk = (byte)'W';
				return true;
			case "a":
				vk = (byte)'A';
				return true;
			case "s":
				vk = (byte)'S';
				return true;
			case "d":
				vk = (byte)'D';
				return true;
			default:
				error = "Unsupported virtual-key name: " + normalized;
				return false;
		}
	}

	private static bool TrySendVirtualKey(byte vk, string phase, out string error)
	{
		error = null;
		try
		{
			if (string.Equals(phase, "down", StringComparison.Ordinal))
				return SendKey(vk, true, out error);
			if (string.Equals(phase, "up", StringComparison.Ordinal))
				return SendKey(vk, false, out error);
			if (!SendKey(vk, true, out error))
				return false;
			return SendKey(vk, false, out error);
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool SendKey(byte vk, bool down, out string error)
	{
		error = null;
		var input = new InputUnion();
		input.ki = new KeybdInput
		{
			wVk = vk,
			wScan = 0,
			dwFlags = down ? (uint)InputKeyDown : (uint)InputKeyUp,
			time = 0,
			dwExtraInfo = IntPtr.Zero
		};
		var inputs = new[]
		{
			new NativeInput
			{
				type = 1, // INPUT_KEYBOARD
				padding = 0,
				U = input
			}
		};
		var sent = SendInput(1, inputs, Marshal.SizeOf<NativeInput>());
		if (sent != 1)
		{
			error = "SendInput returned " + sent.ToString(CultureInfo.InvariantCulture) + ".";
			return false;
		}
		return true;
	}

	private static bool TrySendLeftClick(out string error)
	{
		if (!TrySendMouseButton(up: false, out error))
			return false;
		return TrySendMouseButton(up: true, out error);
	}

	private static bool TrySendMouseButton(bool up, out string error)
	{
		error = null;
		try
		{
			var union = new InputUnion();
			union.mi = new MouseInput
			{
				dx = 0,
				dy = 0,
				mouseData = 0,
				dwFlags = up ? MouseEventLeftUp : MouseEventLeftDown,
				time = 0,
				dwExtraInfo = IntPtr.Zero
			};
			var inputs = new[]
			{
				new NativeInput { type = InputMouse, padding = 0, U = union }
			};
			var sent = SendInput(1, inputs, Marshal.SizeOf<NativeInput>());
			if (sent != 1)
			{
				error = "SendInput mouse returned " + sent.ToString(CultureInfo.InvariantCulture)
					+ " sizeof=" + Marshal.SizeOf<NativeInput>().ToString(CultureInfo.InvariantCulture) + ".";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryFocusGameWindow(out string error)
	{
		error = null;
		try
		{
			var hwnd = ResolveGameWindowHandle();
			if (hwnd == IntPtr.Zero)
			{
				error = "Game main window handle is null.";
				return false;
			}

			ShowWindow(hwnd, SwRestore);
			AllowSetForegroundWindow(AsinProcess);
			if (GetForegroundWindow() == hwnd)
				return true;

			var foreground = GetForegroundWindow();
			var currentThread = GetCurrentThreadId();
			var foregroundThread = GetWindowThreadProcessId(foreground, IntPtr.Zero);
			var targetThread = GetWindowThreadProcessId(hwnd, IntPtr.Zero);
			if (foregroundThread != 0 && foregroundThread != currentThread)
				AttachThreadInput(currentThread, foregroundThread, true);
			if (targetThread != 0 && targetThread != currentThread)
				AttachThreadInput(currentThread, targetThread, true);
			BringWindowToTop(hwnd);
			var focused = SetForegroundWindow(hwnd);
			if (foregroundThread != 0 && foregroundThread != currentThread)
				AttachThreadInput(currentThread, foregroundThread, false);
			if (targetThread != 0 && targetThread != currentThread)
				AttachThreadInput(currentThread, targetThread, false);

			if (GetForegroundWindow() == hwnd)
				return true;
			if (!focused)
			{
				error = "SetForegroundWindow failed and game is not foreground.";
				return false;
			}
			error = "Game window is not foreground after focus attempt.";
			return false;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static IntPtr ResolveGameWindowHandle()
	{
		try
		{
			var handle = Process.GetCurrentProcess().MainWindowHandle;
			if (handle != IntPtr.Zero)
				return handle;
		}
		catch { }
		return GetActiveWindow();
	}

	private static bool TrySetCursorScreenPoint(float unityX, float unityY, out string error)
	{
		error = null;
		try
		{
			var hwnd = ResolveGameWindowHandle();
			if (hwnd == IntPtr.Zero)
			{
				error = "Game window handle is null; cannot map Unity screen coordinates.";
				return false;
			}
			if (!GetClientRect(hwnd, out var client))
			{
				error = "GetClientRect failed.";
				return false;
			}
			var clientHeight = client.Bottom - client.Top;
			var clientWidth = client.Right - client.Left;
			if (clientWidth <= 0 || clientHeight <= 0)
			{
				error = "Game client rect has non-positive size.";
				return false;
			}

			// Unity screen origin is bottom-left; Win32 client origin is top-left.
			var scaleX = clientWidth / (float)Math.Max(1, Screen.width);
			var scaleY = clientHeight / (float)Math.Max(1, Screen.height);
			var clientX = (int)Math.Round(unityX * scaleX);
			var clientY = (int)Math.Round((Screen.height - unityY) * scaleY);
			var point = new POINT { X = clientX, Y = clientY };
			if (!ClientToScreen(hwnd, ref point))
			{
				error = "ClientToScreen failed.";
				return false;
			}
			if (!SetCursorPos(point.X, point.Y))
			{
				error = "SetCursorPos failed.";
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	[DllImport("user32.dll")]
	private static extern uint SendInput(uint nInputs, NativeInput[] pInputs, int cbSize);

	[DllImport("user32.dll")]
	private static extern bool SetCursorPos(int x, int y);

	[DllImport("user32.dll")]
	private static extern IntPtr GetActiveWindow();

	[DllImport("user32.dll")]
	private static extern IntPtr GetForegroundWindow();

	[DllImport("user32.dll")]
	private static extern bool SetForegroundWindow(IntPtr hWnd);

	[DllImport("user32.dll")]
	private static extern bool BringWindowToTop(IntPtr hWnd);

	[DllImport("user32.dll")]
	private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

	[DllImport("user32.dll")]
	private static extern bool AllowSetForegroundWindow(int dwProcessId);

	[DllImport("user32.dll")]
	private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

	[DllImport("user32.dll")]
	private static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr lpdwProcessId);

	[DllImport("kernel32.dll")]
	private static extern uint GetCurrentThreadId();

	private const int SwRestore = 9;
	private const int AsinProcess = -1;

	[DllImport("user32.dll")]
	private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

	[DllImport("user32.dll")]
	private static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

	[StructLayout(LayoutKind.Sequential)]
	private struct NativeInput
	{
		public int type;
		public int padding; // x64: INPUT has 4 bytes of padding before the union
		public InputUnion U;
	}

	[StructLayout(LayoutKind.Explicit)]
	private struct InputUnion
	{
		[FieldOffset(0)] public MouseInput mi;
		[FieldOffset(0)] public KeybdInput ki;
	}

	[StructLayout(LayoutKind.Sequential)]
	private struct MouseInput
	{
		public int dx;
		public int dy;
		public uint mouseData;
		public uint dwFlags;
		public uint time;
		public IntPtr dwExtraInfo;
	}

	[StructLayout(LayoutKind.Sequential)]
	private struct KeybdInput
	{
		public ushort wVk;
		public ushort wScan;
		public uint dwFlags;
		public uint time;
		public IntPtr dwExtraInfo;
	}

	[StructLayout(LayoutKind.Sequential)]
	private struct RECT
	{
		public int Left;
		public int Top;
		public int Right;
		public int Bottom;
	}

	[StructLayout(LayoutKind.Sequential)]
	private struct POINT
	{
		public int X;
		public int Y;
	}
}
