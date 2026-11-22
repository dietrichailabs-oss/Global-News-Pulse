using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Windows.Forms;

internal static class Program
{
    // Deliberately retained until OS process exit: closing a kill-on-close job
    // containing this helper earlier would interrupt private-profile cleanup.
    private static IntPtr processJob;

    [STAThread]
    private static int Main(string[] args)
    {
        Console.SetIn(new StreamReader(Console.OpenStandardInput()));
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
        CameraForm? form = null;
        try
        {
            var catalog = CameraPolicy.Load();
            if (args.Length == 1 && args[0] is "--self-test" or "--self-test-policy")
                return CameraPolicy.SelfTest(catalog);
            bool smoke = args.Length == 1 && args[0] is "--smoke" or "--probe";
            bool embed = args.Length == 2 && args[0] == "--probe-embed";
            long parent = 0;
            CameraPolicy camera = catalog.Values.First();
            if (embed && (!long.TryParse(args[1], out parent) || parent <= 0)) return 2;
            if (!smoke && !embed && (args.Length != 2
                || !catalog.TryGetValue(args[0], out camera!)
                || !long.TryParse(args[1], out parent) || parent <= 0)) return 2;
            using var identity = WindowsIdentity.GetCurrent();
            if (new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                throw new CameraStartupException("standard_user_required");
            processJob = OwnedProcessJob.Create();
            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            form = new CameraForm(camera, new IntPtr(parent), smoke, embed);
            Application.Run(form);
            return form.ExitCode;
        }
        catch (CameraStartupException error)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { type = "error", reason = error.Code,
                camera_id = args.Length > 0 && CameraPolicy.WatchPages.ContainsKey(args[0]) ? args[0] : "" }));
            return 1;
        }
        catch
        {
            Console.WriteLine(JsonSerializer.Serialize(new { type = "error", reason = "initialization_failed",
                camera_id = args.Length > 0 && CameraPolicy.WatchPages.ContainsKey(args[0]) ? args[0] : "" }));
            return 1;
        }
        finally
        {
            if (form != null)
            {
                form.Dispose();
                form.CleanupOwnedProfile();
            }
            GC.KeepAlive(processJob); // OS closes it after this process exits.
        }
    }
}

internal sealed class CameraStartupException(string code) : Exception
{
    internal string Code { get; } = code;
}

