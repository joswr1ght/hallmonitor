#!/usr/bin/env bash
# Sign in, keep the session cookie, sign out, and show the kept cookie still reads room data.
BASE=${BASE:-http://127.0.0.1:18504}
STAFF_PASSWORD=${STAFF_PASSWORD:-testpass123}
cookie=$(curl -s -D - -o /dev/null --data-urlencode "password=$STAFF_PASSWORD" "$BASE/login" |
         sed -n 's/^[Ss]et-[Cc]ookie: \(session=[^;]*\).*/\1/p')
curl -s -o /dev/null -w 'before logout: %{http_code}\n' -b "$cookie" "$BASE/api/v1/rooms"
curl -s -o /dev/null -b "$cookie" "$BASE/logout"
curl -s -o /dev/null -w 'after logout, same cookie: %{http_code}\n' -b "$cookie" "$BASE/api/v1/rooms"
