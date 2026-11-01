package app.nexusgram.network;

import org.json.JSONArray;
import org.json.JSONObject;
import org.telegram.tgnet.TLRPC;

import java.util.ArrayList;

/**
 * Converts the text-only WaysGram REST contract into Telegram's existing
 * in-memory TL models so native DialogsActivity and ChatActivity can render it.
 *
 * This mapper does not implement MTProto or Telegram media types.
 */
public final class WaysGramDataMapper {
    private WaysGramDataMapper() {
    }

    public static TLRPC.TL_user user(JSONObject source, boolean self) {
        if (source == null) {
            return null;
        }
        long id = source.optLong("id", 0);
        if (id <= 0) {
            return null;
        }

        TLRPC.TL_user result = new TLRPC.TL_user();
        result.id = id;
        result.first_name = cleanName(source.optString("display_name", ""));
        if (result.first_name.isEmpty()) {
            result.first_name = cleanName(source.optString("username", ""));
        }
        if (result.first_name.isEmpty()) {
            result.first_name = "WaysGram user";
        }
        result.last_name = "";
        String username = source.optString("username", "");
        result.username = username.isEmpty() ? null : username;
        String phone = source.optString("phone", "");
        result.phone = phone.isEmpty() ? null : phone;
        result.self = self;
        result.contact = !self;
        result.flags = (1 << 1) | (1 << 2) | (self ? (1 << 10) : (1 << 11));
        if (result.username != null) {
            result.flags |= 1 << 3;
        }
        if (result.phone != null) {
            result.flags |= 1 << 4;
        }
        return result;
    }

    public static TLRPC.TL_message message(
            JSONObject source,
            long selfId,
            long peerId
    ) {
        if (source == null || selfId <= 0 || peerId <= 0) {
            return null;
        }
        long rawId = source.optLong("id", 0);
        long senderId = source.optLong("sender_id", 0);
        long recipientId = source.optLong("recipient_id", 0);
        if (rawId <= 0 || rawId > Integer.MAX_VALUE || senderId <= 0
                || recipientId <= 0 || (senderId != selfId && recipientId != selfId)) {
            return null;
        }

        TLRPC.TL_message result = new TLRPC.TL_message();
        result.id = (int) rawId;
        result.out = senderId == selfId;
        result.unread = false;
        result.flags = 1 << 8; // from_id is present
        if (result.out) {
            result.flags |= 1 << 1;
        }
        result.flags2 = 0;

        TLRPC.TL_peerUser from = new TLRPC.TL_peerUser();
        from.user_id = senderId;
        result.from_id = from;

        TLRPC.TL_peerUser peer = new TLRPC.TL_peerUser();
        peer.user_id = peerId;
        result.peer_id = peer;

        long timestamp = source.optLong("created_at", 0);
        result.date = (int) Math.max(0, Math.min(timestamp, Integer.MAX_VALUE));
        result.message = source.optString("body", "");
        result.media = new TLRPC.TL_messageMediaEmpty();
        result.dialog_id = peerId;
        return result;
    }

    public static TLRPC.TL_messages_dialogsSlice dialogs(
            JSONObject response,
            long selfId,
            TLRPC.User selfUser
    ) {
        TLRPC.TL_messages_dialogsSlice result = new TLRPC.TL_messages_dialogsSlice();
        JSONArray rows = response == null ? null : response.optJSONArray("conversations");
        if (rows == null || selfId <= 0) {
            return result;
        }

        result.count = rows.length();
        if (selfUser != null) {
            result.users.add(selfUser);
        }

        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null) {
                continue;
            }
            long peerId = row.optLong("id", 0);
            if (peerId <= 0 || peerId == selfId) {
                continue;
            }

            TLRPC.TL_user peerUser = user(row, false);
            if (peerUser == null) {
                continue;
            }

            long senderId = row.optLong("last_sender_id", peerId);
            long messageId = row.optLong("last_message_id", 0);
            if (messageId <= 0 || messageId > Integer.MAX_VALUE) {
                continue;
            }

            JSONObject messageJson = new JSONObject();
            put(messageJson, "id", messageId);
            put(messageJson, "sender_id", senderId);
            put(messageJson, "recipient_id", senderId == selfId ? peerId : selfId);
            put(messageJson, "body", row.optString("last_message", ""));
            put(messageJson, "created_at", row.optLong("created_at", 0));
            TLRPC.TL_message lastMessage = message(messageJson, selfId, peerId);
            if (lastMessage == null) {
                continue;
            }

            TLRPC.TL_dialog dialog = new TLRPC.TL_dialog();
            TLRPC.TL_peerUser peer = new TLRPC.TL_peerUser();
            peer.user_id = peerId;
            dialog.peer = peer;
            dialog.top_message = lastMessage.id;
            dialog.read_inbox_max_id = lastMessage.id;
            dialog.read_outbox_max_id = lastMessage.id;
            dialog.unread_count = 0;
            dialog.notify_settings = new TLRPC.TL_peerNotifySettings();
            dialog.last_message_date = lastMessage.date;
            DialogObject.initDialog(dialog);

            result.dialogs.add(dialog);
            result.messages.add(lastMessage);
            result.users.add(peerUser);
        }
        return result;
    }

    public static TLRPC.TL_messages_messagesSlice messages(
            JSONObject response,
            long selfId,
            long peerId,
            TLRPC.User selfUser,
            TLRPC.User peerUser
    ) {
        TLRPC.TL_messages_messagesSlice result = new TLRPC.TL_messages_messagesSlice();
        JSONArray rows = response == null ? null : response.optJSONArray("messages");
        if (rows == null || selfId <= 0 || peerId <= 0) {
            return result;
        }
        result.count = response.optInt("count", rows.length());
        if (selfUser != null) {
            result.users.add(selfUser);
        }
        if (peerUser != null && peerUser.id != selfId) {
            result.users.add(peerUser);
        }
        for (int i = 0; i < rows.length(); i++) {
            TLRPC.TL_message item = message(rows.optJSONObject(i), selfId, peerId);
            if (item != null) {
                result.messages.add(item);
            }
        }
        return result;
    }

    private static String cleanName(String value) {
        return value == null ? "" : value.trim();
    }

    private static void put(JSONObject object, String key, Object value) {
        try {
            object.put(key, value);
        } catch (Exception ignored) {
        }
    }
}
