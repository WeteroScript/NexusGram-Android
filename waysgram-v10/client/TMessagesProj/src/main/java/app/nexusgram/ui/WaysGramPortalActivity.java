package app.nexusgram.ui;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import app.nexusgram.network.NexusGramApiClient;

/** Standalone WaysGram authentication flow; it does not create a Telegram MTProto session. */
public final class WaysGramPortalActivity extends Activity {
    public static final String EXTRA_SERVER_URL = "waysgram_server_url";
    private static final String PREFS = "waysgram_portal";
    private static final String SERVER_URL_KEY = "server_url";

    private EditText serverUrlField;
    private EditText phoneField;
    private EditText codeField;
    private TextView statusView;
    private NexusGramApiClient api;
    private String serverUrl;
    private boolean openingHome;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        serverUrl = getIntent().getStringExtra(EXTRA_SERVER_URL);
        if (serverUrl == null || serverUrl.trim().isEmpty()) {
            serverUrl = getSharedPreferences(PREFS, MODE_PRIVATE).getString(SERVER_URL_KEY, "");
        }
        buildUi();
        if (!serverUrl.isEmpty()) {
            serverUrlField.setText(serverUrl);
            connectServer(false);
        }
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(22), dp(28), dp(22), dp(28));
        page.setGravity(Gravity.CENTER_HORIZONTAL);
        page.setBackgroundColor(Color.rgb(245, 247, 251));
        scroll.addView(page, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = text("WaysGram", 30, Color.rgb(25, 42, 70), true);
        title.setGravity(Gravity.CENTER);
        page.addView(title, matchWrap());

        TextView subtitle = text("Вход в аккаунт WaysGram", 16, Color.rgb(92, 105, 124), false);
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subtitleParams = matchWrap();
        subtitleParams.topMargin = dp(7);
        page.addView(subtitle, subtitleParams);

        LinearLayout card = card();
        LinearLayout.LayoutParams cardParams = matchWrap();
        cardParams.topMargin = dp(28);
        page.addView(card, cardParams);

        card.addView(label("Адрес сервера WaysGram"), matchWrap());
        serverUrlField = edit("https://waysgram.example", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        card.addView(serverUrlField, fieldParams());
        Button connectButton = button("Подключить сервер");
        card.addView(connectButton, buttonParams());
        connectButton.setOnClickListener(v -> connectServer(true));

        View separator = new View(this);
        separator.setBackgroundColor(Color.rgb(229, 233, 240));
        LinearLayout.LayoutParams separatorParams = matchWrap();
        separatorParams.height = dp(1);
        separatorParams.topMargin = dp(18);
        separatorParams.bottomMargin = dp(18);
        card.addView(separator, separatorParams);

        card.addView(label("Виртуальный номер"), matchWrap());
        phoneField = edit("+1XXXXXXXXXX", InputType.TYPE_CLASS_PHONE);
        phoneField.setMaxLines(1);
        card.addView(phoneField, fieldParams());

        TextView numberHint = text(
                "Номер выдаётся ботом AuthWaysGram_bot. Это внутренний идентификатор WaysGram, а не телефонная линия для SMS.",
                13, Color.rgb(104, 115, 132), false);
        numberHint.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams hintParams = matchWrap();
        hintParams.topMargin = dp(5);
        card.addView(numberHint, hintParams);

        Button requestButton = button("Получить код WaysGram");
        LinearLayout.LayoutParams requestParams = buttonParams();
        requestParams.topMargin = dp(14);
        card.addView(requestButton, requestParams);
        requestButton.setOnClickListener(v -> requestCode());

        card.addView(label("Шестизначный код"), fieldParams());
        codeField = edit("6 цифр", InputType.TYPE_CLASS_NUMBER);
        codeField.setLetterSpacing(0.12f);
        codeField.setMaxLines(1);
        codeField.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(6)});
        card.addView(codeField, fieldParams());

        Button signInButton = button("Войти");
        LinearLayout.LayoutParams signInParams = buttonParams();
        signInParams.topMargin = dp(12);
        card.addView(signInButton, signInParams);
        signInButton.setOnClickListener(v -> verifyCode());

        statusView = text("Сначала укажите адрес сервера и подключитесь к нему.", 13,
                Color.rgb(90, 104, 123), false);
        statusView.setGravity(Gravity.CENTER);
        statusView.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams statusParams = matchWrap();
        statusParams.topMargin = dp(16);
        card.addView(statusView, statusParams);

        TextView note = text(
                "Сессия WaysGram отдельна от входа Telegram. Внутренние Gram и коллекционные подарки не являются блокчейн-активами.",
                12, Color.rgb(115, 125, 140), false);
        note.setGravity(Gravity.CENTER);
        note.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams noteParams = matchWrap();
        noteParams.topMargin = dp(20);
        page.addView(note, noteParams);

        setContentView(scroll);
    }

    private void connectServer(boolean showMessage) {
        String input = serverUrlField == null ? serverUrl : serverUrlField.getText().toString().trim();
        if (input.isEmpty()) {
            setStatus("Введите HTTPS-адрес backend WaysGram.");
            return;
        }
        final NexusGramApiClient candidate;
        try {
            candidate = new NexusGramApiClient(getApplicationContext(), input);
        } catch (IllegalArgumentException error) {
            setStatus(error.getMessage());
            return;
        }
        if (api != null) {
            api.close();
        }
        api = candidate;
        serverUrl = input.replaceAll("/+$", "");
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(SERVER_URL_KEY, serverUrl).apply();
        setStatus("Проверяем соединение с WaysGram…");
        api.checkHealth(new NexusGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                if (isFinishing()) return;
                String state = result.optString("status", "");
                if (!"online".equalsIgnoreCase(state)) {
                    setStatus("Сервер ответил, но статус WaysGram не подтверждён.");
                    return;
                }
                api.getApiConfig(new NexusGramApiClient.Callback() {
                    @Override
                    public void onSuccess(JSONObject config) {
                        if (isFinishing()) return;
                        boolean botReady = config.optBoolean("authbot_delivery_ready", false);
                        if (!botReady) {
                            setStatus("Backend доступен, но AuthWaysGram_bot не подключён. Администратору нужно настроить AuthBot URL и внутренний API-секрет.");
                        } else {
                            setStatus("Сервер и AuthWaysGram_bot подключены. Введите номер, полученный в боте.");
                        }
                        if (api.isSignedIn()) {
                            validateExistingSession();
                        } else if (showMessage) {
                            toast(botReady ? "WaysGram готов к авторизации" : "Сервер подключён, AuthBot ещё не настроен");
                        }
                    }

                    @Override
                    public void onError(String message) {
                        if (!isFinishing()) setStatus("Сервер подключён, но конфигурацию API прочитать не удалось: " + message);
                    }
                });
            }

            @Override
            public void onError(String message) {
                if (!isFinishing()) setStatus(message);
            }
        });
    }

    private void validateExistingSession() {
        if (api == null || !api.isSignedIn()) return;
        setStatus("Проверяем сохранённую сессию…");
        api.getMe(new NexusGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                openHome();
            }

            @Override
            public void onError(String message) {
                if (!isFinishing()) {
                    if (message != null && message.startsWith("SESSION_EXPIRED:")) {
                        setStatus("Сохранённая сессия истекла. Введите номер и новый код WaysGram.");
                    } else {
                        setStatus("Сессия недоступна. Войдите снова: " + message);
                    }
                }
            }
        });
    }

    private void requestCode() {
        if (api == null) {
            setStatus("Сначала подключите сервер WaysGram.");
            return;
        }
        String phone = phoneField.getText().toString().trim().replace(" ", "");
        setStatus("Запрашиваем код…");
        api.requestCode(phone, new NexusGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                String message = result.optString("message",
                        "Откройте AuthWaysGram_bot и нажмите «Получить код».");
                setStatus(message);
                toast("Запрос кода принят");
            }

            @Override
            public void onError(String message) {
                setStatus(message);
            }
        });
    }

    private void verifyCode() {
        if (api == null) {
            setStatus("Сначала подключите сервер WaysGram.");
            return;
        }
        String phone = phoneField.getText().toString().trim().replace(" ", "");
        String code = codeField.getText().toString().trim();
        setStatus("Проверяем код…");
        api.verifyCode(phone, code, new NexusGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                toast("Вход выполнен");
                openHome();
            }

            @Override
            public void onError(String message) {
                setStatus(message);
            }
        });
    }

    private void openHome() {
        if (openingHome || isFinishing()) return;
        openingHome = true;
        Intent intent = new Intent(this, WaysGramHomeActivity.class);
        intent.putExtra(EXTRA_SERVER_URL, serverUrl);
        startActivity(intent);
        finish();
    }

    private void setStatus(String value) {
        if (statusView != null) statusView.setText(value == null ? "Неизвестная ошибка" : value);
    }

    private void toast(String value) {
        Toast.makeText(this, value, Toast.LENGTH_LONG).show();
    }

    private LinearLayout card() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(18), dp(18), dp(18), dp(18));
        android.graphics.drawable.GradientDrawable bg = new android.graphics.drawable.GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(18));
        bg.setStroke(dp(1), Color.rgb(230, 234, 241));
        layout.setBackground(bg);
        return layout;
    }

    private TextView label(String value) {
        TextView view = text(value, 14, Color.rgb(48, 61, 80), true);
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(4);
        return view;
    }

    private EditText edit(String hint, int inputType) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true);
        edit.setTextSize(16);
        edit.setTextColor(Color.rgb(30, 42, 60));
        edit.setHintTextColor(Color.rgb(145, 154, 168));
        edit.setHint(hint);
        edit.setInputType(inputType);
        edit.setPadding(dp(13), dp(9), dp(13), dp(9));
        android.graphics.drawable.GradientDrawable bg = new android.graphics.drawable.GradientDrawable();
        bg.setColor(Color.rgb(248, 250, 253));
        bg.setCornerRadius(dp(10));
        bg.setStroke(dp(1), Color.rgb(220, 226, 235));
        edit.setBackground(bg);
        return edit;
    }

    private Button button(String value) {
        Button button = new Button(this);
        button.setText(value);
        button.setAllCaps(false);
        button.setTextSize(15);
        button.setTextColor(Color.WHITE);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(38, 113, 190)));
        return button;
    }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams fieldParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(7);
        return params;
    }

    private LinearLayout.LayoutParams buttonParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(9);
        params.height = dp(48);
        return params;
    }

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    @Override
    protected void onDestroy() {
        if (api != null) {
            api.close();
            api = null;
        }
        super.onDestroy();
    }
}