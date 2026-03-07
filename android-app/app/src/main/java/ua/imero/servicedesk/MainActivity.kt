package ua.imero.servicedesk

import android.net.Uri
import android.os.Bundle
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.browser.customtabs.CustomTabsIntent
import androidx.browser.trusted.TrustedWebActivityIntentBuilder
import com.google.androidbrowserhelper.trusted.TwaLauncher

/**
 * MainActivity — entry point for the ServiceDesk Android wrapper.
 *
 * Strategy:
 * 1. Attempt to launch a Trusted Web Activity (TWA) via Chrome.
 *    TWA uses the full Chrome engine and satisfies PWA requirements
 *    (localStorage, Service Worker, HTTPS, etc.) without a separate WebView.
 * 2. If Chrome / Custom Tabs are unavailable on the device, fall back to
 *    a built-in WebView with the minimal settings required for the SPA.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var fallbackWebView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val url = getString(R.string.base_url)

        if (!tryLaunchTwa(url)) {
            launchFallbackWebView(url)
        }
    }

    // -------------------------------------------------------------------------
    // TWA launch
    // -------------------------------------------------------------------------

    /**
     * Tries to start a Trusted Web Activity.
     *
     * Returns `true` when the TWA intent was dispatched successfully, `false`
     * when no supporting browser is installed and a fallback is needed.
     */
    private fun tryLaunchTwa(url: String): Boolean {
        return try {
            val uri = Uri.parse(url)
            val launcher = TwaLauncher(this)
            launcher.launch(
                TrustedWebActivityIntentBuilder(uri),
                null,
                null,
            )
            // TwaLauncher.launch() calls finish() internally when successful,
            // but we return true here to signal that it was attempted.
            true
        } catch (e: Exception) {
            false
        }
    }

    // -------------------------------------------------------------------------
    // Fallback WebView
    // -------------------------------------------------------------------------

    /**
     * Inflates a full-screen [WebView] when TWA is not available.
     *
     * Settings mirror the requirements described in the issue:
     * - JavaScript enabled (SPA routing)
     * - DOM storage enabled (localStorage-based JWT storage)
     * - No file access (security hardening)
     * - Images loaded automatically
     */
    private fun launchFallbackWebView(url: String) {
        fallbackWebView = WebView(this).also { wv ->
            wv.webViewClient = WebViewClient()
            wv.settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                setSupportMultipleWindows(false)
                @Suppress("DEPRECATION")
                allowFileAccess = false
                loadsImagesAutomatically = true
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                cacheMode = WebSettings.LOAD_DEFAULT
            }
            wv.loadUrl(url)
        }
        setContentView(fallbackWebView)

        // Register back-press callback using the modern OnBackPressedDispatcher
        // API (replaces the deprecated onBackPressed() override).
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (fallbackWebView.canGoBack()) {
                        fallbackWebView.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            },
        )
    }
}
