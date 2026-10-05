using System.Text.Json;

namespace Mimas.Monitor;

internal static class SelfTests
{
    public static void Run()
    {
        var product = new ProductSignature
        {
            Id = "product-1", Name = "Example Helper", Executables = ["example-helper.exe"],
            WindowTitles = ["Example Helper*"], Publishers = ["Example Company"]
        };
        var catalog = new CatalogResponse { Products = [product] };
        var largeVersion = JsonSerializer.Deserialize<CatalogResponse>("{\"version\":1780850000000,\"products\":[]}");
        Assert(largeVersion?.Version == 1780850000000, "catalog epoch-millisecond version");
        Assert(SignatureMatcher.ExecutableMatches(product, "example-helper.exe", "Example Company"), "exact executable");
        Assert(!SignatureMatcher.ExecutableMatches(product, "not-example-helper.exe", "Example Company"), "no substring executable");
        Assert(!SignatureMatcher.ExecutableMatches(product, "example-helper.exe", "Other Company"), "publisher");
        Assert(SignatureMatcher.WindowMatches(product, "Example Helper - session", "example-helper.exe", "Example Company"), "title prefix");
        Assert(!SignatureMatcher.WindowMatches(product, "Fake Example Helper", "example-helper.exe", "Example Company"), "title anchoring");
        var titleOnly = new ProductSignature { Id = "title-only", WindowTitles = ["Example Helper*"] };
        Assert(!SignatureMatcher.WindowMatches(titleOnly, "Example Helper - browser tab", "chrome.exe", null),
            "title-only browser window is not native helper evidence");

        var browser = new WindowSnapshot(1, "chrome.exe", null, "mimas — интервью", new ScreenRect(0, 0, 1000, 800), false, false, 1);
        var overlay = new WindowSnapshot(2, "example-helper.exe", "Example Company", "Example Helper - session", new ScreenRect(500, 100, 800, 500), true, true, 0);
        var found = MonitorDetector.Detect(catalog, new DesktopSnapshot(
            [new ProcessSnapshot("example-helper.exe", "Example Company")], [overlay, browser]));
        Assert(found.Contains(new ObservationKey(product.Id, "running_process")), "process event");
        Assert(found.Contains(new ObservationKey(product.Id, "foreground_window")), "foreground event");
        Assert(found.Contains(new ObservationKey(product.Id, "topmost_overlay")), "overlay event");
        var behind = MonitorDetector.Detect(catalog, new DesktopSnapshot([], [overlay with { ZIndex = 2, IsForeground = false }, browser]));
        Assert(!behind.Contains(new ObservationKey(product.Id, "topmost_overlay")), "behind browser is not overlay");
        Console.WriteLine("Windows monitor self-tests passed.");
    }

    private static void Assert(bool result, string name)
    {
        if (!result) throw new InvalidOperationException($"Self-test failed: {name}");
    }
}