internal sealed class CameraForm : Form
{
    private readonly CameraPolicy camera;
    private readonly IntPtr parentHwnd;
    private uint parentPid;
    private readonly bool smoke;
    private readonly bool embed;
    private readonly WebView2 browser = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.Black };
    private readonly System.Windows.Forms.Timer deadline = new() { Interval = 25_000 };
    private readonly System.Windows.Forms.Timer parentWatch = new() { Interval = 500 };
    private readonly string privateFolder = Path.Combine(Path.GetTempPath(), "GlobalPulse-Camera-" + Guid.NewGuid().ToString("N"));
    private bool closing;
    private volatile bool stopRequested;
    private volatile bool initializationInFlight;
    private bool profileCreationAttempted;
    private Process? browserProcess;
    private bool ownerNavigation;
    private ulong navigationId;
    private string playerViewScript = "";
    internal int ExitCode { get; private set; }

    [DllImport("user32.dll", SetLastError = true)] private static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetParent(IntPtr child, IntPtr parent);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr GetParent(IntPtr child);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW", SetLastError = true)] private static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)] private static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);

    internal CameraForm(CameraPolicy camera, IntPtr parent, bool smoke, bool embed)
    {
        this.camera = camera; parentHwnd = parent; this.smoke = smoke; this.embed = embed;
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        BackColor = Color.Black;
        ClientSize = new Size(960, 540);
        Controls.Add(browser);
        Shown += async (_, _) => await OpenAsync();
        deadline.Tick += (_, _) => Fail("page_timeout");
        parentWatch.Tick += (_, _) => {
            if (!IsWindow(parentHwnd) || GetWindowThreadProcessId(parentHwnd, out var pid) == 0 || pid != parentPid)
                Close();
        };
        if (!smoke) _ = Task.Run(ReadCommands);
    }

    private void Reply(object message)
    {
        try { Console.WriteLine(JsonSerializer.Serialize(message)); } catch (IOException) { }
    }

    private void ReadCommands()
    {
        try
        {
            // Only STOP is accepted. Bound even an unexpected local pipe input.
            var command = new System.Text.StringBuilder();
            int value;
            while ((value = Console.Read()) >= 0)
            {
                if (value == '\n')
                {
                    if (command.ToString().TrimEnd('\r') == "STOP") break;
                    command.Clear();
                }
                else if (command.Length >= 32) break;
                else command.Append((char)value);
            }
        }
        catch (IOException) { }
        stopRequested = true; // Also honored when EOF precedes HWND creation.
        try { if (!IsDisposed && IsHandleCreated) BeginInvoke((Action)Close); }
        catch (InvalidOperationException) { }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        if (parentHwnd == IntPtr.Zero) return; // Offline smoke only.
        if (!IsWindow(parentHwnd) || GetWindowThreadProcessId(parentHwnd, out parentPid) == 0)
            throw new CameraStartupException("parent_window_missing");
        var style = GetWindowLongPtr(Handle, -16).ToInt64();
        SetWindowLongPtr(Handle, -16, new IntPtr((style | 0x40000000 | 0x02000000) & ~0x80000000L));
        SetParent(Handle, parentHwnd);
        if (GetParent(Handle) != parentHwnd) throw new CameraStartupException("parent_window_mismatch");
        parentWatch.Start();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        closing = true;
        stopRequested = true;
        ownerNavigation = false;
        deadline.Stop();
        parentWatch.Stop();
        var web = browser.CoreWebView2;
        if (web != null)
        {
            try { web.IsMuted = true; web.Stop(); web.Navigate("about:blank"); }
            catch (COMException) { }
        }
        browser.Dispose();
        base.OnFormClosing(e);
    }

    private void Fail(string reason)
    {
        if (closing) return;
        ExitCode = 1;
        Reply(new { type = "error", camera_id = camera.Id, reason });
        Close();
    }

    private bool ShouldStop()
    {
        if (stopRequested && !closing && !IsDisposed) Close();
        return closing || stopRequested || IsDisposed;
    }

    private static void RejectBrowserOverrides()
    {
        foreach (string key in new[] {
            "WEBVIEW2_USER_DATA_FOLDER", "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE", "WEBVIEW2_RELEASE_CHANNELS", "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER",
            "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER",
        })
            if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(key)))
                throw new CameraStartupException("unsafe_browser_override");
        foreach (RegistryKey root in new[] { Registry.LocalMachine, Registry.CurrentUser })
        foreach (string key in new[] { "UserDataFolder", "BrowserExecutableFolder", "AdditionalBrowserArguments", "ReleaseChannelPreference", "ReleaseChannels" })
        {
            using var policy = root.OpenSubKey(@"SOFTWARE\Policies\Microsoft\Edge\WebView2\" + key);
            if (policy != null && policy.GetValueNames().Any(name => !string.IsNullOrWhiteSpace(policy.GetValue(name)?.ToString())))
                throw new CameraStartupException("unsafe_browser_override");
        }
    }

    private async Task OpenAsync()
    {
        try
        {
            if (ShouldStop()) return;
            deadline.Start();
            RejectBrowserOverrides();
            initializationInFlight = true;
            profileCreationAttempted = true;
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: privateFolder,
                options: new CoreWebView2EnvironmentOptions {
                    ExclusiveUserDataFolderAccess = true,
                    AllowSingleSignOnUsingOSPrimaryAccount = false,
                    // Require deliberate Play; no rewritten URL, Referer or UA.
                    AdditionalBrowserArguments = "--autoplay-policy=user-gesture-required",
                });
            if (ShouldStop()) return;
            if (!string.Equals(Path.GetFullPath(environment.UserDataFolder).TrimEnd(Path.DirectorySeparatorChar),
                               Path.GetFullPath(privateFolder).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
                throw new CameraStartupException("private_profile_mismatch");
            var options = environment.CreateCoreWebView2ControllerOptions();
            options.IsInPrivateModeEnabled = true;
            await browser.EnsureCoreWebView2Async(environment, options);
            if (ShouldStop()) return;
            var web = browser.CoreWebView2 ?? throw new CameraStartupException("webview2_unavailable");
            browserProcess = Process.GetProcessById(checked((int)web.BrowserProcessId));
            // Capture the handle now; never reopen a possibly reused PID later.
            if (!OwnedProcessJob.Contains(browserProcess.Handle))
                throw new CameraStartupException("process_isolation_failed");
            if (!web.Profile.IsInPrivateModeEnabled) throw new CameraStartupException("private_profile_mismatch");
            web.Settings.AreDefaultContextMenusEnabled = false;
            web.Settings.AreDevToolsEnabled = false;
            web.Settings.AreBrowserAcceleratorKeysEnabled = false;
            web.Settings.AreHostObjectsAllowed = false;
            web.Settings.IsWebMessageEnabled = false;
            web.Settings.AreDefaultScriptDialogsEnabled = false;
            web.Settings.IsStatusBarEnabled = false;
            web.Profile.IsPasswordAutosaveEnabled = false;
            web.Profile.IsGeneralAutofillEnabled = false;
            web.IsMuted = true;
            web.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All, CoreWebView2WebResourceRequestSourceKinds.All);
            web.WebResourceRequested += (_, e) => {
                bool internalResource = camera.InternalResource(e.Request.Uri);
                bool allowed = internalResource || !closing && !stopRequested && !smoke && !embed && camera.RequestAllowed(e.Request.Uri);
                if (e.ResourceContext == CoreWebView2WebResourceContext.Document)
                    allowed = e.Request.Uri is "about:blank" or "about:srcdoc"
                        || !closing && !stopRequested && !smoke && !embed && (camera.ExactPage(e.Request.Uri) || camera.FrameAllowed(e.Request.Uri));
                if (!allowed)
                    e.Response = environment.CreateWebResourceResponse(null, 403, "Blocked", "Content-Type: text/plain");
            };
            web.NavigationStarting += (_, e) => {
                if (e.Uri == "about:blank" && (!ownerNavigation || closing)) return;
                if (closing || stopRequested || smoke || embed || !camera.ExactPage(e.Uri)) e.Cancel = true;
                else navigationId = e.NavigationId;
            };
            web.FrameNavigationStarting += (_, e) => {
                if (closing || stopRequested || smoke || embed || !camera.FrameAllowed(e.Uri)) e.Cancel = true;
            };
            web.NewWindowRequested += (_, e) => e.Handled = true;
            web.DownloadStarting += (_, e) => { e.Cancel = true; e.Handled = true; };
            web.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            web.ServerCertificateErrorDetected += (_, e) => e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
            web.BasicAuthenticationRequested += (_, e) => e.Cancel = true;
            web.ClientCertificateRequested += (_, e) => { e.Cancel = true; e.Handled = true; };
            web.ProcessFailed += (_, _) => Fail("renderer_exited");
            web.NavigationCompleted += async (_, e) => {
                if (closing || stopRequested || !ownerNavigation || e.NavigationId != navigationId) return;
                bool success = e.IsSuccess && e.HttpStatusCode >= 200 && e.HttpStatusCode < 300 && camera.ExactPage(web.Source);
                bool playerFocused = false;
                if (success)
                {
                    // Reapply the fixed presentation resource after the provider
                    // has built its DOM. A layout change falls back to the page;
                    // it never rewrites a player URL or establishes video playback.
                    try
                    {
                        using var presentation = JsonDocument.Parse(await web.ExecuteScriptAsync(playerViewScript));
                        playerFocused = presentation.RootElement.ValueKind == JsonValueKind.Object
                            && presentation.RootElement.TryGetProperty("applied", out var applied)
                            && applied.ValueKind == JsonValueKind.True;
                    }
                    catch { /* Keep the successfully loaded provider page usable. */ }
                }
                if (ShouldStop() || e.NavigationId != navigationId) return;
                success = success && camera.ExactPage(web.Source);
                deadline.Stop();
                Reply(new { type = "page_loaded", camera_id = camera.Id, success,
                    player_focused = playerFocused && success, playback_verified = false });
                if (!success) Fail("navigation_failed");
            };
            // Establish codec capability locally before contacting any camera.
            var localPage = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            void Loaded(object? sender, CoreWebView2NavigationCompletedEventArgs e) => localPage.TrySetResult(e.IsSuccess);
            web.NavigationCompleted += Loaded;
            web.Navigate("about:blank");
            await Task.WhenAny(localPage.Task, Task.Delay(10_000));
            web.NavigationCompleted -= Loaded;
            if (ShouldStop()) return;
            if (!localPage.Task.IsCompletedSuccessfully || !localPage.Task.Result)
                throw new CameraStartupException("local_page_unavailable");
            var encoded = await web.ExecuteScriptAsync("JSON.stringify({h264:document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"'),aac:document.createElement('video').canPlayType('audio/mp4; codecs=\"mp4a.40.2\"')})");
            if (ShouldStop()) return;
            using var codec = JsonDocument.Parse(JsonSerializer.Deserialize<string>(encoded) ?? "{}");
            string h264 = codec.RootElement.GetProperty("h264").GetString() ?? "";
            string aac = codec.RootElement.GetProperty("aac").GetString() ?? "";
            bool capable = (h264 is "probably" or "maybe") && (aac is "probably" or "maybe");
            if (smoke)
            {
                Reply(new { type = "camera_codec_probe", camera_id = camera.Id, network = "none",
                    h264, aac, capable, in_private = web.Profile.IsInPrivateModeEnabled });
                if (!capable) ExitCode = 1;
                Close();
                return;
            }
            if (!capable) throw new CameraStartupException("codec_unavailable");
            Reply(new { type = "ready", camera_id = camera.Id, hwnd = Handle.ToInt64(), in_private = web.Profile.IsInPrivateModeEnabled });
            if (embed)
            {
                await web.ExecuteScriptAsync("document.documentElement.style.backgroundColor='#f21a9a';document.body.style.backgroundColor='#f21a9a';document.body.style.margin='0';document.body.style.minHeight='100vh';");
                if (ShouldStop()) return;
                deadline.Stop();
                Reply(new { type = "embed_probe_ready", camera_id = camera.Id, network = "none", marker = "f21a9a" });
                return;
            }
            if (ShouldStop()) return;
            using (var scriptStream = typeof(CameraForm).Assembly.GetManifestResourceStream("GlobalPulse.Camera.player_view.js")
                ?? throw new CameraStartupException("player_view_unavailable"))
            using (var scriptReader = new StreamReader(scriptStream))
                playerViewScript = scriptReader.ReadToEnd();
            // This bundled script guards the exact top document itself, including
            // child frames. No script or URL is accepted from commands or feeds.
            await web.AddScriptToExecuteOnDocumentCreatedAsync(playerViewScript);
            if (ShouldStop()) return;
            ownerNavigation = true;
            web.Navigate(camera.PlayerUrl); // Exact public provider player route.
        }
        catch (WebView2RuntimeNotFoundException) { Fail("webview2_unavailable"); }
        catch (CameraStartupException error) { Fail(error.Code); }
        catch { Fail("initialization_failed"); }
        finally { initializationInFlight = false; }
    }

    internal void CleanupOwnedProfile()
    {
        // If shutdown overtook SDK initialization, it may still create files.
        // A vanished/absent directory at this instant cannot prove cleanup.
        if (initializationInFlight || profileCreationAttempted && browserProcess == null)
        {
            Reply(new { type = "privacy_cleanup", camera_id = camera.Id, state = "pending" });
            return;
        }
        if (browserProcess != null)
        {
            try
            {
                if (!browserProcess.WaitForExit(1200))
                {
                    Reply(new { type = "privacy_cleanup", camera_id = camera.Id, state = "pending" });
                    return;
                }
            }
            catch (InvalidOperationException)
            {
                Reply(new { type = "privacy_cleanup", camera_id = camera.Id, state = "pending" });
                return;
            }
            finally { browserProcess.Dispose(); }
        }
        // Never scan or remove any pre-existing/user-selected profile or folder.
        string path = Path.GetFullPath(privateFolder);
        string temp = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar);
        if (!string.Equals(Path.GetDirectoryName(path), temp, StringComparison.OrdinalIgnoreCase)
            || !Regex.IsMatch(Path.GetFileName(path), @"\AGlobalPulse-Camera-[a-f0-9]{32}\z"))
        {
            Reply(new { type = "privacy_cleanup", camera_id = camera.Id, state = "pending" });
            return;
        }
        for (int attempt = 0; attempt < 6; attempt++)
        {
            try
            {
                if (Directory.Exists(path))
                {
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) break;
                    Directory.Delete(path, recursive: true);
                }
                Reply(new { type = "privacy_cleanup", camera_id = camera.Id, state = "removed" });
                return;
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            Thread.Sleep(100); // Bounded helper-only cleanup, never the Qt UI.
        }
        Reply(new { type = "privacy_cleanup", camera_id = camera.Id, state = "pending" });
    }
}

