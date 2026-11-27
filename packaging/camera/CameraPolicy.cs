using System.Reflection;
using System.Text.Json;

// Finite compiled policy: no command-line URL, host list, file path or script.
internal sealed class CameraPolicy
{
    internal static readonly IReadOnlyDictionary<string, string> WatchPages = new Dictionary<string, string> {
        ["gpc-tannum-sands-live"] = "https://gpcl.com.au/environment/live-beach-cameras/tannum-sands-webcam/",
        ["gpc-1770-live"] = "https://gpcl.com.au/environment/live-beach-cameras/1770-webcam/",
        ["bsyc-seacliff-live"] = "https://www.ipcamlive.com/bsyc1080",
    };
    internal static readonly IReadOnlyDictionary<string, string> PlayerPages = new Dictionary<string, string> {
        ["gpc-tannum-sands-live"] = "https://widget.coastalcoms.com/video/005972b5-8290-420c-8527-9ce69bbcd2ec",
        ["gpc-1770-live"] = "https://widget.coastalcoms.com/video/e53407e0-915b-4964-b60a-638e1bd32d6d",
        // This camera does not permit a standalone IPCamLive embed. Keep the
        // original public document and its provider-created player unchanged.
        ["bsyc-seacliff-live"] = "https://www.ipcamlive.com/bsyc1080",
    };
    private static readonly string[] RetiredHosts = {
        "youtube.com", "youtube-nocookie.com", "youtu.be", "googlevideo.com", "ytimg.com", "kiwisdr.com",
    };
    internal string Id { get; }
    internal string WatchUrl { get; }
    internal string PlayerUrl { get; }
    internal IReadOnlySet<string> Hosts { get; }
    internal IReadOnlySet<string> FrameHosts { get; }

    private CameraPolicy(string id, string watchUrl, string playerUrl, HashSet<string> hosts, HashSet<string> frames)
    {
        Id = id; WatchUrl = watchUrl; PlayerUrl = playerUrl; Hosts = hosts; FrameHosts = frames;
    }

