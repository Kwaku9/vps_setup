#!/usr/bin/env bash
# Verify the AWS account baseline: Config recording group + Security Hub standards.
# Every assertion is paired with a control that MUST fail, so a check that proves
# nothing is visible as a failure rather than passing quietly.
#
#   bash scripts/verify-aws-account-baseline.sh
#
# Exits non-zero on the first real failure.
set -uo pipefail
REGION=${REGION:-us-east-1}
fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
note() { printf '        %s\n' "$1"; }

echo "AWS Config recording group"
GROUP=$(aws configservice describe-configuration-recorders --region "$REGION" \
        --query 'ConfigurationRecorders[0].recordingGroup' --output json 2>/dev/null)

STRAT=$(printf '%s' "$GROUP" | python3 -c 'import json,sys;print((json.load(sys.stdin).get("recordingStrategy") or {}).get("useOnly",""))')
[ "$STRAT" = "EXCLUSION_BY_RESOURCE_TYPES" ] \
  && ok "strategy is EXCLUSION_BY_RESOURCE_TYPES" \
  || bad "strategy is '$STRAT', expected EXCLUSION_BY_RESOURCE_TYPES"

EXCL=$(printf '%s' "$GROUP" | python3 -c 'import json,sys;print("\n".join((json.load(sys.stdin).get("exclusionByResourceTypes") or {}).get("resourceTypes") or []))')
N=$(printf '%s\n' "$EXCL" | grep -c . )
[ "$N" -eq 6 ] && ok "$N resource types excluded" \
  || bad "$N types excluded, expected exactly 6 (see defaults/main.yml)"

# The big one. If AWS rejected this type the apply would have failed, but check
# anyway: it is 42% of recorded items and the main reason for the change.
printf '%s\n' "$EXCL" | grep -qx 'AWS::Config::ResourceCompliance' \
  && ok "AWS::Config::ResourceCompliance excluded" \
  || bad "AWS::Config::ResourceCompliance NOT excluded (the largest single category)"

# CONTROL: a type that must never be excluded. If this passes, the exclusion list
# has grown into territory that would blind the security controls.
printf '%s\n' "$EXCL" | grep -qx 'AWS::S3::Bucket' \
  && bad "CONTROL BREACHED: AWS::S3::Bucket is excluded; S3 controls are now blind" \
  || ok "control held: AWS::S3::Bucket is not excluded"

# The eight types reviewed and deliberately kept on 2026-10-22. They pass the
# "no rule evaluates them" test but their history is what you read after an
# incident, so a later change that quietly re-excludes them should be a failure.
for keep in AWS::KMS::Alias AWS::CloudWatch::Alarm AWS::EC2::RouteTable \
            AWS::EC2::SubnetRouteTableAssociation AWS::EC2::SubnetNetworkAclAssociation \
            AWS::Cognito::UserPoolClient AWS::Cognito::IdentityPoolRoleAttachment \
            AWS::Events::Rule; do
  printf '%s\n' "$EXCL" | grep -qx "$keep" \
    && bad "$keep was excluded; it was reviewed and kept for incident history" \
    || ok "kept as reviewed: $keep"
done

# IAM must survive the narrowing: it is the permission audit trail.
IAM=$(aws configservice get-discovered-resource-counts --region "$REGION" \
      --resource-types AWS::IAM::Role --query 'resourceCounts[0].count' --output text 2>/dev/null)
case "$IAM" in
  ''|None|0) bad "IAM::Role count is '$IAM'; IAM recording was lost" ;;
  *)         ok "IAM::Role still recorded ($IAM items)" ;;
esac

echo
echo "Security Hub standards (CDK-managed: buildfolio-bff-cdk/security_hub_stack.py)"
STD=$(aws securityhub get-enabled-standards --region "$REGION" \
      --query 'StandardsSubscriptions[].StandardsArn' --output text 2>/dev/null | tr '\t' '\n')

printf '%s\n' "$STD" | grep -q 'cis-aws-foundations' \
  && bad "CIS AWS Foundations still enabled; redeploy BuildfolioSecurityHubStack" \
  || ok "CIS AWS Foundations is disabled"

printf '%s\n' "$STD" | grep -q 'aws-foundational-security-best-practices' \
  && ok "FSBP still enabled" \
  || bad "FSBP is NOT enabled; this is the standard carrying every firing control"

printf '%s\n' "$STD" | grep -q 'ai-security-best-practices' \
  && ok "AI Security Best Practices still enabled" \
  || bad "AI Security Best Practices is NOT enabled"

# CONTROL: the matcher must be capable of returning false.
printf '%s\n' "$STD" | grep -q 'nist-800-53' \
  && bad "CONTROL BREACHED: NIST 800-53 is enabled (costs ~\$8.40/mo, was never wanted)" \
  || ok "control held: NIST 800-53 absent, so the matcher can return false"

echo
echo "Config rule noise"
RULES=$(aws configservice describe-config-rules --region "$REGION" \
        --query 'ConfigRules[].ConfigRuleName' --output text 2>/dev/null | tr '\t' '\n' | grep -c .)
note "$RULES Config rules remain (386 before dropping CIS; all created by Security Hub)"

echo
[ "$fail" -eq 0 ] && echo "baseline verified" || echo "baseline has failures"
exit "$fail"
