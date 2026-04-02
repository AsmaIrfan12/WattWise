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
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
 * WattWise Native Signup Screen.
 *
 * Creates a new community participant account via the FastAPI `/api/auth/signup`
 * endpoint. Collects name, email, password and optional home details.
 *
 * Developer : Mr. Suhas Devmane, Cardiff University, Wales, UK
 * Version   : 4.0.0 (Community Release)
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SignupScreen(
    viewModel: AuthViewModel = hiltViewModel(),
    onSignupSuccess: () -> Unit,
    onNavigateToLogin: () -> Unit
) {
    val uiState by viewModel.signupState.collectAsState()
    val keyboardController = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current

    val emailFocus    = remember { FocusRequester() }
    val passwordFocus = remember { FocusRequester() }
    val confirmFocus  = remember { FocusRequester() }

    var name             by rememberSaveable { mutableStateOf("") }
    var email            by rememberSaveable { mutableStateOf("") }
    var password         by rememberSaveable { mutableStateOf("") }
    var confirmPassword  by rememberSaveable { mutableStateOf("") }
    var passwordVisible  by rememberSaveable { mutableStateOf(false) }
    var confirmVisible   by rememberSaveable { mutableStateOf(false) }
    var visible          by remember { mutableStateOf(false) }

    // Local validation
    val passwordMismatch = confirmPassword.isNotEmpty() && password != confirmPassword
    val passwordTooShort = password.isNotEmpty() && password.length < 8
    val canSubmit = name.isNotBlank() && email.isNotBlank() &&
                    password.length >= 8 && password == confirmPassword &&
                    uiState !is AuthUiState.Loading

    LaunchedEffect(Unit) { visible = true }
    LaunchedEffect(uiState) {
        if (uiState is AuthUiState.Success) onSignupSuccess()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(Color(0xFF0F172A), Color(0xFF1E3A5F))
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
                Spacer(modifier = Modifier.height(60.dp))

                Text(text = "🏠", fontSize = 52.sp)
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "Join WattWise",
                    fontSize = 30.sp,
                    fontWeight = FontWeight.Bold,
                    color = Color.White
                )
                Text(
                    text = "Become part of the energy community",
                    fontSize = 13.sp,
                    color = Color.White.copy(alpha = 0.6f)
                )

                Spacer(modifier = Modifier.height(32.dp))

                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(20.dp),
                    color = Color(0xFF1E293B),
                    tonalElevation = 4.dp
                ) {
                    Column(
                        modifier = Modifier.padding(24.dp),
                        verticalArrangement = Arrangement.spacedBy(14.dp)
                    ) {
                        Text(
                            text = "Create Account",
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )

                        // ── Full Name ──
                        OutlinedTextField(
                            value = name,
                            onValueChange = { name = it },
                            label = { Text("Full name") },
                            leadingIcon = { Icon(Icons.Default.Person, contentDescription = null) },
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Text,
                                imeAction = ImeAction.Next
                            ),
                            keyboardActions = KeyboardActions(onNext = { emailFocus.requestFocus() }),
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            colors = authTextFieldColors(),
                            shape = RoundedCornerShape(12.dp)
                        )

                        // ── Email ──
                        OutlinedTextField(
                            value = email,
                            onValueChange = { email = it.trim() },
                            label = { Text("Email address") },
                            leadingIcon = { Icon(Icons.Default.Email, contentDescription = null) },
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Email,
                                imeAction = ImeAction.Next
                            ),
                            keyboardActions = KeyboardActions(onNext = { passwordFocus.requestFocus() }),
                            singleLine = true,
                            modifier = Modifier
                                .fillMaxWidth()
                                .focusRequester(emailFocus),
                            colors = authTextFieldColors(),
                            shape = RoundedCornerShape(12.dp)
                        )

                        // ── Password ──
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            label = { Text("Password (min. 8 characters)") },
                            leadingIcon = { Icon(Icons.Default.Lock, contentDescription = null) },
                            trailingIcon = {
                                IconButton(onClick = { passwordVisible = !passwordVisible }) {
                                    Icon(
                                        if (passwordVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                        contentDescription = "Toggle visibility"
                                    )
                                }
                            },
                            visualTransformation = if (passwordVisible) VisualTransformation.None
                                                   else PasswordVisualTransformation(),
                            isError = passwordTooShort,
                            supportingText = if (passwordTooShort) {
                                { Text("Password must be at least 8 characters", color = MaterialTheme.colorScheme.error) }
                            } else null,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Password,
                                imeAction = ImeAction.Next
                            ),
                            keyboardActions = KeyboardActions(onNext = { confirmFocus.requestFocus() }),
                            singleLine = true,
                            modifier = Modifier
                                .fillMaxWidth()
                                .focusRequester(passwordFocus),
                            colors = authTextFieldColors(),
                            shape = RoundedCornerShape(12.dp)
                        )

                        // ── Confirm Password ──
                        OutlinedTextField(
                            value = confirmPassword,
                            onValueChange = { confirmPassword = it },
                            label = { Text("Confirm password") },
                            leadingIcon = { Icon(Icons.Default.LockOpen, contentDescription = null) },
                            trailingIcon = {
                                IconButton(onClick = { confirmVisible = !confirmVisible }) {
                                    Icon(
                                        if (confirmVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                        contentDescription = "Toggle visibility"
                                    )
                                }
                            },
                            visualTransformation = if (confirmVisible) VisualTransformation.None
                                                   else PasswordVisualTransformation(),
                            isError = passwordMismatch,
                            supportingText = if (passwordMismatch) {
                                { Text("Passwords do not match", color = MaterialTheme.colorScheme.error) }
                            } else null,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Password,
                                imeAction = ImeAction.Done
                            ),
                            keyboardActions = KeyboardActions(
                                onDone = {
                                    keyboardController?.hide()
                                    focusManager.clearFocus()
                                    if (canSubmit) viewModel.signup(name, email, password)
                                }
                            ),
                            singleLine = true,
                            modifier = Modifier
                                .fillMaxWidth()
                                .focusRequester(confirmFocus),
                            colors = authTextFieldColors(),
                            shape = RoundedCornerShape(12.dp)
                        )

                        // ── Error banner ──
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

                        // ── Research consent notice ──
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp),
                            color = Color(0xFF0F3460).copy(alpha = 0.6f)
                        ) {
                            Row(
                                modifier = Modifier.padding(12.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.Top
                            ) {
                                Text("ℹ️", fontSize = 14.sp)
                                Text(
                                    text = "By creating an account you agree to participate in " +
                                           "energy behaviour research at Cardiff University. " +
                                           "Your anonymised data will be used for PhD research purposes.",
                                    fontSize = 11.sp,
                                    color = Color(0xFF94A3B8),
                                    lineHeight = 16.sp
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(4.dp))

                        // ── Submit button ──
                        Button(
                            onClick = {
                                keyboardController?.hide()
                                focusManager.clearFocus()
                                viewModel.signup(name, email, password)
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp),
                            enabled = canSubmit,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color(0xFF0EA5E9)  // Blue accent
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
                                    text = "Create Account",
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.SemiBold
                                )
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                Row(
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Already have an account? ",
                        color = Color(0xFF94A3B8),
                        fontSize = 14.sp
                    )
                    TextButton(onClick = onNavigateToLogin) {
                        Text(
                            text = "Sign In",
                            color = Color(0xFF10B981),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "${Constants.DEVELOPER_NAME} · ${Constants.DEVELOPER_INSTITUTION} · ${Constants.APP_YEAR}",
                    fontSize = 10.sp,
                    color = Color.White.copy(alpha = 0.25f),
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(28.dp))
            }
        }
    }
}
