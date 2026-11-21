using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Windows.Forms;

// Deliberately separate from Pulse's Python/SQLite/news-processing process.
// This process is only launched after the owner explicitly consents to one
// exact YouTube video. No account, source collector or other URL enters it.
internal static class Program
{
    private static readonly Regex VideoId = new(@"\A[A-Za-z0-9_-]{11}\z", RegexOptions.Compiled);

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            bool probe = args.Length == 1 && args[0] == "--probe";
            // A separate offline visual-composition probe is used only by
            // Windows QA. It never opens YouTube or makes a network request.
            bool probeEmbed = args.Length == 2 && args[0] == "--probe-embed";
            bool policySelfTest = args.Length == 1 && args[0] == "--self-test-policy";
            if (policySelfTest)
            {
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
                return TvForm.PolicySelfTest();
            }
            // Video ID, parent window, and watch mode are the *only* inputs.
            if (!probe && !probeEmbed && (args.Length < 2 || args.Length > 3 || !VideoId.IsMatch(args[0])))
                return 2;
            long parent = 0;
            if (probeEmbed && (!long.TryParse(args[1], out parent) || parent <= 0))
                return 2;
            if (!probe && !probeEmbed && (!long.TryParse(args[1], out parent) || parent < 0))
                return 2;
            bool fullWatch = !probe && !probeEmbed && args.Length == 3 && args[2] == "--watch";
            if (!probe && !probeEmbed && args.Length == 3 && !fullWatch)
                return 2;
            Console.SetIn(new StreamReader(Console.OpenStandardInput()));
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
            // Qt's Windows native widgets use a per-monitor DPI context. A
            // mismatched cross-process SetParent can reset or misplace the
            // WebView2 composition surface on mixed-DPI monitors.
            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using var form = new TvForm(probe || probeEmbed ? "YE7VzlLtp-4" : args[0],
                new IntPtr(parent), fullWatch, probe || probeEmbed, probeEmbed);
            Application.Run(form);
            // The WebView2 instance is already gone. Exact-owned profile
            // cleanup may wait briefly in THIS helper process, never Pulse UI.
            form.CleanupPrivateProfileAfterExit();
            return 0;
        }
        catch (Exception ex)
        {
            try { Console.WriteLine(JsonSerializer.Serialize(new { type = "error", reason = ex.GetType().Name })); }
            catch { }
            return 1;
        }
    }
}

internal sealed class TvForm : Form
{
    // This is an OS-backed check of the *current helper process*, not a claim
    // that the publisher web domain is a Windows package/app identifier.
    // Classic EXE/Inno installations typically return NO_PACKAGE (15700).
    // Do not emit the package name, publisher ID, headers or other identity.
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(
        ref uint packageFullNameLength, StringBuilder? packageFullName);

    private static string InstalledPackageIdentityState()
    {
        try
        {
            uint length = 0;
            int result = GetCurrentPackageFullName(ref length, null);
            if (result == 15700) return "absent"; // APPMODEL_ERROR_NO_PACKAGE
            if (result != 122 || length == 0 || length > 512) return "unknown";
            var buffer = new StringBuilder((int)length);
            result = GetCurrentPackageFullName(ref length, buffer);
            return result == 0 && buffer.Length > 0 ? "present" : "unknown";
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            return "unknown";
        }
    }

    // The OS, not a publisher URL or an installer-provided string, supplies
    // the Windows package Name used for YouTube's required desktop Referer.
    // GetCurrentPackageFullName is unavailable for an unpackaged Inno EXE.
    // Never emit the Name, full identity, or resulting header through IPC.
    private static string? PackageNameFromFullName(string fullName)
    {
        string[] parts = fullName.Split('_');
        if (parts.Length != 5) return null;
        string name = parts[0];
        if (name.Length < 3 || name.Length > 50 || name.Contains("..", StringComparison.Ordinal)
            || !Regex.IsMatch(name, @"\A[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]\z")
            || !Regex.IsMatch(parts[1], @"\A[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\z")
            || parts[2] is not ("x86" or "x64" or "arm" or "arm64" or "neutral")
            || !Regex.IsMatch(parts[4], @"\A[A-Za-z0-9]+\z"))
            return null;
        return name;
    }

    private static string? RegisteredWindowsAppReferer()
    {
        try
        {
            uint length = 0;
            if (GetCurrentPackageFullName(ref length, null) != 122
                || length == 0 || length > 512) return null;
            var buffer = new StringBuilder((int)length);
            if (GetCurrentPackageFullName(ref length, buffer) != 0) return null;
            string? name = PackageNameFromFullName(buffer.ToString());
            return name is null ? null : "https://" + name.ToLowerInvariant() + "/";
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            return null;
        }
    }

