#!/usr/bin/env bash
set -u
LOCK=/tmp/promobot-watchdog.lock
FALL=/tmp/promobot-watchdog.fail
NTFY=https://ntfy.sh/cetrio-vps-enzo

if [ -e "$LOCK" ]; then
  pid=$(cat "$LOCK" 2>/dev/null)
  if kill -0 "$pid" 2>/dev/null; then exit 0; fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

fail=0
for url in "https://promobot.enzostana.space/" "https://promobot-evo.enzostana.space/"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 "$url")
  [ "$code" = "200" ] || [ "$code" = "401" ] || [ "$code" = "307" ] || [ "$code" = "302" ] || { fail=1; echo "($url -> $code)"; }
done

prev=0
[ -f "$FALL" ] && prev=$(cat "$FALL")
if [ "$fail" = "1" ]; then
  now=$((prev+1))
  echo "$now" > "$FALL"
  if [ "$now" -ge 2 ]; then
    msg="[WATCHDOG] promobot fora do ar em $(date -u +%FT%TZ): $(cat /tmp/promobot-watchdog.last 2>/dev/null)"
    curl -s -m 10 -d "$msg" -H "Title: promobot DOWN" "$NTFY" >/dev/null 2>&1 || true
    rm -f "$FALL"
  else
    : > /tmp/promobot-watchdog.last
    for url in "https://promobot.enzostana.space/" "https://promobot-evo.enzostana.space/"; do
      code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 "$url")
      echo "$url -> $code" >> /tmp/promobot-watchdog.last
    done
  fi
else
  rm -f "$FALL"
fi
exit 0