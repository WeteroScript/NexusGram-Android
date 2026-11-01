# WaysGram

WaysGram is a rebranded build of the original Android client with the original UI and navigation preserved.

## Current branch state

- The standalone second launcher and standalone MainActivity are not included in the WaysGram APK build.
- The original LoginActivity, LaunchActivity, SettingsActivity and existing screens are retained.
- The visible app name is changed to WaysGram in localized resources.
- The WaysGram backend source is included in the source archive and can be deployed separately to a VDS.
- A dedicated **Админ-панель WaysGram** entry is injected into the original Settings screen immediately below the language row; the existing layout and other screens remain intact.
- The native entry opens the VDS-hosted `/admin` panel over HTTPS. The panel uses the backend's actual `/api/admin/*` routes.
- The admin web panel supports Stars, gift catalog CRUD, channel CRUD, user lookup and ban/unban. Test OTP creation remains restricted to an explicitly configured allowlist on the VDS.

## Important integration status

This branch is a UI-preserving rebrand and source packaging step. It is **not yet a completed migration of Telegram's MTProto services to the WaysGram VDS**. The existing original login, message transport and other Telegram-backed functions still require a separate, feature-by-feature migration to the WaysGram API before user data can be considered VDS-only.

The bot must not relay arbitrary third-party SMS verification codes. A safe WaysGram login flow can issue its own one-time login code to a Telegram account explicitly linked and verified by the user.

The admin password must be configured on the VDS as an environment secret; it must not be committed to this public repository or embedded in the APK.

## Build outputs

GitHub Actions workflow **WaysGram Android APK** builds:
- `WaysGram-APK` — original Android client, with original UI preserved and product name changed.
- `WaysGram-Source-ZIP` — restored Android source tree plus the WaysGram backend source.

These are source/build artifacts, not proof that all app services have already been migrated to the VDS.
