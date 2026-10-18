set -u
q() { echo "### $1 :: $2"; gh search "$1" $2 --limit 30 --json repository,title,url,number,state --jq '.[] | "\(.repository.nameWithOwner)\t#\(.number)\t\(.state)\t\(.title)"' 2>&1 | head -30; }
# C: CollectionsMarshal stale views
q prs '"CollectionsMarshal" stale --language C#'
q prs '"CollectionsMarshal.AsSpan" fix --language C#'
q issues '"CollectionsMarshal.AsSpan" bug --language C#'
q issues '"CollectionsMarshal" "Add" span invalid --language C#'
# B: captured disposable in local lambda
q prs 'dispose captured lambda leak --language C#'
q prs '"local function" dispose leak --language C#'
# A: leak through own helper
q prs '"not disposed" stream passed helper --language C#'
q prs 'fix "undisposed" stream leak --language C#'
