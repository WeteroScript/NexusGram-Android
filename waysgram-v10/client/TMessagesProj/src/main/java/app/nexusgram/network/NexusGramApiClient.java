package app.nexusgram.network;

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
import java.security.MessageDigest;
import java.security.KeyStore;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * WaysGram REST API client. This client talks only to the configured WaysGram backend.
 * It does not call Telegram MTProto endpoints or request Telegram account codes.
 */
public final class NexusGramApiClient implements AutoCloseable {
    public interface Callback {
        void onSuccess(JSONObject result);
        void onError(String message);
    }

    private static final String PREFS = "waysgram_api";
    private static final String LEGACY_TOKEN_KEY = "access_token";
    private static final String ENCRYPTED_TOKEN_KEY = "access_token_enc_v1";
    private static final String KEY_ALIAS = "WaysGram.Api.AccessToken.v1";
    private static final String TOKEN_PREFIX = "v1:";
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String PENDING_IDEMPOTENCY_PREFIX = "pending_idempotency_v1_";
    private static final String PENDING_OPERATION_PREFIX = "pending_operation_v2_";
    private static final String ACCOUNT_ID_KEY = "account_id_v1";
    private static final String LAST_SESSION_REFRESH_KEY = "last_session_refresh_ms_v1";
    private static final String PENDING_OPERATION_SEQUENCE_KEY = "pending_operation_sequence_v1";
    private static final long PENDING_OPERATION_MAX_AGE_MS = 6L * 24L * 60L * 60L * 1000L;
    private static final long SESSION_REFRESH_INTERVAL_MS = 6L * 60L * 60L * 1000L;
    private static final int MAX_PENDING_OPERATIONS = 100;
    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 20000;
    private static final int MAX_RESPONSE_BYTES = 1024 * 1024;
    private static final int GCM_TAG_BITS = 128;
    private static final Pattern PHONE_PATTERN = Pattern.compile("^\\+1[0-9]{10}$");
    private static final Pattern CODE_PATTERN = Pattern.compile("^[0-9]{6}$");

    private final String baseUrl;
    private final SharedPreferences preferences;
    private final ExecutorService executor = Executors.newFixedThreadPool(3);
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean closed = new AtomicBoolean(false);
    private final Object idempotencyLock = new Object();
    private final AtomicBoolean pendingReplayInFlight = new AtomicBoolean(false);
    private volatile Runnable sessionExpiredListener;
    private volatile Runnable pendingOperationsRestoredListener;

