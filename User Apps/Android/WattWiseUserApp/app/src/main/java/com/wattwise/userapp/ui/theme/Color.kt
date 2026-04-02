package com.wattwise.userapp.ui.theme

import androidx.compose.ui.graphics.Color

// ── WattWise Brand Palette — Energy Green ──
val WattGreen       = Color(0xFF16A34A)   // Primary — energy green
val WattGreenDark   = Color(0xFF15803D)   // Dark green
val WattGreenLight  = Color(0xFFDCFCE7)   // Light green surface
val WattBlue        = Color(0xFF0EA5E9)   // Accent — data blue
val WattBlueLight   = Color(0xFFE0F2FE)

// ── Semantic Colors ──
val WattSuccess      = Color(0xFF16A34A)
val WattSuccessLight = Color(0xFFDCFCE7)
val WattWarning      = Color(0xFFF59E0B)  // Amber — warnings
val WattWarningLight = Color(0xFFFEF3C7)
val WattDanger       = Color(0xFFEF4444)  // Red — critical
val WattDangerLight  = Color(0xFFFEE2E2)
val WattPeak         = Color(0xFFF97316)  // Orange — peak tariff

// ── Material 3 Light Scheme ──
val md_theme_light_primary = WattGreen
val md_theme_light_onPrimary = Color.White
val md_theme_light_primaryContainer = WattGreenLight
val md_theme_light_onPrimaryContainer = Color(0xFF002010)
val md_theme_light_secondary = WattBlue
val md_theme_light_onSecondary = Color.White
val md_theme_light_secondaryContainer = WattBlueLight
val md_theme_light_onSecondaryContainer = Color(0xFF001829)
val md_theme_light_background = Color(0xFFF0F4F0)
val md_theme_light_onBackground = Color(0xFF111827)
val md_theme_light_surface = Color.White
val md_theme_light_onSurface = Color(0xFF111827)
val md_theme_light_surfaceVariant = Color(0xFFDCE9DC)
val md_theme_light_onSurfaceVariant = Color(0xFF374151)
val md_theme_light_outline = Color(0xFF6B7280)
val md_theme_light_error = WattDanger
val md_theme_light_onError = Color.White
val md_theme_light_errorContainer = WattDangerLight

// ── Material 3 Dark Scheme (default — WattWise uses dark UI) ──
val md_theme_dark_primary = WattGreen
val md_theme_dark_onPrimary = Color.White
val md_theme_dark_primaryContainer = WattGreenDark
val md_theme_dark_onPrimaryContainer = WattGreenLight
val md_theme_dark_secondary = WattBlue
val md_theme_dark_onSecondary = Color.White
val md_theme_dark_secondaryContainer = Color(0xFF0369A1)
val md_theme_dark_onSecondaryContainer = WattBlueLight
val md_theme_dark_background = Color(0xFF0F172A)  // Slate dark
val md_theme_dark_onBackground = Color(0xFFF8FAFC)
val md_theme_dark_surface = Color(0xFF1E293B)     // Slate surface
val md_theme_dark_onSurface = Color(0xFFF8FAFC)
val md_theme_dark_surfaceVariant = Color(0xFF334155)
val md_theme_dark_onSurfaceVariant = Color(0xFF94A3B8)
val md_theme_dark_outline = Color(0xFF64748B)
val md_theme_dark_error = Color(0xFFFCA5A5)
val md_theme_dark_onError = Color(0xFF7F1D1D)
val md_theme_dark_errorContainer = Color(0xFF991B1B)

