namespace Mimas.Monitor;

internal readonly record struct ScreenRect(int Left, int Top, int Right, int Bottom)
{
    public bool Intersects(ScreenRect other) =>
        Left < other.Right && Right > other.Left && Top < other.Bottom && Bottom > other.Top;
}

internal sealed record ProcessSnapshot(string Executable, string? Publisher);

internal sealed record WindowSnapshot(
    nint Handle, string Executable, string? Publisher, string Title,
    ScreenRect Bounds, bool IsTopmost, bool IsForeground, int ZIndex);

internal sealed record DesktopSnapshot(List<ProcessSnapshot> Processes, List<WindowSnapshot> Windows);

internal static class MonitorDetector
{
    public static HashSet<ObservationKey> Detect(CatalogResponse catalog, DesktopSnapshot snapshot)
    {
        var observed = new HashSet<ObservationKey>();
        var mimasWindows = snapshot.Windows.Where(window =>
            (window.Executable.Equals("chrome.exe", StringComparison.OrdinalIgnoreCase) ||
             window.Executable.Equals("msedge.exe", StringComparison.OrdinalIgnoreCase)) &&
            window.Title.Contains("mimas", StringComparison.OrdinalIgnoreCase)).ToList();

        foreach (var product in catalog.Products.Where(product => product.Id.Length > 0))
        {
            if (snapshot.Processes.Any(process => SignatureMatcher.ExecutableMatches(product, process.Executable, process.Publisher)))
                observed.Add(new ObservationKey(product.Id, "running_process"));

            foreach (var window in snapshot.Windows)
            {
                var matches = SignatureMatcher.ExecutableMatches(product, window.Executable, window.Publisher) ||
                              SignatureMatcher.WindowMatches(product, window.Title, window.Executable, window.Publisher);
                if (!matches) continue;
                if (window.IsForeground)
                    observed.Add(new ObservationKey(product.Id, "foreground_window"));
                if (window.IsTopmost && mimasWindows.Any(browser =>
                    browser.Handle != window.Handle && window.ZIndex < browser.ZIndex &&
                    window.Bounds.Intersects(browser.Bounds)))
                    observed.Add(new ObservationKey(product.Id, "topmost_overlay"));
            }
        }
        return observed;
    }
}
