using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class KdeWindowsInput : IKdeInputSink
{
    private readonly object gate = new();
    private uint heldUp;
    internal bool Available => OperatingSystem.IsWindows() && InteractiveDesktop();
    public bool Keyboard => Available;
    private static readonly ushort[] SpecialKeys = [0, 0x08, 0x09, 0x0d, 0x25, 0x26, 0x27, 0x28,
        0x21, 0x22, 0x24, 0x23, 0x0d, 0x2e, 0x1b, 0x2c, 0x91, 0xa2, 0xa4, 0xa0, 0x5b,
        0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x7b];

    [StructLayout(LayoutKind.Sequential)] private struct Mouse
    { internal int X, Y; internal uint Data, Flags, Time; internal UIntPtr Extra; }
    [StructLayout(LayoutKind.Sequential)] private struct Key
    { internal ushort Virtual, Scan; internal uint Flags, Time; internal UIntPtr Extra; }
    [StructLayout(LayoutKind.Explicit)] private struct Union
    { [FieldOffset(0)] internal Mouse Mouse; [FieldOffset(0)] internal Key Key; }
    [StructLayout(LayoutKind.Sequential)] private struct Input
    { internal uint Type; internal Union Data; }

    [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(uint count, Input[] inputs, int size);
    [DllImport("user32.dll")] private static extern int GetSystemMetrics(int metric);
    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern short VkKeyScanEx(char key, IntPtr layout);
    [DllImport("user32.dll")] private static extern IntPtr GetKeyboardLayout(uint thread);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] private static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetUserObjectInformation(IntPtr handle, int index, StringBuilder value, uint length, out uint needed);

    private static bool InteractiveDesktop()
    {
        var desktop = OpenInputDesktop(0, false, 1);
        if (desktop == IntPtr.Zero) return false;
        try
        {
            var name = new StringBuilder(256);
            return GetUserObjectInformation(desktop, 2, name, 512, out _) && name.ToString().Equals("Default", StringComparison.OrdinalIgnoreCase);
        }
        finally { CloseDesktop(desktop); }
    }

    private static Input MouseEvent(uint flags, int x = 0, int y = 0, uint data = 0) =>
        new() { Type = 0, Data = new Union { Mouse = new Mouse { Flags = flags, X = x, Y = y, Data = data } } };
    private static Input KeyEvent(ushort key, bool up = false, bool unicode = false) =>
        new() { Type = 1, Data = new Union { Key = new Key { Virtual = unicode ? (ushort)0 : key,
            Scan = unicode ? key : (ushort)0, Flags = (up ? 2u : 0u) | (unicode ? 4u : 0u) |
                (!unicode && (key is >= 0x21 and <= 0x28 or 0x2c or 0x2d or 0x2e or 0x5b or 0x5c) ? 1u : 0u) } } };

    private static void Send(params Input[] inputs)
    {
        if (!InteractiveDesktop()) throw new InvalidOperationException("remote_input_desktop_unavailable");
        if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>()) != inputs.Length)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "remote_input_rejected");
    }

    private void Click(uint down, uint up)
    {
        Send(MouseEvent(down));
        try { Send(MouseEvent(up)); if (heldUp == up) heldUp = 0; }
        catch { heldUp = up; throw; }
    }

    public void Apply(JsonObject body)
    {
        body = KdeInputProtocol.Input(body);
        var data = JsonSerializer.SerializeToElement(body);
        bool Flag(string name) => data.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        int Axis(string name) => data.TryGetProperty(name, out var value) ? (int)value.GetDouble() : 0;
        lock (gate)
        {
            if (!Available) throw new InvalidOperationException("remote_input_desktop_unavailable");
            var swapped = GetSystemMetrics(23) != 0;
            uint down = swapped ? 8u : 2u, up = swapped ? 16u : 4u;
            if (Flag("singlehold"))
            {
                if (heldUp == 0 && (GetAsyncKeyState(swapped ? 2 : 1) & 0x8000) == 0) { Send(MouseEvent(down)); heldUp = up; }
            }
            else if (Flag("singlerelease")) Release();
            else if (Flag("singleclick") || Flag("doubleclick")) { Click(down, up); if (Flag("doubleclick")) Click(down, up); }
            else if (Flag("middleclick")) Click(32, 64);
            else if (Flag("rightclick")) Click(swapped ? 2u : 8u, swapped ? 4u : 16u);
            else if (Flag("scroll"))
            {
                if (Axis("dy") != 0) Send(MouseEvent(0x0800, data: unchecked((uint)Axis("dy"))));
                if (Axis("dx") != 0) Send(MouseEvent(0x1000, data: unchecked((uint)Axis("dx"))));
            }
            else if (body.ContainsKey("key") || body.ContainsKey("specialKey")) KeyboardInput(data);
            else if (body.ContainsKey("x"))
            {
                var left = GetSystemMetrics(76); var top = GetSystemMetrics(77);
                var width = Math.Max(1, GetSystemMetrics(78) - 1); var height = Math.Max(1, GetSystemMetrics(79) - 1);
                var x = (int)(Math.Clamp((long)Axis("x") - left, 0, width) * 65535 / width);
                var y = (int)(Math.Clamp((long)Axis("y") - top, 0, height) * 65535 / height);
                Send(MouseEvent(0x0001 | 0x8000 | 0x4000, x, y));
            }
            else Send(MouseEvent(1, Axis("dx"), Axis("dy")));
        }
    }

    private static void KeyboardInput(JsonElement data)
    {
        var pressed = new List<ushort>();
        var text = data.TryGetProperty("key", out var textNode) ? textNode.GetString()! : "";
        var modified = KdeInputProtocol.Modifiers.Any(name => data.TryGetProperty(name, out var value) && value.GetBoolean());
        var layout = GetKeyboardLayout(GetWindowThreadProcessId(GetForegroundWindow(), out _));
        var mapped = modified ? text.Select(character => VkKeyScanEx(character, layout)).ToArray() : [];
        if (mapped.Any(key => key == -1)) throw new InvalidOperationException("remote_input_character_unavailable");
        void Modifier(ushort code)
        {
            if (!pressed.Contains(code) && (GetAsyncKeyState(code) & 0x8000) == 0) { Send(KeyEvent(code)); pressed.Add(code); }
        }
        try
        {
            foreach (var (name, code) in new[] { ("ctrl", (ushort)0xa2), ("alt", (ushort)0xa4), ("shift", (ushort)0xa0), ("super", (ushort)0x5b) })
                if (data.TryGetProperty(name, out var flag) && flag.GetBoolean()) Modifier(code);
            if (data.TryGetProperty("specialKey", out var special))
            {
                var code = SpecialKeys[special.GetInt32()];
                Send(KeyEvent(code));
                try { Send(KeyEvent(code, up: true)); }
                catch { pressed.Add(code); throw; }
            }
            else
            {
                for (var index = 0; index < text.Length; index++)
                {
                    var character = text[index];
                    if (!modified) Send(KeyEvent(character, unicode: true), KeyEvent(character, up: true, unicode: true));
                    else
                    {
                        var key = mapped[index];
                        var initial = pressed.Count;
                        if ((key & 0x100) != 0) Modifier(0xa0);
                        if ((key & 0x200) != 0) Modifier(0xa2);
                        if ((key & 0x400) != 0) Modifier(0xa4);
                        var code = (ushort)(key & 255);
                        Send(KeyEvent(code));
                        try { Send(KeyEvent(code, up: true)); }
                        catch { pressed.Add(code); throw; }
                        for (var p = pressed.Count - 1; p >= initial; p--)
                        {
                            Send(KeyEvent(pressed[p], up: true)); pressed.RemoveAt(p);
                        }
                    }
                }
            }
        }
        finally
        {
            Exception? failure = null;
            foreach (var code in pressed.AsEnumerable().Reverse())
                try { Send(KeyEvent(code, up: true)); } catch (Exception error) { failure ??= error; }
            if (failure is not null) throw failure;
        }
    }

    public void Release()
    {
        lock (gate)
        {
            if (heldUp == 0) return;
            Send(MouseEvent(heldUp)); heldUp = 0;
        }
    }

    public void Dispose() => Release();
}