internal static class OwnedProcessJob
{
    private static IntPtr ownedJob;
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits {
        internal long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        internal uint LimitFlags;
        internal UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        internal uint ActiveProcessLimit;
        internal UIntPtr Affinity;
        internal uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters {
        internal ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        internal ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }
    [StructLayout(LayoutKind.Sequential)] private struct ExtendedLimits {
        internal BasicLimits BasicLimitInformation;
        internal IoCounters IoInfo;
        internal UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateJobObject(IntPtr attributes, string? name);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits limits, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);

    internal static bool Contains(IntPtr process)
        => ownedJob != IntPtr.Zero && IsProcessInJob(process, ownedJob, out var member) && member;

    internal static IntPtr Create()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null); // Non-inheritable handle.
        if (job == IntPtr.Zero) throw new CameraStartupException("process_isolation_failed");
        var limits = new ExtendedLimits();
        limits.BasicLimitInformation.LimitFlags = 0x00002000; // KILL_ON_JOB_CLOSE; no breakaway.
        if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf<ExtendedLimits>())
            || !AssignProcessToJobObject(job, Process.GetCurrentProcess().Handle))
        {
            CloseHandle(job);
            throw new CameraStartupException("process_isolation_failed");
        }
        ownedJob = job;
        return job;
    }
}
