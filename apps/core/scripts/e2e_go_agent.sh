#!/usr/bin/env bash
# Live e2e against the real Go agent on this machine (no destructive actions executed).
set -u
B=http://localhost:8701; A="Authorization: Bearer e2e-key"; J='Content-Type: application/json'
act() { curl -s -X POST -H "$A" -H "$J" $B/api/actions -d "$1"; echo; }
echo "--- devices"; curl -s -H "$A" $B/api/devices; echo
echo "--- get_status (real /proc)"; act '{"device_id":"dev-local","action":"get_status"}'
echo "--- get_metrics (real /proc)"; act '{"device_id":"dev-local","action":"get_metrics"}'
echo "--- get_boot_entries (real bootloader)"; act '{"device_id":"dev-local","action":"get_boot_entries"}'
echo "--- run_approved_command say-hi"; act '{"device_id":"dev-local","action":"run_approved_command","params":{"command_id":"say-hi"}}'
echo "--- run_approved_command not-listed"; act '{"device_id":"dev-local","action":"run_approved_command","params":{"command_id":"rm-everything"}}'
echo "--- restart_service injection attempt"; act '{"device_id":"dev-local","action":"restart_service","params":{"name":"nginx; id"}}'
echo "--- launch_app injection attempt"; act '{"device_id":"dev-local","action":"launch_app","params":{"app":"sh -c id"}}'
echo "--- shutdown from hermes → must wait, then DENY (we do not want to power off)"
R=$(curl -s -X POST -H "$A" -H "$J" $B/api/actions -d '{"device_id":"dev-local","action":"shutdown","requested_by":"hermes"}'); echo "$R"
RID=$(echo "$R" | sed -E 's/.*"request_id":"([^"]+)".*/\1/')
curl -s -X POST -H "$A" -H "$J" $B/api/approvals/$RID/deny -d '{"denied_by":"ui:salih"}'; echo
echo "--- audit (newest first)"; curl -s -H "$A" "$B/api/audit"
