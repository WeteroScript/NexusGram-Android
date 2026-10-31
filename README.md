# NexusGram

NexusGram — Android-мессенджер с Telegram-derived клиентом и отдельным собственным REST backend.

## Состав проекта

- Существующий Telegram-derived Android-клиент и его прежняя сборка сохраняются.
- Самостоятельный Android-клиент NexusGram использует REST API и SQLite-backend.
- Backend содержит авторизацию по SMS-коду, профили, личные сообщения, каналы, каталог подарков, Stars и административную панель.
- Исходный комплект v3 находится в `release/` в виде сегментированного tar.xz-архива. Инструкция: [NEXUSGRAM_SOURCE_BUNDLE_RU.md](NEXUSGRAM_SOURCE_BUNDLE_RU.md).

## Интеграция Android-клиента

Workflow `NexusGram Android APK` восстанавливает существующий Telegram-derived проект и добавляет в его APK самостоятельную Activity:

- оригинальная Activity остаётся основной;
- появляется дополнительный значок запуска **NexusGram Independent**;
- новая Activity использует отдельный REST API-клиент и не заменяет Telegram/MTProto-часть;
- backend подключается по адресу, указанному на экране входа.

Это интеграция двух интерфейсов в один APK, но не миграция Telegram-аккаунтов, истории Telegram-чатов или MTProto на новый backend. Учётные записи и сообщения NexusGram создаются отдельно.

## Сборка

В GitHub Actions доступны два workflow:

- `NexusGram Android APK` — собирает основной Telegram-derived APK и добавляет в него самостоятельный REST-клиент как второй экран запуска. Артефакт: `NexusGram-APK`.
- `NexusGram Standalone Android APK` — собирает самостоятельный APK без Telegram SDK/MTProto. Артефакт: `NexusGram-Standalone-APK`.

Оба APK являются тестовыми сборками. Перед публикацией необходимо провести аудит безопасности, проверить лицензии используемых компонентов и подготовить production-подпись.

## Backend и production

Backend запускается в Termux для локального тестирования или на VDS. Android-клиент обращается к нему через HTTPS; SQLite остаётся на сервере и не публикуется напрямую.

Для production необходимо настроить HTTPS, сильные секреты окружения, production SMS-провайдера и отключить тестовый OTP-режим. Smoke-тесты проверяют API на временной базе данных, но не заменяют аудит безопасности, нагрузочные тесты и проверку восстановления резервных копий.

## Лицензирование

Перед распространением APK на базе Telegram-derived исходников необходимо проверить лицензии Telegram и всех используемых компонентов.
