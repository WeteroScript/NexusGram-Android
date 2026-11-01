NEXUSGRAM — САМОСТОЯТЕЛЬНЫЙ BACKEND
Версия API: 0.5.0

Этот backend является отдельным сервером WaysGram. Он использует собственную SQLite-базу
и собственные REST API для регистрации, профилей, личных сообщений, каналов, каталога и
инвентаря коллекционных подарков, отдельного баланса Gram, истории операций, звёзд и администрирования. Backend не использует Telegram API, Telegram DC или MTProto. Для входа он обращается только к приватному HTTPS API AuthWaysGram_bot, который выдаёт и проверяет отдельный WaysGram OTP; токен Telegram-бота в backend не хранится.

СОСТАВ АРХИВА
- server.py — HTTP API, авторизация и работа с собственной SQLite-базой; одноразовые коды запрашиваются у AuthWaysGram_bot.
- static/admin.html — веб-админ-панель (начисление Stars, управление подарками, каналами, пользователями и тестовым OTP).
- start-termux.sh — локальный тестовый запуск в Termux.
- android-integration/ — пример Java REST-клиента и инструкция по вызову собственного WaysGram API из Android-приложения.
- tests/ — end-to-end smoke test backend.
- deploy/ — примеры конфигурации reverse proxy и systemd для VDS.

1. ЛОКАЛЬНЫЙ ЗАПУСК В TERMUX
1) Установите Python: pkg install python
2) Распакуйте архив и перейдите в папку WaysGram-Backend.
3) Запустите: bash start-termux.sh
4) Скрипт попросит логин и новый пароль администратора, публичный HTTPS URL
   AuthWaysGram_bot и общий внутренний API-секрет. Пароли и ключи не сохраняются в исходниках.
5) Откройте http://127.0.0.1:8080/admin
6) Проверка состояния API: http://127.0.0.1:8080/health

В тестовом режиме код для номера из NEXUSGRAM_TEST_PHONES выводится в консоль Termux.
Это режим только для разработки. Не включайте NEXUSGRAM_DEV_OTP на публичном сервере.

2. АВТОРИЗАЦИЯ ЧЕРЕЗ AUTHWAYSGRAM_BOT
В production WaysGram не отправляет SMS и не создаёт OTP-код самостоятельно. Backend
передаёт виртуальный номер в AuthWaysGram_bot через приватный HTTPS API. Бот проверяет,
что номер закреплён за пользователем, создаёт одноразовый шестизначный код и уведомляет
пользователя в Telegram нажать кнопку «Получить код». Сам код показывается только внутри
личного чата с ботом. Backend проверяет введённый код через приватный API бота.

Переменные окружения WaysGram Backend:
NEXUSGRAM_AUTHBOT_URL=https://<публичный-домен-бота>
NEXUSGRAM_AUTHBOT_TOKEN=<тот же секрет, что INTERNAL_API_TOKEN у бота>
NEXUSGRAM_OTP_SECRET=<длинный случайный HMAC-секрет backend>
NEXUSGRAM_DEV_OTP=0                    обязательно для production

В AuthWaysGram_bot задайте BOT_TOKEN, INTERNAL_API_TOKEN и OTP_FERNET_KEY через
переменные окружения хостинга. INTERNAL_API_TOKEN и NEXUSGRAM_AUTHBOT_TOKEN должны
совпадать. OTP_FERNET_KEY используется только ботом для шифрования ожидающих кодов
в его SQLite-базе. Не размещайте эти секреты в GitHub или Android-клиенте.

Виртуальные номера имеют формат +1 и десять цифр. Они генерируются ботом, являются
внутренними идентификаторами WaysGram и не принимают обычные звонки или SMS.
Вход разрешается только для номера, который бот уже выдал пользователю и для которого
пройдена CAPTCHA. Коды сторонних сервисов и Telegram не запрашиваются и не пересылаются.

3. СОБСТВЕННАЯ БАЗА И VDS
По умолчанию используется файл waysgram.db рядом с server.py. Для VDS задайте отдельный
путь, например NEXUSGRAM_DB=/var/lib/nexusgram/waysgram.db. SQLite включена в комплект
Python и не требует отдельного сервиса базы данных. Для резервного копирования остановите
сервер или используйте SQLite backup API; не копируйте WAL-базу как одиночный файл во
время активной записи.

Пример переменных окружения VDS:
NEXUSGRAM_HOST=127.0.0.1
NEXUSGRAM_PORT=8080
NEXUSGRAM_DB=/var/lib/nexusgram/waysgram.db
NEXUSGRAM_ADMIN_USER=owner
NEXUSGRAM_ADMIN_PASSWORD=<длинный уникальный пароль>
NEXUSGRAM_TRUST_PROXY_HEADERS=1  только если API доступен исключительно через локальный Caddy reverse proxy
NEXUSGRAM_DEV_OTP=0
NEXUSGRAM_AUTHBOT_URL=https://<публичный-домен-бота>
NEXUSGRAM_AUTHBOT_TOKEN=<внутренний API-секрет бота>
NEXUSGRAM_OTP_SECRET=<отдельный случайный секрет>

