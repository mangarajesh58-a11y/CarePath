package com.carepath.patient;

import android.Manifest;
import android.app.Dialog;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Message;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.annotation.NonNull;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebChromeClient;
import java.util.ArrayList;
import java.util.List;

public class MainActivity extends BridgeActivity {

    private static final int PERMISSION_REQUEST_CODE = 2001;
    public static final String NOTIFICATION_CHANNEL_ID = "carepath_alerts_channel";

    private Dialog googleAuthDialog;
    private WebView popupWebView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        createNotificationChannel();
        configureWebView();
        requestEssentialPermissions();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            CharSequence name = "CarePath Alerts";
            String description = "Live OPD queue alerts, token calling announcements, and hospital replies";
            int importance = NotificationManager.IMPORTANCE_HIGH;
            NotificationChannel channel = new NotificationChannel(NOTIFICATION_CHANNEL_ID, name, importance);
            channel.setDescription(description);
            channel.enableVibration(true);
            channel.enableLights(true);

            NotificationManager notificationManager = getSystemService(NotificationManager.class);
            if (notificationManager != null) {
                notificationManager.createNotificationChannel(channel);
            }
        }
    }

    private void requestEssentialPermissions() {
        List<String> permissionsNeeded = new ArrayList<>();

        // 1. Camera Permission
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            permissionsNeeded.add(Manifest.permission.CAMERA);
        }

        // 2. Phone Call Permission
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            permissionsNeeded.add(Manifest.permission.CALL_PHONE);
        }

        // 3. Gallery / Photos / Media Permissions
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) { // Android 13+ (API 33+)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED) {
                permissionsNeeded.add(Manifest.permission.READ_MEDIA_IMAGES);
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_VIDEO) != PackageManager.PERMISSION_GRANTED) {
                permissionsNeeded.add(Manifest.permission.READ_MEDIA_VIDEO);
            }
        } else { // Android 12 and below
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                permissionsNeeded.add(Manifest.permission.READ_EXTERNAL_STORAGE);
            }
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.Q) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                    permissionsNeeded.add(Manifest.permission.WRITE_EXTERNAL_STORAGE);
                }
            }
        }

        // 4. Microphone for Voice Consultation
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissionsNeeded.add(Manifest.permission.RECORD_AUDIO);
        }

        // 5. Geolocation / Location Permissions for Nearby Hospitals & Doctors
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            permissionsNeeded.add(Manifest.permission.ACCESS_FINE_LOCATION);
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            permissionsNeeded.add(Manifest.permission.ACCESS_COARSE_LOCATION);
        }

        if (!permissionsNeeded.isEmpty()) {
            ActivityCompat.requestPermissions(
                this,
                permissionsNeeded.toArray(new String[0]),
                PERMISSION_REQUEST_CODE
            );
        }
    }

    private void configureWebView() {
        WebView webView = getBridge().getWebView();
        if (webView != null) {
            WebSettings settings = webView.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setMediaPlaybackRequiresUserGesture(false);
            settings.setAllowFileAccess(true);
            settings.setDomStorageEnabled(true);
            settings.setDatabaseEnabled(true);
            settings.setGeolocationEnabled(true);
            settings.setSupportMultipleWindows(true);
            settings.setJavaScriptCanOpenWindowsAutomatically(true);

            // Strip embedded webview signature ("; wv" and "Version/4.0") so Google OAuth does not block authentication
            String defaultUa = settings.getUserAgentString();
            if (defaultUa != null) {
                String cleanUa = defaultUa.replace("; wv", "").replaceAll("Version/[0-9.]+\\s*", "");
                settings.setUserAgentString(cleanUa);
            }

            // Enable third-party cookies so Google OAuth session state is preserved
            CookieManager cookieManager = CookieManager.getInstance();
            cookieManager.setAcceptCookie(true);
            cookieManager.setAcceptThirdPartyCookies(webView, true);

            // CustomChromeClient extends BridgeWebChromeClient so camera/file chooser still works,
            // while enabling popup windows (onCreateWindow) for seamless Google Sign-In on mobile devices.
            webView.setWebChromeClient(new CustomChromeClient(getBridge()));
        }
    }

    private class CustomChromeClient extends BridgeWebChromeClient {
        public CustomChromeClient(Bridge bridge) {
            super(bridge);
        }

        @Override
        public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
            if (googleAuthDialog != null && googleAuthDialog.isShowing()) {
                googleAuthDialog.dismiss();
            }
            if (popupWebView != null) {
                popupWebView.destroy();
                popupWebView = null;
            }

            popupWebView = new WebView(MainActivity.this);
            WebSettings popupSettings = popupWebView.getSettings();
            popupSettings.setJavaScriptEnabled(true);
            popupSettings.setDomStorageEnabled(true);
            popupSettings.setDatabaseEnabled(true);
            popupSettings.setSupportMultipleWindows(true);
            popupSettings.setJavaScriptCanOpenWindowsAutomatically(true);

            // Clean User-Agent on popup as well
            String defaultUa = popupSettings.getUserAgentString();
            if (defaultUa != null) {
                String cleanUa = defaultUa.replace("; wv", "").replaceAll("Version/[0-9.]+\\s*", "");
                popupSettings.setUserAgentString(cleanUa);
            }

            CookieManager.getInstance().setAcceptCookie(true);
            CookieManager.getInstance().setAcceptThirdPartyCookies(popupWebView, true);

            googleAuthDialog = new Dialog(MainActivity.this, android.R.style.Theme_DeviceDefault_Light_NoActionBar_Fullscreen);
            googleAuthDialog.setContentView(popupWebView, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            ));
            googleAuthDialog.setCancelable(true);
            googleAuthDialog.setOnCancelListener(d -> {
                if (popupWebView != null) {
                    popupWebView.destroy();
                    popupWebView = null;
                }
            });

            popupWebView.setWebChromeClient(new WebChromeClient() {
                @Override
                public void onCloseWindow(WebView window) {
                    if (googleAuthDialog != null && googleAuthDialog.isShowing()) {
                        googleAuthDialog.dismiss();
                    }
                    if (popupWebView != null) {
                        popupWebView.destroy();
                        popupWebView = null;
                    }
                }
            });

            popupWebView.setWebViewClient(new WebViewClient() {
                @Override
                public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    return false;
                }

                @Override
                public void onPageFinished(WebView view, String url) {
                    super.onPageFinished(view, url);
                    if (url != null && (url.contains("blank") || url.contains("close") || url.contains("oauth2/close"))) {
                        if (googleAuthDialog != null && googleAuthDialog.isShowing()) {
                            googleAuthDialog.dismiss();
                        }
                    }
                }
            });

            googleAuthDialog.show();

            WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
            transport.setWebView(popupWebView);
            resultMsg.sendToTarget();
            return true;
        }

        @Override
        public void onCloseWindow(WebView window) {
            if (googleAuthDialog != null && googleAuthDialog.isShowing()) {
                googleAuthDialog.dismiss();
            }
            if (popupWebView != null) {
                popupWebView.destroy();
                popupWebView = null;
            }
            super.onCloseWindow(window);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
    }

    @Override
    public void onBackPressed() {
        if (googleAuthDialog != null && googleAuthDialog.isShowing()) {
            googleAuthDialog.dismiss();
            if (popupWebView != null) {
                popupWebView.destroy();
                popupWebView = null;
            }
            return;
        }
        WebView webView = getBridge().getWebView();
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
