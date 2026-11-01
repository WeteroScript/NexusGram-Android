package org.telegram.messenger;

import org.json.JSONObject;

/** Typed data objects returned by the WaysGram private API. */
public final class WaysGramModels {
    private WaysGramModels() {}

    public static final class User {
        public final long id;
        public final String username;
        public final String displayName;

        public User(JSONObject json) {
            id = json.optLong("id", 0);
            username = json.optString("username", "");
            displayName = json.optString("display_name", "");
        }
    }

    public static final class Conversation {
        public final long peerId;
        public final String username;
        public final String displayName;
        public final String lastMessage;
        public final long createdAt;

        public Conversation(JSONObject json) {
            peerId = json.optLong("id", 0);
            username = json.optString("username", "");
            displayName = json.optString("display_name", "");
            lastMessage = json.optString("last_message", "");
            createdAt = json.optLong("created_at", 0);
        }
    }

    public static final class Message {
        public final long id;
        public final long senderId;
        public final long recipientId;
        public final String body;
        public final long createdAt;

        public Message(JSONObject json) {
            id = json.optLong("id", 0);
            senderId = json.optLong("sender_id", 0);
            recipientId = json.optLong("recipient_id", 0);
            body = json.optString("body", "");
            createdAt = json.optLong("created_at", 0);
        }
    }

    public static final class Channel {
        public final long id;
        public final String username;
        public final String title;
        public final long ownerUserId;
        public final String ownerUsername;

        public Channel(JSONObject json) {
            id = json.optLong("id", 0);
            username = json.optString("username", "");
            title = json.optString("title", "");
            ownerUserId = json.optLong("owner_user_id", 0);
            ownerUsername = json.optString("owner_username", "");
        }
    }

    public static final class ChannelMessage {
        public final long id;
        public final long channelId;
        public final long authorId;
        public final String body;
        public final long createdAt;

        public ChannelMessage(JSONObject json) {
            id = json.optLong("id", 0);
            channelId = json.optLong("channel_id", 0);
            authorId = json.optLong("author_id", 0);
            body = json.optString("body", "");
            createdAt = json.optLong("created_at", 0);
        }
    }

    public static final class Gift {
        public final long id;
        public final String name;
        public final long price;
        public final long supply;

        public Gift(JSONObject json) {
            id = json.optLong("id", 0);
            name = json.optString("name", "");
            price = json.optLong("price", 0);
            supply = json.optLong("supply", 0);
        }
    }
}
