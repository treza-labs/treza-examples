#!/usr/bin/env bash
# Make a short AI video with Treza's REST API, using curl and jq.
#
# The order every Treza render follows:
#   1. make_video prices the clip and returns a quoteId. Nothing renders yet.
#   2. Stop if the price is over MAX_COST or the balance does not cover it.
#   3. run_pipeline starts the render once, at the quoted price.
#   4. get_run until it finishes, then download the file.
#
#   export TREZA_API_KEY=treza_live_...
#   ./make-video.sh "A paper boat drifts down a rain-filled gutter at dawn"
#
# Settings, as environment variables:
#   CLIP_SECONDS    length to ask for (default 5)
#   ASPECT          16:9, 9:16 or 1:1 (default 9:16)
#   MAX_COST        the most this render may cost, in USD (default 1.00)
#   OUT             where to save the video (default video.mp4)
#   MAX_WAIT        seconds to wait for the render (default 900)
#   TREZA_BASE_URL  Treza's address (default https://www.trezalabs.com)
set -euo pipefail

: "${TREZA_API_KEY:?Set TREZA_API_KEY. Make a key at https://www.trezalabs.com/platform/api-keys}"
BASE_URL="${TREZA_BASE_URL:-https://www.trezalabs.com}"
BASE_URL="${BASE_URL%/}"
PROMPT="${1:-A paper boat drifts down a rain-filled street gutter at dawn, low angle, soft reflections, slow push in}"
CLIP_SECONDS="${CLIP_SECONDS:-5}"
ASPECT="${ASPECT:-9:16}"
MAX_COST="${MAX_COST:-1.00}"
OUT="${OUT:-video.mp4}"
MAX_WAIT="${MAX_WAIT:-900}"

# treza TOOL JSON: call one Treza tool. Sets BODY (the JSON answer) and STATUS (the HTTP code).
treza() {
  local response
  response=$(curl -sS -X POST "$BASE_URL/api/v1/tools/$1" \
    -H "Authorization: Bearer $TREZA_API_KEY" \
    -H "Content-Type: application/json" \
    -H "User-Agent: treza-examples-curl/1.0" \
    --data "$2" -w '\n%{http_code}')
  STATUS=$(printf '%s' "$response" | tail -n 1)
  BODY=$(printf '%s' "$response" | sed '$d')
}

# stop_if_refused WHAT: exit with Treza's reason when the last call was refused.
stop_if_refused() {
  if [ "$STATUS" -ge 400 ]; then
    echo "Treza refused $1 (HTTP $STATUS): $(jq -r '.error // .' <<<"$BODY")" >&2
    exit 1
  fi
}

usd() { printf '$%.2f' "$1"; }

# 1. Quote. With maxPriceUsd, a clip over the cap is refused (code OVER_BUDGET) and nothing is made.
echo "Asking Treza for a quote..."
treza make_video "$(jq -n --arg prompt "$PROMPT" --argjson seconds "$CLIP_SECONDS" --arg aspect "$ASPECT" --argjson max "$MAX_COST" \
  '{prompt: $prompt, durationSec: $seconds, aspectRatio: $aspect} + (if $max > 0 then {maxPriceUsd: $max} else {} end)')"
stop_if_refused "the quote"

PIPELINE_ID=$(jq -r .pipelineId <<<"$BODY")
QUOTE_ID=$(jq -r .quoteId <<<"$BODY")
PRICE=$(jq -r .estimatedChargeUsd <<<"$BODY")
echo "Quote: $(jq -r '"\(.durationSec)s \(.aspectRatio) on \(.model | if type == "object" then .name // .id else . end)"' <<<"$BODY") for $(usd "$PRICE")"
if [ "$(jq -r '.requestedDurationSec // empty' <<<"$BODY")" != "" ]; then
  echo "       (the model renders fixed lengths, so it makes $(jq -r .durationSec <<<"$BODY")s for the ${CLIP_SECONDS}s you asked for)"
fi

# 2. Check the price and the balance before anything is spent.
if awk -v p="$PRICE" -v m="$MAX_COST" 'BEGIN { exit !(p > m) }'; then
  echo "This clip costs $(usd "$PRICE"), over MAX_COST $(usd "$MAX_COST"). Nothing was spent." >&2
  exit 1
fi
if jq -e '.sufficient == false' <<<"$BODY" >/dev/null; then
  echo "Your balance is $(usd "$(jq -r .balanceUsd <<<"$BODY")"). Nothing was spent. Add credits at $(jq -r '.topUpUrl // "https://www.trezalabs.com/platform/settings"' <<<"$BODY")" >&2
  exit 1
fi

# 3. Start it once, with the quoteId. Sending the same quoteId again returns the same run,
#    so a retry never pays twice. STALE_QUOTE or PRICE_CHANGED means: quote again.
treza run_pipeline "$(jq -n --arg p "$PIPELINE_ID" --arg q "$QUOTE_ID" '{pipelineId: $p, quoteId: $q}')"
stop_if_refused "the start"
RUN_ID=$(jq -r .runId <<<"$BODY")
echo "Rendering (run $RUN_ID)..."

# 4. Wait. Treza says how long to wait between checks (pollAfterSec); 2 to 10 seconds is plenty.
START=$(date +%s)
while :; do
  treza get_run "$(jq -n --arg p "$PIPELINE_ID" --arg r "$RUN_ID" '{pipelineId: $p, runId: $r}')"
  stop_if_refused "the status check"
  RUN_STATUS=$(jq -r .status <<<"$BODY")
  [ "$RUN_STATUS" = "running" ] || break
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
    echo "Still rendering after ${ELAPSED}s. It keeps going on Treza: call get_run with pipelineId $PIPELINE_ID and runId $RUN_ID later." >&2
    exit 2
  fi
  echo "  still rendering (${ELAPSED}s)"
  sleep "$(jq -r '[[.pollAfterSec // 3, 2] | max, 10] | min' <<<"$BODY")"
done

if [ "$RUN_STATUS" != "success" ] && [ "$RUN_STATUS" != "partial" ]; then
  REASON=$(jq -r '[.statusNote, .refusalNote, (.nodes[]? | select(.error) | "\(.label // .type): \(.error)")] | map(select(. != null)) | join(" ")' <<<"$BODY")
  echo "The render stopped ($RUN_STATUS). $REASON" >&2
  exit 1
fi

# 5. Download. Finished files are public links: no API key needed, and use the URL exactly as given.
URL=$(jq -r '.outputs.video // ([.outputs // {} | .[] | strings | select(test("^https?://"))] | first) // empty' <<<"$BODY")
if [ -z "$URL" ]; then
  echo "The run finished but returned no video." >&2
  exit 1
fi
curl -sSfL "$URL" -o "$OUT"
echo "Saved $OUT ($(wc -c <"$OUT" | tr -d ' ') bytes). Quoted price: $(usd "$PRICE")."
echo "Link: $URL"