Запускайте API за HTTPS reverse proxy. В архиве есть примеры Caddy и systemd в deploy/.
Если используется именно локальный Caddy из примера, задайте NEXUSGRAM_TRUST_PROXY_HEADERS=1:
сервер будет принимать X-Forwarded-For только от loopback-подключения. Caddy в примере
перезаписывает заголовок адресом реального TCP-клиента. Не включайте этот параметр, если
порт API доступен напрямую или перед приложением есть другой, не проверенный proxy.
Не выставляйте тестовый HTTP-порт 8080 напрямую в интернет. Секреты храните в защищённом
EnvironmentFile или менеджере секретов, а не в Git и не в Android-клиенте.

4. АДМИНИСТРИРОВАНИЕ И ВАЛЮТЫ
- Stars и Gram — раздельные балансы. Существующие Stars не конвертируются в Gram.
- Gram начисляются администратором через POST /api/admin/grams; операция попадает в журнал.
- Каталог подарков управляется администратором: название, цена в Gram и supply.
- Покупка списывает Gram, уменьшает supply и создаёт уникальный экземпляр подарка в одной
  транзакции SQLite. Баланс не может уйти ниже нуля.
- Передача принадлежавшего пользователю экземпляра выполняется по серийному номеру и
  @username/ID получателя. Передача записывается в историю, повторная передача бывшим
  владельцем отклоняется.
- Каналы — создание, назначение владельца, просмотр, изменение username/названия и удаление.
- Пользователи — поиск по ID/username, бан/разбан и отзыв сессий при блокировке.
- Тестовый код — только для allowlist в локальном dev-режиме.

Подарки в этой версии — внутренние коллекционные объекты WaysGram. Они не являются NFT,
не записаны в блокчейн и не представляют денежную стоимость или внешний актив.

5. ОСНОВНЫЕ REST API
GET    /health
GET    /api/config
POST   /api/auth/request-code          {"phone":"+1XXXXXXXXXX"}
POST   /api/auth/verify-code           {"phone":"+1XXXXXXXXXX","code":"123456"}
POST   /api/auth/refresh                Bearer token — продление действующей сессии
POST   /api/auth/logout                Bearer token
GET    /api/me                         Bearer token (включая Stars и Gram)
GET    /api/me/wallet                  балансы Stars и Gram
GET    /api/me/wallet/transactions     история Gram
GET    /api/me/gifts                   инвентарь текущего пользователя
GET    /api/me/gifts/transactions      история покупок/передач
PATCH  /api/me                         {"username":"...","display_name":"..."}
GET    /api/users?q=<username>         Bearer token
GET    /api/users/<id>                 Bearer token
GET    /api/messages?with=<user_id>[&after_id=<id>] Bearer token; after_id — только новые сообщения
GET    /api/conversations              последние диалоги Bearer token
POST   /api/messages                   {"recipient_id":1,"body":"..."}; optional Idempotency-Key header
GET    /api/gifts                      каталог; price указывается в Gram
POST   /api/gifts/<id>/purchase        покупка за Gram, выдаёт WG-серийный номер; optional Idempotency-Key
POST   /api/gifts/transfer             {"serial_number":"WG-...","recipient":"username|id"}; optional Idempotency-Key
GET    /api/channels                   Bearer token
GET    /api/channels/<id>              Bearer token
GET    /api/channels/<id>/messages[?after_id=<id>] Bearer token; after_id — только новые публикации
POST   /api/channels/<id>/messages     публикация владельцем канала; optional Idempotency-Key
POST   /api/admin/login
POST   /api/admin/logout               Bearer admin token
GET    /api/admin/users?q=<id|username>
POST   /api/admin/stars                отдельное начисление Stars
GET    /api/admin/stars/history
POST   /api/admin/grams                начисление Gram и запись в журнал
GET    /api/admin/grams/history
GET/POST /api/admin/gifts
PATCH/DELETE /api/admin/gifts/<id>
GET/POST /api/admin/channels
PATCH/DELETE /api/admin/channels/<id>
POST   /api/admin/ban
POST   /api/admin/dev-code             только allowlisted test phone
GET    /api/admin/overview            статистика backend

ПРОВЕРКА BACKEND
Для локального end-to-end smoke test: python tests/smoke_test.py. Скрипт поднимает временный
сервер, базу и поддельный AuthWaysGram_bot API, проверяет выдачу и одноразовую проверку кодов,
лимиты неверных попыток, авторизацию пользователей, инкрементальную загрузку сообщений/публикаций, лимиты отправки, каналы, Gram-баланс,
покупку, инвентарь и передачу подарков, журнал операций, безопасный повтор записывающих запросов,
конкурентные повторы сообщений/покупок, звёзды, блокировку и выход администратора.
Реальный Telegram-бот и реальные SMS не используются.

