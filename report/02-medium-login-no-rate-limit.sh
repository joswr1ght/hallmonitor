#!/usr/bin/env bash
# Send 200 wrong staff passwords, then the right one, and show nothing slowed or blocked the login.
BASE=${BASE:-http://127.0.0.1:18504}
STAFF_PASSWORD=${STAFF_PASSWORD:-testpass123}
SECONDS=0
codes=$(for i in $(seq 1 200); do curl -s -o /dev/null -w '%{http_code}\n' -d "password=wrong$i" "$BASE/login"; done |
        sort | uniq -c | awk '{printf "%s x%s ", $2, $1}')
echo "200 wrong guesses: ${codes}in ${SECONDS}s"
printf 'correct guess after them: '
curl -s -o /dev/null -w '%{http_code}\n' --data-urlencode "password=$STAFF_PASSWORD" "$BASE/login"
