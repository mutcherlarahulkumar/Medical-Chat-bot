package com.skintracker.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Pink, as asked for — warm blush surfaces with a deeper rose for anything
// interactive, so buttons and ticks stay legible against the background.
val Blush       = Color(0xFFFFF5F8)
val BlushDeep   = Color(0xFFFFEAF1)
val PinkSoft    = Color(0xFFFFE3EC)
val PinkLine    = Color(0xFFFFD3E0)
val Pink        = Color(0xFFE05C86)
val PinkDark    = Color(0xFFC74773)
val Ink         = Color(0xFF4A2C38)
val Muted       = Color(0xFFA3808F)

private val LightColors = lightColorScheme(
    primary = Pink,
    onPrimary = Color.White,
    primaryContainer = PinkSoft,
    onPrimaryContainer = PinkDark,
    secondary = PinkDark,
    onSecondary = Color.White,
    secondaryContainer = PinkSoft,
    onSecondaryContainer = PinkDark,
    background = Blush,
    onBackground = Ink,
    surface = Color.White,
    onSurface = Ink,
    surfaceVariant = BlushDeep,
    onSurfaceVariant = Muted,
    outline = PinkLine,
    error = Color(0xFFC0506D),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFFF9EC0),
    onPrimary = Color(0xFF4A0E27),
    primaryContainer = Color(0xFF6D2743),
    onPrimaryContainer = PinkSoft,
    secondary = Color(0xFFFFC2D6),
    onSecondary = Color(0xFF4A0E27),
    background = Color(0xFF1A1114),
    onBackground = Color(0xFFF3E1E7),
    surface = Color(0xFF241A1E),
    onSurface = Color(0xFFF3E1E7),
    surfaceVariant = Color(0xFF3A2A31),
    onSurfaceVariant = Color(0xFFD7B8C4),
    outline = Color(0xFF5C424C),
)

@Composable
fun SkinTrackerTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = Typography(),
        content = content,
    )
}
