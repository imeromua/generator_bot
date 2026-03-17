package ua.imero.servicedesk

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

/**
 * SplashActivity — shown briefly while the app initialises.
 *
 * The Activity uses the `Theme.ServiceDesk.Splash` window background
 * (defined in `themes.xml`) so no layout needs to be inflated; Android
 * draws the splash screen purely from the theme's `windowBackground`.
 *
 * After a single frame the user is forwarded to [MainActivity].
 */
class SplashActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}
