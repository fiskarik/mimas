using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace Mimas.Monitor;

internal sealed class Win32Scanner
{
    private const int ExStyle = -20;
    private const long WsExTopmost = 0x8;
    private readonly HashSet<string> interestingExecutables = new(StringComparer.OrdinalIgnoreCase);

    public Win32Scanner(CatalogResponse catalog) => SetCatalog(catalog);

    public void SetCatalog(CatalogResponse catalog)
    {
        interestingExecutables.Clear();
        foreach (var executable in catalog.Products.SelectMany(product => product.Executables))
        {
            if (!string.IsNullOrWhiteSpace(executable))
                interestingExecutables.Add(executable.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                    ? executable.Trim() : executable.Trim() + ".exe");
        }
    }

    public DesktopSnapshot Capture()
    {
        var processes = new List<ProcessSnapshot>();
        var byPid = new Dictionary<uint, ProcessSnapshot>();
        foreach (var process in Process.GetProcesses())
        {
            using (process)
            {
                try
                {
                    var executable = process.ProcessName + ".exe";
                    var publisher = interestingExecutables.Contains(executable) ? GetCompanyName(process) : null;
                    var info = new ProcessSnapshot(executable, publisher);
                    processes.Add(info);
                    byPid[(uint)process.Id] = info;
                }
                catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // Protected or exited processes are inaccessible without elevation; never elevate.
                }
            }
        }

        var windows = new List<WindowSnapshot>();
        var foreground = GetForegroundWindow();
        EnumWindows((handle, _) =>
        {
            if (!IsWindowVisible(handle) || IsIconic(handle) || IsCloaked(handle) || !GetWindowRect(handle, out var rect))
                return true;
            if (rect.Right <= rect.Left || rect.Bottom <= rect.Top) return true;
            GetWindowThreadProcessId(handle, out var pid);
            if (!byPid.TryGetValue(pid, out var process)) return true;
            var length = Math.Min(GetWindowTextLength(handle), 2048);
            var title = new StringBuilder(length + 1);
            GetWindowText(handle, title, title.Capacity);
            var topmost = (GetWindowLongPtr(handle, ExStyle).ToInt64() & WsExTopmost) != 0;
            windows.Add(new WindowSnapshot(handle, process.Executable, process.Publisher, title.ToString(),
                new ScreenRect(rect.Left, rect.Top, rect.Right, rect.Bottom), topmost,
                handle == foreground, windows.Count));
            return true;
        }, nint.Zero);
        return new DesktopSnapshot(processes, windows);
    }

    private static string? GetCompanyName(Process process)
    {
        try
        {
            var path = process.MainModule?.FileName;
            return path is null ? null : FileVersionInfo.GetVersionInfo(path).CompanyName;
        }
        catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static bool IsCloaked(nint handle)
    {
        try { return DwmGetWindowAttribute(handle, 14, out var cloaked, sizeof(int)) == 0 && cloaked != 0; }
        catch (DllNotFoundException) { return false; }
    }

    private delegate bool EnumWindowsCallback(nint window, nint data);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsCallback callback, nint data);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(nint window);
    [DllImport("user32.dll")] private static extern bool IsIconic(nint window);
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(nint window, StringBuilder value, int capacity);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextLength(nint window);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint window, out uint processId);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(nint window, out NativeRect rectangle);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern nint GetWindowLongPtr(nint window, int index);
    [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(nint window, int attribute, out int value, int size);

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeRect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
}
