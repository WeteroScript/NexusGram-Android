package org.telegram.messenger;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Stores a WaysGram access token encrypted with a non-exportable Android Keystore key.
 * This store is separate from Telegram UserConfig and Telegram account sessions.
 */
public final class WaysGramSessionStore {
    private static final String KEY_ALIAS = "WaysGram.Session.AES.GCM.v1";
    private static final String PREFS = "waysgram_private_session";
    private static final String IV_KEY = "access_token_iv";
    private static final String TOKEN_KEY = "access_token_ciphertext";
    private static final int GCM_TAG_BITS = 128;

    private final SharedPreferences preferences;

    public WaysGramSessionStore(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("Context is required");
        }
        preferences = context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public synchronized void saveAccessToken(String token)
            throws GeneralSecurityException, IOException {
        if (token == null || token.trim().isEmpty() || token.length() > 4096) {
            throw new IllegalArgumentException("Некорректный токен WaysGram");
        }

        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] encrypted = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        boolean stored = preferences.edit()
                .putString(IV_KEY, Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                .putString(TOKEN_KEY, Base64.encodeToString(encrypted, Base64.NO_WRAP))
                .commit();
        if (!stored) {
            throw new IOException("Не удалось сохранить сессию WaysGram");
        }
    }

    public synchronized String getAccessToken() throws GeneralSecurityException, IOException {
        String ivValue = preferences.getString(IV_KEY, null);
        String tokenValue = preferences.getString(TOKEN_KEY, null);
        if (ivValue == null || tokenValue == null) {
            return null;
        }

        try {
            KeyStore keyStore = loadKeyStore();
            SecretKey key = (SecretKey) keyStore.getKey(KEY_ALIAS, null);
            if (key == null) {
                clearPreferences();
                return null;
            }
            byte[] iv = Base64.decode(ivValue, Base64.NO_WRAP);
            byte[] encrypted = Base64.decode(tokenValue, Base64.NO_WRAP);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(GCM_TAG_BITS, iv));
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IllegalArgumentException e) {
            clear();
            if (e instanceof GeneralSecurityException) {
                throw (GeneralSecurityException) e;
            }
            throw new GeneralSecurityException("Сохранённая сессия WaysGram повреждена", e);
        }
    }

    public synchronized void clear() throws GeneralSecurityException, IOException {
        clearPreferences();
        KeyStore keyStore = loadKeyStore();
        if (keyStore.containsAlias(KEY_ALIAS)) {
            keyStore.deleteEntry(KEY_ALIAS);
        }
    }

    private SecretKey getOrCreateKey() throws GeneralSecurityException {
        KeyStore keyStore = loadKeyStore();
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        }

        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        KeyGenParameterSpec spec = new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build();
        generator.init(spec);
        return generator.generateKey();
    }

    private static KeyStore loadKeyStore() throws GeneralSecurityException {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        try {
            keyStore.load(null);
        } catch (IOException e) {
            throw new GeneralSecurityException("Не удалось открыть Android Keystore", e);
        }
        return keyStore;
    }

    private void clearPreferences() throws IOException {
        if (!preferences.edit().remove(IV_KEY).remove(TOKEN_KEY).commit()) {
            throw new IOException("Не удалось удалить локальную сессию WaysGram");
        }
    }
}
