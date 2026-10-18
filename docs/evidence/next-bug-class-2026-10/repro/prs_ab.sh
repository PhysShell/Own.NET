v() { echo "################ $1#$2"; gh pr view "$2" -R "$1" --json title,state,baseRefOid,mergeCommit --jq '"\(.title) state=\(.state) base=\(.baseRefOid) merge=\(.mergeCommit.oid)"'; gh pr diff "$2" -R "$1" 2>&1 | grep -E "^(\+\+\+|@@|[-+])" | grep -v "^[-+]\s*//" | head -${3:-70}; }
v mono/SkiaSharp 4814 60
v Flakroup/FEx 172 80
v ChrisBrooksbank/Vox 41 90
v thomhurst/ModularPipelines 6634 60
v blxkstxllion/shopkeeper 119 60
