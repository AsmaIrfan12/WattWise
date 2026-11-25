package com.wattwise.userapp.ui.main

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.http.SslError
import android.os.Build
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import com.wattwise.userapp.BuildConfig
import com.wattwise.userapp.util.DeepLinks
import kotlinx.coroutines.launch
import timber.log.Timber

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

@OptIn(ExperimentalMaterial3Api::class)
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MainScreen(
    viewModel: MainViewModel = hiltViewModel(),
    onNavigateToSettings: () -> Unit,
    onLogout: () -> Unit = {}
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    val fullUrl by viewModel.fullUrl.collectAsState()
    val webUrl by viewModel.webUrl.collectAsState()
    val isConnected by viewModel.isConnected.collectAsState()
    val isPageLoaded by viewModel.isPageLoaded.collectAsState()
    val isError by viewModel.isError.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val lastWebViewUrl by viewModel.lastWebViewUrl.collectAsState()
    val logoutEvent by viewModel.logoutEvent.collectAsState()
    val pendingDeepLinkTab by viewModel.pendingDeepLinkTab.collectAsState()
    val pendingAlertId by viewModel.pendingAlertId.collectAsState()

    var webViewRef by remember { mutableStateOf<WebView?>(null) }
    var progress by remember { mutableIntStateOf(0) }
    var isRefreshing by remember { mutableStateOf(false) }
    // True once THIS WebView has finished loading the dashboard. (The ViewModel flag
    // outlives the WebView, so it cannot say whether the page can run a deep link yet.)
    var pageReady by remember { mutableStateOf(false) }
    // The server address the WebView was last told to load from.
    var loadedServer by remember { mutableStateOf<String?>(null) }

    // Coming back to this screen after a failed load (e.g. from Settings, with a
    // corrected address) should try again, not show the old error.
    LaunchedEffect(Unit) {
        if (viewModel.isError.value) viewModel.onRetry()
    }
    // Track previous connectivity to only show snackbar on change
    var wasConnected by remember { mutableStateOf(true) }

    // ── Notification permission request (Android 13+) ────────────────────
    val notifPermLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        Timber.i("POST_NOTIFICATIONS permission: ${if (granted) "granted" else "denied"}")
    }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val state = ContextCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS
            )
            if (state != PackageManager.PERMISSION_GRANTED) {
                notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    // ── Navigate to Login on logout event ────────────────────────────────
    LaunchedEffect(logoutEvent) {
        if (logoutEvent) {
            viewModel.logoutEventConsumed()
            onLogout()
        }
    }

    // ── Connectivity banner (only fires on change, not on initial load) ──
    LaunchedEffect(isConnected) {
        if (!isConnected && wasConnected) {
            scope.launch {
                snackbarHostState.showSnackbar(
                    message = "📡 No internet connection",
                    duration = SnackbarDuration.Long
                )
            }
        } else if (isConnected && !wasConnected) {
            scope.launch {
                snackbarHostState.showSnackbar(
                    message = "✅ Connection restored",
                    duration = SnackbarDuration.Short
                )
            }
        }
        wasConnected = isConnected
    }

    // ── Deep-link → WebView JS navigation ────────────────────────────────
    // When a pending tab is queued (from a notification tap or Intent), evaluate
    // the JS function in the WebView and clear the pending state.
    LaunchedEffect(pendingDeepLinkTab, pendingAlertId, pageReady) {
        val tab = pendingDeepLinkTab
        val wv = webViewRef
        if (tab != null && pageReady && wv != null) {
            // The script is built from a whitelisted tab and a numeric id only.
            DeepLinks.navigationJs(tab, pendingAlertId)?.let { js ->
                wv.evaluateJavascript(js, null)
                Timber.d("Deep link executed: tab=$tab alert=$pendingAlertId")
            }
            viewModel.deepLinkConsumed()
        }
    }

    // ── Back button ──────────────────────────────────────────────────────
    // Back belongs to the dashboard first: it closes whatever is open, returns to the
    // previous section, then to Home. Only when the dashboard has nothing left to go
    // back to does the app step into the background (it is not destroyed, so it
    // reopens where it was). Before this, Back closed the app from any section.
    BackHandler(enabled = true) {
        val leaveApp: () -> Unit = { context.findActivity()?.moveTaskToBack(true) }
        val wv = webViewRef
        if (wv == null || !pageReady) {
            leaveApp()
        } else {
            wv.evaluateJavascript(DeepLinks.BACK_JS) { answer ->
                if (!DeepLinks.dashboardHandledBack(answer)) leaveApp()
            }
        }
    }

    // ── Re-inject JWT after settings save ────────────────────────────────
    // Fires whenever webUrl changes (e.g. server URL or port edited in Settings).
    // Re-injects the token into WebView localStorage so the web frontend
    // can re-authenticate via window.onNativeTokenInjected without a reload.
    LaunchedEffect(webUrl) {
        val wv = webViewRef ?: return@LaunchedEffect
        if (webUrl.isBlank()) return@LaunchedEffect
        // The server address changed (Settings). The WebView is created once, possibly
        // with the address this screen last knew, so it has to be told to move: without
        // this the dashboard kept showing the previous server until the app restarted.
        if (!DeepLinks.isServerUrl(loadedServer, webUrl)) {
            Timber.i("Server address changed: reloading the dashboard from the new server")
            pageReady = false
            loadedServer = webUrl
            wv.loadUrl(webUrl)
            return@LaunchedEffect
        }
        val tok = viewModel.secureTokenStore.getTokenSync() ?: return@LaunchedEffect
        val safeToken = JSONObject.quote(tok)
        val js = """
            (function() {
              try {
                localStorage.setItem('ww_token', $safeToken);
                if (typeof window.onNativeTokenInjected === 'function') {
                  window.onNativeTokenInjected($safeToken);
                }
              } catch(e) {}
            })();
        """.trimIndent()
        wv.evaluateJavascript(js, null)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("WattWise", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = { webViewRef?.reload() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                    IconButton(onClick = onNavigateToSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "Settings")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    titleContentColor = MaterialTheme.colorScheme.onPrimary,
                    actionIconContentColor = MaterialTheme.colorScheme.onPrimary
                )
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // ── Layer 1: WebView ──
            if (!isError && webUrl.isNotBlank()) {
                PullToRefreshBox(
                    isRefreshing = isRefreshing,
                    onRefresh = {
                        isRefreshing = true
                        webViewRef?.reload()
                    },
                    modifier = Modifier.fillMaxSize()
                ) {
                    AndroidView(
                        factory = { ctx ->
                            WebView(ctx).apply {
                                layoutParams = ViewGroup.LayoutParams(
                                    ViewGroup.LayoutParams.MATCH_PARENT,
                                    ViewGroup.LayoutParams.MATCH_PARENT
                                )

                                // Debug builds only: lets chrome://inspect attach to the dashboard
                                // exactly as this WebView renders it (desktop browsers lay the
                                // page out differently from a phone WebView).
                                if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true)

                                CookieManager.getInstance().setAcceptCookie(true)
                                CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

                                settings.apply {
                                    javaScriptEnabled = true
                                    domStorageEnabled = true
                                    databaseEnabled = true
                                    useWideViewPort = true
                                    loadWithOverviewMode = true
                                    setSupportZoom(true)
                                    builtInZoomControls = true
                                    displayZoomControls = false
                                    mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                                    allowFileAccess = false
                                    allowContentAccess = false
                                    setGeolocationEnabled(true)
                                    cacheMode = WebSettings.LOAD_DEFAULT
                                    mediaPlaybackRequiresUserGesture = false
                                    userAgentString = "$userAgentString WattWiseApp/${BuildConfig.VERSION_NAME}"
                                }

                                // ── JS Bridge: window.WattWiseApp ──────────────────
                                addJavascriptInterface(
                                    WattWiseJsBridge(
                                        onTabNavigation = { tab ->
                                            // JS called WattWiseApp.navigateTo("goals") — queue it
                                            viewModel.handleDeepLink(tab)
                                            // Immediately evaluate since page is loaded (tab is whitelisted by the bridge)
                                            DeepLinks.navigationJs(tab, null)?.let { post { evaluateJavascript(it, null) } }
                                        },
                                        onLogoutRequest = {
                                            viewModel.logout()
                                        },
                                        onTokenChange = { token ->
                                            viewModel.onWebTokenChanged(token)
                                        },
                                        appVersion = BuildConfig.VERSION_NAME
                                    ),
                                    "WattWiseApp"
                                )

                                // A failed main-frame load still ends with onPageFinished (for
                                // the built-in error page). Without this flag that call marked
                                // the page as loaded, which hid the error screen and reloaded the
                                // dashboard in an endless loop while the server was unreachable.
                                var mainFrameFailed = false

                                webViewClient = object : WebViewClient() {
                                    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                                        mainFrameFailed = false
                                        progress = 0
                                        url?.let { viewModel.onWebViewUrlChanged(it) }
                                    }

                                    // The WebView is the dashboard, not a browser: anything that is not
                                    // the configured WattWise server opens in the system browser instead,
                                    // so a redirect can never take the session (and the JS bridge) elsewhere.
                                    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                                        val target = request?.url?.toString() ?: return true
                                        if (DeepLinks.isServerUrl(target, viewModel.fullUrl.value)) return false
                                        if (request.isForMainFrame && (target.startsWith("http://") || target.startsWith("https://"))) {
                                            try {
                                                ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(target)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                                            } catch (e: Exception) {
                                                Timber.w("No app to open external link")
                                            }
                                        }
                                        return true
                                    }

                                    override fun onPageFinished(view: WebView?, url: String?) {
                                        isRefreshing = false
                                        progress = 100
                                        if (mainFrameFailed) return
                                        viewModel.onPageLoaded()
                                        pageReady = true

                                        // ── Inject JWT into localStorage ──────────────
                                        // This ensures the web frontend always has the token
                                        // even after rotation (when the URL fragment is not resent).
                                        // Only ever hand the session token to the WattWise server's own page.
                                        val token = viewModel.secureTokenStore.getTokenSync()
                                        if (!token.isNullOrBlank() && DeepLinks.isServerUrl(url, viewModel.fullUrl.value)) {
                                            // JSONObject.quote() safely escapes the token so any
                                            // special chars (e.g. from a crafted token) cannot break
                                            // out of the JS string literal.
                                            val safeToken = JSONObject.quote(token)
                                            val js = """
                                                (function() {
                                                  try {
                                                    var t = $safeToken;
                                                    var existing = localStorage.getItem('ww_token');
                                                    if (!existing || existing !== t) {
                                                      localStorage.setItem('ww_token', t);
                                                      if (typeof window.onNativeTokenInjected === 'function') {
                                                        window.onNativeTokenInjected(t);
                                                      }
                                                    }
                                                  } catch(e) {}
                                                })();
                                            """.trimIndent()
                                            view?.evaluateJavascript(js, null)
                                            Timber.d("JWT injected into WebView localStorage")
                                        }
                                    }

                                    override fun onReceivedError(
                                        view: WebView?,
                                        request: WebResourceRequest?,
                                        error: WebResourceError?
                                    ) {
                                        if (request?.isForMainFrame == true) {
                                            mainFrameFailed = true
                                            isRefreshing = false
                                            viewModel.onPageError(
                                                "Could not connect to the WattWise server.\n\nPlease check your internet connection and server settings."
                                            )
                                        }
                                    }

                                    // The server answered, but with a failure page (e.g. 502 while
                                    // it restarts): show the retry screen, not a bare error page.
                                    override fun onReceivedHttpError(
                                        view: WebView?,
                                        request: WebResourceRequest?,
                                        errorResponse: WebResourceResponse?
                                    ) {
                                        val status = errorResponse?.statusCode ?: return
                                        if (request?.isForMainFrame == true && status >= 500) {
                                            mainFrameFailed = true
                                            isRefreshing = false
                                            viewModel.onPageError(
                                                "The WattWise server is temporarily unavailable (HTTP $status).\n\nPlease try again in a minute."
                                            )
                                        }
                                    }

                                    override fun onReceivedSslError(
                                        view: WebView?,
                                        handler: SslErrorHandler?,
                                        error: SslError?
                                    ) {
                                        if (BuildConfig.DEBUG) {
                                            Timber.w("SSL error: $error — proceeding for dev")
                                            handler?.proceed()
                                        } else {
                                            Timber.e("SSL error dropped in production: $error")
                                            handler?.cancel()
                                        }
                                    }
                                }

                                webChromeClient = object : WebChromeClient() {
                                    override fun onProgressChanged(view: WebView?, newProgress: Int) {
                                        progress = newProgress
                                    }

                                    // Debug builds: surface the page's own warnings and errors in
                                    // logcat, so a section that fails to open can be diagnosed.
                                    override fun onConsoleMessage(message: ConsoleMessage?): Boolean {
                                        val level = message?.messageLevel()
                                        if (BuildConfig.DEBUG && (level == ConsoleMessage.MessageLevel.ERROR ||
                                                    level == ConsoleMessage.MessageLevel.WARNING)) {
                                            Timber.w("Dashboard console: ${message?.message()} (line ${message?.lineNumber()})")
                                        }
                                        return true
                                    }

                                    override fun onGeolocationPermissionsShowPrompt(
                                        origin: String?,
                                        callback: GeolocationPermissions.Callback?
                                    ) {
                                        // Location is only shared with the WattWise server itself.
                                        callback?.invoke(origin, DeepLinks.isServerUrl(origin, viewModel.fullUrl.value), false)
                                    }
                                }

                                webViewRef = this
                                // Returning to this screen: go back to the page that was open,
                                // but only if it belongs to the server that is configured NOW
                                // (after a change in Settings the old address must not be reused).
                                val previous = lastWebViewUrl?.takeIf { DeepLinks.isServerUrl(it, webUrl) }
                                loadedServer = webUrl
                                loadUrl(previous ?: webUrl)
                            }
                        },
                        modifier = Modifier.fillMaxSize(),
                        onRelease = { released ->
                            // Leaving the screen or switching to the error screen: free the
                            // WebView so it cannot keep loading (and calling back) unseen.
                            pageReady = false
                            if (webViewRef === released) webViewRef = null
                            released.destroy()
                        }
                    )
                }

                // Progress bar
                if (progress in 1..99) {
                    LinearProgressIndicator(
                        progress = { progress / 100f },
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.secondary
                    )
                }

                // ── Connectivity banner overlay (non-blocking) ────────────
                AnimatedVisibility(
                    visible = !isConnected && isPageLoaded,
                    enter = fadeIn(animationSpec = tween(300)),
                    exit = fadeOut(animationSpec = tween(300)),
                    modifier = Modifier.align(Alignment.TopCenter)
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Color(0xFFDC2626))
                            .padding(horizontal = 16.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.WifiOff,
                            contentDescription = null,
                            tint = Color.White,
                            modifier = Modifier.size(14.dp)
                        )
                        Spacer(modifier = Modifier.size(6.dp))
                        Text(
                            text = "No internet connection",
                            color = Color.White,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
            }

            // ── Layer 2: Loading overlay ──
            if (!isPageLoaded && !isError) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Text(text = "🌿", fontSize = 56.sp)
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "WattWise",
                        fontSize = 22.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Smart Energy Monitoring",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.height(32.dp))
                    CircularProgressIndicator(
                        modifier = Modifier.size(36.dp),
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "Connecting to server…",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.outline
                    )
                }
            }

            // ── Layer 3: Error overlay ──
            if (isError) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background)
                        .padding(32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Icon(
                        imageVector = Icons.Default.WifiOff,
                        contentDescription = null,
                        modifier = Modifier.size(64.dp),
                        tint = MaterialTheme.colorScheme.error
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        text = "Connection Failed",
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = errorMessage,
                        fontSize = 14.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        lineHeight = 20.sp
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Server: $fullUrl\nNetwork: ${viewModel.getNetworkType()}",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.outline,
                        fontFamily = FontFamily.Monospace,
                        textAlign = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(24.dp))
                    Button(
                        onClick = {
                            // Clearing the error brings back a fresh WebView, which loads the dashboard.
                            viewModel.onRetry()
                        },
                        modifier = Modifier.fillMaxWidth(0.6f)
                    ) {
                        Text("Retry Connection")
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = onNavigateToSettings,
                        modifier = Modifier.fillMaxWidth(0.6f)
                    ) {
                        Text("Edit Server Settings")
                    }
                }
            }
        }
    }

}
