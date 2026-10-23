#!/usr/bin/env bash
# C01-PRECISION-1 dev-set job (inside qubix scanbox): baseline vs patched extractor on the UNCHANGED
# revisions of MAUI 10.0.0 (H1 scope and invocation, byte for byte) and OpenSilver fa7c4c5a (its run.sh scope).
set -u
. /job/sb-lib.sh
stamp "start dev job, patch $(cat /job/PATCH_SHA)"
isolation
build_variant base "$in/ownnet-base.tar"
build_variant patched "$in/ownnet-patched.tar"

m="$w/maui"
fetch "$m" https://github.com/dotnet/maui.git 9d881e94b1c56692e40a16262897677a3bb46fcb \
  '/src/Core/src/' '/src/Controls/src/Core/' '/src/Essentials/src/'
stamp "maui $(git -C "$m" rev-parse HEAD)"
for v in base patched; do
  run_variant "$v" maui "$m/src/Core/src" "$m/src/Controls/src/Core" "$m/src/Essentials/src"
done

os="$w/os"
fetch "$os" https://github.com/OpenSilver/OpenSilver.git fa7c4c5ac2205e759429f0b2f02d09eee26a6d8c '/src/Runtime/'
stamp "opensilver $(git -C "$os" rev-parse HEAD)"
for v in base patched; do
  run_variant "$v" opensilver "$os/src/Runtime"
done
stamp done
exit 0
