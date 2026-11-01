# Android REST integration

`NexusGramApiClient.java` is included twice in the source bundle:

- standalone example: `WaysGram-Backend/android-integration/src/main/java/app/nexusgram/network/NexusGramApiClient.java`
- Android application source: `TMessagesProj/src/main/java/app/nexusgram/network/NexusGramApiClient.java`

The application copy is part of the `TMessagesProj` Android library source set. It can therefore be compiled with the Android project; it is not just an unattached example file.

## Client contract

The client communicates only with the WaysGram REST base URL. It does not contain Telegram DC addresses, Telegram API credentials, MTProto transport, or Telegram login methods.

Implemented calls:

- `checkHealth()` — `GET /health`
- `getApiConfig()` — `GET /api/config`
- `requestCode(phone)` and `verifyCode(phone, code)` — WaysGram authentication through AuthWaysGram_bot
- `getMe()`, `refreshSession()` and `updateProfile(...)`
- `searchUsers(...)` and `getUser(id)`
- `getConversations()`, `getMessages(peerId)`, `getMessages(peerId, afterMessageId, ...)`, and `sendMessage(...)`
- `getGifts()` — gift catalogue; prices are denominated in Gram
- `getWallet()` and `getGramTransactions()` — separate Stars/Gram balances and Gram ledger
- `getMyGifts()` and `getGiftTransactions()` — collectible inventory and transfer history
- `purchaseGift(giftId)` — atomic Gram purchase and serial issuance
- `transferGift(serialNumber, recipient)` — transfer by serial to username or numeric user ID
- `getChannels()`, `getChannel(id)`, `getChannelMessages(id)`, `getChannelMessages(id, afterMessageId, ...)`, and `publishToChannel(...)`
- `getStarsBalance()` — reads the current `stars` field from `/api/me`
- `logout(...)`

The access token is encrypted with AES-GCM using a key held by Android Keystore. A legacy token in plain SharedPreferences is migrated once and removed. The client requires HTTPS except for loopback/local development URLs (`127.0.0.1`, `localhost`, `::1`, or Android emulator host `10.0.2.2`). It limits response bodies to 1 MiB. Any authenticated HTTP 401 clears only the expired credentials, preserves v9 pending operations, and notifies the foreground account screen so it can return to the existing login portal. Explicit logout is handled separately and cancels the queue.

The app stores the stable server-side user ID after `verifyCode()`/`getMe()`. Server state remains authoritative: after any new login the client reloads profile, wallet, gifts, conversation lists and channels from the backend. It does not restore a different account's state merely because an old token existed on the device.

`POST /api/auth/refresh` extends an unexpired session by 30 days. The app checks on resume and, while the WaysGram screen remains active, refreshes at most once every six hours. An expired or revoked session cannot be refreshed and returns HTTP 401; the existing login portal remains available for a new OTP login.

## Incremental message updates

The backend accepts an optional `after_id` cursor on direct-message and channel-message reads. A zero/missing cursor returns the latest 100 records; a positive cursor returns up to 100 newer records in ascending ID order. The app polls an open conversation or channel every five seconds while the screen is in the foreground, appends only new records, and stops polling when the dialog closes or the activity pauses. Existing manual refresh controls remain available. Polling is foreground-only; there is no WebSocket, push delivery, or background service.

The backend enforces atomic per-user limits of 30 direct messages and 20 channel posts per minute. Both message types are limited to 4,000 characters.

## Network recovery and duplicate-safe writes

The Android client monitors `ConnectivityManager` while the account activity exists. When the network is lost, polling pauses rather than repeatedly opening failed HTTP connections. When a network becomes available, list and active conversation/channel sync are scheduled immediately. If requests continue to fail while a network route exists, foreground polling uses exponential backoff: 5 seconds up to a 120-second cap for an open conversation/channel, and 15 seconds up to a 120-second cap for the conversation/channel lists. A successful response resets the delay. Polling still stops on `onPause()` and when the dialog closes; the screen layout and controls are unchanged.

For message send, channel publish, gift purchase and gift transfer, the v9 client stores the complete pending operation and its generated `Idempotency-Key` in app-private preferences encrypted with Android Keystore (AES-GCM). The queue is limited to 100 operations and retains an operation for at most six days, shorter than the backend's seven-day idempotency window. A retry after a timeout, process death, connection reset or session expiry reuses the same key. The backend records the result in the same SQLite transaction as the write and replays that result for the same user, route and body.

