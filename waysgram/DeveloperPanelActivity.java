package org.telegram.ui;

import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.webkit.SslErrorHandler;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.R;
import org.telegram.ui.ActionBar.ActionBar;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;
import org.telegram.ui.ActionBar.Theme;
import org.telegram.ui.Components.EditTextBoldCursor;
import org.telegram.ui.Components.LayoutHelper;

/** WaysGram admin panel hosted by the user's HTTPS VDS. */
public class DeveloperPanelActivity extends BaseFragment {
    private static final String PREFS = "waysgram_admin_panel";
    private static final String PREF_API_URL = "api_url";

    private WebView webView;
    private TextView statusView;
    private String apiBaseUrl;

    public DeveloperPanelActivity() {
        super();
    }

    @Override
    public View createView(Context context) {
        apiBaseUrl = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(PREF_API_URL, "");

        actionBar.setBackButtonImage(R.drawable.ic_ab_back);
        actionBar.setAllowOverlayTitle(true);
        actionBar.setTitle("Админ-панель WaysGram");
        actionBar.setActionBarMenuOnItemClick(new ActionBar.ActionBarMenuOnItemClick() {
            @Override
            public void onItemClick(int id) {
                if (id == -1) {
                    finishFragment();
                }
            }
        });

        LinearLayout root = new LinearLayout(context);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Theme.getColor(Theme.key_windowBackgroundGray));

        LinearLayout header = new LinearLayout(context);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(AndroidUtilities.dp(16), AndroidUtilities.dp(10), AndroidUtilities.dp(16), AndroidUtilities.dp(10));
        header.setBackgroundColor(Theme.getColor(Theme.key_windowBackgroundWhite));
        root.addView(header, LayoutHelper.createLinear(-1, -2));

        statusView = new TextView(context);
        statusView.setTextSize(13);
        statusView.setTextColor(Theme.getColor(Theme.key_windowBackgroundWhiteGrayText));
        statusView.setText("Панель подключается к API твоего VDS по HTTPS.");
        header.addView(statusView, LayoutHelper.createLinear(-1, -2));

        TextView changeServer = new TextView(context);
        changeServer.setText("Изменить адрес сервера");
        changeServer.setTextSize(14);
        changeServer.setGravity(Gravity.CENTER_VERTICAL);
        changeServer.setTextColor(Theme.getColor(Theme.key_windowBackgroundWhiteBlueText));
        changeServer.setPadding(0, AndroidUtilities.dp(10), 0, AndroidUtilities.dp(4));
        changeServer.setOnClickListener(v -> showServerDialog());
        header.addView(changeServer, LayoutHelper.createLinear(-1, -2));

        webView = new WebView(context);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= 26) {
            settings.setSafeBrowsingEnabled(true);
        }
        webView.setBackgroundColor(Theme.getColor(Theme.key_windowBackgroundGray));
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !isAllowedUrl(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return !isAllowedUrl(Uri.parse(url));
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, android.net.http.SslError error) {
                handler.cancel();
                setStatus("Ошибка сертификата HTTPS. Проверь TLS-сертификат на VDS.");
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                setStatus("Подключено: " + apiBaseUrl);
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (isAllowedUrl(Uri.parse(failingUrl))) {
                    setStatus("Не удалось открыть панель. Проверь адрес VDS и доступность /admin.");
                }
            }
        });
        root.addView(webView, new LinearLayout.LayoutParams(-1, 0, 1f));

        fragmentView = root;
        if (apiBaseUrl.isEmpty()) {
            root.post(this::showServerDialog);
        } else {
            loadAdminPage();
        }
        return fragmentView;
    }

    private boolean isAllowedUrl(Uri uri) {
        if (uri == null || apiBaseUrl == null || apiBaseUrl.isEmpty()) {
            return false;
        }
        Uri base = Uri.parse(apiBaseUrl);
        return "https".equalsIgnoreCase(uri.getScheme())
                && base.getHost() != null
                && base.getHost().equalsIgnoreCase(uri.getHost())
                && (uri.getPort() == -1 || uri.getPort() == base.getPort());
    }

    private void showServerDialog() {
        if (getParentActivity() == null) {
            return;
        }
        EditTextBoldCursor field = new EditTextBoldCursor(getParentActivity());
        field.setTextSize(16);
        field.setTextColor(Theme.getColor(Theme.key_windowBackgroundWhiteBlackText));
        field.setHintTextColor(Theme.getColor(Theme.key_windowBackgroundWhiteHintText));
        field.setSingleLine(true);
        field.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        field.setHint("https://chat.example.com");
        field.setText(apiBaseUrl);
        field.setPadding(AndroidUtilities.dp(12), 0, AndroidUtilities.dp(12), 0);
        field.setBackgroundColor(Theme.getColor(Theme.key_windowBackgroundWhite));

        AlertDialog dialog = new AlertDialog.Builder(getParentActivity())
                .setTitle("Адрес сервера WaysGram")
                .setMessage("Укажи HTTPS-адрес своего VDS. Адрес сохраняется только на этом устройстве.")
                .setView(field)
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Подключить", (d, which) -> {
                    String value = field.getText().toString().trim();
                    while (value.endsWith("/")) {
                        value = value.substring(0, value.length() - 1);
                    }
                    Uri uri = Uri.parse(value);
                    if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                            || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
                        setStatus("Нужен корректный HTTPS-адрес без логина, пароля, query и fragment.");
                        return;
                    }
                    apiBaseUrl = value;
                    getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                            .edit().putString(PREF_API_URL, apiBaseUrl).apply();
                    loadAdminPage();
                })
                .create();
        dialog.show();
    }

    private void loadAdminPage() {
        if (webView == null || apiBaseUrl == null || apiBaseUrl.isEmpty()) {
            return;
        }
        setStatus("Подключение к VDS…");
        webView.loadUrl(apiBaseUrl + "/admin");
    }

    private void setStatus(String value) {
        if (statusView != null) {
            statusView.setText(value);
        }
    }

    @Override
    public void onFragmentDestroy() {
        if (webView != null) {
            webView.stopLoading();
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onFragmentDestroy();
    }
}
