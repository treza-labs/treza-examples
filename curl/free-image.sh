#!/usr/bin/env bash
# Make one of today's free pictures with Treza's REST API, using curl and jq.
#
# Every Treza account gets a few free pictures a day on the default image model
# (Nano Banana). make_image says so in its quote: estimatedChargeUsd is 0 and
# freeImage is true. With the default MAX_COST=0, this script only renders a
# picture that is free, so it never spends anything.
#
#   export TREZA_API_KEY=treza_live_...
#   ./free-image.sh "A lighthouse on a sea cliff at golden hour, watercolor"
#
# Settings, as environment variables:
#   ASPECT          1:1, 16:9, 9:16, 4:5, 3:2 and more (default 16:9)
#   MAX_COST        the most this picture may cost, in USD (default 0: free only)
#   OUT             where to save it (default image.<extension of the file>)
#   TREZA_BASE_URL  Treza's address (default https://www.trezalabs.com)
set -euo pipefail

: "${TREZA_API_KEY:?Set TREZA_API_KEY. Make a key at https://www.trezalabs.com/platform/api-keys}"
BASE_URL="${TREZA_BASE_URL:-https://www.trezalabs.com}"
BASE_URL="${BASE_URL%/}"
PROMPT="${1:-A lighthouse on a sea cliff at golden hour, loose watercolor, soft paper texture}"
ASPECT="${ASPECT:-16:9}"
MAX_COST="${MAX_COST:-0}"

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

stop_if_refused() {
  if [ "$STATUS" -ge 400 ]; then
    echo "Treza refused $1 (HTTP $STATUS): $(jq -r '.error // .' <<<"$BODY")" >&2
    exit 1
  fi
}

usd() { printf '$%.2f' "$1"; }

# 1. Quote. A free picture is quoted at 0 whatever maxPriceUsd says.
treza make_image "$(jq -n --arg prompt "$PROMPT" --arg aspect "$ASPECT" --argjson max "$MAX_COST" \
  '{prompt: $prompt, aspectRatio: $aspect} + (if $max > 0 then {maxPriceUsd: $max} else {} end)')"
stop_if_refused "the quote"

PRICE=$(jq -r .estimatedChargeUsd <<<"$BODY")
if jq -e '.freeImage == true' <<<"$BODY" >/dev/null; then
  echo "Free: $(jq -r .freeImagesLeftToday <<<"$BODY") free pictures left today (this one included). Nothing will be charged."
elif awk -v p="$PRICE" -v m="$MAX_COST" 'BEGIN { exit !(p > m) }'; then
  echo "Today's free pictures are used up. This one costs $(usd "$PRICE"). Nothing was spent." >&2
  echo "Run it again tomorrow (they come back at midnight UTC), or with MAX_COST=0.10 to pay for it." >&2
  exit 1
fi
if jq -e '.sufficient == false' <<<"$BODY" >/dev/null; then
  echo "Your balance does not cover $(usd "$PRICE"). Nothing was spent. Add credits at $(jq -r '.topUpUrl // "https://www.trezalabs.com/platform/settings"' <<<"$BODY")" >&2
  exit 1
fi
PIPELINE_ID=$(jq -r .pipelineId <<<"$BODY")
QUOTE_ID=$(jq -r .quoteId <<<"$BODY")

# 2. Start it once with the quoteId. If the free pictures ran out since the quote,
#    Treza refuses with PRICE_CHANGED rather than charging for it.
treza run_pipeline "$(jq -n --arg p "$PIPELINE_ID" --arg q "$QUOTE_ID" '{pipelineId: $p, quoteId: $q}')"
stop_if_refused "the start"
RUN_ID=$(jq -r .runId <<<"$BODY")
echo "Drawing (run $RUN_ID)..."

# 3. Wait. Pictures usually take under a minute.
while :; do
  treza get_run "$(jq -n --arg p "$PIPELINE_ID" --arg r "$RUN_ID" '{pipelineId: $p, runId: $r}')"
  stop_if_refused "the status check"
  RUN_STATUS=$(jq -r .status <<<"$BODY")
  [ "$RUN_STATUS" = "running" ] || break
  sleep "$(jq -r '[[.pollAfterSec // 3, 2] | max, 10] | min' <<<"$BODY")"
done
if [ "$RUN_STATUS" != "success" ]; then
  echo "The render stopped ($RUN_STATUS). $(jq -r '[.statusNote, .refusalNote] | map(select(. != null)) | join(" ")' <<<"$BODY")" >&2
  exit 1
fi

# 4. Download. The picture is outputs.image, a public link.
URL=$(jq -r '.outputs.image // empty' <<<"$BODY")
if [ -z "$URL" ]; then
  echo "The run finished but returned no picture." >&2
  exit 1
fi
EXT=$(printf '%s' "${URL%%\?*}" | sed -nE 's/.*\.([A-Za-z0-9]{3,4})$/\1/p')
OUT="${OUT:-image.${EXT:-png}}"
curl -sSfL "$URL" -o "$OUT"
echo "Saved $OUT ($(wc -c <"$OUT" | tr -d ' ') bytes)."
echo "Link: $URL"