    public NexusGramApiClient(Context context, String serverBaseUrl) {
        if (context == null) {
            throw new IllegalArgumentException("Context is required");
        }
        if (serverBaseUrl == null || serverBaseUrl.trim().isEmpty()) {
            throw new IllegalArgumentException("WaysGram server URL is required");
        }

        String normalized = serverBaseUrl.trim().replaceAll("/+$", "");
        try {
            URI parsed = URI.create(normalized);
            String scheme = parsed.getScheme();
            String host = parsed.getHost();
            if (host == null || parsed.getUserInfo() != null || parsed.getQuery() != null || parsed.getFragment() != null) {
                throw new IllegalArgumentException("Invalid WaysGram server URL");
            }
            boolean https = "https".equalsIgnoreCase(scheme);
            boolean localHttp = "http".equalsIgnoreCase(scheme)
                    && ("127.0.0.1".equals(host)
                    || "localhost".equalsIgnoreCase(host)
                    || "::1".equals(host)
                    || "10.0.2.2".equals(host));
            if (!https && !localHttp) {
                throw new IllegalArgumentException("Use HTTPS. HTTP is allowed only for local development.");
            }
        } catch (IllegalArgumentException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalArgumentException("Invalid WaysGram server URL", error);
        }

        this.baseUrl = normalized;
        this.preferences = context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Returns a token decrypted from Android Keystore, or null when there is no session. */
    public String getAccessToken() {
        String encrypted = preferences.getString(ENCRYPTED_TOKEN_KEY, null);
        if (encrypted != null && encrypted.startsWith(TOKEN_PREFIX)) {
            try {
                return decryptToken(encrypted.substring(TOKEN_PREFIX.length()));
            } catch (GeneralSecurityException | IllegalArgumentException error) {
                clearCredentialsPreservingPending();
                return null;
            }
        }

        // One-time migration from the previous plain SharedPreferences token.
        String legacy = preferences.getString(LEGACY_TOKEN_KEY, null);
        if (legacy == null || legacy.isEmpty()) {
            return null;
        }
        try {
            saveAccessToken(legacy);
            return legacy;
        } catch (GeneralSecurityException error) {
            clearCredentialsPreservingPending();
            return null;
        }
    }

    public boolean isSignedIn() {
        String token = getAccessToken();
        return token != null && !token.isEmpty();
    }

    /** Registers a foreground owner callback for any authenticated HTTP 401 response. */
    public void setSessionExpiredListener(Runnable listener) {
        sessionExpiredListener = listener;
    }

    /** Registers a callback after one or more queued writes have been applied/replayed. */
    public void setPendingOperationsRestoredListener(Runnable listener) {
        pendingOperationsRestoredListener = listener;
    }

    /** Explicit logout: remove credentials and cancel locally queued writes for this device. */
    public void clearLocalSession() {
        synchronized (idempotencyLock) {
            SharedPreferences.Editor editor = preferences.edit()
                    .remove(LEGACY_TOKEN_KEY)
                    .remove(ENCRYPTED_TOKEN_KEY)
                    .remove(ACCOUNT_ID_KEY)
                    .remove(LAST_SESSION_REFRESH_KEY)
                    .remove(PENDING_OPERATION_SEQUENCE_KEY);
            for (String key : preferences.getAll().keySet()) {
                if (key.startsWith(PENDING_IDEMPOTENCY_PREFIX)
                        || key.startsWith(PENDING_OPERATION_PREFIX)) {
                    editor.remove(key);
                }
            }
            editor.commit();
        }
    }

    /** A revoked/expired session must not destroy operations waiting for the same account to sign in again. */
    private void clearCredentialsPreservingPending() {
        preferences.edit()
                .remove(LEGACY_TOKEN_KEY)
                .remove(ENCRYPTED_TOKEN_KEY)
                .remove(LAST_SESSION_REFRESH_KEY)
                .commit();
    }

    private long getStoredAccountId() {
        return preferences.getLong(ACCOUNT_ID_KEY, 0L);
    }

    private boolean saveAccountId(long accountId) {
        if (accountId <= 0) return false;
        boolean stored = preferences.edit().putLong(ACCOUNT_ID_KEY, accountId).commit();
        if (!stored) preferences.edit().remove(ACCOUNT_ID_KEY).commit();
        return stored;
    }

    private void clearLegacyPendingMarkers() {
        synchronized (idempotencyLock) {
            SharedPreferences.Editor editor = preferences.edit();
            boolean changed = false;
            for (String key : preferences.getAll().keySet()) {
                if (key.startsWith(PENDING_IDEMPOTENCY_PREFIX)) {
                    editor.remove(key);
                    changed = true;
                }
            }
            if (changed) editor.commit();
        }
    }

    /** Refresh a valid session at most once every six hours while the app is in use. */
    public boolean shouldRefreshSession() {
        long last = preferences.getLong(LAST_SESSION_REFRESH_KEY, 0L);
        return last <= 0L || System.currentTimeMillis() - last >= SESSION_REFRESH_INTERVAL_MS;
    }

    /** Retry durable writes when the app returns to the foreground or connectivity is restored. */
    public void resumePendingOperations() {
        if (closed.get() || getAccessToken() == null) return;
        long accountId = getStoredAccountId();
        if (accountId > 0L) replayPendingOperations(accountId);
    }

    public void checkHealth(Callback callback) {
        get("/health", false, callback);
    }

    public void getApiConfig(Callback callback) {
        get("/api/config", false, callback);
    }

    public void requestCode(String phone, Callback callback) {
        if (!isValidPhone(phone)) {
            deliverError(callback, "Номер WaysGram должен иметь формат +1 и 10 цифр");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "phone", phone);
        post("/api/auth/request-code", body, false, callback);
    }

    public void verifyCode(String phone, String code, Callback callback) {
        if (!isValidPhone(phone) || code == null || !CODE_PATTERN.matcher(code).matches()) {
            deliverError(callback, "Проверьте виртуальный номер +1 и шестизначный код");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "phone", phone);
        put(body, "code", code);
        post("/api/auth/verify-code", body, false, new Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                JSONObject user = result.optJSONObject("user");
                String token = result.optString("token", "");
                if (token.isEmpty() || user == null || user.optLong("id", 0) <= 0) {
                    deliverError(callback, "Сервер вернул неполный ответ авторизации");
                    return;
                }
                try {
                    saveAccessToken(token);
                    long accountId = user.optLong("id", 0L);
                    if (!saveAccountId(accountId)) {
                        clearCredentialsPreservingPending();
                        deliverError(callback, "Не удалось сохранить идентификатор аккаунта для восстановления операций");
                        return;
                    }
                    clearLegacyPendingMarkers(); // v8 kept only opaque keys and cannot restore request bodies after token rotation.
                    preferences.edit().putLong(LAST_SESSION_REFRESH_KEY, 0L).commit();
                    replayPendingOperations(accountId);
                    deliverSuccess(callback, result);
                } catch (GeneralSecurityException error) {
                    clearLocalSession();
                    deliverError(callback, "Не удалось безопасно сохранить сессию на устройстве");
                }
            }

            @Override
            public void onError(String message) {
                deliverError(callback, message);
            }
        });
    }

    public void getMe(Callback callback) {
        get("/api/me", true, new Callback() {
            @Override public void onSuccess(JSONObject result) {
                long accountId = result.optLong("id", 0L);
                if (accountId > 0) {
                    if (saveAccountId(accountId)) replayPendingOperations(accountId);
                }
                deliverSuccess(callback, result);
            }
            @Override public void onError(String message) { deliverError(callback, message); }
        });
    }

    public void refreshSession(Callback callback) {
        post("/api/auth/refresh", new JSONObject(), true, new Callback() {
            @Override public void onSuccess(JSONObject result) {
                JSONObject user = result.optJSONObject("user");
                if (user != null) {
                    long accountId = user.optLong("id", 0L);
                    if (accountId > 0) {
                        if (saveAccountId(accountId)) replayPendingOperations(accountId);
                    }
                }
                preferences.edit().putLong(LAST_SESSION_REFRESH_KEY, System.currentTimeMillis()).commit();
                deliverSuccess(callback, result);
            }
            @Override public void onError(String message) { deliverError(callback, message); }
        });
    }

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
        if (userId <= 0) {
            deliverError(callback, "Некорректный ID пользователя");
            return;
        }
        get("/api/users/" + userId, true, callback);
    }

    public void getConversations(Callback callback) {
        get("/api/conversations", true, callback);
    }

    public void getMessages(long peerUserId, Callback callback) {
        getMessages(peerUserId, 0L, callback);
    }

    /** Loads the latest history when afterMessageId is zero, or only newer messages otherwise. */
    public void getMessages(long peerUserId, long afterMessageId, Callback callback) {
        if (peerUserId <= 0 || afterMessageId < 0) {
            deliverError(callback, "Некорректный ID собеседника или сообщения");
            return;
        }
        get("/api/messages?with=" + peerUserId + "&after_id=" + afterMessageId, true, callback);
    }

    public void sendMessage(long recipientId, String text, Callback callback) {
        if (recipientId <= 0 || text == null || text.trim().isEmpty()) {
            deliverError(callback, "Укажите получателя и текст сообщения");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "recipient_id", recipientId);
        put(body, "body", text);
        postIdempotent("/api/messages", body, true, callback);
    }

    public void getGifts(Callback callback) {
        get("/api/gifts", true, callback);
    }

    /** Reads the separate Stars and Gram balances. Gift purchases spend Gram only. */
    public void getWallet(Callback callback) {
        get("/api/me/wallet", true, callback);
    }

    public void getGramTransactions(Callback callback) {
        get("/api/me/wallet/transactions", true, callback);
    }

    /** Returns the collectible gifts currently owned by the signed-in account. */
    public void getMyGifts(Callback callback) {
        get("/api/me/gifts", true, callback);
    }

    public void getGiftTransactions(Callback callback) {
        get("/api/me/gifts/transactions", true, callback);
    }

    /** Buys one catalogue item using the user's Gram balance. */
    public void purchaseGift(long giftId, Callback callback) {
        if (giftId <= 0) {
            deliverError(callback, "Некорректный ID подарка");
            return;
        }
        postIdempotent("/api/gifts/" + giftId + "/purchase", new JSONObject(), true, callback);
    }

    /** Transfers an owned collectible by its serial number to a username or numeric user ID. */
    public void transferGift(String serialNumber, String recipient, Callback callback) {
        if (serialNumber == null || !serialNumber.trim().matches("(?i)^WG-[A-F0-9]{12}$")
                || recipient == null || recipient.trim().isEmpty()) {
            deliverError(callback, "Укажите корректный серийный номер и получателя подарка");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "serial_number", serialNumber.trim());
        put(body, "recipient", recipient.trim());
        postIdempotent("/api/gifts/transfer", body, true, callback);
    }

    public void getChannels(Callback callback) {
        get("/api/channels", true, callback);
    }

    public void getChannel(long channelId, Callback callback) {
        if (channelId <= 0) {
            deliverError(callback, "Некорректный ID канала");
            return;
        }
        get("/api/channels/" + channelId, true, callback);
    }

    public void getChannelMessages(long channelId, Callback callback) {
        getChannelMessages(channelId, 0L, callback);
    }

    /** Loads the latest channel history or only posts newer than afterMessageId. */
    public void getChannelMessages(long channelId, long afterMessageId, Callback callback) {
        if (channelId <= 0 || afterMessageId < 0) {
            deliverError(callback, "Некорректный ID канала или публикации");
            return;
        }
        get("/api/channels/" + channelId + "/messages?after_id=" + afterMessageId, true, callback);
    }

    public void publishToChannel(long channelId, String text, Callback callback) {
        if (channelId <= 0 || text == null || text.trim().isEmpty()) {
            deliverError(callback, "Укажите канал и текст публикации");
            return;
        }
        JSONObject body = new JSONObject();
        put(body, "body", text);
        postIdempotent("/api/channels/" + channelId + "/messages", body, true, callback);
    }

    /** Stars balance is returned by GET /api/me as the "stars" field. */
    public void getStarsBalance(Callback callback) {
        getMe(new Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                JSONObject balance = new JSONObject();
                put(balance, "stars", result.optInt("stars", 0));
                deliverSuccess(callback, balance);
            }

            @Override
            public void onError(String message) {
                deliverError(callback, message);
            }
        });
    }

    public void logout(Callback callback) {
        post("/api/auth/logout", new JSONObject(), true, new Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                clearLocalSession();
                deliverSuccess(callback, result);
            }

            @Override
            public void onError(String message) {
                // Clear local credentials even if the server is unreachable. The server-side
                // session then expires according to its own policy.
                clearLocalSession();
                deliverError(callback, message);
            }
        });
    }

    private void get(String path, boolean authenticated, Callback callback) {
        execute("GET", path, null, authenticated, callback);
    }

    private void post(String path, JSONObject body, boolean authenticated, Callback callback) {
        execute("POST", path, body, authenticated, callback);
    }

    /**
     * Persist the complete operation before sending it. This allows the same request and
     * Idempotency-Key to be replayed after process death, network loss, or a fresh login.
     */
    private void postIdempotent(String path, JSONObject body, boolean authenticated, Callback callback) {
        if (!authenticated) {
            deliverError(callback, "Для восстановления операции требуется аккаунт WaysGram");
            return;
        }
        PendingOperation operation = createPendingOperation(path, body);
        if (operation == null) {
            deliverError(callback, "Не удалось безопасно сохранить операцию на устройстве");
            return;
        }
        execute("POST", path, body, true, operation.idempotencyKey,
                () -> removePendingOperation(operation.preferenceKey, operation.idempotencyKey), callback);
    }

    private static final class PendingOperation {
        final String preferenceKey;
        final String path;
        final String bodyJson;
        final String idempotencyKey;
        final long accountId;
        final long createdAt;
        final long sequence;

        PendingOperation(String preferenceKey, String path, String bodyJson,
                         String idempotencyKey, long accountId, long createdAt, long sequence) {
            this.preferenceKey = preferenceKey;
            this.path = path;
            this.bodyJson = bodyJson;
            this.idempotencyKey = idempotencyKey;
            this.accountId = accountId;
            this.createdAt = createdAt;
            this.sequence = sequence;
        }
    }

    private PendingOperation createPendingOperation(String path, JSONObject body) {
        long accountId = getStoredAccountId();
        if (accountId <= 0L) return null;
        String bodyJson = body == null ? "{}" : body.toString();
        synchronized (idempotencyLock) {
            long now = System.currentTimeMillis();
            int pendingCount = 0;
            SharedPreferences.Editor cleanup = preferences.edit();
            boolean cleanupChanged = false;
            for (java.util.Map.Entry<String, ?> entry : preferences.getAll().entrySet()) {
                if (!entry.getKey().startsWith(PENDING_OPERATION_PREFIX)) continue;
                if (!(entry.getValue() instanceof String)) {
                    cleanup.remove(entry.getKey());
                    cleanupChanged = true;
                    continue;
                }
                PendingOperation stored = decodePendingOperation(entry.getKey(), (String) entry.getValue());
                if (stored == null || now - stored.createdAt > PENDING_OPERATION_MAX_AGE_MS) {
                    cleanup.remove(entry.getKey());
                    cleanupChanged = true;
                } else {
                    pendingCount++;
                }
            }
            if (cleanupChanged && !cleanup.commit()) return null;
            if (pendingCount >= MAX_PENDING_OPERATIONS) return null;

            // v8 stored only an opaque retry key. Migrate it once when the exact old request is retried.
            String legacyKey = null;
            String token = getAccessToken();
            if (token != null) {
                try {
                    String legacyIdentity = baseUrl + "\n" + token + "\n" + path + "\n" + bodyJson;
                    String legacyPreferenceKey = PENDING_IDEMPOTENCY_PREFIX + sha256Hex(legacyIdentity);
                    legacyKey = preferences.getString(legacyPreferenceKey, null);
                    if (legacyKey != null) preferences.edit().remove(legacyPreferenceKey).commit();
                } catch (GeneralSecurityException ignored) { }
            }

            String operationId = UUID.randomUUID().toString();
            String preferenceKey = PENDING_OPERATION_PREFIX + operationId;
            String idempotencyKey = legacyKey == null || legacyKey.isEmpty()
                    ? operationId : legacyKey;
            long previousSequence = preferences.getLong(PENDING_OPERATION_SEQUENCE_KEY, 0L);
            long sequence = Math.max(now * 1000L, previousSequence + 1L);
            JSONObject record = new JSONObject();
            put(record, "account_id", accountId);
            put(record, "path", path);
            put(record, "body", bodyJson);
            put(record, "idempotency_key", idempotencyKey);
            put(record, "created_at", now);
            put(record, "sequence", sequence);
            try {
                String encrypted = TOKEN_PREFIX + encryptToken(record.toString());
                boolean stored = preferences.edit()
                        .putString(preferenceKey, encrypted)
                        .putLong(PENDING_OPERATION_SEQUENCE_KEY, sequence)
                        .commit();
                if (!stored) return null;
                return new PendingOperation(preferenceKey, path, bodyJson, idempotencyKey,
                        accountId, now, sequence);
            } catch (GeneralSecurityException error) {
                return null;
            }
        }
    }

    private PendingOperation decodePendingOperation(String preferenceKey, String encrypted) {
        if (encrypted == null || !encrypted.startsWith(TOKEN_PREFIX)) return null;
        try {
            JSONObject record = new JSONObject(decryptToken(encrypted.substring(TOKEN_PREFIX.length())));
            String path = record.optString("path", "");
            String body = record.optString("body", "{}");
            String key = record.optString("idempotency_key", "");
            long accountId = record.optLong("account_id", 0L);
            long createdAt = record.optLong("created_at", 0L);
            // v9 records predate sequence numbers; their creation time provides a stable fallback.
            long sequence = record.optLong("sequence", createdAt * 1000L);
            boolean supportedPath = "/api/messages".equals(path)
                    || "/api/gifts/transfer".equals(path)
                    || path.matches("/api/gifts/[0-9]+/purchase")
                    || path.matches("/api/channels/[0-9]+/messages");
            if (!supportedPath || key.isEmpty() || accountId <= 0L || createdAt <= 0L || sequence <= 0L) return null;
            new JSONObject(body); // Reject malformed/tampered persisted request bodies.
            return new PendingOperation(preferenceKey, path, body, key, accountId, createdAt, sequence);
        } catch (Exception error) {
            return null;
        }
    }

    private void removePendingOperation(String preferenceKey, String expectedIdempotencyKey) {
        synchronized (idempotencyLock) {
            String value = preferences.getString(preferenceKey, null);
            PendingOperation current = value == null ? null : decodePendingOperation(preferenceKey, value);
            if (current != null && expectedIdempotencyKey.equals(current.idempotencyKey)) {
                preferences.edit().remove(preferenceKey).commit();
            }
        }
    }

    private boolean hasPendingOperation(PendingOperation operation) {
        synchronized (idempotencyLock) {
            String value = preferences.getString(operation.preferenceKey, null);
            PendingOperation current = value == null ? null : decodePendingOperation(operation.preferenceKey, value);
            return current != null && operation.idempotencyKey.equals(current.idempotencyKey);
        }
    }

    private void replayPendingOperations(long accountId) {
        if (accountId <= 0L || closed.get() || !pendingReplayInFlight.compareAndSet(false, true)) return;
        List<PendingOperation> pending = new ArrayList<>();
        long now = System.currentTimeMillis();
        synchronized (idempotencyLock) {
            for (java.util.Map.Entry<String, ?> entry : preferences.getAll().entrySet()) {
                if (!entry.getKey().startsWith(PENDING_OPERATION_PREFIX) || !(entry.getValue() instanceof String)) continue;
                PendingOperation operation = decodePendingOperation(entry.getKey(), (String) entry.getValue());
                if (operation == null || now - operation.createdAt > PENDING_OPERATION_MAX_AGE_MS) {
                    preferences.edit().remove(entry.getKey()).commit();
                } else if (operation.accountId == accountId) {
                    pending.add(operation);
                }
            }
        }
        if (pending.isEmpty()) {
            pendingReplayInFlight.set(false);
            return;
        }
        java.util.Collections.sort(pending, (left, right) -> {
            int sequenceOrder = Long.compare(left.sequence, right.sequence);
            if (sequenceOrder != 0) return sequenceOrder;
            int timeOrder = Long.compare(left.createdAt, right.createdAt);
            if (timeOrder != 0) return timeOrder;
            return left.preferenceKey.compareTo(right.preferenceKey);
        });
        replayPendingOperationAt(pending, 0, false);
    }

    private void notifyPendingOperationsRestored() {
        Runnable listener = pendingOperationsRestoredListener;
        if (listener != null && !closed.get()) main.post(listener);
    }

    private void replayPendingOperationAt(List<PendingOperation> pending, int index, boolean stateChanged) {
        if (closed.get() || index >= pending.size()) {
            pendingReplayInFlight.set(false);
            if (stateChanged) notifyPendingOperationsRestored();
            return;
        }
        PendingOperation operation = pending.get(index);
        try {
            JSONObject body = new JSONObject(operation.bodyJson);
            execute("POST", operation.path, body, true, operation.idempotencyKey,
                    () -> removePendingOperation(operation.preferenceKey, operation.idempotencyKey),
                    new Callback() {
                        @Override public void onSuccess(JSONObject result) {
                            replayPendingOperationAt(pending, index + 1, true);
                        }
                        @Override public void onError(String message) {
                            if (hasPendingOperation(operation)) {
                                // Network errors, 401, 429 and server errors stay queued for the next active session.
                                pendingReplayInFlight.set(false);
                                if (stateChanged) notifyPendingOperationsRestored();
                            } else {
                                replayPendingOperationAt(pending, index + 1, stateChanged);
                            }
                        }
                    });
        } catch (JSONException error) {
            removePendingOperation(operation.preferenceKey, operation.idempotencyKey);
            replayPendingOperationAt(pending, index + 1, stateChanged);
        }
    }

    private static String sha256Hex(String value) throws GeneralSecurityException {
        byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder output = new StringBuilder(digest.length * 2);
        for (byte item : digest) output.append(String.format(java.util.Locale.US, "%02x", item & 0xff));
        return output.toString();
    }

    private void patch(String path, JSONObject body, boolean authenticated, Callback callback) {
        execute("PATCH", path, body, authenticated, callback);
    }

    private void execute(String method, String path, JSONObject body, boolean authenticated, Callback callback) {
        execute(method, path, body, authenticated, null, null, callback);
    }

    private void execute(String method, String path, JSONObject body, boolean authenticated,
                         String idempotencyKey, Runnable onHttpResponse, Callback callback) {
        if (closed.get()) {
            deliverError(callback, "WaysGram API client is closed");
            return;
        }
        try {
            executor.execute(() -> {
                HttpURLConnection connection = null;
                try {
                    URL url = URI.create(baseUrl + path).toURL();
                    connection = (HttpURLConnection) url.openConnection();
                    connection.setRequestMethod(method);
                    connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
                    connection.setReadTimeout(READ_TIMEOUT_MS);
                    connection.setInstanceFollowRedirects(false);
                    connection.setUseCaches(false);
                    connection.setRequestProperty("Accept", "application/json");
                    connection.setRequestProperty("Cache-Control", "no-store");
                    connection.setRequestProperty("Connection", "close");
                    if (idempotencyKey != null) {
                        connection.setRequestProperty("Idempotency-Key", idempotencyKey);
                    }
                    if (authenticated) {
                        String token = getAccessToken();
                        if (token == null || token.isEmpty()) {
                            throw new IOException("Требуется вход в WaysGram");
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
                    InputStream stream = status >= 200 && status < 300
                            ? connection.getInputStream() : connection.getErrorStream();
                    String response = readAll(stream, MAX_RESPONSE_BYTES);
                    JSONObject json = parseJson(response);
                    boolean definitive = (status >= 200 && status < 300)
                            || (status >= 400 && status < 500
                            && status != 401 && status != 408 && status != 425 && status != 429);
                    if (definitive && onHttpResponse != null) onHttpResponse.run();
                    if (status < 200 || status >= 300) {
                        String message = json.optString("error", "Ошибка WaysGram API: HTTP " + status);
                        if (status == 401 && authenticated) {
                            clearCredentialsPreservingPending();
                            message = "SESSION_EXPIRED: " + message;
                            Runnable listener = sessionExpiredListener;
                            if (listener != null && !"/api/auth/logout".equals(path)) {
                                main.post(listener);
                            }
                        }
                        deliverError(callback, message);
                    } else {
                        deliverSuccess(callback, json);
                    }
                } catch (Exception error) {
                    String message = error.getMessage();
                    deliverError(callback, message == null ? "Не удалось подключиться к серверу WaysGram" : message);
                } finally {
                    if (connection != null) connection.disconnect();
                }
            });
        } catch (RejectedExecutionException error) {
            deliverError(callback, "WaysGram API client is closed");
        }
    }

    private void saveAccessToken(String token) throws GeneralSecurityException {
        String encrypted = encryptToken(token);
        boolean stored = preferences.edit()
                .putString(ENCRYPTED_TOKEN_KEY, TOKEN_PREFIX + encrypted)
                .remove(LEGACY_TOKEN_KEY)
                .commit();
        if (!stored) throw new GeneralSecurityException("Could not persist access token");
    }

    private static SecretKey getOrCreateKeystoreKey() throws GeneralSecurityException {
        try {
            KeyStore keyStore = KeyStore.getInstance(KEYSTORE);
            keyStore.load(null);
            if (keyStore.containsAlias(KEY_ALIAS)) {
                java.security.Key key = keyStore.getKey(KEY_ALIAS, null);
                if (key instanceof SecretKey) {
                    return (SecretKey) key;
                }
                keyStore.deleteEntry(KEY_ALIAS);
            }

            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
            KeyGenParameterSpec spec = new KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build();
            generator.init(spec);
            return generator.generateKey();
        } catch (java.io.IOException error) {
            throw new GeneralSecurityException("Android Keystore is unavailable", error);
        } catch (java.security.KeyStoreException | java.security.cert.CertificateException error) {
            throw new GeneralSecurityException("Android Keystore is unavailable", error);
        }
    }

    private static String encryptToken(String token) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKeystoreKey());
        byte[] encrypted = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV();
        byte[] combined = new byte[iv.length + encrypted.length];
        System.arraycopy(iv, 0, combined, 0, iv.length);
        System.arraycopy(encrypted, 0, combined, iv.length, encrypted.length);
        return Base64.encodeToString(combined, Base64.NO_WRAP);
    }

    private static String decryptToken(String encoded) throws GeneralSecurityException {
        byte[] combined;
        try {
            combined = Base64.decode(encoded, Base64.NO_WRAP);
        } catch (IllegalArgumentException error) {
            throw new GeneralSecurityException("Invalid encrypted token", error);
        }
        final int ivLength = 12;
        if (combined.length <= ivLength) {
            throw new GeneralSecurityException("Invalid encrypted token length");
        }
        byte[] iv = new byte[ivLength];
        byte[] ciphertext = new byte[combined.length - ivLength];
        System.arraycopy(combined, 0, iv, 0, ivLength);
        System.arraycopy(combined, ivLength, ciphertext, 0, ciphertext.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKeystoreKey(), new GCMParameterSpec(GCM_TAG_BITS, iv));
        return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
    }

    private static boolean isValidPhone(String phone) {
        return phone != null && PHONE_PATTERN.matcher(phone).matches();
    }

    private static JSONObject parseJson(String response) throws IOException {
        if (response == null || response.trim().isEmpty()) {
            return new JSONObject();
        }
        try {
            return new JSONObject(response);
        } catch (JSONException error) {
            throw new IOException("Сервер WaysGram вернул некорректный JSON", error);
        }
    }

    private static String readAll(InputStream stream, int maximumBytes) throws IOException {
        if (stream == null) {
            return "";
        }
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            int total = 0;
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > maximumBytes) {
                    throw new IOException("Ответ WaysGram API превышает допустимый размер");
                }
                output.write(buffer, 0, read);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String encode(String value) {
        try {
            return java.net.URLEncoder.encode(value == null ? "" : value, "UTF-8");
        } catch (Exception ignored) {
            return "";
        }
    }

    private static void put(JSONObject object, String key, Object value) {
        try {
            object.put(key, value);
        } catch (JSONException error) {
            throw new IllegalArgumentException("Cannot encode request JSON", error);
        }
    }

    private void deliverSuccess(Callback callback, JSONObject result) {
        if (callback != null) {
            main.post(() -> callback.onSuccess(result));
        }
    }

    private void deliverError(Callback callback, String message) {
        if (callback != null) {
            main.post(() -> callback.onError(message));
        }
    }

    @Override
    public void close() {
        if (closed.compareAndSet(false, true)) {
            executor.shutdownNow();
        }
    }
}