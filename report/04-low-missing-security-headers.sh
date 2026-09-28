#!/usr/bin/env bash
# List which browser security headers a signed-in room page response carries.
BASE=${BASE:-http://127.0.0.1:18504}
STAFF_PASSWORD=${STAFF_PASSWORD:-testpass123}
cookie=$(curl -s -D - -o /dev/null --data-urlencode "password=$STAFF_PASSWORD" "$BASE/login" |
         sed -n 's/^[Ss]et-[Cc]ookie: \(session=[^;]*\).*/\1/p')
headers=$(curl -s -D - -o /dev/null -b "$cookie" "$BASE/rooms/1")
for h in Content-Security-Policy X-Frame-Options X-Content-Type-Options Referrer-Policy Strict-Transport-Security; do
    if grep -qi "^$h:" <<<"$headers"; then echo "$h: present"; else echo "$h: missing"; fi
done
