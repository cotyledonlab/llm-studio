#!/bin/sh
set -eu

# Read-only discovery probe for an already enabled Ardour MCP HTTP surface.
# Keep the endpoint loopback-only: this probe intentionally rejects other hosts.
endpoint=${ARDOUR_MCP_URL:-http://127.0.0.1:4820/mcp}
case "$endpoint" in
  http://127.0.0.1:*/*|http://localhost:*/*) ;;
  *)
    echo "refusing non-loopback endpoint: $endpoint" >&2
    exit 64
    ;;
esac

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/ardour-mcp-probe.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

headers="$tmpdir/headers"
body="$tmpdir/initialize.json"
accept='Accept: application/json, text/event-stream'
content_type='Content-Type: application/json'
initialize='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"llm-studio-qualification","version":"0.1.0"}}}'

echo "endpoint=$endpoint"
if ! curl --fail-with-body --silent --show-error --max-time 5 \
  -D "$headers" -o "$body" -H "$accept" -H "$content_type" \
  --data "$initialize" "$endpoint"; then
  echo "result=unreachable-or-initialization-failed"
  exit 1
fi

session_id=$(awk 'BEGIN { IGNORECASE=1 } /^Mcp-Session-Id:/ { sub(/\r$/, "", $2); print $2 }' "$headers" | tail -1)
echo "initialize_response:"
sed -n '1,80p' "$body"

session_header=
if [ -n "$session_id" ]; then
  session_header="Mcp-Session-Id: $session_id"
fi

curl --fail-with-body --silent --show-error --max-time 5 \
  -H "$accept" -H "$content_type" ${session_header:+-H "$session_header"} \
  --data '{"jsonrpc":"2.0","method":"notifications/initialized"}' "$endpoint" >/dev/null

echo "tools_list_response:"
curl --fail-with-body --silent --show-error --max-time 10 \
  -H "$accept" -H "$content_type" ${session_header:+-H "$session_header"} \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' "$endpoint"
echo