    internal static IReadOnlyDictionary<string, CameraPolicy> Load()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("GlobalPulse.Camera.camera_catalog.json")
            ?? throw new InvalidOperationException("Compiled camera catalog missing");
        using var document = JsonDocument.Parse(stream);
        var result = new Dictionary<string, CameraPolicy>(StringComparer.Ordinal);
        foreach (var row in document.RootElement.GetProperty("entries").EnumerateArray())
        {
            if (!row.TryGetProperty("playback", out var playback) || playback.GetString() != "live_video") continue;
            string id = row.GetProperty("id").GetString() ?? "";
            string url = row.GetProperty("url").GetString() ?? "";
            string playerUrl = row.GetProperty("player_url").GetString() ?? "";
            if (!WatchPages.TryGetValue(id, out var expected) || url != expected
                || !PlayerPages.TryGetValue(id, out var expectedPlayer) || playerUrl != expectedPlayer
                || row.GetProperty("type").GetString() != "webcam"
                || !row.GetProperty("manual_only").GetBoolean())
                throw new InvalidOperationException("Invalid compiled camera");
            var hosts = HostList(row.GetProperty("allowed_hosts"), 24);
            var frames = HostList(row.GetProperty("allowed_frame_hosts"), 12);
            if (!PublicUri(url, out var page) || !hosts.Contains(page!.IdnHost)
                || !PublicUri(playerUrl, out var player) || !hosts.Contains(player!.IdnHost)
                || !frames.IsSubsetOf(hosts) || result.ContainsKey(id))
                throw new InvalidOperationException("Invalid compiled camera admission");
            result.Add(id, new CameraPolicy(id, url, playerUrl, hosts, frames));
        }
        if (result.Count != WatchPages.Count || result.Count != PlayerPages.Count)
            throw new InvalidOperationException("Incomplete compiled camera catalog");
        return result;
    }

    private static HashSet<string> HostList(JsonElement values, int maximum)
    {
        if (values.ValueKind != JsonValueKind.Array || values.GetArrayLength() < 1 || values.GetArrayLength() > maximum)
            throw new InvalidOperationException("Invalid camera host list");
        var result = new HashSet<string>(StringComparer.Ordinal);
        foreach (var value in values.EnumerateArray())
        {
            string host = value.GetString() ?? "";
            if (host.Length == 0 || host != host.Trim() || host.IndexOfAny("/\\:@?#[]*".ToCharArray()) >= 0
                || !PublicUri("https://" + host + "/", out var uri) || uri!.IdnHost != host)
                throw new InvalidOperationException("Camera hosts must be exact public names");
            result.Add(host);
        }
        return result;
    }

    internal static bool PublicUri(string value, out Uri? uri)
    {
        uri = null;
        if (value.Length > 8192 || value.Any(char.IsControl) || value.Contains('\\')
            || !Uri.TryCreate(value, UriKind.Absolute, out var parsed)
            || parsed.Scheme is not ("https" or "wss") || parsed.Port != 443
            || parsed.UserInfo.Length != 0 || parsed.HostNameType != UriHostNameType.Dns)
            return false;
        string host = parsed.IdnHost.ToLowerInvariant();
        if (!host.Contains('.') || host.EndsWith('.') || host.EndsWith(".local", StringComparison.Ordinal)
            || host.EndsWith(".localhost", StringComparison.Ordinal) || host.EndsWith(".internal", StringComparison.Ordinal)
            || host.EndsWith(".lan", StringComparison.Ordinal)
            || RetiredHosts.Any(retired => host == retired || host.EndsWith("." + retired, StringComparison.Ordinal)))
            return false;
        uri = parsed;
        return true;
    }

    internal bool RequestAllowed(string value)
        => PublicUri(value, out var uri) && Hosts.Contains(uri!.IdnHost);

    internal bool ExactPage(string value)
    {
        if (!PublicUri(value, out var uri) || uri!.Scheme != "https") return false;
        // Fragments have no network effect. Path/query are never broadened.
        return uri.GetComponents(UriComponents.HttpRequestUrl, UriFormat.UriEscaped)
            == new Uri(PlayerUrl).GetComponents(UriComponents.HttpRequestUrl, UriFormat.UriEscaped);
    }

    internal bool FrameAllowed(string value)
        => value is "about:blank" or "about:srcdoc"
           || PublicUri(value, out var uri) && uri!.Scheme == "https" && FrameHosts.Contains(uri.IdnHost);

    internal bool InternalResource(string value)
        => value is "about:blank" or "about:srcdoc"
           || value.StartsWith("data:", StringComparison.Ordinal)
           || value.StartsWith("blob:", StringComparison.Ordinal) && RequestAllowed(value[5..]);

    internal static int SelfTest(IReadOnlyDictionary<string, CameraPolicy> cameras)
    {
        int cases = 0, failures = 0;
        void Check(bool okay) { cases++; if (!okay) failures++; }
        Check(cameras.Count == 3);
        Check(!cameras.ContainsKey("arbitrary-camera"));
        Check(PlayerPages.Count == WatchPages.Count);
        foreach (var entry in cameras.Values)
        {
            Check(entry.PlayerUrl == PlayerPages[entry.Id]);
            Check(entry.WatchUrl == WatchPages[entry.Id]);
            Check(entry.RequestAllowed(entry.PlayerUrl));
            Check(entry.ExactPage(entry.PlayerUrl));
            Check(entry.ExactPage(entry.PlayerUrl + "#player"));
            Check(entry.ExactPage(entry.WatchUrl) == (entry.WatchUrl == entry.PlayerUrl));
            Check(entry.ExactPage(entry.WatchUrl + "#player") == (entry.WatchUrl == entry.PlayerUrl));
            string querySeparator = entry.PlayerUrl.Contains('?') ? "&" : "?";
            Check(!entry.ExactPage(entry.PlayerUrl + querySeparator + "other=1"));
            Check(!entry.ExactPage(entry.PlayerUrl + "/another-page"));
            Check(!entry.ExactPage(new Uri(entry.PlayerUrl).GetLeftPart(UriPartial.Authority) + "/"));
            Check(!entry.ExactPage(entry.PlayerUrl.Replace("https://", "http://", StringComparison.Ordinal)));
            Check(!entry.ExactPage(entry.WatchUrl + "?other=1"));
            Check(!entry.ExactPage(entry.WatchUrl + "another-page"));
            foreach (var other in cameras.Values.Where(other => other.Id != entry.Id))
                Check(!entry.ExactPage(other.PlayerUrl));
            Check(!entry.ExactPage("https://www.ipcamlive.com/player/player.php?alias=bsyc1080"));
            Check(!entry.ExactPage("https://www.ipcamlive.com/player/player.php?alias=bsyc1080&ispublicpage=1"));
            foreach (string host in entry.Hosts)
            {
                Check(entry.RequestAllowed("https://" + host + "/asset"));
                Check(entry.RequestAllowed("wss://" + host + "/socket"));
                Check(!entry.RequestAllowed("https://" + host + ".invalid/asset"));
                Check(!entry.RequestAllowed("https://" + host + ":8443/asset"));
                Check(!entry.RequestAllowed("https://name:password@" + host + "/asset"));
            }
            foreach (string host in entry.FrameHosts)
                Check(entry.FrameAllowed("https://" + host + "/provider-player?temporary=normal"));
            Check(entry.FrameAllowed("about:blank"));
            Check(entry.InternalResource("blob:" + entry.PlayerUrl + "uuid"));
            Check(!entry.InternalResource("blob:https://unreviewed.example/uuid"));
            foreach (string denied in new[] {
                "https://www.youtube.com/watch?v=abcdefghijk", "https://youtu.be/abcdefghijk",
                "https://r1.googlevideo.com/stream", "https://kiwisdr.com/", "https://unreviewed.example/",
                "http://gpcl.com.au/", "https://127.0.0.1/", "https://[::1]/", "https://169.254.169.254/",
                "file:///C:/Windows/win.ini", "javascript:alert(1)", "https://2130706433/",
            })
            {
                Check(!entry.RequestAllowed(denied));
                Check(!entry.ExactPage(denied));
                Check(!entry.FrameAllowed(denied));
            }
        }
        Console.WriteLine(JsonSerializer.Serialize(new { type = "camera_policy_self_test", cases,
            failures, passed = failures == 0, network = "none" }));
        return failures == 0 ? 0 : 1;
    }
}
