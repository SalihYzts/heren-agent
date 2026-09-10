#!/usr/bin/env bash
# End-to-end smoke: LOW auto-run, HIGH approval gate, Hermes self-approval refused, audit trail.
set -u
B=http://localhost:8701; A="Authorization: Bearer e2e-key"; J='Content-Type: application/json'
echo "--- devices"; curl -s -H "$A" $B/api/devices; echo
echo "--- LOW get_status"; curl -s -X POST -H "$A" -H "$J" $B/api/actions -d '{"device_id":"dev-local","action":"get_status"}'; echo
echo "--- HIGH shutdown from hermes"
R=$(curl -s -w '\n%{http_code}' -X POST -H "$A" -H "$J" $B/api/actions -d '{"device_id":"dev-local","action":"shutdown","requested_by":"hermes"}')
echo "$R"; RID=$(echo "$R" | head -1 | sed -E 's/.*"request_id":"([^"]+)".*/\1/')
echo "--- hermes tries to approve"; curl -s -w ' %{http_code}\n' -X POST -H "$A" -H "$J" $B/api/approvals/$RID/approve -d '{"approved_by":"hermes"}'
echo "--- pending"; curl -s -H "$A" $B/api/approvals; echo
echo "--- user approves"; curl -s -X POST -H "$A" -H "$J" $B/api/approvals/$RID/approve -d '{"approved_by":"ui:salih"}'; echo
echo "--- CRITICAL format_disk"; curl -s -X POST -H "$A" -H "$J" $B/api/actions -d '{"device_id":"dev-local","action":"format_disk"}'; echo
echo "--- audit"; curl -s -H "$A" "$B/api/audit"