    // Microsoft documents that these host-machine overrides can silently
    // replace the requested private profile, redirect the runtime, or expose
    // the page to script debuggers. The helper fails closed on any override.
    private static readonly string[] WebView2OverrideNames = {
        "WEBVIEW2_USER_DATA_FOLDER", "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE",
        "WEBVIEW2_RELEASE_CHANNELS", "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER",
        "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER",
    };
    private static readonly string[] WebView2PolicyOverrides = {
        "UserDataFolder", "BrowserExecutableFolder", "AdditionalBrowserArguments",
        "ReleaseChannelPreference", "ReleaseChannels",
    };
    private static readonly string[] AllowedHosts = {
        "youtube.com", "youtube-nocookie.com", "youtubei.googleapis.com",
        "googlevideo.com", "ytimg.com", "gstatic.com", "ggpht.com",
    };
    // Publisher-owned URL in the existing app. This alone is not evidence
    // of a Windows-registered package identity under Google's requirements.
    private const string PublisherReferer = "https://www.dietrichailabs.com/";
    private const long WsChild = 0x40000000;
    private const long WsPopup = unchecked((long)0x80000000);
    private const uint SwpFrameChanged = 0x0020;
    private const uint SwpNoMove = 0x0002;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoZOrder = 0x0004;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetParent(IntPtr child, IntPtr parent);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr GetParent(IntPtr child);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr GetWindowLongPtr(IntPtr handle, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr SetWindowLongPtr(IntPtr handle, int index, IntPtr value);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(IntPtr handle, IntPtr after, int x, int y, int width, int height, uint flags);

    private readonly WebView2 browser = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.Black };
    private readonly System.Windows.Forms.Timer telemetry = new() { Interval = 1000 };
    private readonly string videoId;
    private readonly IntPtr parentHwnd;
    private readonly bool fullWatch;
    private readonly bool offlineProbe;
    private readonly bool visibleOfflineProbe;
    private readonly string privateFolder;
    private bool initialized;
    private bool pollPending;
    private bool identityObservationSent;
    private int exactVideoHttpResponseCount;
    private readonly Stopwatch playbackClock = new();
    private readonly PlaybackObservation playback = new();
    // Commands may arrive before YouTube creates its <video> element.
    // Native WebView2 starts muted before navigation, independent of HTML.
    private bool desiredMuted = true;
    private int desiredVolume = 60;

    // Waiting for the user's deliberate Play gesture is not a playback
    // failure. Keep that separate from an absent document/player, a lost
    // script callback, and an actually unpaused player that cannot progress.
    // All deadlines use one monotonic clock; none extend callback liveness.
    private sealed class PlaybackObservation
    {
        internal bool DocumentLoaded;
        internal bool Played { get; private set; }
        internal string State { get; private set; } = "loading";
        private double lastObservationAt;
        private double lastProgressAt;
        private double? missingSince;
        private double previousTime = -1;
        private int previousFrames = -1;

        internal string? ExpiredReason(double now)
        {
            if (!DocumentLoaded && now > 45) return "video_document_timeout_45s";
            if (now - lastObservationAt > 45) return "telemetry_timeout_45s";
            if (missingSince.HasValue && now - missingSince.Value > 45)
                return "video_element_missing_45s";
            if ((State is "buffering" or "stalled") && now - lastProgressAt > 45)
                return "no_media_progress_45s";
            return null;
        }

        internal string Observe(double now, bool present, bool paused, bool ended,
                                double? current, int frames, int width, int ready)
        {
            lastObservationAt = now;
            if (!present)
            {
                missingSince ??= now;
                previousTime = -1;
                previousFrames = -1;
                return State = "missing_player";
            }
            if (State is "loading" or "missing_player") lastProgressAt = now;
            missingSince = null;
            bool advancing = current.HasValue && double.IsFinite(current.Value)
                && current.Value > previousTime && previousTime >= 0
                && !paused && ready >= 2 && width > 0
                && frames > previousFrames && previousFrames >= 0;
            if (current.HasValue && double.IsFinite(current.Value))
                previousTime = current.Value;
            previousFrames = frames;
            if (ended) return State = "ended";
            if (paused)
            {
                lastProgressAt = now;
                return State = Played ? "paused" : "awaiting_play";
            }
            if (advancing)
            {
                Played = true;
                lastProgressAt = now;
                return State = "advancing";
            }
            return State = Played && ready >= 2 ? "stalled" : "buffering";
        }
    }

