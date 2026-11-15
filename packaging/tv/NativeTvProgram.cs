using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
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
            Application.Run(new TvForm(probe ? "YE7VzlLtp-4" : args[0], new IntPtr(parent), fullWatch, probe));
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
    private static readonly string[] AllowedHosts = {
        "youtube.com", "youtube-nocookie.com", "youtubei.googleapis.com",
        "googlevideo.com", "ytimg.com", "gstatic.com", "ggpht.com",
        "googleapis.com", "google.com", "googleusercontent.com",
        "gvt1.com", "gvt2.com", "doubleclick.net",
        "googlesyndication.com", "googleadservices.com",
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
        FormClosed += (_, _) => { telemetry.Stop(); browser.Dispose(); TryRemoveOwnFolder(); };
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
                        BeginInvoke((Action)(() => BrowserScript(
                            "(()=>{const v=document.querySelector('video');if(v)v.muted=" +
                            (muted ? "true" : "false") + ";})()")));
                    }
                    if (command.StartsWith("VOLUME ", StringComparison.Ordinal)
                        && int.TryParse(command[7..], out int volume) && volume >= 0 && volume <= 100)
                    {
                        BeginInvoke((Action)(() => BrowserScript(
                            "(()=>{const v=document.querySelector('video');if(v)v.volume=" +
                            (volume / 100d).ToString("0.00",System.Globalization.CultureInfo.InvariantCulture) + ";})()")));
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

    private async Task OpenAsync()
    {
        try
        {
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: privateFolder);
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

            // Attach guards BEFORE navigation. Redirects and subresources must
            // never leave the explicitly consented provider-host family.
            web.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            web.WebResourceRequested += (_, e) => {
                if (!Uri.TryCreate(e.Request.Uri, UriKind.Absolute, out var u) || !Allowed(u))
                    e.Response = web.Environment.CreateWebResourceResponse(null, 403, "Blocked", "Content-Type: text/plain");
            };
            web.NavigationStarting += (_, e) => {
                if (!ExactVideoNavigation(e.Uri, videoId, fullWatch)) e.Cancel = true;
            };
            web.FrameNavigationStarting += (_, e) => {
                if (!Uri.TryCreate(e.Uri,UriKind.Absolute,out var u)
                    || (u.Scheme != "about" && !Allowed(u))) e.Cancel = true;
            };
            web.NewWindowRequested += (_, e) => e.Handled = true;
            web.DownloadStarting += (_, e) => { e.Cancel = true; e.Handled = true; };
            web.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            web.ServerCertificateErrorDetected += (_, e) => e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
            web.BasicAuthenticationRequested += (_, e) => e.Cancel = true;
            web.NavigationCompleted += (_, e) => Reply(new {type="page_loaded", success=e.IsSuccess});
            web.ProcessFailed += (_, e) => { Reply(new {type="error",reason="renderer_exited"}); Close(); };
            initialized = true;
            Reply(new { type="ready", hwnd=Handle.ToInt64(), in_private=web.Profile.IsInPrivateModeEnabled });
            if (offlineProbe)
            {
                var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                web.NavigationCompleted += (_, e) => done.TrySetResult(e.IsSuccess);
                web.NavigateToString("<!doctype html><html><body>Codec probe without network</body></html>");
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
                ? "https://www.youtube.com/watch?v=" + videoId
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
            const string query = @"(()=>{let v=document.querySelector('video');let d=document.createElement('video');let e=document.querySelector('.ytp-error-content-wrap,.ytp-error-message');return JSON.stringify({time:v?v.currentTime:null,paused:v?v.paused:true,ready:v?v.readyState:0,frames:v&&v.getVideoPlaybackQuality?v.getVideoPlaybackQuality().totalVideoFrames:0,width:v?v.videoWidth:0,h264:d.canPlayType('video/mp4; codecs=""avc1.42E01E,mp4a.40.2""'),provider_error:e&&e.textContent?e.textContent.slice(0,120):null});})()";
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

    private void TryRemoveOwnFolder()
    {
        try
        {
            // Exact unique directory created by THIS session; never recurse
            // through profile roots or other app/user directories.
            if (Directory.Exists(privateFolder)
                && Path.GetFileName(privateFolder).StartsWith("GlobalPulse-TV-",StringComparison.Ordinal))
                Directory.Delete(privateFolder, recursive:true);
        }
        catch (IOException) { /* Edge subprocess still exiting; no broad cleanup */ }
        catch (UnauthorizedAccessException) { }
    }
}
