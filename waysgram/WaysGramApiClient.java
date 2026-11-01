package org.telegram.messenger;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URLEncoder;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * REST transport for the private WaysGram backend.
 *
 * This is deliberately separate from ConnectionsManager: Telegram MTProto
 * remains untouched until each UI flow has an equivalent WaysGram repository
 * and is migrated and tested independently.
 */
public final class WaysGramApiClient {
    public interface Callback {
        void onSuccess(JSONObject result);
        void onError(ApiError error);
    }

    public static final class ApiError extends Exception {
        public final int statusCode;

        ApiError(int statusCode, String message) {
            super(message);
            this.statusCode = statusCode;
        }
    }

    private static final int CONNECT_TIMEOUT_MS = 10000;
    private static final int READ_TIMEOUT_MS = 15000;
    private static final int MAX_RESPONSE_CHARS = 256 * 1024;
    private static final ExecutorService IO = Executors.newFixedThreadPool(3);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private final String baseUrl;

    /**
     * Accepts HTTPS URLs only. Plain HTTP is permitted for loopback development
     * endpoints; remote cleartext hosts are rejected before any request is sent.
     */
    public WaysGramApiClient(String serverUrl) {
        baseUrl = normalizeBaseUrl(serverUrl);
    }

    /**
     * Uses the server URL already saved by the original Settings > WaysGram admin panel.
     * This avoids adding a second server-address setting to the existing UI.
     */
    public WaysGramApiClient(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("Context is required");
        }
        SharedPreferences preferences = context.getApplicationContext()
                .getSharedPreferences("waysgram_admin_panel", Context.MODE_PRIVATE);
        baseUrl = normalizeBaseUrl(preferences.getString("api_url", ""));
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public static String normalizeBaseUrl(String value) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException("Укажите адрес WaysGram API");
        }
        try {
            URI uri = new URI(value.trim());
            String scheme = uri.getScheme();
            String host = uri.getHost();
            if (scheme == null || host == null || uri.getUserInfo() != null
                    || uri.getQuery() != null || uri.getFragment() != null) {
                throw new IllegalArgumentException("Некорректный адрес WaysGram API");
            }
            boolean secure = "https".equalsIgnoreCase(scheme);
            boolean loopbackHttp = "http".equalsIgnoreCase(scheme) && isLoopbackHost(host);
            if (!secure && !loopbackHttp) {
                throw new IllegalArgumentException("Для удалённого сервера требуется HTTPS");
            }
            String normalized = uri.normalize().toASCIIString();
            while (normalized.endsWith("/")) {
                normalized = normalized.substring(0, normalized.length() - 1);
            }
            return normalized;
        } catch (java.net.URISyntaxException e) {
            throw new IllegalArgumentException("Некорректный адрес WaysGram API", e);
        }
    }

    private static boolean isLoopbackHost(String host) {
        String value = host.toLowerCase(java.util.Locale.US);
        return "localhost".equals(value) || "127.0.0.1".equals(value)
                || "::1".equals(value) || "10.0.2.2".equals(value);
    }

    public void getConfig(Callback callback) {
        enqueue("GET", "/api/config", null, null, callback);
    }

    public void requestCode(String phone, Callback callback) {
        enqueue("POST", "/api/auth/request-code", json("phone", phone), null, callback);
    }

    public void verifyCode(String phone, String code, Callback callback) {
        enqueue("POST", "/api/auth/verify-code",
                json("phone", phone, "code", code), null, callback);
    }

    public void logout(String token, Callback callback) {
        enqueue("POST", "/api/auth/logout", new JSONObject(), token, callback);
    }

    public void getMe(String token, Callback callback) {
        enqueue("GET", "/api/me", null, token, callback);
    }

    public void getConversations(String token, Callback callback) {
        enqueue("GET", "/api/conversations", null, token, callback);
    }

    public void searchUsers(String token, String query, Callback callback) {
        enqueue("GET", "/api/users?q=" + encode(query == null ? "" : query), null, token, callback);
    }

    public void getUser(String token, long userId, Callback callback) {
        requirePositiveId(userId);
        enqueue("GET", "/api/users/" + userId, null, token, callback);
    }

    public void getMessages(String token, long peerId, Callback callback) {
        requirePositiveId(peerId);
        enqueue("GET", "/api/messages?with=" + peerId, null, token, callback);
    }

    public void sendMessage(String token, long recipientId, String body, Callback callback) {
        requirePositiveId(recipientId);
        enqueue("POST", "/api/messages",
                json("recipient_id", recipientId, "body", body), token, callback);
    }

    public void getChannels(String token, Callback callback) {
        enqueue("GET", "/api/channels", null, token, callback);
    }

    public void getChannel(String token, long channelId, Callback callback) {
        requirePositiveId(channelId);
        enqueue("GET", "/api/channels/" + channelId, null, token, callback);
    }

    public void getChannelMessages(String token, long channelId, Callback callback) {
        requirePositiveId(channelId);
        enqueue("GET", "/api/channels/" + channelId + "/messages", null, token, callback);
    }

    public void publishChannelMessage(String token, long channelId, String body, Callback callback) {
        requirePositiveId(channelId);
        enqueue("POST", "/api/channels/" + channelId + "/messages",
                json("body", body), token, callback);
    }

    public void getGifts(String token, Callback callback) {
        enqueue("GET", "/api/gifts", null, token, callback);
    }

    private void enqueue(final String method, final String path, final JSONObject body,
                         final String token, final Callback callback) {
        if (callback == null) {
            throw new IllegalArgumentException("Callback is required");
        }
        IO.execute(() -> {
            JSONObject result = null;
            ApiError failure = null;
            try {
                result = execute(method, path, body, token);
            } catch (ApiError e) {
                failure = e;
            } catch (Exception e) {
                failure = new ApiError(0, safeMessage(e));
            }
            final JSONObject response = result;
            final ApiError error = failure;
            MAIN.post(() -> {
                if (error == null) {
                    callback.onSuccess(response);
                } else {
                    callback.onError(error);
                }
            });
        });
    }

    private JSONObject execute(String method, String path, JSONObject body, String token)
            throws IOException, JSONException, ApiError {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(baseUrl + path);
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            if (token != null && !token.isEmpty()) {
                if (token.indexOf('\n') >= 0 || token.indexOf('\r') >= 0) {
                    throw new IOException("Некорректный токен сессии");
                }
                connection.setRequestProperty("Authorization", "Bearer " + token);
            }
            if (body != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(bytes);
                }
            }

            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 400
                    ? connection.getInputStream() : connection.getErrorStream();
            String payload = stream == null ? "" : readLimited(stream);
            JSONObject response;
            try {
                response = payload.isEmpty() ? new JSONObject() : new JSONObject(payload);
            } catch (JSONException e) {
                response = new JSONObject();
                response.put("error", "Сервер вернул некорректный JSON");
            }
            if (status < 200 || status >= 300) {
                throw new ApiError(status, response.optString("error", "HTTP " + status));
            }
            return response;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String readLimited(InputStream input) throws IOException {
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(input, StandardCharsets.UTF_8))) {
            char[] buffer = new char[4096];
            int count;
            while ((count = reader.read(buffer)) != -1) {
                if (result.length() + count > MAX_RESPONSE_CHARS) {
                    throw new IOException("Ответ WaysGram API превышает допустимый размер");
                }
                result.append(buffer, 0, count);
            }
        }
        return result.toString();
    }

    private static JSONObject json(Object... pairs) {
        JSONObject result = new JSONObject();
        try {
            for (int i = 0; i + 1 < pairs.length; i += 2) {
                result.put(String.valueOf(pairs[i]), pairs[i + 1]);
            }
        } catch (JSONException e) {
            throw new IllegalArgumentException("Не удалось сформировать JSON-запрос", e);
        }
        return result;
    }

    private static String encode(String value) {
        try {
            return URLEncoder.encode(value, "UTF-8");
        } catch (java.io.UnsupportedEncodingException e) {
            throw new IllegalStateException("UTF-8 is unavailable", e);
        }
    }

    private static void requirePositiveId(long value) {
        if (value <= 0) {
            throw new IllegalArgumentException("ID должен быть положительным");
        }
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty()
                ? "Не удалось связаться с WaysGram API" : message;
    }
}
