# NexusGram

NexusGram — Android-мессенджер с отдельным клиентом и собственной серверной инфраструктурой.

## Состав проекта

В репозитории сохранён исходный Telegram-derived Android-клиент и его прежняя сборка. Дополнительно в этой ветке добавлен самостоятельный вариант NexusGram:

- Android-клиент с собственным интерфейсом и REST API.
- Python backend с SQLite.
- Панель администратора для управления пользователями, Stars, подарками и каналами.
- Тесты API и примеры конфигурации для Termux/VDS.

Полный самостоятельный комплект хранится в `release/` в виде сегментированного tar.xz-архива. Инструкция по восстановлению: [NEXUSGRAM_SOURCE_BUNDLE_RU.md](NEXUSGRAM_SOURCE_BUNDLE_RU.md).

## Сборка

Есть два независимых workflow:

- `NexusGram Android APK` — прежняя Telegram-derived сборка. Она использует архивные части `nexusgram.part01`–`nexusgram.part09` и требует Firebase secret `GOOGLE_SERVICES_JSON_BASE64`.
- `NexusGram Standalone Android APK` — восстанавливает самостоятельный исходный комплект, прогоняет backend smoke-тесты и собирает APK без Telegram SDK, Firebase и MTProto.

Для запуска открой **Actions**, выбери нужный workflow и нажми **Run workflow**. Самостоятельный APK загружается как artifact `NexusGram-Standalone-APK`. Это debug-сборка для тестирования, не релиз для Google Play.

## Backend и production

Самостоятельный backend рассчитан на запуск в Termux для тестирования и на последующее развёртывание на VDS. Для публичного использования необходимо настроить HTTPS, production SMS-провайдера, секреты окружения и отключить тестовый OTP-режим. SQLite должна оставаться на сервере и не должна публиковаться напрямую.

Smoke-тесты проверяют основные API-сценарии на временной базе данных. Успешный smoke-тест не заменяет аудит безопасности и production-нагрузочное тестирование.

## Лицензирование

Перед распространением сборок на основе Telegram-derived исходников необходимо проверить лицензии Telegram и всех используемых компонентов.
