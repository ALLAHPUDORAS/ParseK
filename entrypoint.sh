#!/bin/sh
set -e

# Poll interval in seconds (default 1 hour)
POLL_INTERVAL="${POLL_INTERVAL:-3600}"

term_handler() {
  echo "$(date -u) - Signal received, exiting..."
  exit 0
}

trap term_handler INT TERM

echo "$(date -u) - entrypoint starting (POLL_INTERVAL=${POLL_INTERVAL})"

while true; do
  echo "$(date -u) - Running pipeline"
  python -m src.main "$@" || echo "$(date -u) - pipeline exited with $? — continuing"

  if [ "${ONE_SHOT}" = "1" ]; then
    echo "$(date -u) - ONE_SHOT=1 set — exiting after one run"
    break
  fi

  sleep "$POLL_INTERVAL"
done

echo "$(date -u) - entrypoint exiting"
exit 0
