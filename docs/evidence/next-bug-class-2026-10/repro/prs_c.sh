v() { echo "################ $1#$2"; gh pr view "$2" -R "$1" --json title,state,mergedAt,baseRefOid,headRefOid,mergeCommit,body --jq '"\(.title)\nstate=\(.state) merged=\(.mergedAt) base=\(.baseRefOid) head=\(.headRefOid) merge=\(.mergeCommit.oid)\n\(.body[0:1800])"'; echo "------ diff"; gh pr diff "$2" -R "$1" 2>&1 | grep -v "^index " | head -${3:-120}; }
v meziantou/Meziantou.Framework 2825 160
v dotnet/maui 37148 200
v rtkelly-labs/Parquet.SourceGenerator 639 80
