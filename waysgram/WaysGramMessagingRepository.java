package org.telegram.messenger;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Authenticated WaysGram data repository for conversations, messages,
 * users, channels and gifts. It has no dependency on Telegram TLRPC models.
 */
public final class WaysGramMessagingRepository {
    public interface Callback<T> {
        void onSuccess(T result);
        void onError(WaysGramApiClient.ApiError error);
    }

    private interface AuthenticatedCall {
        void run(String token);
    }

    private static final ExecutorService STORAGE = Executors.newSingleThreadExecutor();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private final WaysGramApiClient api;
    private final WaysGramSessionStore sessions;

    public WaysGramMessagingRepository(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("Context is required");
        }
        api = new WaysGramApiClient(context);
        sessions = new WaysGramSessionStore(context);
    }

    public void getConversations(Callback<List<WaysGramModels.Conversation>> callback) {
        withSession(callback, token -> api.getConversations(token, listCallback(
                "conversations", WaysGramModels.Conversation::new, callback)));
    }

    public void searchUsers(String query, Callback<List<WaysGramModels.User>> callback) {
        String safeQuery = query == null ? "" : query.trim();
        if (safeQuery.length() > 80) {
            fail(callback, 400, "Поисковый запрос слишком длинный");
            return;
        }
        withSession(callback, token -> api.searchUsers(token, safeQuery, listCallback(
                "users", WaysGramModels.User::new, callback)));
    }

    public void getMessages(long peerId, Callback<List<WaysGramModels.Message>> callback) {
        if (peerId <= 0) {
            fail(callback, 400, "Некорректный ID собеседника");
            return;
        }
        withSession(callback, token -> api.getMessages(token, peerId, listCallback(
                "messages", WaysGramModels.Message::new, callback)));
    }

    public void sendMessage(long recipientId, String body, Callback<JSONObject> callback) {
        if (recipientId <= 0) {
            fail(callback, 400, "Некорректный ID получателя");
            return;
        }
        if (body == null || body.trim().isEmpty() || body.length() > 4000) {
            fail(callback, 400, "Сообщение должно содержать от 1 до 4000 символов");
            return;
        }
        withSession(callback, token -> api.sendMessage(token, recipientId, body, jsonCallback(callback)));
    }

    public void updateProfile(String username, String displayName, Callback<JSONObject> callback) {
        if (username == null && displayName == null) {
            fail(callback, 400, "Укажите username или отображаемое имя");
            return;
        }
        if (username != null && !username.matches("[A-Za-z][A-Za-z0-9_]{0,31}")) {
            fail(callback, 400, "Username: 1–32 символа, латиница, цифры и _, первый символ — буква");
            return;
        }
        if (displayName != null && displayName.trim().length() > 60) {
            fail(callback, 400, "Имя профиля слишком длинное");
            return;
        }
        withSession(callback, token -> api.updateProfile(token, username, displayName, jsonCallback(callback)));
    }

    public void getChannels(Callback<List<WaysGramModels.Channel>> callback) {
        withSession(callback, token -> api.getChannels(token, listCallback(
                "channels", WaysGramModels.Channel::new, callback)));
    }

    public void getChannelMessages(long channelId, Callback<List<WaysGramModels.ChannelMessage>> callback) {
        if (channelId <= 0) {
            fail(callback, 400, "Некорректный ID канала");
            return;
        }
        withSession(callback, token -> api.getChannelMessages(token, channelId, listCallback(
                "messages", WaysGramModels.ChannelMessage::new, callback)));
    }

    public void publishChannelMessage(long channelId, String body, Callback<JSONObject> callback) {
        if (channelId <= 0) {
            fail(callback, 400, "Некорректный ID канала");
            return;
        }
        if (body == null || body.trim().isEmpty() || body.length() > 4000) {
            fail(callback, 400, "Сообщение канала должно содержать от 1 до 4000 символов");
            return;
        }
        withSession(callback, token -> api.publishChannelMessage(
                token, channelId, body, jsonCallback(callback)));
    }

    public void getGifts(Callback<List<WaysGramModels.Gift>> callback) {
        withSession(callback, token -> api.getGifts(token, listCallback(
                "gifts", WaysGramModels.Gift::new, callback)));
    }

    private <T> void withSession(Callback<T> callback, AuthenticatedCall call) {
        if (callback == null) {
            throw new IllegalArgumentException("Callback is required");
        }
        STORAGE.execute(() -> {
            final String token;
            try {
                token = sessions.getAccessToken();
            } catch (GeneralSecurityException | IOException e) {
                fail(callback, 0, "Не удалось прочитать сессию WaysGram");
                return;
            }
            if (token == null || token.isEmpty()) {
                fail(callback, 401, "Требуется войти в WaysGram");
                return;
            }
            call.run(token);
        });
    }

    private <T> WaysGramApiClient.Callback listCallback(
            String key, ModelFactory<T> factory, Callback<List<T>> callback) {
        return new WaysGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject response) {
                JSONArray items = response.optJSONArray(key);
                if (items == null) {
                    fail(callback, 502, "Ответ WaysGram API не содержит список " + key);
                    return;
                }
                ArrayList<T> result = new ArrayList<>(items.length());
                for (int i = 0; i < items.length(); i++) {
                    JSONObject item = items.optJSONObject(i);
                    if (item == null) {
                        fail(callback, 502, "Некорректная запись в ответе WaysGram API");
                        return;
                    }
                    try {
                        result.add(factory.create(item));
                    } catch (RuntimeException e) {
                        fail(callback, 502, "Не удалось обработать данные WaysGram");
                        return;
                    }
                }
                callbackSuccess(callback, Collections.unmodifiableList(result));
            }

            @Override
            public void onError(WaysGramApiClient.ApiError error) {
                clearSessionIfUnauthorized(error);
                callbackError(callback, error);
            }
        };
    }

    private WaysGramApiClient.Callback jsonCallback(Callback<JSONObject> callback) {
        return new WaysGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject response) {
                callbackSuccess(callback, response);
            }

            @Override
            public void onError(WaysGramApiClient.ApiError error) {
                clearSessionIfUnauthorized(error);
                callbackError(callback, error);
            }
        };
    }

    private void clearSessionIfUnauthorized(WaysGramApiClient.ApiError error) {
        if (error != null && error.statusCode == 401) {
            STORAGE.execute(() -> {
                try {
                    sessions.clear();
                } catch (GeneralSecurityException | IOException ignored) {
                    // Keep the original API error as the user-visible failure.
                }
            });
        }
    }

    private interface ModelFactory<T> {
        T create(JSONObject json);
    }

    private static <T> void fail(Callback<T> callback, int status, String message) {
        callbackError(callback, new WaysGramApiClient.ApiError(status, message));
    }

    private static <T> void callbackSuccess(Callback<T> callback, T result) {
        if (callback != null) {
            MAIN.post(() -> callback.onSuccess(result));
        }
    }

    private static <T> void callbackError(Callback<T> callback, WaysGramApiClient.ApiError error) {
        if (callback != null) {
            MAIN.post(() -> callback.onError(error));
        }
    }
}
