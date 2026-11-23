# Project-specific ProGuard rules for Q-Arovia (Capacitor Android)

# Capacitor & WebView Keep Rules
-keepattributes *Annotation*
-keepattributes JavascriptInterface
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.getcapacitor.** { *; }
-keep interface com.getcapacitor.** { *; }
-keep class * extends com.getcapacitor.Plugin { *; }
-keep class com.getcapacitor.PluginMethod { *; }

# Cordova Compatibility Plugins
-keep class org.apache.cordova.** { *; }
-keep interface org.apache.cordova.** { *; }
-keep class * extends org.apache.cordova.CordovaPlugin { *; }

# Native WebKit
-keepclassmembers class * extends android.webkit.WebViewClient {
    public void *(android.webkit.WebView, java.lang.String);
    public void *(android.webkit.WebView, java.lang.String, android.graphics.Bitmap);
}
-keepclassmembers class * extends android.webkit.WebChromeClient {
    public void *(android.webkit.WebView, ...);
}

# Preserve Line Numbers for Crash Reporting
-keepattributes SourceFile,LineNumberTable
