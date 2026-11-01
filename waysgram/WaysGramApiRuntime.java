package app.nexusgram.network;

import android.content.Context;
import android.util.Log;

/**
 * Process-wide owner of the WaysGram REST client.
 *
 * Screens must obtain the same instance from this class so that the encrypted
 * session token and request executor are shared across the native Telegram UI.
 */
public final class WaysGramApiRuntime {
    private static final String TAG = "WaysGramApiRuntime";
    private static final Object LOCK = new Object();

    private static volatile NexusGramApiClient client;
    private static volatile String configurationError = "";

    private WaysGramApiRuntime() {
    }

    public static void initialize(Context context) {
        if (context == null || client != null) {
            return;
        }
        synchronized (LOCK) {
            if (client != null) {
                return;
            }
            String baseUrl = WaysGramApiConfig.getBaseUrl(context);
            if (baseUrl == null || baseUrl.trim().isEmpty()) {
                configurationError = "WAYSGRAM_API_BASE_URL is not configured in this build";
                return;
            }
            try {
                client = new NexusGramApiClient(context.getApplicationContext(), baseUrl);
                configurationError = "";
            } catch (RuntimeException error) {
                configurationError = error.getMessage() == null
                        ? "Invalid WaysGram API configuration"
                        : error.getMessage();
                Log.e(TAG, "Could not initialize WaysGram REST client", error);
            }
        }
    }

    /** Returns the process-wide client, or null when this build has no API URL. */
    public static NexusGramApiClient getClient() {
        return client;
    }

    public static boolean isConfigured() {
        return client != null;
    }

    public static boolean isSignedIn() {
        NexusGramApiClient current = client;
        return current != null && current.isSignedIn();
    }

    public static String getConfigurationError() {
        return configurationError;
    }
}
