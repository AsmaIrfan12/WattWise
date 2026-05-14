package com.wattwise.userapp.ui.main

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.http.SslError
import android.os.Build
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
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
import androidx.compose.runtime.DisposableEffect
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
import kotlinx.coroutines.launch
import timber.log.Timber

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

    var webViewRef by remember { mutableStateOf<WebView?>(null) }
    var progress by remember { mutableIntStateOf(0) }
    var isRefreshing by remember { mutableStateOf(false) }
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
    LaunchedEffect(pendingDeepLinkTab, isPageLoaded) {
        val tab = pendingDeepLinkTab
        if (tab != null && isPageLoaded) {
            webViewRef?.evaluateJavascript("window.goSection?.('$tab');", null)
            Timber.d("🔗 Deep-link executed: goSection('$tab')")
            viewModel.deepLinkConsumed()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "WattWise",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold
                    )
                },
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
                                    mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                                    allowFileAccess = false
                                    allowContentAccess = false
                                    setGeolocationEnabled(true)
                                    cacheMode = WebSettings.LOAD_DEFAULT
                                    mediaPlaybackRequiresUserGesture = false
                                    userAgentString = "$userAgentString WattWiseApp/4.0"
                                }

                                // ── JS Bridge: window.WattWiseApp ──────────────────
                                addJavascriptInterface(
                                    WattWiseJsBridge(
                                        onTabNavigation = { tab ->
                                            // JS called WattWiseApp.navigateTo("goals") — queue it
                                            viewModel.handleDeepLink(tab)
                                            // Immediately evaluate since page is loaded
                                            evaluateJavascript("window.goSection?.('$tab');", null)
                                        },
                                        onLogoutRequest = {
                                            viewModel.logout()
                                        },
                                        appVersion = BuildConfig.VERSION_NAME
                                    ),
                                    "WattWiseApp"
                                )

                                webViewClient = object : WebViewClient() {
                                    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                                        progress = 0
                                        url?.let { viewModel.onWebViewUrlChanged(it) }
                                    }

                                    override fun onPageFinished(view: WebView?, url: String?) {
                                        viewModel.onPageLoaded()
                                        isRefreshing = false
                                        progress = 100

                                        // ── Inject JWT into localStorage ──────────────
                                        // This ensures the web frontend always has the token
                                        // even after rotation (when the URL fragment is not resent).
                                        val token = viewModel.secureTokenStore.getTokenSync()
                                        if (!token.isNullOrBlank()) {
                                            val js = """
                                                (function() {
                                                  try {
                                                    var existing = localStorage.getItem('ww_token');
                                                    if (!existing || existing !== '$token') {
                                                      localStorage.setItem('ww_token', '$token');
                                                      if (typeof window.onNativeTokenInjected === 'function') {
                                                        window.onNativeTokenInjected('$token');
                                                      }
                                                    }
                                                  } catch(e) {}
                                                })();
                                            """.trimIndent()
                                            view?.evaluateJavascript(js, null)
                                            Timber.d("🔐 JWT injected into WebView localStorage")
                                        }
                                    }

                                    override fun onReceivedError(
                                        view: WebView?,
                                        request: WebResourceRequest?,
                                        error: WebResourceError?
                                    ) {
                                        if (request?.isForMainFrame == true) {
                                            isRefreshing = false
                                            viewModel.onPageError(
                                                "Could not connect to the WattWise server.\n\nPlease check your internet connection and server settings."
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

                                    override fun onGeolocationPermissionsShowPrompt(
                                        origin: String?,
                                        callback: GeolocationPermissions.Callback?
                                    ) {
                                        callback?.invoke(origin, true, false)
                                    }
                                }

                                webViewRef = this
                                // On rotation: restore last URL instead of re-sending token fragment
                                val urlToLoad = lastWebViewUrl ?: webUrl
                                loadUrl(urlToLoad)
                            }
                        },
                        modifier = Modifier.fillMaxSize()
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
                            viewModel.onRetry()
                            webViewRef?.loadUrl(webUrl)
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

    // Cleanup WebView on dispose
    DisposableEffect(Unit) {
        onDispose {
            webViewRef?.destroy()
            webViewRef = null
        }
    }
}
