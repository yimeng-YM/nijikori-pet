using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class NijiComputer {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] public struct Mouse {
        public int dx, dy; public uint data, flags, time; public UIntPtr extra;
    }
    [StructLayout(LayoutKind.Sequential)] public struct Keyboard {
        public ushort vk, scan; public uint flags, time; public UIntPtr extra;
    }
    [StructLayout(LayoutKind.Explicit)] public struct Payload {
        [FieldOffset(0)] public Mouse mouse;
        [FieldOffset(0)] public Keyboard keyboard;
    }
    [StructLayout(LayoutKind.Sequential)] public struct Input { public uint type; public Payload value; }
    [StructLayout(LayoutKind.Sequential)] public struct BitmapInfoHeader {
        public uint biSize; public int biWidth; public int biHeight; public ushort biPlanes; public ushort biBitCount;
        public uint biCompression; public uint biSizeImage; public int biXPelsPerMeter; public int biYPelsPerMeter;
        public uint biClrUsed; public uint biClrImportant;
    }
    public class Window { public long id; public uint process_id; public string title; public string process; }
    public delegate bool EnumProc(IntPtr hwnd, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr SetActiveWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint attach, uint attachTo, bool join);
    [DllImport("user32.dll")] static extern uint MapVirtualKey(uint code, uint mapType);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] static extern uint SendInput(uint count, Input[] inputs, int size);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPhysicalPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr hwnd, uint flags);
    [DllImport("user32.dll")] static extern IntPtr GetWindowDC(IntPtr hwnd);
    [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr hwnd, IntPtr hdc);
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetWindowDpiAwarenessContext(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool AreDpiAwarenessContextsEqual(IntPtr a, IntPtr b);
    [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("gdi32.dll")] static extern int GetDeviceCaps(IntPtr hdc, int index);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int width, int height);
    [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr hdc, IntPtr obj);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr obj);
    [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr hdc);
    [DllImport("gdi32.dll")] static extern int GetDIBits(IntPtr hdc, IntPtr hbm, uint start, uint lines, byte[] bits, ref BitmapInfoHeader header, uint usage);
    public static int InputSize() { return Marshal.SizeOf(typeof(Input)); }
    /// Prefer PER_MONITOR_AWARE_V2 so physical coordinates stay correct on
    /// monitors with different scaling; fall back to system DPI awareness.
    public static string MakeDpiAware() {
        try { if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return "per-monitor-v2"; } catch { }
        try { if (SetProcessDpiAwarenessContext(new IntPtr(-3))) return "per-monitor"; } catch { }
        try { if (SetProcessDPIAware()) return "system"; } catch { }
        return "none";
    }
    /// Whole virtual desktop (all monitors), in physical pixels.
    public static Rect VirtualScreen() {
        return new Rect {
            Left = GetSystemMetrics(76), Top = GetSystemMetrics(77),
            Right = GetSystemMetrics(76) + GetSystemMetrics(78),
            Bottom = GetSystemMetrics(77) + GetSystemMetrics(79)
        };
    }
    /// Effective DPI of a window (96 when unknown).
    public static uint WindowDpi(IntPtr hwnd) {
        try { uint dpi = GetDpiForWindow(hwnd); return dpi == 0 ? 96u : dpi; }
        catch { return 96u; }
    }
    /// DPI awareness context of a window (-1 unaware, -2 system, -3/ -4 per-monitor, -5 gdi-scaled, 0 unknown).
    public static int DpiAwareness(IntPtr hwnd) {
        try { return GetWindowDpiAwarenessContext(hwnd).ToInt32(); }
        catch { return 0; }
    }
    /// True for legacy DPI-unaware windows: PrintWindow renders them at their
    /// own logical size, so the render box must be scaled by the system DPI.
    public static bool IsDpiUnaware(IntPtr hwnd) {
        try {
            IntPtr ctx = GetWindowDpiAwarenessContext(hwnd);
            return AreDpiAwarenessContextsEqual(ctx, new IntPtr(-1))
                || AreDpiAwarenessContextsEqual(ctx, new IntPtr(-5));
        } catch { return false; }
    }
    /// Desktop DPI (LOGPIXELSX), 96 when unavailable.
    public static int SystemDpi() {
        try {
            IntPtr dc = GetDC(IntPtr.Zero);
            int dpi = GetDeviceCaps(dc, 88);
            ReleaseDC(IntPtr.Zero, dc);
            return dpi <= 0 ? 96 : dpi;
        } catch { return 96; }
    }
    public static long Foreground() { return GetForegroundWindow().ToInt64(); }
    public static void CheckStop() {
        if ((GetAsyncKeyState(0x1B) & 0x8000) != 0) throw new Exception("ESC held: stopped");
    }
    public static void Guard(IntPtr hwnd) {
        CheckStop();
        if (GetForegroundWindow() != hwnd) throw new Exception("Target is no longer foreground; observe again (another window stole focus)");
    }
    static bool WaitForeground(IntPtr hwnd, int milliseconds) {
        int deadline = Environment.TickCount + milliseconds;
        while (GetForegroundWindow() != hwnd && Environment.TickCount < deadline) Thread.Sleep(20);
        return GetForegroundWindow() == hwnd;
    }
    /// Bring a window to the front even when the caller does not own the current
    /// foreground window (normally the pet's own chat window).  Windows refuses a
    /// plain SetForegroundWindow in that case, so attach the input queues first.
    public static bool ForceForeground(IntPtr hwnd) {
        if (hwnd == IntPtr.Zero || !IsWindow(hwnd)) throw new Exception("Window no longer exists");
        if (GetForegroundWindow() == hwnd) return true;
        if (IsIconic(hwnd)) { ShowWindow(hwnd, 9); Thread.Sleep(150); }
        try { SetForegroundWindow(hwnd); } catch { }
        if (WaitForeground(hwnd, 250)) return true;
        uint ignored = 0;
        uint targetThread = GetWindowThreadProcessId(hwnd, out ignored);
        IntPtr foreground = GetForegroundWindow();
        uint foregroundThread = foreground == IntPtr.Zero ? 0u : GetWindowThreadProcessId(foreground, out ignored);
        uint current = GetCurrentThreadId();
        bool joinedForeground = false, joinedTarget = false;
        try {
            if (foregroundThread != 0 && foregroundThread != current)
                joinedForeground = AttachThreadInput(current, foregroundThread, true);
            if (targetThread != 0 && targetThread != current && targetThread != foregroundThread)
                joinedTarget = AttachThreadInput(current, targetThread, true);
            BringWindowToTop(hwnd);
            SetActiveWindow(hwnd);
            SetForegroundWindow(hwnd);
        } catch { } finally {
            if (joinedTarget) AttachThreadInput(current, targetThread, false);
            if (joinedForeground) AttachThreadInput(current, foregroundThread, false);
        }
        return WaitForeground(hwnd, 500);
    }
    /// Process id of the top-level window covering a physical screen point, or 0.
    /// Used to notice that the always-on-top pet is sitting over a click target.
    public static int ProcessIdAtPoint(int x, int y) {
        var point = new Point { X = x, Y = y };
        IntPtr hwnd = GetAncestor(WindowFromPoint(point), 2);
        if (hwnd == IntPtr.Zero) hwnd = WindowFromPoint(point);
        if (hwnd == IntPtr.Zero) return 0;
        uint pid = 0;
        GetWindowThreadProcessId(hwnd, out pid);
        return (int)pid;
    }
    public static void TargetPoint(IntPtr hwnd, int x, int y) {
        Guard(hwnd);
        var p = new Point { X=x, Y=y };
        if (GetAncestor(WindowFromPoint(p), 2) != hwnd) throw new Exception("Target point is covered by another window");
    }
    public static uint ProcessId(IntPtr hwnd) { uint pid; GetWindowThreadProcessId(hwnd, out pid); return pid; }
    public static Rect Bounds(IntPtr hwnd) {
        Rect r;
        if (!GetWindowRect(hwnd, out r)) throw new Exception("Window no longer exists");
        return r;
    }
    static string ProcessName(uint pid) {
        try { using (var p = System.Diagnostics.Process.GetProcessById((int)pid)) { return p.ProcessName; } }
        catch { return ""; }
    }
    public static Window[] Windows() {
        var result = new List<Window>();
        EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
            var text = new StringBuilder(1024);
            GetWindowText(hwnd, text, text.Capacity);
            if (IsWindowVisible(hwnd) && text.Length > 0) {
                uint pid = ProcessId(hwnd);
                result.Add(new Window { id=hwnd.ToInt64(), process_id=pid, title=text.ToString(), process=ProcessName(pid) });
            }
            return true;
        }, IntPtr.Zero);
        return result.ToArray();
    }
    static void Send(Input input) {
        if (SendInput(1, new Input[] { input }, InputSize()) != 1)
            throw new Exception("Windows rejected input (possibly privilege mismatch)");
    }
    public static void MouseEvent(uint flags, int data) {
        Send(new Input { type=0, value=new Payload { mouse=new Mouse { flags=flags, data=unchecked((uint)data) } } });
    }
    public static void KeyEvent(ushort vk, ushort scan, uint flags) {
        Send(new Input { type=1, value=new Payload { keyboard=new Keyboard { vk=vk, scan=scan, flags=flags } } });
    }
    public static ushort KeyCode(string key) {
        key=key.Trim().ToUpperInvariant();
        if (key.Length==1 && ((key[0]>='A' && key[0]<='Z') || (key[0]>='0' && key[0]<='9'))) return (ushort)key[0];
        int number;
        if (key.StartsWith("F") && Int32.TryParse(key.Substring(1), out number) && number>=1 && number<=12) return (ushort)(111+number);
        switch (key) {
            case "CTRL": return 17; case "ALT": return 18; case "SHIFT": return 16; case "WIN": return 91;
            case "ENTER": return 13; case "TAB": return 9; case "ESC": return 27; case "BACKSPACE": return 8;
            case "DELETE": return 46; case "SPACE": return 32; case "HOME": return 36; case "END": return 35;
            case "PAGEUP": return 33; case "PAGEDOWN": return 34; case "LEFT": return 37;
            case "RIGHT": return 39; case "UP": return 38; case "DOWN": return 40;
            default: throw new Exception("Unsupported key: " + key);
        }
    }
    static uint Extended(ushort key) { return ((key>=33 && key<=40) || key==46 || key==91) ? 1u : 0u; }
    public static void Chord(IntPtr hwnd, string keys) {
        var names=keys.Split(',');
        if (names.Length<1 || names.Length>4) throw new Exception("Use 1 to 4 keys");
        var codes=new List<ushort>();
        foreach (var name in names) { var code=KeyCode(name); if (codes.Contains(code)) throw new Exception("Duplicate key"); codes.Add(code); }
        var held=new List<ushort>();
        try {
            foreach (var code in codes) { Guard(hwnd); KeyEvent(code,0,Extended(code)); held.Add(code); }
        } finally {
            Exception releaseError=null;
            for (int i=held.Count-1;i>=0;i--) {
                try { KeyEvent(held[i],0,Extended(held[i])|2u); }
                catch (Exception ex) { releaseError=ex; }
            }
            if (releaseError!=null) throw releaseError;
        }
    }
    /// Key chord without a foreground-window guard: used for whole-screen
    /// operation, where the keys simply go to whatever window is focused.
    public static void ChordFree(string keys) {
        var names=keys.Split(',');
        if (names.Length<1 || names.Length>4) throw new Exception("Use 1 to 4 keys");
        var codes=new List<ushort>();
        foreach (var name in names) { var code=KeyCode(name); if (codes.Contains(code)) throw new Exception("Duplicate key"); codes.Add(code); }
        var held=new List<ushort>();
        try {
            foreach (var code in codes) { CheckStop(); KeyEvent(code,0,Extended(code)); held.Add(code); }
        } finally {
            Exception releaseError=null;
            for (int i=held.Count-1;i>=0;i--) {
                try { KeyEvent(held[i],0,Extended(held[i])|2u); }
                catch (Exception ex) { releaseError=ex; }
            }
            if (releaseError!=null) throw releaseError;
        }
    }
    /// Shared typing core.  Plain characters go out as KEYEVENTF_UNICODE, while
    /// newline/tab become real virtual keys with their scan code so editors and
    /// presentation apps (which translate WM_KEYDOWN themselves) see Enter/Tab.
    static void TypeCore(IntPtr hwnd, string text, bool guarded) {
        if (text.Length>1000) throw new Exception("Text limit is 1000 UTF-16 characters");
        foreach (char c in text) {
            if (c=='\r') continue;
            if (guarded) Guard(hwnd); else CheckStop();
            ushort vk, scan; uint flags;
            if (c=='\n') { vk = 13; scan = (ushort)MapVirtualKey(13, 0); flags = 0; }
            else if (c=='\t') { vk = 9; scan = (ushort)MapVirtualKey(9, 0); flags = 0; }
            else { vk = 0; scan = c; flags = 4u; }
            try { KeyEvent(vk,scan,flags); }
            finally { KeyEvent(vk,scan,flags|2u); }
            Thread.Sleep(c=='\n' || c=='\t' ? 30 : 2);
        }
    }
    /// Type text without the foreground-window guard (whole-screen operation).
    public static void TypeTextFree(string text) { TypeCore(IntPtr.Zero, text, false); }
    /// Type text into a specific window, re-checking that it stays foreground.
    public static void TypeText(IntPtr hwnd, string text) { TypeCore(hwnd, text, true); }
    /// Off-screen render of a window into top-down BGRA bytes (occlusion-free).
    public static byte[] CaptureBgra(IntPtr hwnd, int width, int height) {
        if (width <= 0 || height <= 0) throw new Exception("Invalid window size");
        IntPtr hwndDc = GetWindowDC(hwnd);
        if (hwndDc == IntPtr.Zero) throw new Exception("GetWindowDC failed");
        IntPtr mem = CreateCompatibleDC(hwndDc);
        IntPtr bmp = CreateCompatibleBitmap(hwndDc, width, height);
        IntPtr old = SelectObject(mem, bmp);
        try {
            bool ok = PrintWindow(hwnd, mem, 2);   // PW_RENDERFULLCONTENT
            if (!ok) ok = PrintWindow(hwnd, mem, 1); // PW_CLIENTONLY
            if (!ok) throw new Exception("PrintWindow failed");
            SelectObject(mem, old);                 // GetDIBits wants a deselected bitmap
            var header = new BitmapInfoHeader();
            header.biSize = 40; header.biWidth = width; header.biHeight = -height;
            header.biPlanes = 1; header.biBitCount = 32; header.biCompression = 0;
            var bits = new byte[width * height * 4];
            int got = GetDIBits(hwndDc, bmp, 0, (uint)height, bits, ref header, 0);
            if (got == 0) throw new Exception("GetDIBits failed");
            return bits;
        } finally {
            SelectObject(mem, old);
            DeleteObject(bmp);
            DeleteDC(mem);
            ReleaseDC(hwnd, hwndDc);
        }
    }
    /// True when a BGRA buffer is essentially one flat colour (bad GPU render).
    public static bool IsFlatPixels(byte[] bits) {
        if (bits == null || bits.Length < 16) return true;
        int step = 4 * Math.Max(1, bits.Length / 4096);
        int b0 = -1, g0 = -1, r0 = -1;
        for (int i = 0; i + 2 < bits.Length; i += step) {
            if (b0 < 0) { b0 = bits[i]; g0 = bits[i+1]; r0 = bits[i+2]; continue; }
            if (Math.Abs(bits[i]-b0) > 6 || Math.Abs(bits[i+1]-g0) > 6 || Math.Abs(bits[i+2]-r0) > 6) return false;
        }
        return true;
    }
}
