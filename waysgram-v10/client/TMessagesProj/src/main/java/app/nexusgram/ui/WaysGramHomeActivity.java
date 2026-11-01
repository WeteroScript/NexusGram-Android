package app.nexusgram.ui;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
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

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.atomic.AtomicBoolean;

import app.nexusgram.network.NexusGramApiClient;

/** WaysGram account hub for profile, balances, internal collectibles and transfers. */
public final class WaysGramHomeActivity extends Activity {
    private String serverUrl;
    private NexusGramApiClient api;
    private LinearLayout page;
    private LinearLayout conversationsSection;
    private LinearLayout channelsSection;
    private LinearLayout catalogSection;
    private LinearLayout inventorySection;
    private LinearLayout historySection;
    private long currentUserId;
    private TextView profileView;
    private TextView walletView;
    private TextView statusView;
    private JSONArray giftHistoryData;
    private JSONArray gramHistoryData;
    private final Handler pollingHandler = new Handler(Looper.getMainLooper());
    private Runnable activePollingTask;
    private boolean activityResumed;
    private boolean pendingAccountRefresh;
    private ConnectivityManager connectivityManager;
    private ConnectivityManager.NetworkCallback networkCallback;
    private volatile boolean networkAvailable = true;
    private int homeSyncFailures;
    private final AtomicBoolean homeSyncInFlight = new AtomicBoolean(false);
    private static final long SESSION_REFRESH_CHECK_MS = 6L * 60L * 60L * 1000L;
    private final Runnable sessionRefreshTask = new Runnable() {
        @Override public void run() {
            if (!activityResumed || isFinishing() || isDestroyed()) return;
            refreshSessionIfNeeded();
            pollingHandler.postDelayed(this, SESSION_REFRESH_CHECK_MS);
        }
    };
    private final Runnable homeSyncTask = new Runnable() {
        @Override public void run() {
            if (!activityResumed || isFinishing() || isDestroyed() || api == null) return;
            if (!networkAvailable) {
                pollingHandler.postDelayed(this, 60000L);
                return;
            }
            if (!homeSyncInFlight.compareAndSet(false, true)) {
                pollingHandler.postDelayed(this, 5000L);
                return;
            }
            final java.util.concurrent.atomic.AtomicInteger remaining =
                    new java.util.concurrent.atomic.AtomicInteger(2);
            final AtomicBoolean failed = new AtomicBoolean(false);
            Runnable completed = () -> {
                if (remaining.decrementAndGet() != 0) return;
                homeSyncInFlight.set(false);
                if (failed.get()) homeSyncFailures = Math.min(homeSyncFailures + 1, 8);
                else homeSyncFailures = 0;
                if (activityResumed && !isFinishing() && !isDestroyed()) {
                    long delay = networkAvailable
                            ? retryDelayMillis(homeSyncFailures, 15000L, 120000L) : 60000L;
                    pollingHandler.removeCallbacks(this);
                    pollingHandler.postDelayed(this, delay);
                }
            };
            api.getConversations(new NexusGramApiClient.Callback() {
                @Override public void onSuccess(JSONObject result) {
                    renderConversations(result.optJSONArray("conversations"));
                    completed.run();
                }
                @Override public void onError(String message) {
                    failed.set(true);
                    preserveRowsOrShowError(conversationsSection, message);
                    completed.run();
                }
            });
            api.getChannels(new NexusGramApiClient.Callback() {
                @Override public void onSuccess(JSONObject result) {
                    renderChannels(result.optJSONArray("channels"));
                    completed.run();
                }
                @Override public void onError(String message) {
                    failed.set(true);
                    preserveRowsOrShowError(channelsSection, message);
                    completed.run();
                }
            });
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        serverUrl = getIntent().getStringExtra(WaysGramPortalActivity.EXTRA_SERVER_URL);
        if (serverUrl == null || serverUrl.trim().isEmpty()) {
            serverUrl = getSharedPreferences("waysgram_portal", MODE_PRIVATE).getString("server_url", "");
        }
        try {
            api = new NexusGramApiClient(getApplicationContext(), serverUrl);
            api.setSessionExpiredListener(() -> goToLogin("Сессия WaysGram истекла. Войдите снова."));
            api.setPendingOperationsRestoredListener(() -> {
                if (isFinishing()) return;
                if (activityResumed) loadAll();
                else pendingAccountRefresh = true;
            });
        } catch (Exception error) {
            goToLogin("Укажите сервер WaysGram повторно.");
            return;
        }
        if (!api.isSignedIn()) {
            goToLogin("Сессия WaysGram не найдена.");
            return;
        }
        registerNetworkMonitor();
        buildUi();
        loadAll();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(18), dp(22), dp(18), dp(28));
        page.setBackgroundColor(Color.rgb(245, 247, 251));
        scroll.addView(page, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setOrientation(LinearLayout.HORIZONTAL);
        TextView title = text("WaysGram", 27, Color.rgb(25, 42, 70), true);
        header.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Button refresh = button("Обновить", false);
        header.addView(refresh, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(42)));
        refresh.setOnClickListener(v -> loadAll());
        page.addView(header, matchWrap());

        statusView = text("Загружаем данные аккаунта…", 13, Color.rgb(103, 115, 132), false);
        statusView.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams statusParams = matchWrap();
        statusParams.topMargin = dp(7);
        page.addView(statusView, statusParams);

        LinearLayout profileCard = card();
        LinearLayout.LayoutParams profileParams = matchWrap();
        profileParams.topMargin = dp(18);
        page.addView(profileCard, profileParams);
        profileCard.addView(label("Аккаунт"), matchWrap());
        profileView = text("—", 16, Color.rgb(42, 55, 74), true);
        LinearLayout.LayoutParams profileTextParams = matchWrap();
        profileTextParams.topMargin = dp(8);
        profileCard.addView(profileView, profileTextParams);

        LinearLayout walletCard = card();
        LinearLayout.LayoutParams walletParams = matchWrap();
        walletParams.topMargin = dp(12);
        page.addView(walletCard, walletParams);
        walletCard.addView(label("Баланс"), matchWrap());
        walletView = text("Stars: —     Gram: —", 19, Color.rgb(36, 79, 126), true);
        LinearLayout.LayoutParams walletTextParams = matchWrap();
        walletTextParams.topMargin = dp(10);
        walletCard.addView(walletView, walletTextParams);
        TextView walletHint = text("Stars и Gram — разные внутренние балансы. Покупка подарков списывает только Gram.",
                12, Color.rgb(111, 121, 137), false);
        LinearLayout.LayoutParams walletHintParams = matchWrap();
        walletHintParams.topMargin = dp(7);
        walletCard.addView(walletHint, walletHintParams);

        conversationsSection = addSection("Диалоги WaysGram", "Личные сообщения внутри отдельной системы WaysGram.");
        channelsSection = addSection("Каналы WaysGram", "Список каналов и их публикации.");
        catalogSection = addSection("Каталог подарков", "Подарки с ограниченным количеством экземпляров. Покупка выполняется за Gram.");
        inventorySection = addSection("Мои подарки", "Каждый экземпляр имеет уникальный серийный номер WG-…");
        historySection = addSection("История операций", "Покупки и передачи подарков, а также изменения Gram.");

        Button logout = button("Выйти из WaysGram", true);
        LinearLayout.LayoutParams logoutParams = buttonParams();
        logoutParams.topMargin = dp(22);
        page.addView(logout, logoutParams);
        logout.setOnClickListener(v -> logout());

        TextView disclaimer = text("Внутренние коллекционные записи WaysGram. Не блокчейн-NFT и не внешний актив.",
                12, Color.rgb(119, 128, 143), false);
        disclaimer.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams disclaimerParams = matchWrap();
        disclaimerParams.topMargin = dp(12);
        page.addView(disclaimer, disclaimerParams);
        setContentView(scroll);
    }

