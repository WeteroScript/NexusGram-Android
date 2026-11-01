package org.telegram.messenger;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/**
 * Own-account authentication for the WaysGram backend.
 *
 * This repository deliberately does not call Telegram auth.sendCode/auth.signIn
 * and does not convert a WaysGram account into a synthetic TLRPC.User.
 */
public final class WaysGramAuthRepository {
    public interface Callback {
        void onSuccess(JSONObject result);
        void onError(WaysGramApiClient.ApiError error);
    }

    private static final Pattern PHONE_PATTERN = Pattern.compile("\\+[1-9][0-9]{7,14}");
    private static final Pattern CODE_PATTERN = Pattern.compile("[0-9]{6}");
    private static final ExecutorService STORAGE = Executors.newSingleThreadExecutor();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private final WaysGramApiClient api;
    private final WaysGramSessionStore sessions;

    public WaysGramAuthRepository(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("Context is required");
        }
        api = new WaysGramApiClient(context);
        sessions = new WaysGramSessionStore(context);
    }

    public void requestCode(String rawPhone, Callback callback) {
        final String phone;
        try {
            phone = normalizePhone(rawPhone);
        } catch (IllegalArgumentException e) {
            fail(callback, 400, e.getMessage());
            return;
        }
        api.requestCode(phone, new WaysGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                callbackSuccess(callback, result);
            }

            @Override
            public void onError(WaysGramApiClient.ApiError error) {
                callbackError(callback, error);
            }
        });
    }

    public void verifyCode(String rawPhone, String rawCode, Callback callback) {
        final String phone;
        final String code;
        try {
            phone = normalizePhone(rawPhone);
            code = rawCode == null ? "" : rawCode.trim();
            if (!CODE_PATTERN.matcher(code).matches()) {
                throw new IllegalArgumentException("Введите шестизначный код WaysGram");
            }
        } catch (IllegalArgumentException e) {
            fail(callback, 400, e.getMessage());
            return;
        }

        api.verifyCode(phone, code, new WaysGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject response) {
                final String token = response.optString("token", "");
                final JSONObject user = response.optJSONObject("user");
                if (token.trim().isEmpty() || user == null || user.optLong("id", 0) <= 0) {
                    fail(callback, 502, "Ответ сервера авторизации неполный");
                    return;
                }
                STORAGE.execute(() -> {
                    try {
                        sessions.saveAccessToken(token);
                        api.getMe(token, new WaysGramApiClient.Callback() {
                            @Override
                            public void onSuccess(JSONObject profile) {
                                JSONObject result = new JSONObject();
                                try {
                                    result.put("status", "authenticated");
                                    result.put("user", profile);
                                } catch (JSONException e) {
                                    fail(callback, 502, "Не удалось обработать профиль WaysGram");
                                    return;
                                }
                                callbackSuccess(callback, result);
                            }

                            @Override
                            public void onError(WaysGramApiClient.ApiError error) {
                                clearStoredSession();
                                callbackError(callback, error);
                            }
                        });
                    } catch (GeneralSecurityException | IOException e) {
                        callbackError(callback, new WaysGramApiClient.ApiError(
                                0, "Не удалось безопасно сохранить сессию WaysGram"));
                    }
                });
            }

            @Override
            public void onError(WaysGramApiClient.ApiError error) {
                callbackError(callback, error);
            }
        });
    }

    public void restoreSession(Callback callback) {
        STORAGE.execute(() -> {
            final String token;
            try {
                token = sessions.getAccessToken();
            } catch (GeneralSecurityException | IOException e) {
                callbackError(callback, new WaysGramApiClient.ApiError(
                        0, "Не удалось прочитать защищённую сессию WaysGram"));
                return;
            }
            if (token == null || token.isEmpty()) {
                callbackError(callback, new WaysGramApiClient.ApiError(
                        401, "Сохранённая сессия WaysGram отсутствует"));
                return;
            }
            api.getMe(token, new WaysGramApiClient.Callback() {
                @Override
                public void onSuccess(JSONObject profile) {
                    JSONObject result = new JSONObject();
                    try {
                        result.put("status", "authenticated");
                        result.put("user", profile);
                    } catch (JSONException e) {
                        callbackError(callback, new WaysGramApiClient.ApiError(
                                502, "Не удалось обработать профиль WaysGram"));
                        return;
                    }
                    callbackSuccess(callback, result);
                }

                @Override
                public void onError(WaysGramApiClient.ApiError error) {
                    if (error.statusCode == 401 || error.statusCode == 403) {
                        clearStoredSession();
                    }
                    callbackError(callback, error);
                }
            });
        });
    }

    public void logout(Callback callback) {
        STORAGE.execute(() -> {
            final String token;
            try {
                token = sessions.getAccessToken();
            } catch (GeneralSecurityException | IOException e) {
                callbackError(callback, new WaysGramApiClient.ApiError(
                        0, "Не удалось прочитать сессию WaysGram"));
                return;
            }

            if (token == null || token.isEmpty()) {
                clearAndComplete(callback);
                return;
            }

            api.logout(token, new WaysGramApiClient.Callback() {
                @Override
                public void onSuccess(JSONObject ignored) {
                    clearAndComplete(callback);
                }

                @Override
                public void onError(WaysGramApiClient.ApiError error) {
                    // Always remove the local bearer token, even if the VDS is offline.
                    clearStoredSession();
                    callbackError(callback, error);
                }
            });
        });
    }

    private static String normalizePhone(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException("Введите номер телефона");
        }
        String value = raw.trim().replaceAll("[\\s()\\-]", "");
        if (!PHONE_PATTERN.matcher(value).matches()) {
            throw new IllegalArgumentException(
                    "Номер должен быть в международном формате, например +35312345678");
        }
        return value;
    }

    private void clearStoredSession() {
        STORAGE.execute(() -> {
            try {
                sessions.clear();
            } catch (GeneralSecurityException | IOException ignored) {
                // The caller already receives the originating auth/network error.
            }
        });
    }

    private void clearAndComplete(Callback callback) {
        try {
            sessions.clear();
            JSONObject result = new JSONObject();
            result.put("status", "logged_out");
            callbackSuccess(callback, result);
        } catch (GeneralSecurityException | IOException | JSONException e) {
            callbackError(callback, new WaysGramApiClient.ApiError(
                    0, "Не удалось очистить локальную сессию WaysGram"));
        }
    }

    private static void fail(Callback callback, int status, String message) {
        callbackError(callback, new WaysGramApiClient.ApiError(status, message));
    }

    private static void callbackSuccess(Callback callback, JSONObject result) {
        if (callback != null) {
            MAIN.post(() -> callback.onSuccess(result));
        }
    }

    private static void callbackError(Callback callback, WaysGramApiClient.ApiError error) {
        if (callback != null) {
            MAIN.post(() -> callback.onError(error));
        }
    }
}
