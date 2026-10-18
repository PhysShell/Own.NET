#!/usr/bin/env bash
# Fetch Meziantou.Framework DictionaryExtensions.cs at the BUGGY commit 7addb26c (MIT) and move it
# into namespace BuggyNs so Program.cs exercises the original code verbatim otherwise.
set -euo pipefail
cd "$(dirname "$0")"
gh api "repos/meziantou/Meziantou.Framework/contents/src/Meziantou.Framework/DictionaryExtensions.cs?ref=7addb26cfd08a6ed6119a3d0a186486befaa923b" \
  -H "Accept: application/vnd.github.raw" > BuggyMeziantou.cs
sed -i 's/^namespace Meziantou.Framework;/namespace BuggyNs;/' BuggyMeziantou.cs
