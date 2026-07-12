#!/usr/bin/env bash
# Decides whether a GitHub Environment's "Get an environment" API response
# proves an actual human-reviewer gate is configured -- the ONLY protection
# rule type that means "this job pauses for a person to approve it".
#
# GitHub's `protection_rules` array can hold three rule types (wait_timer,
# required_reviewers, branch_policy); a bare `.protection_rules | length`
# check accepts any of them, including a wait_timer-only or
# branch_policy-only environment that never actually waits for a human
# (review: two release workflows -- owen-cli-release.yml's `publish` job,
# action-marketplace-readiness.yml's `move-major-tag` job -- both once made
# this mistake). A `required_reviewers` rule with an EMPTY `reviewers` array
# is likewise not a real gate -- GitHub allows saving one, and it approves
# nothing.
#
# Usage: check_environment_protection.sh <environment-json-file>
# Exit 0 (ACCEPT) only if at least one required_reviewers rule has >=1
# reviewer. Exit 1 (REJECT) for every other case, with a reason on stderr.
set -euo pipefail

file="${1:?usage: check_environment_protection.sh <environment-json-file>}"

count=$(jq '[
  .protection_rules[]?
  | select(.type == "required_reviewers")
  | select((.reviewers // []) | length > 0)
] | length' "$file")

if [ "$count" -eq 0 ]; then
  echo "REJECT: no required_reviewers protection rule with at least one reviewer found" >&2
  exit 1
fi

echo "ACCEPT: $count required_reviewers rule(s) with at least one reviewer configured"
