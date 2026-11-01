#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

printf 'Логин администратора [owner]: '
read -r ADMIN_LOGIN
ADMIN_LOGIN=${ADMIN_LOGIN:-owner}
read -r -s -p 'Новый пароль администратора: ' ADMIN_SECRET
printf '\n'
if [[ ${#ADMIN_SECRET} -lt 14 ]]; then
  echo 'Пароль должен содержать минимум 14 символов.' >&2
  exit 1
fi

printf 'Публичный HTTPS URL AuthWaysGram_bot: '
read -r AUTHBOT_URL
if [[ ! "$AUTHBOT_URL" =~ ^https:// ]]; then
  echo 'AuthWaysGram_bot должен быть доступен через HTTPS.' >&2
  exit 1
fi
read -r -s -p 'Внутренний API-секрет (должен совпадать с INTERNAL_API_TOKEN у бота, минимум 32 символа): ' AUTHBOT_SECRET
printf '\n'
if [[ ${#AUTHBOT_SECRET} -lt 32 ]]; then
  echo 'Внутренний API-секрет должен содержать минимум 32 символа.' >&2
  exit 1
fi

export NEXUSGRAM_HOST=127.0.0.1
export NEXUSGRAM_PORT=8080
export NEXUSGRAM_ADMIN_USER="$ADMIN_LOGIN"
export NEXUSGRAM_ADMIN_PASSWORD="$ADMIN_SECRET"
export NEXUSGRAM_AUTHBOT_URL="$AUTHBOT_URL"
export NEXUSGRAM_AUTHBOT_TOKEN="$AUTHBOT_SECRET"
export NEXUSGRAM_DEV_OTP=0
export NEXUSGRAM_TRUST_PROXY_HEADERS=0
unset ADMIN_SECRET AUTHBOT_SECRET

printf '\nЗапуск WaysGram. Откройте http://127.0.0.1:8080/admin\n'
python server.py