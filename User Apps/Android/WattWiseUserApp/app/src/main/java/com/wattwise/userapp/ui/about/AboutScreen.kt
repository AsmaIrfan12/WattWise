package com.wattwise.userapp.ui.about

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.wattwise.userapp.util.Constants

/**
 * WattWise About Screen
 * Displays developer, research, and system version information.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AboutScreen(onNavigateBack: () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("About WattWise") },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    titleContentColor = MaterialTheme.colorScheme.onPrimary,
                    navigationIconContentColor = MaterialTheme.colorScheme.onPrimary
                )
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .padding(innerPadding)
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // ── Hero Banner ──
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(Color(0xFF0F172A), Color(0xFF15803D))
                        )
                    )
                    .padding(vertical = 40.dp),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(text = "⚡", fontSize = 64.sp)
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "WattWise",
                        fontSize = 32.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color.White
                    )
                    Text(
                        text = "Smart Energy Monitoring",
                        fontSize = 14.sp,
                        color = Color.White.copy(alpha = 0.75f)
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = Color(0xFF16A34A).copy(alpha = 0.25f)
                    ) {
                        Text(
                            text = "v${Constants.APP_VERSION}",
                            fontSize = 12.sp,
                            color = Color.White,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp)
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            // ── Info Cards ──
            InfoCard(
                icon = "🔬",
                title = "Research",
                lines = listOf(
                    "PhD Research Programme",
                    Constants.RESEARCH_DESCRIPTION,
                    "",
                    "PhD Researcher",
                    "${Constants.RESEARCHER_NAME}  ·  ${Constants.RESEARCHER_EMAIL}",
                    "",
                    "Platform Developer",
                    "${Constants.DEVELOPER_NAME}  ·  ${Constants.DEVELOPER_EMAIL}"
                )
            )
            InfoCard(
                icon = "👨‍🏫",
                title = "Supervisors",
                lines = listOf(
                    Constants.SUPERVISOR_1,
                    Constants.SUPERVISOR_2,
                    Constants.DEVELOPER_INSTITUTION
                )
            )
            InfoCard(
                icon = "🎓",
                title = "Developer",
                lines = listOf(Constants.DEVELOPER_NAME, Constants.DEVELOPER_INSTITUTION)
            )
            InfoCard(
                icon = "🏫",
                title = "School",
                lines = listOf(Constants.DEVELOPER_SCHOOL, Constants.DEVELOPER_LOCATION)
            )
            InfoCard(
                icon = "⚡",
                title = "System",
                lines = listOf(
                    "WattWise Community Energy Platform",
                    "App Version: ${Constants.APP_VERSION}",
                    "API: ${Constants.DEFAULT_SERVER_URL}"
                )
            )
            InfoCard(
                icon = "🔒",
                title = "Privacy",
                lines = listOf(
                    "Energy data collected for research purposes",
                    "Data anonymised for community rankings",
                    "All processing complies with GDPR"
                )
            )

            Spacer(modifier = Modifier.height(12.dp))

            // ── Tagline ──
            Text(
                text = "Track. Save. Compete.",
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.primary,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 32.dp)
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "© 2024–2026 ${Constants.RESEARCHER_NAME} & ${Constants.DEVELOPER_NAME}\n${Constants.DEVELOPER_INSTITUTION}",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                lineHeight = 18.sp,
                modifier = Modifier.padding(horizontal = 32.dp)
            )

            Spacer(modifier = Modifier.height(40.dp))
        }
    }
}

@Composable
private fun InfoCard(icon: String, title: String, lines: List<String>) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.Top
        ) {
            Text(text = icon, fontSize = 28.sp, modifier = Modifier.width(44.dp))
            Column {
                Text(
                    text = title,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.primary
                )
                lines.forEach { line ->
                    if (line.isEmpty()) {
                        Spacer(modifier = Modifier.height(6.dp))
                    } else {
                        Text(
                            text = line,
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            lineHeight = 20.sp,
                            modifier = Modifier.padding(top = 2.dp)
                        )
                    }
                }
            }
        }
    }
}
