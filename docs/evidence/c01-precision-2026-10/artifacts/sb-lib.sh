# Shared helpers for the C01-PRECISION-1 scanbox jobs (sourced by run.sh INSIDE the guest).
# /job read-only (inputs), /out writable (results), /var/lib/job disposable.
out=/out; in=/job; w=/var/lib/job/w
mkdir -p "$w" "$out"
stamp() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)  $*" | tee -a "$out/steps.log"; }
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
export NUGET_PACKAGES="$w/nuget-packages" GIT_LFS_SKIP_SMUDGE=1 PYTHONUTF8=1 HOME=/var/lib/job GIT_CONFIG_NOSYSTEM=1

isolation() {
  { id; uname -a
    touch /job/.w 2>/dev/null && echo "JOB WRITABLE (bad)" || echo "job read-only: ok"
    curl -sS -o /dev/null --max-time 5 http://10.0.2.2:80/ && echo "host REACHABLE (bad)" || echo "host 10.0.2.2 blocked: ok"
    dotnet nuget list source --configfile "$in/nuget.isolated.config"
    dotnet --version; python3 --version; git --version; } > "$out/isolation.txt" 2>&1
}

# build_variant <name> <tar>  -> sets EXDLL_<name>, own core dir $w/own-<name>
build_variant() {
  local v=$1 tarf=$2 d="$w/own-$1"
  mkdir -p "$d"; tar -xf "$tarf" -C "$d"
  sha256sum "$tarf" >> "$out/ownnet-tars.sha256"
  local ex="$d/frontend/roslyn/OwnSharp.Extractor/OwnSharp.Extractor.csproj"
  { dotnet restore "$ex" --configfile "$in/nuget.isolated.config"; dotnet build "$ex" -c Release --no-restore; } > "$out/build-$v.txt" 2>&1
  local dll; dll=$(find "$d/frontend/roslyn/OwnSharp.Extractor/bin/Release" -name ownsharp-extract.dll | head -1)
  echo "$v extractor=${dll:-NONE} $( [ -n "$dll" ] && sha256sum "$dll" | cut -d' ' -f1)" >> "$out/built.txt"
  eval "EXDLL_$v=\"$dll\""
  stamp "built $v: ${dll:-NONE}"
}

# run_variant <variant> <label> <inputs...>   (H1 invocation: --flow-locals --stats; core: python sarif warning)
run_variant() {
  local v=$1 label=$2; shift 2
  local dll; eval "dll=\$EXDLL_$v"
  local dir="$out/run/$label/$v"; mkdir -p "$dir"
  local e0 e1 rc1 rc2=null
  e0=$(date +%s)
  ( cd "$w" && dotnet "$dll" "$@" -o "$dir/facts.json" --flow-locals --stats ) 2> "$dir/extract.log" 1> "$dir/extract.out"
  rc1=$?; e1=$(date +%s)
  if [ "$rc1" = 0 ] && [ -f "$dir/facts.json" ]; then
    ( cd "$w/own-$v" && python3 -s -m ownlang ownir "$dir/facts.json" --format sarif --severity warning ) 1> "$dir/findings.sarif" 2> "$dir/core.log"
    rc2=$?
  fi
  { echo "extractor_rc=$rc1 core_rc=$rc2 extractor_seconds=$((e1 - e0))"
    [ -f "$dir/facts.json" ] && sha256sum "$dir/facts.json"
    [ -f "$dir/findings.sarif" ] && sha256sum "$dir/findings.sarif"; } > "$dir/meta.txt"
  stamp "$label/$v extractor rc=$rc1 core rc=$rc2 $(tail -1 "$dir/core.log" 2>/dev/null)"
}

# fetch <dir> <url> <sha> [sparse paths...]
fetch() {
  local r=$1 url=$2 sha=$3; shift 3
  { git init -q "$r"; git -C "$r" config core.autocrlf false; git -C "$r" config core.longpaths true
    git -C "$r" config core.symlinks false
    git -C "$r" remote add origin "$url"
    git -C "$r" fetch --depth 1 --filter=blob:none origin "$sha"
    if [ $# -gt 0 ]; then git -C "$r" sparse-checkout set --no-cone "$@"; fi
    git -C "$r" checkout -q --detach FETCH_HEAD; } >> "$out/git-fetch.txt" 2>&1
  echo "$url $(git -C "$r" rev-parse HEAD)" >> "$out/revisions.txt"
}
