# ── Standard Android ──
-keepattributes *Annotation*
-keepattributes Signature
-keepattributes InnerClasses
-keepattributes EnclosingMethod
-keepattributes RuntimeVisibleAnnotations
-keepattributes RuntimeVisibleParameterAnnotations

# ── App classes (keep everything — Hilt generates code referencing these) ──
-keep class com.wattwise.userapp.** { *; }
-keepclassmembers class com.wattwise.userapp.** { *; }

# ── Hilt / Dagger ──
-keep class dagger.hilt.** { *; }
-keep class dagger.** { *; }
-keep class javax.inject.** { *; }
-keep class * extends dagger.hilt.android.internal.managers.ViewComponentManager$FragmentContextWrapper { *; }

# Keep Hilt-generated classes (pattern: Hilt_*, *_HiltModules*, *_Factory, *_MembersInjector)
-keep class **_HiltModules* { *; }
-keep class **Hilt_* { *; }
-keep class **_Factory { *; }
-keep class **_MembersInjector { *; }
-keep class **_ComponentTreeDeps { *; }
-keep class **_HiltComponents* { *; }

# Keep @HiltViewModel annotated classes and their @Inject constructors
-keep @dagger.hilt.android.lifecycle.HiltViewModel class * { *; }
-keep class * extends androidx.lifecycle.ViewModel { *; }

# Keep @AndroidEntryPoint, @HiltAndroidApp annotated classes
-keep @dagger.hilt.android.AndroidEntryPoint class * { *; }
-keep @dagger.hilt.android.HiltAndroidApp class * { *; }

# Keep @Module/@InstallIn annotated classes
-keep @dagger.Module class * { *; }
-keep @dagger.hilt.InstallIn class * { *; }

# Keep @Singleton/@Inject annotated members
-keepclassmembers class * {
    @javax.inject.Inject <init>(...);
    @javax.inject.Inject <fields>;
}
-keepclassmembers class * {
    @dagger.Provides <methods>;
}

# ── Retrofit ──
-dontwarn retrofit2.**
-keep class retrofit2.** { *; }
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}

# ── Gson ──
-keep class com.google.gson.** { *; }
-keepclassmembernames class * {
    @com.google.gson.annotations.SerializedName <fields>;
}
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# ── OkHttp ──
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }
-keep class okio.** { *; }

# ── Compose ──
-keep class androidx.compose.** { *; }
-dontwarn androidx.compose.**

# ── Navigation Compose ──
-keep class androidx.navigation.** { *; }
-dontwarn androidx.navigation.**

# ── Hilt Navigation Compose ──
-keep class androidx.hilt.navigation.** { *; }
-dontwarn androidx.hilt.navigation.**

# ── DataStore ──
-keep class androidx.datastore.** { *; }
-keepclassmembers class * {
    *** dataStore(...);
}

# ── Lifecycle / ViewModel ──
-keep class androidx.lifecycle.** { *; }
-dontwarn androidx.lifecycle.**

# ── WebView ──
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# ── Kotlin ──
-dontwarn kotlin.**
-keep class kotlin.** { *; }
-keep class kotlinx.coroutines.** { *; }
-dontwarn kotlinx.coroutines.**

# ── Enum classes ──
-keepclassmembers enum * {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# ── Sealed classes (keep subclasses) ──
-keep class * extends com.wattwise.userapp.domain.model.Resource { *; }
-keep class * extends com.wattwise.userapp.domain.model.ConnectivityStatus { *; }

# ── Timber ──
-dontwarn timber.log.**
-keep class timber.log.** { *; }

# ── Material ──
-keep class com.google.android.material.** { *; }
-dontwarn com.google.android.material.**
