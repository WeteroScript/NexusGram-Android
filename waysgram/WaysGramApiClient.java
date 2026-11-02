package app.waysgram.network;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Pattern;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** REST client for the single WaysGram AuthBot backend. */
public final class WaysGramApiClient implements AutoCloseable {
    public interface Callback {
        void onSuccess(JSONObject result);
        void onError(String message);
    }

    private static final String PREFS = "waysgram_api";
    private static final String TOKEN_KEY = "access_token_enc_v1";
    private static final String KEY_ALIAS = "WaysGram.Api.AccessToken.v1";
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String TOKEN_PREFIX = "v1:";
    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 20000;
    private static final int MAX_RESPONSE_BYTES = 1024 * 1024;
    private static final int GCM_TAG_BITS = 128;
    private static final Pattern PHONE = Pattern.compile("^\\+1[0-9]{10}$");
    private static final Pattern CODE = Pattern.compile("^[0-9]{6}$");

    private final String baseUrl;
    private final SharedPreferences preferences;
    private final ExecutorService executor = Executors.newFixedThreadPool(3);
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean closed = new AtomicBoolean(false);

    public WaysGramApiClient(Context context, String serverBaseUrl) {
        if (context == null) throw new IllegalArgumentException("Context is required");
        if (serverBaseUrl == null || serverBaseUrl.trim().isEmpty()) {
            throw new IllegalArgumentException("WaysGram server URL is required");
        }
        String normalized = serverBaseUrl.trim().replaceAll("/+$", "");
        URI parsed = URI.create(normalized);
        String scheme = parsed.getScheme();
        String host = parsed.getHost();
        boolean https = "https".equalsIgnoreCase(scheme);
        boolean localHttp = "http".equalsIgnoreCase(scheme)
                && ("127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host)
                || "::1".equals(host) || "10.0.2.2".equals(host));
        if (host == null || parsed.getUserInfo() != null || parsed.getQuery() != null
                || parsed.getFragment() != null || (!https && !localHttp)) {
            throw new IllegalArgumentException("Use a valid HTTPS WaysGram API URL");
        }
        baseUrl = normalized;
        preferences = context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public String getAccessToken() {
        String saved = preferences.getString(TOKEN_KEY, null);
        if (saved == null || !saved.startsWith(TOKEN_PREFIX)) return null;
        try {
            return decrypt(saved.substring(TOKEN_PREFIX.length()));
        } catch (GeneralSecurityException | IllegalArgumentException error) {
            clearLocalSession();
            return null;
        }
    }

    public boolean isSignedIn() {
        String token = getAccessToken();
        return token != null && !token.isEmpty();
    }

    public void clearLocalSession() {
        preferences.edit().remove(TOKEN_KEY).apply();
    }

    public void checkHealth(Callback callback) { get("/health", false, callback); }
    public void getApiConfig(Callback callback) { get("/api/config", false, callback); }

    public void requestCode(String phone, Callback callback) {
        if (phone == null || !PHONE.matcher(phone).matches()) {
            error(callback, "Номер WaysGram должен иметь формат +1 и 10 цифр");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "phone", phone);
        post("/api/auth/request-code", body, false, callback);
    }

    public void verifyCode(String phone, String code, Callback callback) {
        if (phone == null || !PHONE.matcher(phone).matches()
                || code == null || !CODE.matcher(code).matches()) {
            error(callback, "Проверьте виртуальный номер и шестизначный код");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "phone", phone);
        put(body, "code", code);
        post("/api/auth/verify-code", body, false, new Callback() {
            @Override public void onSuccess(JSONObject result) {
                JSONObject user = result.optJSONObject("user");
                String token = result.optString("token", "");
                if (user == null || user.optLong("id", 0) <= 0 || token.isEmpty()) {
                    error(callback, "Сервер вернул неполный ответ авторизации");
                    return;
                }
                try {
                    preferences.edit().putString(TOKEN_KEY, TOKEN_PREFIX + encrypt(token)).apply();
                    success(callback, result);
                } catch (GeneralSecurityException e) {
                    clearLocalSession();
                    error(callback, "Не удалось безопасно сохранить сессию на устройстве");
                }
            }
            @Override public void onError(String message) { error(callback, message); }
        });
    }

    public void refreshSession(Callback callback) { post("/api/auth/refresh", new JSONObject(), true, callback); }
    public void logout(Callback callback) {
        post("/api/auth/logout", new JSONObject(), true, new Callback() {
            @Override public void onSuccess(JSONObject result) { clearLocalSession(); success(callback, result); }
            @Override public void onError(String message) { clearLocalSession(); error(callback, message); }
        });
    }
    public void getMe(Callback callback) { get("/api/me", true, callback); }
    public void updateProfile(String username, String displayName, Callback callback) {
        JSONObject body = new JSONObject();
        if (username != null) put(body, "username", username);
        if (displayName != null) put(body, "display_name", displayName);
        patch("/api/me", body, true, callback);
    }
    public void searchUsers(String query, Callback callback) {
        get("/api/users?q=" + encode(query), true, callback);
    }
    public void getUser(long userId, Callback callback) {
        if (userId <= 0) { error(callback, "Некорректный ID пользователя"); return; }
        get("/api/users/" + userId, true, callback);
    }
    public void getConversations(Callback callback) { get("/api/conversations", true, callback); }
    public void getMessages(long peerId, Callback callback) { getMessages(peerId, 0, 0, callback); }
    public void getMessages(long peerId, long afterId, Callback callback) {
        getMessages(peerId, afterId, 0, callback);
    }
    public void getMessages(long peerId, long afterId, long beforeId, Callback callback) {
        if (peerId <= 0 || afterId < 0 || beforeId < 0 || (afterId > 0 && beforeId > 0)) {
            error(callback, "Некорректные параметры переписки");
            return;
        }
        String path = "/api/messages?with=" + peerId;
        if (afterId > 0) {
            path += "&after_id=" + afterId;
        } else if (beforeId > 0) {
            path += "&before_id=" + beforeId;
        }
        get(path, true, callback);
    }
    public void sendMessage(long recipientId, String text, Callback callback) {
        if (recipientId <= 0 || text == null || text.trim().isEmpty()) {
            error(callback, "Укажите получателя и текст сообщения"); return;
        }
        JSONObject body = new JSONObject();
        put(body, "recipient_id", recipientId);
        put(body, "body", text);
        postIdempotent("/api/messages", body, callback);
    }
    public void getWallet(Callback callback) { get("/api/me/wallet", true, callback); }
    public void getGramTransactions(Callback callback) { get("/api/me/wallet/transactions", true, callback); }
    public void getStarsBalance(Callback callback) { getMe(callback); }
    public void getGifts(Callback callback) { get("/api/gifts", true, callback); }
    public void getMyGifts(Callback callback) { get("/api/me/gifts", true, callback); }
    public void getGiftTransactions(Callback callback) { get("/api/me/gifts/transactions", true, callback); }
    public void purchaseGift(long giftId, Callback callback) {
        if (giftId <= 0) { error(callback, "Некорректный ID подарка"); return; }
        postIdempotent("/api/gifts/" + giftId + "/purchase", new JSONObject(), callback);
    }
    public void transferGift(String serial, String recipient, Callback callback) {
        if (serial == null || !serial.matches("(?i)^WG-[A-F0-9]{12}$")
                || recipient == null || recipient.trim().isEmpty()) {
            error(callback, "Укажите корректный серийный номер и получателя"); return;
        }
        JSONObject body = new JSONObject();
        put(body, "serial_number", serial);
        put(body, "recipient", recipient.trim());
        postIdempotent("/api/gifts/transfer", body, callback);
    }
    public void getChannels(Callback callback) { get("/api/channels", true, callback); }
    public void getChannel(long id, Callback callback) { get("/api/channels/" + id, true, callback); }
    public void getChannelMessages(long id, Callback callback) { getChannelMessages(id, 0, callback); }
    public void getChannelMessages(long id, long afterId, Callback callback) {
        if (id <= 0 || afterId < 0) { error(callback, "Некорректные параметры канала"); return; }
        get("/api/channels/" + id + "/messages?after_id=" + afterId, true, callback);
    }
    public void publishToChannel(long id, String text, Callback callback) {
        if (id <= 0 || text == null || text.trim().isEmpty()) {
            error(callback, "Укажите канал и текст публикации"); return;
        }
        JSONObject body = new JSONObject();
        put(body, "body", text);
        postIdempotent("/api/channels/" + id + "/messages", body, callback);
    }

    private void get(String path, boolean auth, Callback callback) { execute("GET", path, null, auth, null, callback); }
    private void post(String path, JSONObject body, boolean auth, Callback callback) { execute("POST", path, body, auth, null, callback); }
    private void patch(String path, JSONObject body, boolean auth, Callback callback) { execute("PATCH", path, body, auth, null, callback); }
    private void postIdempotent(String path, JSONObject body, Callback callback) {
        execute("POST", path, body, true, UUID.randomUUID().toString(), callback);
    }

    private void execute(String method, String path, JSONObject body, boolean auth, String idempotencyKey, Callback callback) {
        if (closed.get()) { error(callback, "WaysGram API client is closed"); return; }
        try {
            executor.execute(() -> {
                HttpURLConnection connection = null;
                try {
                    connection = (HttpURLConnection) new URL(baseUrl + path).openConnection();
                    connection.setRequestMethod(method);
                    connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
                    connection.setReadTimeout(READ_TIMEOUT_MS);
                    connection.setInstanceFollowRedirects(false);
                    connection.setUseCaches(false);
                    connection.setRequestProperty("Accept", "application/json");
                    connection.setRequestProperty("Cache-Control", "no-store");
                    if (auth) {
                        String token = getAccessToken();
                        if (token == null || token.isEmpty()) throw new IOException("Требуется вход в WaysGram");
                        connection.setRequestProperty("Authorization", "Bearer " + token);
                    }
                    if (idempotencyKey != null) connection.setRequestProperty("Idempotency-Key", idempotencyKey);
                    if (body != null) {
                        connection.setDoOutput(true);
                        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                        connection.setFixedLengthStreamingMode(bytes.length);
                        try (OutputStream out = connection.getOutputStream()) { out.write(bytes); }
                    }
                    int status = connection.getResponseCode();
                    InputStream stream = status >= 200 && status < 300
                            ? connection.getInputStream() : connection.getErrorStream();
                    JSONObject json = parse(readAll(stream));
                    if (status < 200 || status >= 300) {
                        if (status == 401 && auth) clearLocalSession();
                        error(callback, json.optString("detail", json.optString("error", "HTTP " + status)));
                    } else success(callback, json);
                } catch (Exception e) {
                    error(callback, e.getMessage() == null ? "Не удалось подключиться к WaysGram" : e.getMessage());
                } finally {
                    if (connection != null) connection.disconnect();
                }
            });
        } catch (RuntimeException e) { error(callback, "WaysGram API client is closed"); }
    }

    private static String readAll(InputStream stream) throws IOException {
        if (stream == null) return "";
        try (InputStream in = stream; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count, total = 0;
            while ((count = in.read(buffer)) != -1) {
                total += count;
                if (total > MAX_RESPONSE_BYTES) throw new IOException("API response is too large");
                out.write(buffer, 0, count);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static JSONObject parse(String value) throws IOException {
        try { return value == null || value.trim().isEmpty() ? new JSONObject() : new JSONObject(value); }
        catch (JSONException e) { throw new IOException("Сервер вернул некорректный JSON", e); }
    }
    private static String encode(String value) {
        try { return java.net.URLEncoder.encode(value == null ? "" : value, "UTF-8"); }
        catch (Exception e) { return ""; }
    }
    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value); } catch (JSONException e) { throw new IllegalArgumentException(e); }
    }
    private void success(Callback callback, JSONObject result) {
        if (callback != null) main.post(() -> callback.onSuccess(result));
    }
    private void error(Callback callback, String message) {
        if (callback != null) main.post(() -> callback.onError(message));
    }

    private static SecretKey key() throws GeneralSecurityException {
        KeyStore store = KeyStore.getInstance(KEYSTORE);
        try { store.load(null); } catch (IOException | java.security.cert.CertificateException e) {
            throw new GeneralSecurityException(e);
        }
        if (store.containsAlias(KEY_ALIAS)) {
            java.security.Key existing = store.getKey(KEY_ALIAS, null);
            if (existing instanceof SecretKey) return (SecretKey) existing;
            store.deleteEntry(KEY_ALIAS);
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }
    private static String encrypt(String token) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] encrypted = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV();
        byte[] joined = new byte[iv.length + encrypted.length];
        System.arraycopy(iv, 0, joined, 0, iv.length);
        System.arraycopy(encrypted, 0, joined, iv.length, encrypted.length);
        return Base64.encodeToString(joined, Base64.NO_WRAP);
    }
    private static String decrypt(String encoded) throws GeneralSecurityException {
        byte[] joined = Base64.decode(encoded, Base64.NO_WRAP);
        if (joined.length <= 12) throw new GeneralSecurityException("Invalid token");
        byte[] iv = new byte[12];
        byte[] cipherText = new byte[joined.length - 12];
        System.arraycopy(joined, 0, iv, 0, 12);
        System.arraycopy(joined, 12, cipherText, 0, cipherText.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(GCM_TAG_BITS, iv));
        return new String(cipher.doFinal(cipherText), StandardCharsets.UTF_8);
    }

    @Override public void close() {
        if (closed.compareAndSet(false, true)) executor.shutdownNow();
    }
}
