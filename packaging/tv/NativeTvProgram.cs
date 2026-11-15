using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
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
            bool policySelfTest = args.Length == 1 && args[0] == "--self-test-policy";
            if (policySelfTest)
            {
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
                return TvForm.PolicySelfTest();
            }
            // Video ID, parent window, and watch mode are the *only* inputs.
            if (!probe && (args.Length < 2 || args.Length > 3 || !VideoId.IsMatch(args[0])))
                return 2;
            long parent = 0;
            if (!probe && (!long.TryParse(args[1], out parent) || parent < 0))
                return 2;
            bool fullWatch = !probe && args.Length == 3 && args[2] == "--watch";
            if (!probe && args.Length == 3 && !fullWatch)
                return 2;
            Console.SetIn(new StreamReader(Console.OpenStandardInput()));
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using var form = new TvForm(probe ? "YE7VzlLtp-4" : args[0], new IntPtr(parent), fullWatch, probe);
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
    private const long WsChild = 0x40000000;
    private const long WsPopup = unchecked((long)0x80000000);
    private const uint SwpFrameChanged = 0x0020;
    private const uint SwpNoMove = 0x0002;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoZOrder = 0x0004;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetParent(IntPtr child, IntPtr parent);
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
    private readonly string privateFolder;
    private bool initialized;
    private bool pollPending;
    private bool played;
    // Commands may arrive before YouTube creates its <video> element.
    // Native WebView2 starts muted before navigation, independent of HTML.
    private bool desiredMuted = true;
    private int desiredVolume = 60;
    private double previousTime = -1;
    private DateTime started = DateTime.UtcNow;

    internal TvForm(string videoId, IntPtr parentHwnd, bool fullWatch, bool offlineProbe)
    {
        this.videoId = videoId;
        this.parentHwnd = parentHwnd;
        this.fullWatch = fullWatch;
        this.offlineProbe = offlineProbe;
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
        return candidate.Query.TrimStart('?').Split('&',StringSplitOptions.RemoveEmptyEntries)
            .Any(pair => pair == "v=" + id);
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
        Console.WriteLine(JsonSerializer.Serialize(new {
            type="policy_self_test", cases=exact.Length * 2 + 11,
            passed=failures==0, failures, network="none"
        }));
        return failures==0 ? 0 : 1;
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
                if (!Uri.TryCreate(e.Request.Uri, UriKind.Absolute, out var u) || !Allowed(u))
                    e.Response = web.Environment.CreateWebResourceResponse(null, 403, "Blocked", "Content-Type: text/plain");
            };
            web.NavigationStarting += (_, e) => {
                if (offlineProbe && e.Uri == "about:blank") return;
                if (!ExactVideoNavigation(e.Uri, videoId, fullWatch)) e.Cancel = true;
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
                if (e.IsSuccess) ApplyElementAudio();
                Reply(new {type="page_loaded", success=e.IsSuccess});
            };
            web.ProcessFailed += (_, e) => { Reply(new {type="error",reason="renderer_exited"}); Close(); };
            initialized = true;
            Reply(new { type="ready", hwnd=Handle.ToInt64(), in_private=web.Profile.IsInPrivateModeEnabled });
            if (offlineProbe)
            {
                var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                web.NavigationCompleted += (_, e) => done.TrySetResult(e.IsSuccess);
                web.Navigate("about:blank");
                var first = await Task.WhenAny(done.Task, Task.Delay(10000));
                if (first != done.Task || !await done.Task)
                    throw new InvalidOperationException("Offline HTML failed");
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
            // Referer matches our actual publisher domain; it is not a forged
            // Google origin. YouTube otherwise returns embed error 153.
            var request = environment.CreateWebResourceRequest(
                url, "GET", null, "Referer: https://www.dietrichailabs.com/\r\n");
            web.NavigateWithWebResourceRequest(request);
            started = DateTime.UtcNow;
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

    private async Task InspectVideoAsync()
    {
        if (!initialized || pollPending || browser.CoreWebView2 == null) return;
        if (!played && (DateTime.UtcNow - started).TotalSeconds > 45)
        {
            Reply(new { type="error", reason="no_media_progress_45s" });
            Close();
            return;
        }
        pollPending = true;
        try
        {
            // Re-apply desired controls during polling: YouTube often
            // replaces the <video> element after NavigationCompleted.
            string volume = (desiredVolume / 100d).ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
            string muted = desiredMuted ? "true" : "false";
            string query = @"(()=>{let v=document.querySelector('video');if(v){v.muted=" + muted
                + ";v.volume=" + volume + @";}let d=document.createElement('video');let e=document.querySelector('.ytp-error-content-wrap,.ytp-error-message');return JSON.stringify({time:v?v.currentTime:null,paused:v?v.paused:true,ready:v?v.readyState:0,frames:v&&v.getVideoPlaybackQuality?v.getVideoPlaybackQuality().totalVideoFrames:0,width:v?v.videoWidth:0,muted:v?v.muted:null,volume:v?v.volume:null,h264:d.canPlayType('video/mp4; codecs=""avc1.42E01E,mp4a.40.2""'),provider_error:e&&e.textContent?e.textContent.slice(0,120):null});})()";
            var encoded = await browser.CoreWebView2.ExecuteScriptAsync(query);
            using var outer = JsonDocument.Parse(encoded);
            var innerJson = outer.RootElement.GetString();
            if (innerJson == null) return;
            using var inner = JsonDocument.Parse(innerJson);
            var root = inner.RootElement;
            var codec = root.GetProperty("h264").GetString() ?? "";
            var clock = root.GetProperty("time");
            var frames = root.GetProperty("frames").GetInt32();
            var width = root.GetProperty("width").GetInt32();
            double? current = clock.ValueKind == JsonValueKind.Number ? clock.GetDouble() : null;
            bool paused = root.GetProperty("paused").GetBoolean();
            var providerError = root.GetProperty("provider_error");
            if (providerError.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(providerError.GetString()))
            {
                Reply(new {type="error",reason="youtube_unavailable"});
                Close(); return;
            }
            if (current != null && current > previousTime && previousTime >= 0
                && !paused && frames > 0 && width > 0)
            {
                played = true;
                Reply(new {type="advancing", current_time=current, decoded_frames=frames, h264=codec});
            }
            else if (!played)
                Reply(new {type="waiting", h264=codec, frames, video_width=width});
            if (current != null) previousTime = current.Value;
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
