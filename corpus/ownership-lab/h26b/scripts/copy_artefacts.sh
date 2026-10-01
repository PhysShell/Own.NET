#!/bin/bash
# Copy the H-26B census artefacts (gzipped census files, logs, aggregate, scripts) into the Own.NET research corpus directory.
set -e
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; D=/home/user/Own.NET/corpus/ownership-lab/h26b
mkdir -p $D/census $D/scripts
for f in $S/lab/h26b/census/*.h26b.json; do gzip -c "$f" > "$D/census/$(basename "$f").gz"; done
cp $S/lab/h26b/census.log $D/census.log
[ -f $S/lab/h26b/rerun-log.json ] && cp $S/lab/h26b/rerun-log.json $D/rerun-log.json
cp $S/lab/h26b/h26b-census-v1.json $D/h26b-census-v1.json
cp $S/lab/h26b/h26bcensus.py $S/lab/h26b/h26bagg.py $S/lab/h26b/rerun_failed.py $S/lab/h26b/h26b_register.py $S/lab/h24/implicit_usings.py $S/lab/sc/manifest_append.py $D/scripts/
cp $S/lab/h26b/copy_artefacts.sh $D/scripts/
ls -la $D $D/census $D/scripts
