package com.wattwise.userapp.ui.splash

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.wattwise.userapp.ui.theme.WattGreen
import com.wattwise.userapp.ui.theme.WattBlue
import com.wattwise.userapp.util.Constants
import kotlinx.coroutines.delay

/**
 * WattWise Splash Screen.
 * Shows animated logo, tagline and developer credit.
 */
@Composable
fun SplashScreen(onSplashFinished: () -> Unit) {
    var startAnimation by remember { mutableStateOf(false) }
    val alpha by animateFloatAsState(
        targetValue = if (startAnimation) 1f else 0f,
        animationSpec = tween(700),
        label = "splash_fade"
    )

    LaunchedEffect(Unit) {
        startAnimation = true
        delay(2000)
        onSplashFinished()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                brush = Brush.verticalGradient(
                    colors = listOf(
                        Color(0xFF0F172A),   // Slate dark
                        Color(0xFF15803D),   // WattGreen
                    )
                )
            ),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .alpha(alpha),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Spacer(modifier = Modifier.weight(1f))

            // Energy bolt icon
            Text(text = "⚡", fontSize = 72.sp)

            Spacer(modifier = Modifier.height(16.dp))

            // App name
            Text(
                text = "WattWise",
                fontSize = 36.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White
            )

            Spacer(modifier = Modifier.height(8.dp))

            // Tagline
            Text(
                text = "Track. Save. Compete.",
                fontSize = 15.sp,
                color = Color.White.copy(alpha = 0.75f)
            )

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "Smart Energy Monitoring",
                fontSize = 12.sp,
                color = Color.White.copy(alpha = 0.55f)
            )

            Spacer(modifier = Modifier.height(48.dp))

            CircularProgressIndicator(
                modifier = Modifier.size(28.dp),
                color = WattGreen,
                strokeWidth = 2.dp
            )

            Spacer(modifier = Modifier.weight(1f))

            Text(
                text = "v${Constants.APP_VERSION}",
                fontSize = 11.sp,
                color = Color.White.copy(alpha = 0.5f)
            )

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = "Developed by ${Constants.DEVELOPER_CREDIT}",
                fontSize = 10.sp,
                color = Color.White.copy(alpha = 0.4f),
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 24.dp)
            )

            Spacer(modifier = Modifier.height(28.dp))
        }
    }
}