6. АВТОРИЗАЦИЯ И ЗАЩИТА
- Код действует 5 минут; после 5 неверных попыток требуется новый код.
- Ограничение: повторная отправка не чаще 30 секунд, до 5 запросов на номер и 15 запросов
  с IP за час.
- В production сам OTP хранится только в AuthWaysGram_bot в зашифрованном виде; WaysGram Backend хранит HMAC-хеш маркера запроса и метаданные срока действия. Локальные тестовые OTP также хранятся в backend как HMAC-хеш. Для VDS задайте отдельный NEXUSGRAM_OTP_SECRET и храните его отдельно от файла базы.
- Пользовательские и административные сессии хранятся в базе в хешированном виде.
- Активную пользовательскую сессию можно продлить через `POST /api/auth/refresh` ещё на 30 дней; клиент вызывает маршрут не чаще одного раза за 6 часов в foreground. Истёкшая/отозванная сессия не восстанавливается этим маршрутом и требует повторной проверки OTP.
- Бан отзывает активные пользовательские сессии.
- Входящие сообщения и публикации ограничены 4 000 символами.
- Ограничение отправки: до 30 личных сообщений и 20 публикаций на пользователя за минуту; счётчики проверяются атомарно.
- Для POST `/api/messages`, `/api/channels/<id>/messages`, `/api/gifts/<id>/purchase` и `/api/gifts/transfer` поддерживается заголовок `Idempotency-Key` (16–128 символов `[A-Za-z0-9._:-]`). Ключ привязан к пользователю, маршруту и точному телу запроса. Повтор с тем же ключом и телом возвращает сохранённый HTTP-результат; повтор ключа с другим телом получает HTTP 409. Результаты хранятся 7 дней.
- Админ-пароль, внутренние API-ключи и OTP secret не должны попадать в исходники или Android-клиент.

7. ANDROID ИНТЕГРАЦИЯ
В папке android-integration/ находится Java REST-клиент NexusGramApiClient.java.
Его рабочая копия добавлена в Android Gradle source tree:
TMessagesProj/src/main/java/app/nexusgram/network/NexusGramApiClient.java.
Клиент обращается только к собственному WaysGram REST API и не содержит Telegram DC,
MTProto или Telegram API. Он поддерживает проверку health/config, вход по виртуальному
+1 ID и WaysGram-коду, профиль, поиск пользователей, диалоги, личные сообщения, каталог
подарков, Gram-кошелёк, инвентарь, покупку и передачу подарков, историю операций и каналы.
Сессионный токен шифруется AES-GCM ключом Android Keystore; старый открытый токен из SharedPreferences переносится и удаляется.

Порядок входа: пользователь получает виртуальный +1 идентификатор в AuthWaysGram_bot,
вводит его в WaysGram и запрашивает код через REST API. Бот уведомляет, что код готов;
пользователь нажимает «Получить код» в боте и вводит его в WaysGram. Backend проверяет код
через AuthWaysGram_bot и создаёт аккаунт/сессию в собственной SQLite-базе WaysGram.

ВАЖНО: в исходный LoginActivity добавлена кнопка «Войти через WaysGram», которая открывает
WaysGramPortalActivity. После проверки кода пользователь попадает в WaysGramHomeActivity с
профилем, балансами Stars/Gram, поиском пользователей, личными диалогами, каналами, каталогом,
покупкой, инвентарём и передачей подарков. Эта
WaysGram-сессия отдельна от Telegram MTProto: оригинальный Telegram sign-in и его сетевой слой
остаются неизменными. Поэтому текущее приложение ещё не является полностью самостоятельным
WaysGram-мессенджером.

Версия backend — 0.5.0. Он поддерживает отдельные Stars и Gram-балансы. Gram можно начислить через
админ API и потратить на внутренние коллекционные подарки. Подарки имеют уникальные WG-серийные
номера, инвентарь и историю передач. Эти объекты не являются блокчейн-NFT или денежными активами.
Пользовательский перевод Stars не реализован.

Для production нужен публичный HTTPS URL WaysGram Backend. Секреты AuthBot, админ-пароль,
внутренний API-ключ и OTP-ключ не должны помещаться в APK. Android-клиент не подключается
к SQLite напрямую. Полная миграция приложения требует последовательной замены MTProto,
обновлений, контактов, media, push и звонков на собственные WaysGram-сервисы, сохраняя
существующий Telegram-подобный интерфейс.

## Android-клиент v10 — восстановление очереди

- Каждая новая отправка/покупка/передача получает отдельный UUID и независимую зашифрованную запись. Два отдельных одинаковых сообщения больше не объединяются по hash маршрута и тела.
- Очередь имеет монотонный порядок создания; восстановление выполняется последовательно.
- Сохранённая операция повторяется с исходным `Idempotency-Key`; после возврата сети и после возвращения приложения в foreground очередь проверяется повторно.
- Записи v9 без sequence совместимы и сортируются по времени создания.
- Сборка APK v10 требует Android SDK 36, NDK 27.2.12479018, CMake 3.22.1 и Gradle 8.13.