package com.wattwise.userapp.ui.auth

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.wattwise.userapp.util.Constants

/**
 * WattWise Native Login Screen.
 *
 * Provides email + password authentication against the FastAPI backend.
 * On success, navigates to the main WebView dashboard.
 *
 * Developer : Mr. Suhas Devmane, Cardiff University, Wales, UK
 * Version   : 4.0.0 (Community Release)
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(
    viewModel: AuthViewModel = hiltViewModel(),
    onLoginSuccess: () -> Unit,
    onNavigateToSignup: () -> Unit
) {
    val uiState by viewModel.loginState.collectAsState()
    val keyboardController = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current
    val passwordFocusRequester = remember { FocusRequester() }

    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var passwordVisible by rememberSaveable { mutableStateOf(false) }
    var visible by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { visible = true }

    // Navigate on success
    LaunchedEffect(uiState) {
        if (uiState is AuthUiState.Success) {
            onLoginSuccess()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(Color(0xFF0F172A), Color(0xFF1E293B))
                )
            )
    ) {
        AnimatedVisibility(
            visible = visible,
            enter = fadeIn(animationSpec = tween(600)) +
                    slideInVertically(animationSpec = tween(600)) { it / 4 }
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 28.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Spacer(modifier = Modifier.height(72.dp))

                // ── Logo + Header ──
                Text(text = "⚡", fontSize = 60.sp)
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "WattWise",
                    fontSize = 32.sp,
                    fontWeight = FontWeight.Bold,
                    color = Color.White
                )
                Text(
                    text = Constants.APP_TAGLINE,
                    fontSize = 14.sp,
                    color = Color.White.copy(alpha = 0.65f)
                )

                Spacer(modifier = Modifier.height(48.dp))

                // ── Card ──
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(20.dp),
                    color = Color(0xFF1E293B),
                    tonalElevation = 4.dp
                ) {
                    Column(
                        modifier = Modifier.padding(24.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        Text(
                            text = "Sign In",
                            fontSize = 22.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                        Text(
                            text = "Access your community energy dashboard",
                            fontSize = 13.sp,
                            color = Color(0xFF94A3B8)
                        )

                        Spacer(modifier = Modifier.height(4.dp))

                        // ── Email field ──
                        OutlinedTextField(
                            value = email,
                            onValueChange = { email = it.trim() },
                            label = { Text("Email address") },
                            leadingIcon = { Icon(Icons.Default.Email, contentDescription = null) },
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Email,
                                imeAction = ImeAction.Next
                            ),
                            keyboardActions = KeyboardActions(
                                onNext = { passwordFocusRequester.requestFocus() }
                            ),
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            colors = authTextFieldColors(),
                            shape = RoundedCornerShape(12.dp)
                        )

                        // ── Password field ──
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            label = { Text("Password") },
                            leadingIcon = { Icon(Icons.Default.Lock, contentDescription = null) },
                            trailingIcon = {
                                IconButton(onClick = { passwordVisible = !passwordVisible }) {
                                    Icon(
                                        imageVector = if (passwordVisible) Icons.Default.VisibilityOff
                                                      else Icons.Default.Visibility,
                                        contentDescription = if (passwordVisible) "Hide password" else "Show password"
                                    )
                                }
                            },
                            visualTransformation = if (passwordVisible) VisualTransformation.None
                                                   else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Password,
                                imeAction = ImeAction.Done
                            ),
                            keyboardActions = KeyboardActions(
                                onDone = {
                                    keyboardController?.hide()
                                    focusManager.clearFocus()
                                    if (email.isNotBlank() && password.isNotBlank()) {
                                        if (android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
                                            viewModel.login(email, password)
                                        } else {
                                            viewModel.setError("Please enter a valid email address")
                                        }
                                    }
                                }
                            ),
                            singleLine = true,
                            modifier = Modifier
                                .fillMaxWidth()
                                .focusRequester(passwordFocusRequester),
                            colors = authTextFieldColors(),
                            shape = RoundedCornerShape(12.dp)
                        )

                        // ── Error message ──
                        AnimatedVisibility(visible = uiState is AuthUiState.Error) {
                            if (uiState is AuthUiState.Error) {
                                Surface(
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(8.dp),
                                    color = MaterialTheme.colorScheme.errorContainer
                                ) {
                                    Text(
                                        text = (uiState as AuthUiState.Error).message,
                                        color = MaterialTheme.colorScheme.onErrorContainer,
                                        fontSize = 13.sp,
                                        modifier = Modifier.padding(12.dp)
                                    )
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(4.dp))

                        // ── Login button ──
                        Button(
                            onClick = {
                                keyboardController?.hide()
                                focusManager.clearFocus()
                                if (android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
                                    viewModel.login(email, password)
                                } else {
                                    viewModel.setError("Please enter a valid email address")
                                }
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp),
                            enabled = email.isNotBlank() && password.isNotBlank() &&
                                      uiState !is AuthUiState.Loading,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color(0xFF10B981)  // WattGreen
                            )
                        ) {
                            if (uiState is AuthUiState.Loading) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(22.dp),
                                    color = Color.White,
                                    strokeWidth = 2.dp
                                )
                            } else {
                                Text(
                                    text = "Sign In",
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.SemiBold
                                )
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(24.dp))

                // ── Signup link ──
                Row(
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "New to WattWise? ",
                        color = Color(0xFF94A3B8),
                        fontSize = 14.sp
                    )
                    TextButton(onClick = onNavigateToSignup) {
                        Text(
                            text = "Create Account",
                            color = Color(0xFF10B981),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                }

                Spacer(modifier = Modifier.height(32.dp))

                // ── Research credit ──
                Text(
                    text = "PhD Research — ${Constants.RESEARCH_DESCRIPTION}",
                    fontSize = 10.sp,
                    color = Color.White.copy(alpha = 0.3f),
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = 16.dp)
                )
                Text(
                    text = "${Constants.DEVELOPER_NAME}, ${Constants.DEVELOPER_INSTITUTION}",
                    fontSize = 10.sp,
                    color = Color.White.copy(alpha = 0.25f),
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(24.dp))
            }
        }
    }
}

/** Consistent text field colours for the dark-themed auth forms. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun authTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor     = Color(0xFF10B981),
    unfocusedBorderColor   = Color(0xFF334155),
    focusedLabelColor      = Color(0xFF10B981),
    unfocusedLabelColor    = Color(0xFF64748B),
    focusedTextColor       = Color.White,
    unfocusedTextColor     = Color(0xFFCBD5E1),
    focusedLeadingIconColor   = Color(0xFF10B981),
    unfocusedLeadingIconColor = Color(0xFF64748B),
    cursorColor            = Color(0xFF10B981),
    focusedContainerColor  = Color(0xFF0F172A),
    unfocusedContainerColor = Color(0xFF0F172A),
)