    internal TvForm(string videoId, IntPtr parentHwnd, bool fullWatch,
                    bool offlineProbe, bool visibleOfflineProbe)
    {
        this.videoId = videoId;
        this.parentHwnd = parentHwnd;
        this.fullWatch = fullWatch;
        this.offlineProbe = offlineProbe;
        this.visibleOfflineProbe = visibleOfflineProbe;
        privateFolder = Path.Combine(Path.GetTempPath(), "GlobalPulse-TV-" + Guid.NewGuid().ToString("N"));
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        BackColor = Color.Black;
        ClientSize = new Size(960, 540);
        Controls.Add(browser);
        Shown += async (_, _) => await OpenAsync();
        FormClosed += (_, _) => { telemetry.Stop(); browser.Dispose(); };
        telemetry.Tick += async (_, _) => await InspectVideoAsync();
        // Handle a quit request or stdin EOF without blocking the UI loop.
        if (!offlineProbe) _ = Task.Run(() => {
            try
            {
                string? command;
                while ((command = Console.ReadLine()) != null)
                {
                    if (IsDisposed) break;
                    if (command == "STOP") { BeginInvoke((Action)Close); break; }
                    if (command == "MUTE 1" || command == "MUTE 0")
                    {
                        bool muted = command.EndsWith('1');
                        BeginInvoke((Action)(() => SetAudio(muted, null)));
                    }
                    if (command.StartsWith("VOLUME ", StringComparison.Ordinal)
                        && int.TryParse(command[7..], out int volume) && volume >= 0 && volume <= 100)
                    {
                        BeginInvoke((Action)(() => SetAudio(null, volume)));
                    }
                }
            }
            catch { }
            if (!IsDisposed && IsHandleCreated) BeginInvoke((Action)Close);
        });
    }

    private void Reply(object message)
    {
        try { Console.WriteLine(JsonSerializer.Serialize(message)); } catch { }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        if (parentHwnd == IntPtr.Zero) return; // standalone smoke/debug
        // Reparent only this newly created child, never any existing user app.
        var style = GetWindowLongPtr(Handle, -16).ToInt64();
        SetWindowLongPtr(Handle, -16, new IntPtr((style | WsChild) & ~WsPopup));
        SetParent(Handle, parentHwnd);
        if (GetParent(Handle) != parentHwnd)
            throw new InvalidOperationException("Native TV child window parent mismatch");
        SetWindowPos(Handle, IntPtr.Zero, 0, 0, 0, 0,
                     SwpFrameChanged | SwpNoMove | SwpNoSize | SwpNoZOrder);
    }

    private static bool Allowed(Uri candidate)
    {
        if (candidate.Scheme != Uri.UriSchemeHttps || !candidate.IsDefaultPort)
            return false;
        string host = candidate.IdnHost.ToLowerInvariant();
        return AllowedHosts.Any(allowed => host == allowed || host.EndsWith("." + allowed, StringComparison.Ordinal));
    }