    private LinearLayout addSection(String title, String hint) {
        LinearLayout section = card();
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(12);
        page.addView(section, params);
        section.addView(label(title), matchWrap());
        TextView description = text(hint, 12, Color.rgb(111, 121, 137), false);
        LinearLayout.LayoutParams descriptionParams = matchWrap();
        descriptionParams.topMargin = dp(5);
        section.addView(description, descriptionParams);
        View divider = new View(this);
        divider.setBackgroundColor(Color.rgb(232, 236, 242));
        LinearLayout.LayoutParams dividerParams = matchWrap();
        dividerParams.height = dp(1);
        dividerParams.topMargin = dp(12);
        dividerParams.bottomMargin = dp(8);
        section.addView(divider, dividerParams);
        return section;
    }

    private void loadAll() {
        if (api == null) return;
        statusView.setText("Обновляем аккаунт…");
        api.getMe(new NexusGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                String displayName = result.optString("display_name", "").trim();
                String username = result.optString("username", "");
                long id = result.optLong("id", 0);
                currentUserId = id;
                if (displayName.isEmpty()) displayName = username.isEmpty() ? "Пользователь" : "@" + username;
                profileView.setText(displayName + (username.isEmpty() ? "" : "\n@" + username)
                        + "\nID: " + id);
                statusView.setText("Аккаунт подключён");
                loadConversations();
                loadChannels();
            }

            @Override
            public void onError(String message) {
                statusView.setText(message);
                if (!api.isSignedIn()) goToLogin("Сессия истекла. Войдите снова.");
            }
        });
        api.getWallet(new NexusGramApiClient.Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                walletView.setText("Stars: " + result.optLong("stars", 0)
                        + "       Gram: " + result.optLong("grams", 0));
            }
            @Override public void onError(String message) { statusView.setText(message); }
        });
        api.getGifts(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) { renderCatalog(result.optJSONArray("gifts")); }
            @Override public void onError(String message) { renderEmpty(catalogSection, message); }
        });
        api.getMyGifts(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) { renderInventory(result.optJSONArray("gifts")); }
            @Override public void onError(String message) { renderEmpty(inventorySection, message); }
        });
        giftHistoryData = null;
        gramHistoryData = null;
        api.getGiftTransactions(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) {
                giftHistoryData = result.optJSONArray("transactions");
                renderHistory();
            }
            @Override public void onError(String message) {
                giftHistoryData = new JSONArray();
                statusView.setText(message);
                renderHistory();
            }
        });
        api.getGramTransactions(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) {
                gramHistoryData = result.optJSONArray("transactions");
                renderHistory();
            }
            @Override public void onError(String message) {
                gramHistoryData = new JSONArray();
                statusView.setText(message);
                renderHistory();
            }
        });
    }

    private void renderConversations(JSONArray conversations) {
        clearRows(conversationsSection);
        Button findUser = button("Найти пользователя", false);
        addRow(conversationsSection, findUser);
        findUser.setOnClickListener(v -> showUserSearchDialog());
        if (conversations == null || conversations.length() == 0) {
            addRow(conversationsSection, text("Диалогов пока нет. Найдите пользователя, чтобы начать переписку.",
                    13, Color.GRAY, false));
            return;
        }
        for (int i = 0; i < conversations.length(); i++) {
            JSONObject conversation = conversations.optJSONObject(i);
            if (conversation == null) continue;
            long peerId = conversation.optLong("id", 0);
            String username = conversation.optString("username", "user_" + peerId);
            String displayName = conversation.optString("display_name", "");
            String lastMessage = conversation.optString("last_message", "");
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.VERTICAL);
            TextView heading = text((displayName.isEmpty() ? "@" + username : displayName + " · @" + username),
                    14, Color.rgb(49, 62, 80), true);
            TextView preview = text(lastMessage, 12, Color.rgb(111, 121, 137), false);
            row.addView(heading, matchWrap());
            LinearLayout.LayoutParams previewParams = matchWrap();
            previewParams.topMargin = dp(3);
            row.addView(preview, previewParams);
            row.setPadding(0, dp(5), 0, dp(5));
            row.setOnClickListener(v -> openConversation(peerId, username));
            addRow(conversationsSection, row);
        }
    }

    private void showUserSearchDialog() {
        EditText query = new EditText(this);
        query.setSingleLine(true);
        query.setHint("username");
        query.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        LinearLayout wrapper = new LinearLayout(this);
        wrapper.setPadding(dp(18), dp(4), dp(18), 0);
        wrapper.addView(query, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));
        new AlertDialog.Builder(this)
                .setTitle("Найти пользователя")
                .setView(wrapper)
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Поиск", (dialog, which) -> {
                    String value = query.getText().toString().trim();
                    if (value.isEmpty()) {
                        toast("Введите username");
                        return;
                    }
                    api.searchUsers(value, new NexusGramApiClient.Callback() {
                        @Override public void onSuccess(JSONObject result) {
                            JSONArray users = result.optJSONArray("users");
                            if (users == null || users.length() == 0) {
                                toast("Пользователи не найдены");
                                return;
                            }
                            java.util.ArrayList<JSONObject> matches = new java.util.ArrayList<>();
                            java.util.ArrayList<String> labels = new java.util.ArrayList<>();
                            for (int i = 0; i < users.length(); i++) {
                                JSONObject user = users.optJSONObject(i);
                                if (user == null || user.optLong("id", 0) == currentUserId) continue;
                                matches.add(user);
                                String username = user.optString("username", "");
                                String displayName = user.optString("display_name", "");
                                labels.add(displayName.isEmpty() ? "@" + username : displayName + " (@" + username + ")");
                            }
                            if (matches.isEmpty()) {
                                toast("Других пользователей не найдено");
                                return;
                            }
                            String[] choices = labels.toArray(new String[0]);
                            new AlertDialog.Builder(WaysGramHomeActivity.this)
                                    .setTitle("Выберите собеседника")
                                    .setItems(choices, (choiceDialog, index) -> {
                                        JSONObject selected = matches.get(index);
                                        openConversation(selected.optLong("id", 0), selected.optString("username", "user"));
                                    }).setNegativeButton("Закрыть", null).show();
                        }
                        @Override public void onError(String message) { toast(message); }
                    });
                }).show();
    }

    private void openConversation(long peerId, String username) {
        if (peerId <= 0) return;
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(8), dp(16), dp(4));
        ScrollView historyScroll = new ScrollView(this);
        TextView history = text("Загружаем переписку…", 13, Color.rgb(62, 73, 90), false);
        history.setPadding(dp(4), dp(4), dp(4), dp(4));
        historyScroll.addView(history, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        content.addView(historyScroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(260)));
        EditText composer = new EditText(this);
        composer.setHint("Сообщение");
        composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        composer.setMinLines(1);
        composer.setMaxLines(4);
        composer.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(4000)});
        content.addView(composer, matchWrap());
        Button send = button("Отправить", true);
        LinearLayout.LayoutParams sendParams = buttonParams();
        sendParams.topMargin = dp(8);
        content.addView(send, sendParams);

        Button refresh = button("Обновить переписку", false);
        LinearLayout.LayoutParams refreshParams = buttonParams();
        refreshParams.topMargin = dp(5);
        content.addView(refresh, refreshParams);

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("@" + username)
                .setView(content)
                .setNegativeButton("Закрыть", null)
                .create();
        final boolean[] dialogIsClosed = {false};
        StringBuilder messageHistory = new StringBuilder();
        final long[] lastMessageId = {0L};
        final AtomicBoolean messageRequestInFlight = new AtomicBoolean(false);
        final int[] messageFailures = {0};
        final Runnable[] pollMessagesRef = {null};
        Runnable scheduleNextMessagePoll = () -> {
            if (pollMessagesRef[0] != null) {
                scheduleActivePolling(pollMessagesRef[0], retryDelayMillis(messageFailures[0], 5000L, 120000L));
            }
        };
        Runnable reloadMessages = () -> {
            if (!messageRequestInFlight.compareAndSet(false, true)) return;
            if (!networkAvailable) {
                messageRequestInFlight.set(false);
                messageFailures[0] = Math.min(messageFailures[0] + 1, 8);
                scheduleNextMessagePoll.run();
                return;
            }
            api.getMessages(peerId, lastMessageId[0], new NexusGramApiClient.Callback() {
                @Override public void onSuccess(JSONObject result) {
                    try {
                        if (dialogIsClosed[0]) return;
                        messageFailures[0] = 0;
                        JSONArray messages = result.optJSONArray("messages");
                        boolean wasAtBottom = historyScroll.getChildCount() == 0
                                || historyScroll.getScrollY() + historyScroll.getHeight()
                                >= historyScroll.getChildAt(0).getHeight() - dp(48);
                        if (lastMessageId[0] == 0L) messageHistory.setLength(0);
                        if (messages != null) {
                            for (int i = 0; i < messages.length(); i++) {
                                JSONObject message = messages.optJSONObject(i);
                                if (message == null) continue;
                                long messageId = message.optLong("id", 0L);
                                if (messageId <= lastMessageId[0]) continue;
                                boolean outgoing = message.optLong("sender_id", 0) == currentUserId;
                                messageHistory.append(outgoing ? "Вы" : "@" + username).append(":\n")
                                        .append(message.optString("body", "")).append("\n\n");
                                lastMessageId[0] = Math.max(lastMessageId[0], messageId);
                            }
                        }
                        if (messageHistory.length() == 0) history.setText("Сообщений пока нет.");
                        else history.setText(messageHistory.toString());
                        if (wasAtBottom) historyScroll.post(() -> historyScroll.fullScroll(View.FOCUS_DOWN));
                    } finally {
                        messageRequestInFlight.set(false);
                        if (!dialogIsClosed[0]) scheduleNextMessagePoll.run();
                    }
                }
                @Override public void onError(String message) {
                    messageRequestInFlight.set(false);
                    messageFailures[0] = Math.min(messageFailures[0] + 1, 8);
                    if (!dialogIsClosed[0] && messageHistory.length() == 0) history.setText("Нет соединения. Повторим загрузку автоматически.");
                    if (!dialogIsClosed[0]) scheduleNextMessagePoll.run();
                }
            });
        };
        refresh.setOnClickListener(v -> reloadMessages.run());
        send.setOnClickListener(v -> {
            String body = composer.getText().toString().trim();
            if (body.isEmpty()) return;
            send.setEnabled(false);
            api.sendMessage(peerId, body, new NexusGramApiClient.Callback() {
                @Override public void onSuccess(JSONObject result) {
                    composer.setText("");
                    send.setEnabled(true);
                    reloadMessages.run();
                    loadConversations();
                }
                @Override public void onError(String message) {
                    send.setEnabled(true);
                    toast(message);
                }
            });
        });
        dialog.setOnDismissListener(ignored -> {
            dialogIsClosed[0] = true;
            stopActivePolling();
        });
        dialog.show();
        reloadMessages.run();
        Runnable pollMessages = new Runnable() {
            @Override public void run() {
                if (dialogIsClosed[0] || !dialog.isShowing() || !activityResumed || isFinishing() || isDestroyed()) return;
                if (!networkAvailable) {
                    scheduleActivePolling(this, 60000L);
                    return;
                }
                reloadMessages.run();
            }
        };
        pollMessagesRef[0] = pollMessages;
        startActivePolling(pollMessages);
    }

    private void loadConversations() {
        api.getConversations(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) { renderConversations(result.optJSONArray("conversations")); }
            @Override public void onError(String message) { preserveRowsOrShowError(conversationsSection, message); }
        });
    }

    private void loadChannels() {
        api.getChannels(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) { renderChannels(result.optJSONArray("channels")); }
            @Override public void onError(String message) { preserveRowsOrShowError(channelsSection, message); }
        });
    }

    private void renderChannels(JSONArray channels) {
        clearRows(channelsSection);
        if (channels == null || channels.length() == 0) {
            addRow(channelsSection, text("Каналов пока нет.", 13, Color.GRAY, false));
            return;
        }
        for (int i = 0; i < channels.length(); i++) {
            JSONObject channel = channels.optJSONObject(i);
            if (channel == null) continue;
            long channelId = channel.optLong("id", 0);
            String username = channel.optString("username", "");
            String title = channel.optString("title", "Канал");
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.VERTICAL);
            TextView heading = text(title, 14, Color.rgb(49, 62, 80), true);
            TextView subtitle = text("@" + username, 12, Color.rgb(111, 121, 137), false);
            row.addView(heading, matchWrap());
            LinearLayout.LayoutParams subtitleParams = matchWrap();
            subtitleParams.topMargin = dp(3);
            row.addView(subtitle, subtitleParams);
            row.setPadding(0, dp(5), 0, dp(5));
            row.setOnClickListener(v -> openChannel(channelId, title));
            addRow(channelsSection, row);
        }
    }

    private void openChannel(long channelId, String title) {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(8), dp(16), dp(4));
        ScrollView postsScroll = new ScrollView(this);
        TextView posts = text("Загружаем публикации…", 13, Color.rgb(62, 73, 90), false);
        posts.setPadding(dp(4), dp(4), dp(4), dp(4));
        postsScroll.addView(posts, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        content.addView(postsScroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(260)));
        EditText composer = new EditText(this);
        composer.setHint("Новая публикация (если у вас есть права)");
        composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        composer.setMinLines(1);
        composer.setMaxLines(4);
        composer.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(4000)});
        content.addView(composer, matchWrap());
        Button publish = button("Опубликовать", true);
        LinearLayout.LayoutParams publishParams = buttonParams();
        publishParams.topMargin = dp(8);
        content.addView(publish, publishParams);
        Button refresh = button("Обновить публикации", false);
        LinearLayout.LayoutParams refreshParams = buttonParams();
        refreshParams.topMargin = dp(5);
        content.addView(refresh, refreshParams);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(title)
                .setView(content)
                .setNegativeButton("Закрыть", null)
                .create();
        final boolean[] dialogIsClosed = {false};
        StringBuilder postHistory = new StringBuilder();
        final long[] lastPostId = {0L};
        final AtomicBoolean postRequestInFlight = new AtomicBoolean(false);
        final int[] postFailures = {0};
        final Runnable[] pollPostsRef = {null};
        Runnable scheduleNextPostPoll = () -> {
            if (pollPostsRef[0] != null) {
                scheduleActivePolling(pollPostsRef[0], retryDelayMillis(postFailures[0], 5000L, 120000L));
            }
        };
        Runnable reloadPosts = () -> {
            if (!postRequestInFlight.compareAndSet(false, true)) return;
            if (!networkAvailable) {
                postRequestInFlight.set(false);
                postFailures[0] = Math.min(postFailures[0] + 1, 8);
                scheduleNextPostPoll.run();
                return;
            }
            api.getChannelMessages(channelId, lastPostId[0], new NexusGramApiClient.Callback() {
                @Override public void onSuccess(JSONObject result) {
                    try {
                        if (dialogIsClosed[0]) return;
                        postFailures[0] = 0;
                        JSONArray messages = result.optJSONArray("messages");
                        boolean wasAtBottom = postsScroll.getChildCount() == 0
                                || postsScroll.getScrollY() + postsScroll.getHeight()
                                >= postsScroll.getChildAt(0).getHeight() - dp(48);
                        if (lastPostId[0] == 0L) postHistory.setLength(0);
                        if (messages != null) {
                            for (int i = 0; i < messages.length(); i++) {
                                JSONObject message = messages.optJSONObject(i);
                                if (message == null) continue;
                                long postId = message.optLong("id", 0L);
                                if (postId <= lastPostId[0]) continue;
                                postHistory.append("ID ").append(message.optLong("author_id", 0)).append(":\n")
                                        .append(message.optString("body", "")).append("\n\n");
                                lastPostId[0] = Math.max(lastPostId[0], postId);
                            }
                        }
                        if (postHistory.length() == 0) posts.setText("Публикаций пока нет.");
                        else posts.setText(postHistory.toString());
                        if (wasAtBottom) postsScroll.post(() -> postsScroll.fullScroll(View.FOCUS_DOWN));
                    } finally {
                        postRequestInFlight.set(false);
                        if (!dialogIsClosed[0]) scheduleNextPostPoll.run();
                    }
                }
                @Override public void onError(String message) {
                    postRequestInFlight.set(false);
                    postFailures[0] = Math.min(postFailures[0] + 1, 8);
                    if (!dialogIsClosed[0] && postHistory.length() == 0) posts.setText("Нет соединения. Повторим загрузку автоматически.");
                    if (!dialogIsClosed[0]) scheduleNextPostPoll.run();
                }
            });
        };
        refresh.setOnClickListener(v -> reloadPosts.run());
        publish.setOnClickListener(v -> {
            String body = composer.getText().toString().trim();
            if (body.isEmpty()) return;
            publish.setEnabled(false);
            api.publishToChannel(channelId, body, new NexusGramApiClient.Callback() {
                @Override public void onSuccess(JSONObject result) {
                    composer.setText("");
                    publish.setEnabled(true);
                    reloadPosts.run();
                }
                @Override public void onError(String message) {
                    publish.setEnabled(true);
                    toast(message);
                }
            });
        });
        dialog.setOnDismissListener(ignored -> {
            dialogIsClosed[0] = true;
            stopActivePolling();
        });
        dialog.show();
        reloadPosts.run();
        Runnable pollPosts = new Runnable() {
            @Override public void run() {
                if (dialogIsClosed[0] || !dialog.isShowing() || !activityResumed || isFinishing() || isDestroyed()) return;
                if (!networkAvailable) {
                    scheduleActivePolling(this, 60000L);
                    return;
                }
                reloadPosts.run();
            }
        };
        pollPostsRef[0] = pollPosts;
        startActivePolling(pollPosts);
    }

    private void renderCatalog(JSONArray gifts) {
        clearRows(catalogSection);
        if (gifts == null || gifts.length() == 0) {
            addRow(catalogSection, text("Сейчас нет доступных подарков.", 14, Color.GRAY, false));
            return;
        }
        for (int i = 0; i < gifts.length(); i++) {
            JSONObject gift = gifts.optJSONObject(i);
            if (gift == null) continue;
            long id = gift.optLong("id", 0);
            String name = gift.optString("name", "Подарок");
            long price = gift.optLong("price", 0);
            long supply = gift.optLong("supply", 0);
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            TextView details = text(name + "\n" + price + " Gram · осталось: " + supply,
                    14, Color.rgb(49, 62, 80), true);
            row.addView(details, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            Button buy = button("Купить", false);
            row.addView(buy, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(42)));
            buy.setOnClickListener(v -> confirmPurchase(id, name, price));
            addRow(catalogSection, row);
        }
    }

    private void confirmPurchase(long giftId, String name, long price) {
        new AlertDialog.Builder(this)
                .setTitle("Купить подарок")
                .setMessage(name + "\nСтоимость: " + price + " Gram. Продолжить?")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Купить", (dialog, which) -> {
                    statusView.setText("Покупаем подарок…");
                    api.purchaseGift(giftId, new NexusGramApiClient.Callback() {
                        @Override public void onSuccess(JSONObject result) {
                            JSONObject gift = result.optJSONObject("gift");
                            String serial = gift == null ? "" : gift.optString("serial_number", "");
                            toast("Подарок куплен" + (serial.isEmpty() ? "" : ": " + serial));
                            loadAll();
                        }
                        @Override public void onError(String message) {
                            statusView.setText(message);
                            toast(message);
                        }
                    });
                }).show();
    }

    private void renderInventory(JSONArray gifts) {
        clearRows(inventorySection);
        if (gifts == null || gifts.length() == 0) {
            addRow(inventorySection, text("Инвентарь пуст.", 14, Color.GRAY, false));
            return;
        }
        for (int i = 0; i < gifts.length(); i++) {
            JSONObject gift = gifts.optJSONObject(i);
            if (gift == null) continue;
            String name = gift.optString("gift_name", gift.optString("name", "Подарок"));
            String serial = gift.optString("serial_number", "");
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            TextView details = text(name + "\n" + serial, 14, Color.rgb(49, 62, 80), true);
            row.addView(details, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            Button transfer = button("Передать", false);
            row.addView(transfer, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(42)));
            transfer.setOnClickListener(v -> showTransferDialog(serial, name));
            addRow(inventorySection, row);
        }
    }

    private void showTransferDialog(String serial, String giftName) {
        EditText recipient = new EditText(this);
        recipient.setSingleLine(true);
        recipient.setHint("username или ID пользователя");
        recipient.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        int pad = dp(18);
        LinearLayout wrapper = new LinearLayout(this);
        wrapper.setPadding(pad, dp(6), pad, 0);
        wrapper.addView(recipient, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));
        new AlertDialog.Builder(this)
                .setTitle("Передать: " + giftName)
                .setMessage("Серийный номер: " + serial)
                .setView(wrapper)
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Передать", (dialog, which) -> {
                    String target = recipient.getText().toString().trim();
                    if (target.isEmpty()) {
                        toast("Укажите получателя");
                        return;
                    }
                    api.transferGift(serial, target, new NexusGramApiClient.Callback() {
                        @Override public void onSuccess(JSONObject result) {
                            toast("Подарок передан");
                            loadAll();
                        }
                        @Override public void onError(String message) {
                            statusView.setText(message);
                            toast(message);
                        }
                    });
                }).show();
    }

    private void renderHistory() {
        clearRows(historySection);
        boolean hasRows = false;
        if (giftHistoryData != null) {
            for (int i = 0; i < giftHistoryData.length(); i++) {
                JSONObject tx = giftHistoryData.optJSONObject(i);
                if (tx == null) continue;
                String event = tx.optString("event_type", "");
                String name = tx.optString("gift_name", "Подарок");
                String serial = tx.optString("serial_number", "");
                String from = tx.optString("from_username", "");
                String to = tx.optString("to_username", "");
                String direction;
                if ("purchase".equals(event)) {
                    direction = "Покупка";
                } else if (!from.isEmpty() && !to.isEmpty()) {
                    direction = "@" + from + " → @" + to;
                } else {
                    direction = "Передача";
                }
                addRow(historySection, text(direction + ": " + name + "\n" + serial,
                        13, Color.rgb(72, 84, 101), false));
                hasRows = true;
            }
        }
        if (gramHistoryData != null && gramHistoryData.length() > 0) {
            addRow(historySection, text("Изменения Gram", 14, Color.rgb(49, 62, 80), true));
            int count = Math.min(gramHistoryData.length(), 8);
            for (int i = 0; i < count; i++) {
                JSONObject tx = gramHistoryData.optJSONObject(i);
                if (tx == null) continue;
                long amount = tx.optLong("amount", 0);
                long balance = tx.optLong("balance_after", 0);
                String reason = tx.optString("reason", "Операция");
                addRow(historySection, text((amount > 0 ? "+" : "") + amount + " Gram · баланс: " + balance
                        + "\n" + reason, 12, Color.rgb(103, 115, 132), false));
                hasRows = true;
            }
        }
        if (!hasRows && giftHistoryData != null && gramHistoryData != null) {
            addRow(historySection, text("История операций пока пуста.", 14, Color.GRAY, false));
        }
    }

    private void clearRows(LinearLayout section) {
        while (section.getChildCount() > 3) section.removeViewAt(3);
    }

    private void renderEmpty(LinearLayout section, String message) {
        clearRows(section);
        addRow(section, text(message, 13, Color.rgb(155, 75, 75), false));
    }

    private void addRow(LinearLayout section, View row) {
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(10);
        section.addView(row, params);
    }

    private void startActivePolling(Runnable task) {
        stopActivePolling();
        activePollingTask = task;
        if (activityResumed) scheduleActivePolling(task, 5000L);
    }

    private void scheduleActivePolling(Runnable task, long delayMillis) {
        if (task == null || activePollingTask != task || !activityResumed
                || isFinishing() || isDestroyed()) return;
        pollingHandler.removeCallbacks(task);
        pollingHandler.postDelayed(task, Math.max(1000L, delayMillis));
    }

    private static long retryDelayMillis(int failures, long baseMillis, long maximumMillis) {
        long delay = baseMillis;
        for (int i = 0; i < failures && delay < maximumMillis; i++) {
            delay = Math.min(maximumMillis, delay * 2L);
        }
        return Math.min(delay, maximumMillis);
    }

    private void registerNetworkMonitor() {
        connectivityManager = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        networkAvailable = hasUsableNetwork();
        if (connectivityManager == null) return;
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) {
                runOnUiThread(() -> onNetworkStateChanged(true));
            }
            @Override public void onLost(Network network) {
                runOnUiThread(() -> onNetworkStateChanged(hasUsableNetwork()));
            }
            @Override public void onUnavailable() {
                runOnUiThread(() -> onNetworkStateChanged(false));
            }
        };
        try {
            if (Build.VERSION.SDK_INT >= 24) {
                connectivityManager.registerDefaultNetworkCallback(networkCallback);
            } else {
                NetworkRequest request = new NetworkRequest.Builder()
                        .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                        .build();
                connectivityManager.registerNetworkCallback(request, networkCallback);
            }
        } catch (RuntimeException ignored) {
            networkCallback = null;
            networkAvailable = hasUsableNetwork();
        }
    }

    private boolean hasUsableNetwork() {
        if (connectivityManager == null) {
            connectivityManager = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        }
        if (connectivityManager == null) return true;
        try {
            if (Build.VERSION.SDK_INT >= 23) {
                Network active = connectivityManager.getActiveNetwork();
                if (active == null) return false;
                NetworkCapabilities capabilities = connectivityManager.getNetworkCapabilities(active);
                return capabilities != null && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
            }
            android.net.NetworkInfo info = connectivityManager.getActiveNetworkInfo();
            return info != null && info.isConnected();
        } catch (SecurityException ignored) {
            return true;
        }
    }

    private void onNetworkStateChanged(boolean available) {
        networkAvailable = available;
        if (!available || !activityResumed || isFinishing() || isDestroyed()) return;
        pollingHandler.removeCallbacks(homeSyncTask);
        pollingHandler.postDelayed(homeSyncTask, 250L);
        if (api != null) api.resumePendingOperations();
        if (activePollingTask != null) scheduleActivePolling(activePollingTask, 1000L);
    }

    private void preserveRowsOrShowError(LinearLayout section, String message) {
        if (section == null) return;
        // Keep the last successfully loaded rows visible while the connection recovers.
        if (section.getChildCount() <= 3) renderEmpty(section, message);
    }

    private void stopActivePolling() {
        if (activePollingTask != null) {
            pollingHandler.removeCallbacks(activePollingTask);
            activePollingTask = null;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        activityResumed = true;
        networkAvailable = hasUsableNetwork();
        if (pendingAccountRefresh) {
            pendingAccountRefresh = false;
            loadAll();
        }
        pollingHandler.removeCallbacks(homeSyncTask);
        pollingHandler.postDelayed(homeSyncTask, 15000L);
        if (activePollingTask != null) pollingHandler.postDelayed(activePollingTask, 1000L);
        refreshSessionIfNeeded();
        pollingHandler.removeCallbacks(sessionRefreshTask);
        pollingHandler.postDelayed(sessionRefreshTask, SESSION_REFRESH_CHECK_MS);
    }

    private void refreshSessionIfNeeded() {
        if (api == null) return;
        if (!api.isSignedIn()) {
            goToLogin("Сессия WaysGram не найдена. Войдите снова.");
            return;
        }
        if (!api.shouldRefreshSession()) {
            api.resumePendingOperations();
            return;
        }
        api.refreshSession(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) { }
            @Override public void onError(String message) {
                if (api != null && !api.isSignedIn()) {
                    goToLogin("Сессия истекла. Войдите снова.");
                }
            }
        });
    }

    @Override
    protected void onPause() {
        activityResumed = false;
        pollingHandler.removeCallbacks(homeSyncTask);
        pollingHandler.removeCallbacks(sessionRefreshTask);
        if (activePollingTask != null) pollingHandler.removeCallbacks(activePollingTask);
        super.onPause();
    }

    private void logout() {
        if (api == null) return;
        statusView.setText("Завершаем сессию…");
        api.logout(new NexusGramApiClient.Callback() {
            @Override public void onSuccess(JSONObject result) { goToLogin("Вы вышли из WaysGram."); }
            @Override public void onError(String message) { goToLogin("Локальная сессия очищена."); }
        });
    }

    private void goToLogin(String message) {
        if (isFinishing()) return;
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        Intent intent = new Intent(this, WaysGramPortalActivity.class);
        intent.putExtra(WaysGramPortalActivity.EXTRA_SERVER_URL, serverUrl);
        startActivity(intent);
        finish();
    }
    private LinearLayout card() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(16), dp(16), dp(16), dp(16));
        android.graphics.drawable.GradientDrawable bg = new android.graphics.drawable.GradientDrawable();
        bg.setColor(Color.WHITE);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), Color.rgb(230, 234, 241));
        layout.setBackground(bg);
        return layout;
    }

    private TextView label(String value) { return text(value, 15, Color.rgb(42, 55, 74), true); }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setLineSpacing(dp(2), 1f);
        return view;
    }

    private Button button(String value, boolean fullWidth) {
        Button button = new Button(this);
        button.setText(value);
        button.setAllCaps(false);
        button.setTextSize(14);
        button.setTextColor(Color.WHITE);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                fullWidth ? Color.rgb(177, 65, 65) : Color.rgb(38, 113, 190)));
        return button;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams buttonParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.height = dp(48);
        return params;
    }

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void toast(String value) { Toast.makeText(this, value, Toast.LENGTH_LONG).show(); }

    @Override
    protected void onDestroy() {
        stopActivePolling();
        pollingHandler.removeCallbacks(homeSyncTask);
        pollingHandler.removeCallbacks(sessionRefreshTask);
        pollingHandler.removeCallbacksAndMessages(null);
        if (connectivityManager != null && networkCallback != null) {
            try { connectivityManager.unregisterNetworkCallback(networkCallback); }
            catch (RuntimeException ignored) { }
            networkCallback = null;
        }
        if (api != null) {
            api.close();
            api = null;
        }
        super.onDestroy();
    }
}