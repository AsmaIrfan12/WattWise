package com.wattwise.userapp.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.wattwise.userapp.domain.model.Resource
import com.wattwise.userapp.ui.theme.WattDanger
import com.wattwise.userapp.ui.theme.WattSuccess
import com.wattwise.userapp.util.Constants

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    viewModel: SettingsViewModel = hiltViewModel(),
    onNavigateBack: () -> Unit,
    onLogout: () -> Unit = {}
) {
    val currentUrl by viewModel.serverUrl.collectAsState()
    val currentPort by viewModel.port.collectAsState()
    val currentTimeout by viewModel.timeout.collectAsState()
    val testResult by viewModel.testResult.collectAsState()

    var url by remember(currentUrl) { mutableStateOf(currentUrl) }
    var port by remember(currentPort) { mutableStateOf(currentPort.toString()) }
    var timeout by remember(currentTimeout) { mutableStateOf(currentTimeout.toString()) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Server Settings", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
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
                .padding(innerPadding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // ── Server Connection Card ──
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Server Connection",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(16.dp))

                    OutlinedTextField(
                        value = url,
                        onValueChange = { url = it },
                        label = { Text("Server URL") },
                        placeholder = { Text(Constants.DEFAULT_SERVER_URL) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        OutlinedTextField(
                            value = port,
                            onValueChange = { port = it.filter { c -> c.isDigit() } },
                            label = { Text("Port") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            singleLine = true,
                            modifier = Modifier.weight(1f)
                        )
                        OutlinedTextField(
                            value = timeout,
                            onValueChange = { timeout = it.filter { c -> c.isDigit() } },
                            label = { Text("Timeout (s)") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            singleLine = true,
                            modifier = Modifier.weight(1f)
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Default: ${Constants.DEFAULT_SERVER_URL} (port ${Constants.DEFAULT_PORT})\nFor local dev: http://<server-ip>:3001",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.outline,
                        lineHeight = 16.sp
                    )
                }
            }

            // ── Connection Test Card ──
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Connection Test",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(8.dp))

                    // Network status
                    val networkType = viewModel.getNetworkType()
                    val connected = viewModel.isConnected()
                    Text(
                        text = if (connected) "🟢  Connected via $networkType" else "⚫  No internet connection",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    Button(
                        onClick = {
                            viewModel.testConnection(url, port.toIntOrNull() ?: Constants.DEFAULT_PORT)
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = WattSuccess)
                    ) {
                        Text("⚡  Test Connection")
                    }

                    // Test result
                    when (val result = testResult) {
                        is Resource.Loading -> {
                            Spacer(modifier = Modifier.height(12.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("Testing connection…", fontSize = 13.sp)
                            }
                        }
                        is Resource.Success -> {
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = "✅  Connected — HTTP ${result.data}",
                                color = WattSuccess,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 14.sp
                            )
                        }
                        is Resource.Error -> {
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = "❌  ${result.message}",
                                color = WattDanger,
                                fontSize = 14.sp
                            )
                        }
                        null -> { /* No test run yet */ }
                    }
                }
            }

            // ── Action Buttons ──
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                OutlinedButton(
                    onClick = onNavigateBack,
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Cancel")
                }
                Button(
                    onClick = {
                        val validUrl = url.trim()
                        val validPort = port.toIntOrNull() ?: Constants.DEFAULT_PORT
                        val validTimeout = timeout.toIntOrNull() ?: Constants.DEFAULT_TIMEOUT
                        if (validUrl.startsWith("http://") || validUrl.startsWith("https://")) {
                            viewModel.saveSettings(validUrl, validPort, validTimeout)
                            onNavigateBack()
                        }
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("💾  Save")
                }
            }

            TextButton(
                onClick = {
                    viewModel.resetToDefaults()
                    url = Constants.DEFAULT_SERVER_URL
                    port = Constants.DEFAULT_PORT.toString()
                    timeout = Constants.DEFAULT_TIMEOUT.toString()
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Reset to Defaults", color = MaterialTheme.colorScheme.outline)
            }

            // ── Sign Out ──
            Button(
                onClick = { viewModel.logout(onLogout) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = WattDanger)
            ) {
                Text("Sign Out", fontWeight = FontWeight.SemiBold)
            }

            // ── About & Developer Card ──
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "About & Developer",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(12.dp))

                    Text(
                        text = "WattWise",
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "Version ${Constants.APP_VERSION}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    Text(
                        text = "Developed By — ${Constants.DEVELOPER_NAME}, ${Constants.DEVELOPER_SCHOOL}, ${Constants.DEVELOPER_INSTITUTION}, UK",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurface
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        text = "WattWise Community Energy Platform · ${Constants.APP_YEAR}",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.outline
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
        }
    }
}
