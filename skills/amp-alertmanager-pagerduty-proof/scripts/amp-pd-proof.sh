#!/bin/bash
# Proof: AMP alert manager -> PagerDuty (Events API v2). Point it at a NON-PROD workspace.
# usage: amp-pd-proof.sh setup | alert | resolve | rule-on | rule-off | status | cleanup
# The routing key never passes through this script: `setup` creates an EMPTY secret; a human sets
# its value in the Secrets Manager console as {"routing_key": "<Events v2 integration key>"}.
set -euo pipefail
# Required. Nothing here is specific to one account: supply your own.
R="${AMP_REGION:-us-east-1}"
ACCT="${AMP_ACCOUNT_ID:?set AMP_ACCOUNT_ID}"
WS="${AMP_WORKSPACE_ID:?set AMP_WORKSPACE_ID (the ws-... id, not the alias)}"
TICKET="${AMP_PROOF_TAG:-amp-pagerduty-proof}"
WS_ARN="arn:aws:aps:$R:$ACCT:workspace/$WS"
NAME=amp-pagerduty-proof-dev
TAGS="Key=purpose,Value=temporary-proof Key=ticket,Value=$TICKET"
S="${TMPDIR:-/tmp}/amp-pd-proof"; mkdir -p "$S"
AWS="aws --no-cli-pager --region $R"

sigv4_post() {   # sigv4_post <path> <json-file>  -- signed POST to the AMP workspace API
  python3 - "$1" "$2" <<'PY'
import sys, json, boto3, botocore.auth, botocore.awsrequest, urllib.request
path, body = sys.argv[1], open(sys.argv[2]).read()
url = f"https://aps-workspaces.us-east-1.amazonaws.com{path}"
req = botocore.awsrequest.AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
botocore.auth.SigV4Auth(boto3.Session().get_credentials(), "aps", "us-east-1").add_auth(req)
r = urllib.request.urlopen(urllib.request.Request(url, data=body.encode(), headers=dict(req.headers), method="POST"))
print("HTTP", r.status, r.read().decode()[:200])
PY
}

alert_json() {   # alert_json <endsAt or empty>
  local ends="${1:-}"
  jq -n --arg ends "$ends" '[{labels: {alertname: "TicketAmpPagerDutyProof", severity: "critical", env: "dev"},
    annotations: {summary: "proof: AMP alert manager to PagerDuty (dev). Safe to resolve."}}
    + (if $ends != "" then {endsAt: $ends} else {} end)]' > "$S/amp-proof-alert.json"
}

case "${1:-}" in
setup)
  KEY_ID=$($AWS kms create-key --description "AMP PagerDuty proof (temporary)" --tags TagKey=ticket,TagValue="$TICKET" \
    --policy "$(jq -n --arg acct "$ACCT" --arg ws "$WS_ARN" '{Version:"2012-10-17",Statement:[
      {Sid:"Admin",Effect:"Allow",Principal:{AWS:("arn:aws:iam::"+$acct+":root")},Action:"kms:*",Resource:"*"},
      {Sid:"AmpDecrypt",Effect:"Allow",Principal:{Service:"aps.amazonaws.com"},Action:"kms:Decrypt",Resource:"*",
       Condition:{ArnEquals:{"aws:SourceArn":$ws},StringEquals:{"aws:SourceAccount":$acct}}}]}')" \
    --query KeyMetadata.KeyId --output text)
  $AWS kms create-alias --alias-name "alias/$NAME" --target-key-id "$KEY_ID"
  SECRET_ARN=$($AWS secretsmanager create-secret --name "$NAME" --kms-key-id "$KEY_ID" \
    --description "PagerDuty Events v2 routing key for the AMP alert manager. Value set by hand." \
    --tags $TAGS --query ARN --output text)
  $AWS secretsmanager put-resource-policy --secret-id "$SECRET_ARN" --resource-policy "$(jq -n --arg acct "$ACCT" --arg ws "$WS_ARN" '{Version:"2012-10-17",Statement:[
      {Effect:"Allow",Principal:{Service:"aps.amazonaws.com"},Action:"secretsmanager:GetSecretValue",Resource:"*",
       Condition:{ArnEquals:{"aws:SourceArn":$ws},StringEquals:{"aws:SourceAccount":$acct}}}]}')" > /dev/null
  echo "KMS key $KEY_ID (alias/$NAME); secret $SECRET_ARN (EMPTY: set its value in the console)"
  ;;