After the same account signs in again, or a successful `/api/me`/session refresh confirms the account ID, the client replays that account's queued operations sequentially. Operations belonging to a different account are not sent. Network failures, HTTP 401, 429 and server errors leave the operation queued; successful responses and definitive non-retryable 4xx responses remove it. Explicit logout cancels the local pending queue. Replay occurs only while the app has a valid foreground session; it is not a background service. v8 stored only opaque idempotency keys, not request bodies, so an unresolved v8 request cannot be reconstructed automatically after an app update and session rotation; v9 persists full operations going forward.

## Setup

1. Configure the public HTTPS URL of WaysGram Backend in app configuration. Do not put bot secrets, internal API secrets, or admin credentials in the APK.
2. Construct `new NexusGramApiClient(context, serverBaseUrl)` from an application-scoped component.
3. Request a code after the user has received their virtual `+1XXXXXXXXXX` identifier in `AuthWaysGram_bot`.
4. Submit the six-digit WaysGram code. On success the client securely stores the returned WaysGram bearer token.
5. Use the authenticated API methods and call `close()` when the owning component is destroyed. The WaysGram account screen checks the current session on resume and reloads account data from the backend after login.

For local development on the same Android device, `http://127.0.0.1:8080` is accepted. For an Android emulator, `http://10.0.2.2:8080` is accepted. Production must use HTTPS.

## Current backend scope

The backend exposes separate Stars and Gram balances. Admins can credit Gram; users can spend Gram on internal collectible gifts, view their inventory and transfer an owned serial-numbered gift. These collectibles are internal WaysGram records, not blockchain NFTs or cash-equivalent assets. User-to-user Stars transfers are not implemented. The Android REST client exposes methods for the implemented Gram and gift operations.

## Android UI integration and migration boundary

The Android source tree now contains two app-internal screens:

- `app.nexusgram.ui.WaysGramPortalActivity` — server URL setup, virtual WaysGram ID entry, code request, and six-digit code verification.
- `app.nexusgram.ui.WaysGramHomeActivity` — account summary, Stars/Gram balances, user search, direct-message conversations, channel list/publications, gift catalogue, Gram purchase, inventory, serial-number transfer, and operation history.

A **Войти через WaysGram** entry point opens the portal from the existing login screen. The new activities are registered as non-exported in the app manifest. The WaysGram token remains encrypted by the Android Keystore-backed REST client.

This is an additional WaysGram account portal, not a full migration of the Telegram-derived messenger. The original Telegram MTProto sign-in and Telegram messaging stack remain unchanged. WaysGram REST profiles, DMs, channels, wallet, and gifts are available through the separate WaysGram account screens; the Telegram chat list and MTProto account state do not automatically become WaysGram data. A full replacement still requires porting the main chat, contacts, media, push, and call layers to WaysGram REST/WebSocket implementations. Do not describe the app as a complete standalone WaysGram messenger until that work is done.

## AuthWaysGram bot login flow

1. The user opens `AuthWaysGram_bot`, chooses Russian or English, and passes the emoji CAPTCHA.
2. The user taps **Get number**. The bot allocates and stores a unique virtual WaysGram identifier in `+1` plus ten digits format.
3. The user enters that identifier in WaysGram and requests a code.
4. WaysGram Backend asks AuthWaysGram_bot to generate a one-time WaysGram code. The bot notifies the user that a code is ready.
5. The user taps **Get code** in the bot and enters that code in WaysGram.
6. The WaysGram backend verifies the code with the bot and creates the WaysGram account/session in its own SQLite database.

These `+1` identifiers are internal WaysGram IDs, not carrier-issued phone numbers; they cannot receive calls or SMS. The bot does not request or forward Telegram or third-party login codes.
После восстановления одной или нескольких отложенных операций Android повторно запрашивает актуальные данные аккаунта с backend. Это не добавляет новых элементов интерфейса.

## v10 queue semantics

Each new call that creates a write (DM, channel post, gift purchase or transfer) receives its own UUID and durable encrypted record. Payload equality is not treated as operation identity, so separate identical actions remain separate. A retry of an already-persisted record keeps its original idempotency key. Records carry a monotonic sequence number and replay in creation order. The queue is retried when the home screen resumes and when connectivity returns. Existing v9 encrypted records without a sequence field remain readable and use their creation timestamp as an ordering fallback.