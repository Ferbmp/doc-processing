#!/usr/bin/env bash
set -euo pipefail

python manage.py wait_for_db

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] applying migrations"
  python manage.py migrate --noinput
else
  # Workers must not race the API's migrate, but they also must not start
  # querying tables that do not exist yet.
  python manage.py wait_for_migrations
fi

exec "$@"