alertmanager)
  SECRET_ARN=$($AWS secretsmanager describe-secret --secret-id "$NAME" --query ARN --output text)
  cat > "$S/amp-proof-am.yaml" <<EOF
alertmanager_config: |
  route:
    receiver: 'pagerduty-proof'
    group_by: ['alertname']
    group_wait: 10s
    group_interval: 1m
    repeat_interval: 4h
  receivers:
    - name: 'pagerduty-proof'
      pagerduty_configs:
      - routing_key:
          aws_secrets_manager:
            secret_arn: '$SECRET_ARN'
            secret_key: 'routing_key'
            refresh_interval: 5m
        description: '{{ .CommonLabels.alertname }}'
        severity: 'critical'
EOF
  $AWS amp create-alert-manager-definition --workspace-id "$WS" --data "fileb://$S/amp-proof-am.yaml" --query status --output json
  ;;
alert)   alert_json "";  sigv4_post "/workspaces/$WS/alertmanager/api/v2/alerts" "$S/amp-proof-alert.json" ;;
resolve) alert_json "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; sigv4_post "/workspaces/$WS/alertmanager/api/v2/alerts" "$S/amp-proof-alert.json" ;;
rule-on)
  cat > "$S/amp-proof-rules.yaml" <<'EOF'
groups:
  - name: ticket-proof
    rules:
      - alert: TicketAmpRuleProof
        expr: vector(1)
        for: 0m
        labels: {severity: critical, env: dev}
        annotations: {summary: "proof: an AMP-evaluated rule reaching PagerDuty (dev). Resolves when the namespace is deleted."}
EOF
  $AWS amp create-rule-groups-namespace --workspace-id "$WS" --name ticket-proof --data "fileb://$S/amp-proof-rules.yaml" --query status --output json ;;
rule-off) $AWS amp delete-rule-groups-namespace --workspace-id "$WS" --name ticket-proof && echo "rule namespace deleted" ;;
status)
  $AWS amp describe-alert-manager-definition --workspace-id "$WS" --query 'alertManagerDefinition.status' --output json 2>&1 | head -3
  $AWS cloudwatch get-metric-statistics --namespace AWS/Prometheus --metric-name SecretFetchFailure --dimensions Name=Workspace,Value="$WS" \
    --start-time "$(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 300 --statistics Sum --output json | jq -c '[.Datapoints[] | .Sum]' ;;
cleanup)
  $AWS amp delete-rule-groups-namespace --workspace-id "$WS" --name ticket-proof 2>/dev/null || true
  $AWS amp delete-alert-manager-definition --workspace-id "$WS" 2>/dev/null || true
  $AWS secretsmanager delete-secret --secret-id "$NAME" --force-delete-without-recovery --query Name --output text 2>/dev/null || true
  KEY_ID=$($AWS kms describe-key --key-id "alias/$NAME" --query KeyMetadata.KeyId --output text 2>/dev/null || true)
  [ -n "$KEY_ID" ] && $AWS kms delete-alias --alias-name "alias/$NAME" && $AWS kms schedule-key-deletion --key-id "$KEY_ID" --pending-window-in-days 7 --query DeletionDate --output text
  ;;
*) echo "usage: $0 setup|alertmanager|alert|resolve|rule-on|rule-off|status|cleanup"; exit 1 ;;
esac