    private static bool ExactVideoNavigation(string url, string id, bool watch)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var candidate) || !Allowed(candidate))
            return false;
        string host = candidate.IdnHost.ToLowerInvariant();
        if (host != "www.youtube.com" && host != "youtube.com"
            && host != "www.youtube-nocookie.com" && host != "youtube-nocookie.com")
            return false;
        if (candidate.AbsolutePath == "/embed/" + id)
            return true;
        if (!watch || (host != "www.youtube.com" && host != "youtube.com")
            || candidate.AbsolutePath != "/watch")
            return false;
        // A duplicated or encoded v key makes the actual selected video
        // ambiguous. Approve one canonical literal v=ID and reject every
        // second spelling, even when one copy matches the consented ID.
        // System.Uri can normalize percent escapes in Query, which would
        // turn an encoded key (%76) into the literal key (v) before this
        // equality gate. Preserve the original spelling for the canonical
        // consented video parameter while still decoding names to detect
        // duplicates/aliases.
        string original = candidate.OriginalString;
        int question = original.IndexOf('?');
        if (question < 0) return false;
        int fragment = original.IndexOf('#', question + 1);
        string rawQuery = fragment < 0
            ? original[(question + 1)..]
            : original[(question + 1)..fragment];
        var videoParameters = rawQuery
            .Split('&', StringSplitOptions.RemoveEmptyEntries)
            .Where(pair => {
                string key = pair.Split('=', 2)[0];
                return Uri.UnescapeDataString(key).Equals("v", StringComparison.OrdinalIgnoreCase);
            }).ToArray();
        return videoParameters.Length == 1 && videoParameters[0] == "v=" + id;
    }

    private static bool InternalResource(string url)
    {
        if (url == "about:blank" || url == "about:srcdoc" || url.StartsWith("data:", StringComparison.Ordinal))
            return true;
        if (!url.StartsWith("blob:",StringComparison.Ordinal)) return false;
        // A blob may only originate within the consented YouTube/media set.
        return Uri.TryCreate(url[5..],UriKind.Absolute,out var origin) && Allowed(origin);
    }

    private static bool FrameAllowed(string url, string id, bool watch)
    {
        // Child frames may not open sign-in, a new video, or a Google account.
        // Local generated frames have no independent network origin; all
        // network fetches still pass the WebResourceRequested host filter.
        return url == "about:blank" || url == "about:srcdoc"
            || url.StartsWith("data:",StringComparison.Ordinal)
            || ExactVideoNavigation(url,id,watch);
    }

    internal static int PolicySelfTest()
    {
        const string id = "YE7VzlLtp-4";
        var exact = new (string Url, bool Expected, bool Watch)[] {
            ("https://www.youtube.com/embed/YE7VzlLtp-4", true, false),
            ("https://www.youtube.com/embed/YE7VzlLtp-4?mute=1", true, false),
            ("https://www.youtube.com/watch?v=YE7VzlLtp-4", true, true),
            ("https://www.youtube.com/watch?v=YE7VzlLtp-4", false, false),
            ("https://www.youtube.com/watch?v=b0ZhJhN_Sn8", false, true),
            ("https://www.youtube.com/watch?v=YE7VzlLtp-4&v=b0ZhJhN_Sn8", false, true),
            ("https://www.youtube.com/watch?v=b0ZhJhN_Sn8&v=YE7VzlLtp-4", false, true),
            ("https://www.youtube.com/watch?v=YE7VzlLtp-4&%76=b0ZhJhN_Sn8", false, true),
            ("https://www.youtube.com/watch?%76=YE7VzlLtp-4", false, true),
            ("https://www.youtube.com/watch?%56=YE7VzlLtp-4", false, true),
            ("https://www.youtube.com/embed/b0ZhJhN_Sn8", false, true),
            ("https://accounts.google.com/", false, true),
            ("https://youtube.com.bad.example/embed/YE7VzlLtp-4", false, true),
            ("http://www.youtube.com/embed/YE7VzlLtp-4", false, true),
            ("https://www.youtube.com:8443/embed/YE7VzlLtp-4", false, true),
        };
        int failures = 0;
        foreach (var item in exact)
        {
            if (ExactVideoNavigation(item.Url,id,item.Watch) != item.Expected) failures++;
            if (FrameAllowed(item.Url,id,item.Watch) != item.Expected) failures++;
        }
        if (FrameAllowed("https://accounts.google.com/Login",id,true)) failures++;
        if (FrameAllowed("https://www.youtube.com/watch?v=b0ZhJhN_Sn8",id,true)) failures++;
        if (!FrameAllowed("about:blank",id,false)) failures++;
        if (!InternalResource("blob:https://www.youtube.com/some-guid")) failures++;
        if (InternalResource("blob:https://evil.example/uuid")) failures++;
        if (!Uri.TryCreate("https://rr1---sn-abc.googlevideo.com/videoplayback",UriKind.Absolute,out var good)
            || !Allowed(good)) failures++;
        if (!Uri.TryCreate("https://accounts.google.com/signin",UriKind.Absolute,out var bad)
            || Allowed(bad)) failures++;
        if (!WebView2OverrideNames.Contains("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS")) failures++;
        if (!WebView2OverrideNames.Contains("WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER")) failures++;
        if (!WebView2PolicyOverrides.Contains("AdditionalBrowserArguments")) failures++;
        if (!WebView2PolicyOverrides.Contains("UserDataFolder")) failures++;
        // Exercise the real local Win32 API in an offline native test process.
        // A missing package identity is valid for classic EXE installs.
        string installedPackageState = InstalledPackageIdentityState();
        if (installedPackageState is not ("present" or "absent" or "unknown")) failures++;
        // Offline parser cases: use the package's actual manifest Name only.
        if (PackageNameFromFullName("DietrichAI.GlobalPulse_1.2.3.4_x64__abc123")
            != "DietrichAI.GlobalPulse") failures++;
        if (PackageNameFromFullName("malicious.example_1.2.3.4_x64__abc123") != "malicious.example") failures++;
        if (PackageNameFromFullName("DietrichAI.GlobalPulse_1.2.3.4_x64__abc123\r\nX-Injected:yes") != null) failures++;
        if (PackageNameFromFullName("Fake_1.2.3.4_x64__") != null) failures++;
        failures += PlaybackPolicySelfTest(out int playbackCases);
        Console.WriteLine(JsonSerializer.Serialize(new {
            type="policy_self_test", cases=exact.Length * 2 + 16 + playbackCases,
            playback_cases=playbackCases,
            passed=failures==0, failures, network="none",
            os_package_identity_state=installedPackageState
        }));
        return failures==0 ? 0 : 1;
    }

    private static int PlaybackPolicySelfTest(out int cases)
    {
        int failures = 0;
        int count = 0;
        void Check(bool condition) { count++; if (!condition) failures++; }
        var absentDocument = new PlaybackObservation();
        Check(absentDocument.ExpiredReason(46) == "video_document_timeout_45s");
        var lostCallback = new PlaybackObservation { DocumentLoaded = true };
        Check(lostCallback.ExpiredReason(46) == "telemetry_timeout_45s");
        var idle = new PlaybackObservation { DocumentLoaded = true };
        bool idleConnected = true;
        for (int second = 1; second <= 120; second++)
        {
            idleConnected &= idle.ExpiredReason(second) == null;
            idle.Observe(second, true, true, false, 0, 0, 0, 0);
        }
        Check(idleConnected && idle.State == "awaiting_play" && !idle.Played);
        Check(idle.ExpiredReason(166) == "telemetry_timeout_45s");
        Check(idle.Observe(121, true, false, false, 0, 1, 640, 4) == "buffering");
        Check(idle.Observe(122, true, false, false, 1, 2, 640, 4) == "advancing");
        Check(idle.Played);
        Check(idle.Observe(123, true, true, false, 1, 2, 640, 4) == "paused");
        idle.Observe(200, true, true, false, 1, 2, 640, 4);
        Check(idle.ExpiredReason(200) == null);
        Check(idle.ExpiredReason(246) == "telemetry_timeout_45s");
        Check(idle.Observe(201, true, false, false, 1, 2, 640, 4) == "stalled");
        idle.Observe(246, true, false, false, 1, 2, 640, 4);
        Check(idle.ExpiredReason(246) == "no_media_progress_45s");
        Check(idle.Observe(247, true, false, true, 2, 3, 640, 4) == "ended");
        var missing = new PlaybackObservation { DocumentLoaded = true };
        Check(missing.Observe(1, false, true, false, null, 0, 0, 0) == "missing_player");
        missing.Observe(46, false, true, false, null, 0, 0, 0);
        Check(missing.ExpiredReason(46) == null);
        missing.Observe(47, false, true, false, null, 0, 0, 0);
        Check(missing.ExpiredReason(47) == "video_element_missing_45s");
        var buffering = new PlaybackObservation { DocumentLoaded = true };
        Check(buffering.Observe(1, true, false, false, 0, 0, 0, 0) == "buffering");
        buffering.Observe(47, true, false, false, 0, 0, 0, 0);
        Check(buffering.ExpiredReason(47) == "no_media_progress_45s");
        var clockOnly = new PlaybackObservation { DocumentLoaded = true };
        clockOnly.Observe(1, true, false, false, 0, 3, 640, 4);
        Check(clockOnly.Observe(2, true, false, false, 1, 3, 640, 4) == "buffering");
        Check(!clockOnly.Played);
        cases = count;
        return failures;
    }

    private static void RejectWebView2Overrides()
    {
        foreach (string name in WebView2OverrideNames)
        {
            if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(name)))
                throw new InvalidOperationException("WebView2 override refused: " + name);
        }
        // The override registry fallback is consulted only if variables are
        // absent. Examine both policy hives read-only, including wildcard and
        // app-specific values; fail closed if a nonempty override exists.
        // This may refuse playback on managed computers but leaves all other
        // Pulse features running and never relaxes the video isolation.
        foreach (RegistryKey root in new [] { Registry.LocalMachine, Registry.CurrentUser })
        {
            foreach (string key in WebView2PolicyOverrides)
            {
                using var policy = root.OpenSubKey(@"SOFTWARE\Policies\Microsoft\Edge\WebView2\" + key);
                if (policy == null) continue;
                foreach (string name in policy.GetValueNames())
                    if (!string.IsNullOrWhiteSpace(policy.GetValue(name)?.ToString()))
                        throw new InvalidOperationException("WebView2 policy override refused: " + key);
            }
        }
    }

    private async Task OpenAsync()
    {
        try
        {
            RejectWebView2Overrides();
            string? registeredAppReferer = offlineProbe || fullWatch ? null : RegisteredWindowsAppReferer();
            var environmentOptions = new CoreWebView2EnvironmentOptions {
                ExclusiveUserDataFolderAccess = true,
                AllowSingleSignOnUsingOSPrimaryAccount = false,
            };
            var environment = await CoreWebView2Environment.CreateAsync(
                userDataFolder: privateFolder, options: environmentOptions);
            if (!string.Equals(
                    Path.GetFullPath(environment.UserDataFolder).TrimEnd(Path.DirectorySeparatorChar),
                    Path.GetFullPath(privateFolder).TrimEnd(Path.DirectorySeparatorChar),
                    StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("WebView2 redirected private folder");
            var options = environment.CreateCoreWebView2ControllerOptions();
            options.IsInPrivateModeEnabled = true;
            await browser.EnsureCoreWebView2Async(environment, options);
            var web = browser.CoreWebView2 ?? throw new InvalidOperationException("WebView2 missing");
            web.Settings.AreDefaultContextMenusEnabled = false;
            web.Settings.AreDevToolsEnabled = false;
            web.Settings.AreBrowserAcceleratorKeysEnabled = false;
            web.Settings.AreHostObjectsAllowed = false;
            web.Settings.IsWebMessageEnabled = false;
            web.Settings.IsZoomControlEnabled = false;
            web.Settings.IsStatusBarEnabled = false;
            web.Profile.IsPasswordAutosaveEnabled = false;
            web.Profile.IsGeneralAutofillEnabled = false;
            // No audio can escape between native process start and a late
            // MUTE command or delayed YouTube video-element initialization.
            web.IsMuted = desiredMuted;

            // Attach guards BEFORE navigation. Redirects and subresources must
            // never leave the explicitly consented provider-host family.
            web.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            web.WebResourceRequested += (_, e) => {
                if (InternalResource(e.Request.Uri))
                    return;
                if (!Uri.TryCreate(e.Request.Uri, UriKind.Absolute, out var u) || !Allowed(u)) {
                    e.Response = web.Environment.CreateWebResourceResponse(null, 403, "Blocked", "Content-Type: text/plain");
                    return;
                }
                // Inspect the trusted, exact consented document *before* WebView2
                // sends it. Do not echo headers/URLs, alter subresources, or
                // mistake this callback for proof of what YouTube received.
                if (!identityObservationSent && !offlineProbe
                    && e.ResourceContext == CoreWebView2WebResourceContext.Document
                    && ExactVideoNavigation(e.Request.Uri, videoId, fullWatch)) {
                    identityObservationSent = true;
                    bool present = false;
                    bool publisherMatch = false;
                    bool registeredMatch = false;
                    try {
                        if (e.Request.Headers.Contains("Referer")) {
                            string value = e.Request.Headers.GetHeader("Referer");
                            present = !string.IsNullOrWhiteSpace(value);
                            publisherMatch = string.Equals(value, PublisherReferer, StringComparison.Ordinal);
                            registeredMatch = registeredAppReferer != null
                                && string.Equals(value, registeredAppReferer, StringComparison.Ordinal);
                        }
                    } catch (COMException) {
                        // A failed inspection is UNKNOWN, never a passed identity gate.
                    }
                    Reply(new { type = "web_request_identity", stage = "pre_network",
                        mode = fullWatch ? "watch" : "embed",
                        referer_present = present, publisher_url_match = publisherMatch,
                        registered_app_id_match = registeredMatch,
                        os_app_identity_verified = registeredMatch, network_delivery_verified = false });
                }
            };
            // Exact consented document URL only. WebView2 HTTP status is NOT
            // proof of installed app identity, Referer acceptance, or playback.
            // Never emit URL, header, cookie, body, or any sensitive payload.
            web.WebResourceResponseReceived += (_, e) => {
                if (offlineProbe || exactVideoHttpResponseCount >= 8
                    || !ExactVideoNavigation(e.Request.Uri, videoId, fullWatch))
                    return;
                exactVideoHttpResponseCount++;
                int status = 0;
                try { status = e.Response?.StatusCode ?? 0; }
                catch (COMException) { /* Unknown remains unknown. */ }
                Reply(new { type = "exact_video_http_response",
                    http_status = status, stage = "webview2_response",
                    provider_identity_acceptance_verified = false,
                    os_app_identity_verified = false,
                    picture_audio_verified = false });
            };
            web.NavigationStarting += (_, e) => {
                if (offlineProbe && e.Uri == "about:blank") return;
                bool permitted = ExactVideoNavigation(e.Uri, videoId, fullWatch);
                if (e.IsRedirected)
                    Reply(new { type = "navigation_redirect", allowed = permitted,
                        actual_network_result_verified = false });
                if (!permitted) e.Cancel = true;
            };
            web.FrameNavigationStarting += (_, e) => {
                if (!FrameAllowed(e.Uri,videoId,fullWatch)) e.Cancel = true;
            };
            web.NewWindowRequested += (_, e) => e.Handled = true;
            web.DownloadStarting += (_, e) => { e.Cancel = true; e.Handled = true; };
            web.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            web.ServerCertificateErrorDetected += (_, e) => e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
            web.BasicAuthenticationRequested += (_, e) => e.Cancel = true;
            web.NavigationCompleted += (_, e) => {
                if (e.IsSuccess) {
                    playback.DocumentLoaded = true;
                    ApplyElementAudio();
                }
                Reply(new {type="page_loaded", success=e.IsSuccess});
            };
            web.ProcessFailed += (_, e) => { Reply(new {type="error",reason="renderer_exited"}); Close(); };
            initialized = true;
            Reply(new { type="ready", hwnd=Handle.ToInt64(), in_private=web.Profile.IsInPrivateModeEnabled,
                mode=fullWatch ? "watch" : "embed" });
            if (offlineProbe)
            {
                var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                web.NavigationCompleted += (_, e) => done.TrySetResult(e.IsSuccess);
                web.Navigate("about:blank");
                var first = await Task.WhenAny(done.Task, Task.Delay(10000));
                if (first != done.Task || !await done.Task)
                    throw new InvalidOperationException("Offline HTML failed");
                if (visibleOfflineProbe)
                {
                    // Inspect a pixel in the real Qt-hosted window, not a
                    // decoder clock or JS frame counter. This static color
                    // exposes Win32 parent/compositor clipping failures.
                    await web.ExecuteScriptAsync(
                        "document.documentElement.style.backgroundColor='#f21a9a';" +
                        "document.body.style.backgroundColor='#f21a9a';" +
                        "document.body.style.margin='0';" +
                        "document.body.style.minHeight='100vh';");
                    Reply(new { type="embed_probe_ready", network="none", marker="f21a9a" });
                    return; // Wait for STOP from the exact test-owned pipe.
                }
                var encoded = await web.ExecuteScriptAsync(
                    "document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E,mp4a.40.2\"')");
                Reply(new {
                    type = "codec_probe", network = "none", h264 = JsonSerializer.Deserialize<string>(encoded),
                    in_private = web.Profile.IsInPrivateModeEnabled,
                });
                Close();
                return;
            }
            var url = fullWatch
                ? "https://www.youtube.com/watch?v=" + videoId + "&autoplay=0"
                : "https://www.youtube.com/embed/" + videoId + "?autoplay=0&mute=1&playsinline=1";
            // YouTube requires the OS-registered app ID, when available, as
            // HTTPS Referer for desktop WebViews. Classic Inno installations
            // have no MSIX package identity: retain the historical publisher
            // fallback only as a best-effort request, never as a passing gate.
            // Registration and server acceptance require separate evidence.
            Reply(new { type = "installed_package_identity",
                state = InstalledPackageIdentityState(),
                source = "GetCurrentPackageFullName",
                mode = fullWatch ? "watch" : "embed",
                referer_matches_registered_app_id = registeredAppReferer != null,
                provider_acceptance_verified = false });
            playbackClock.Restart();
            if (fullWatch)
            {
                // Normal top-level navigation, not an iframe identity workaround.
                // Browser-managed headers, exact-video guards, consent and manual
                // Play remain. Success here would not prove an embed-153 fix.
                web.Navigate(url);
            }
            else
            {
                var request = environment.CreateWebResourceRequest(url, "GET", null, "");
                request.Headers.SetHeader("Referer", registeredAppReferer ?? PublisherReferer);
                web.NavigateWithWebResourceRequest(request);
            }
            telemetry.Start();
        }
        catch (Exception ex)
        {
            Reply(new { type="error", reason="startup_" + ex.GetType().Name });
            Close();
        }
    }

    private void BrowserScript(string script)
    {
        if (initialized && browser.CoreWebView2 != null)
            _ = browser.CoreWebView2.ExecuteScriptAsync(script);
    }

    private void SetAudio(bool? muted, int? volume)
    {
        if (muted.HasValue) desiredMuted = muted.Value;
        if (volume.HasValue) desiredVolume = Math.Clamp(volume.Value, 0, 100);
        // WebView2-level mute applies across every frame immediately, even
        // when the media element has not been created or has been replaced.
        if (browser.CoreWebView2 != null)
            browser.CoreWebView2.IsMuted = desiredMuted;
        ApplyElementAudio();
    }

    private string AudioScript()
    {
        string volume = (desiredVolume / 100d).ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
        string muted = desiredMuted ? "true" : "false";
        return "(()=>{const v=document.querySelector('video');if(v){v.muted=" + muted
            + ";v.volume=" + volume + ";return true;}return false;})()";
    }

    private void ApplyElementAudio()
    {
        if (initialized) BrowserScript(AudioScript());
    }

    // Read only the rendered provider error area and standard media properties.
    // A visible DOM message is NOT an IFrame API onError/autoplay event. The
    // text stays inside the page: only recognized numbers/booleans cross IPC.
    // Keep this actual probe independently executable in offline JS fixtures.
    private const string PlaybackProbe = @"(()=>{
        function visible(e) {
            if (!e || !e.isConnected) return false;
            const rects=Array.from(e.getClientRects()).slice(0,16).filter(r=>r.width>0&&r.height>0);
            if (!rects.length || !(window.innerWidth>0&&window.innerHeight>0)) return false;
            let left=0,top=0,right=window.innerWidth,bottom=window.innerHeight;
            let depth=0;
            for (let n=e;n;n=n.parentElement) {
                if (++depth>64) return false;
                const s=getComputedStyle(n);
                if (s.display==='none' || s.visibility==='hidden' ||
                    s.visibility==='collapse' || s.contentVisibility==='hidden' ||
                    Number(s.opacity)===0) return false;
                const clipX=['hidden','clip','scroll','auto'].includes(s.overflowX);
                const clipY=['hidden','clip','scroll','auto'].includes(s.overflowY);
                if (clipX||clipY) {
                    const box=n.getBoundingClientRect();
                    const x=box.left+n.clientLeft,y=box.top+n.clientTop;
                    if (clipX) {left=Math.max(left,x);right=Math.min(right,x+n.clientWidth);}
                    if (clipY) {top=Math.max(top,y);bottom=Math.min(bottom,y+n.clientHeight);}
                }
            }
            return rects.some(r=>Math.min(right,r.right)>Math.max(left,r.left)&&
                                 Math.min(bottom,r.bottom)>Math.max(top,r.top));
        }
        let providerError=false,providerCode=0;
        for (const e of Array.from(document.querySelectorAll('.ytp-error-content-wrap,.ytp-error-message')).slice(0,16)) {
            if (!visible(e)) continue;
            const message=(e.innerText||'').slice(0,512).trim();
            if (!message) continue;
            providerError=true;
            const match=message.match(/\berror(?:\s+code)?\s*[:#]?\s*(2|5|100|101|150|153)\b/i);
            providerCode=match?Number(match[1]):0;
            break;
        }
        const v=document.querySelector('video'),d=document.createElement('video');
        const mediaCode=v&&v.error&&[1,2,3,4].includes(v.error.code)?v.error.code:0;
        return JSON.stringify({present:!!v,time:v?v.currentTime:null,
            paused:v?v.paused:true,ended:v?v.ended:false,ready:v?v.readyState:0,
            frames:v&&v.getVideoPlaybackQuality?v.getVideoPlaybackQuality().totalVideoFrames:0,
            width:v?v.videoWidth:0,h264:d.canPlayType('video/mp4; codecs=""avc1.42E01E,mp4a.40.2""'),
            provider_error_visible:providerError,provider_error_code:providerCode,
            media_error_code:mediaCode});
    })()";

    private async Task InspectVideoAsync()
    {
        if (!initialized || browser.CoreWebView2 == null) return;
        // Check liveness even while a previous ExecuteScriptAsync is pending.
        // A paused player does not reset this independent callback deadline.
        string? timeout = playback.ExpiredReason(playbackClock.Elapsed.TotalSeconds);
        if (timeout != null)
        {
            Reply(new { type="error", reason=timeout, observation="local_deadline",
                mode=fullWatch ? "watch" : "embed", state=playback.State });
            Close();
            return;
        }
        if (pollPending) return;
        pollPending = true;
        try
        {
            // Re-apply desired controls during polling: YouTube often
            // replaces the <video> element after NavigationCompleted.
            string query = AudioScript() + ";" + PlaybackProbe;
            var encoded = await browser.CoreWebView2.ExecuteScriptAsync(query);
            if (IsDisposed || Disposing) return;
            using var outer = JsonDocument.Parse(encoded);
            var innerJson = outer.RootElement.GetString();
            if (innerJson == null) return;
            using var inner = JsonDocument.Parse(innerJson);
            var root = inner.RootElement;
            var codec = root.GetProperty("h264").GetString() ?? "";
            if (codec is not ("probably" or "maybe")) codec = "unknown";
            var clock = root.GetProperty("time");
            var frames = root.GetProperty("frames").GetInt32();
            var width = root.GetProperty("width").GetInt32();
            var ready = root.GetProperty("ready").GetInt32();
            double? current = clock.ValueKind == JsonValueKind.Number ? clock.GetDouble() : null;
            bool present = root.GetProperty("present").GetBoolean();
            bool paused = root.GetProperty("paused").GetBoolean();
            bool ended = root.GetProperty("ended").GetBoolean();
            int providerCode = root.GetProperty("provider_error_code").GetInt32();
            if (providerCode is not (2 or 5 or 100 or 101 or 150 or 153)) providerCode = 0;
            if (root.GetProperty("provider_error_visible").GetBoolean())
            {
                Reply(new {type="error", reason="youtube_unavailable", observation="visible_dom",
                    youtube_error_code=providerCode, mode=fullWatch ? "watch" : "embed"});
                Close(); return;
            }
            int mediaCode = root.GetProperty("media_error_code").GetInt32();
            if (mediaCode is >= 1 and <= 4)
            {
                Reply(new {type="error", reason="html_media_error", observation="html_media_element",
                    media_error_code=mediaCode, mode=fullWatch ? "watch" : "embed"});
                Close(); return;
            }
            string state = playback.Observe(playbackClock.Elapsed.TotalSeconds,
                present, paused, ended, current, frames, width, ready);
            if (state == "advancing")
                Reply(new {type="advancing", current_time=current, decoded_frames=frames, h264=codec});
            else if (state == "ended")
            {
                Reply(new {type="ended", observation="html_media_element"});
                Close();
            }
            else
                Reply(new {type="waiting", state, h264=codec, frames, video_width=width});
        }
        catch (Exception ex)
        {
            Reply(new {type="diagnostic",reason=ex.GetType().Name});
        }
        finally { pollPending = false; }
    }

    internal void CleanupPrivateProfileAfterExit()
    {
        // Never traverse a user-controlled or broad directory. This is the
        // unique GUID folder allocated by this helper beneath OS temp.
        string fullPath = Path.GetFullPath(privateFolder);
        string tempRoot = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar);
        string name = Path.GetFileName(fullPath);
        if (!string.Equals(Path.GetDirectoryName(fullPath),tempRoot,StringComparison.OrdinalIgnoreCase)
            || !Regex.IsMatch(name, @"\AGlobalPulse-TV-[a-f0-9]{32}\z"))
            return;
        for (int attempt = 0; attempt < 10; attempt++)
        {
            if (!Directory.Exists(fullPath)) return;
            try
            {
                if ((File.GetAttributes(fullPath) & FileAttributes.ReparsePoint) != 0)
                    return;
                Directory.Delete(fullPath,recursive:true);
                return;
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            // Browser subprocesses may still hold the profile for a moment.
            // This bounded retry runs after the host window is already gone.
            Thread.Sleep(180);
        }
        Reply(new {type="privacy_cleanup_pending",reason="owned_temp_profile_locked"});
    }
}
