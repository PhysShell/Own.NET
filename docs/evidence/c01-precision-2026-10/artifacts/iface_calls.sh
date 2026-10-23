#!/usr/bin/env bash
# Text census: self-calls through an interface cast in MAUI scope sources (diagnosis aid only).
cd ~/Documents/ownnet-eng/work/maui-src || exit 1
echo "files with (this as I*).M( or ((I*)this).M( :"
grep -rlE '\(this as I[A-Za-z]+\)\??\.[A-Za-z]+\(|\(\(I[A-Za-z]+\)this\)\.[A-Za-z]+\(' --include=*.cs src | wc -l
echo "call sites:"
grep -rnE '\(this as I[A-Za-z]+\)\??\.[A-Za-z]+\(|\(\(I[A-Za-z]+\)this\)\.[A-Za-z]+\(' --include=*.cs src | wc -l
echo "-- distinct called members:"
grep -rhoE '\(this as I[A-Za-z]+\)\??\.[A-Za-z]+\(|\(\(I[A-Za-z]+\)this\)\.[A-Za-z]+\(' --include=*.cs src | sed -E 's/\?//' | sort | uniq -c | sort -rn | head -30
echo "-- explicit interface impls of Disconnect / Dispose-like:"
grep -rnE 'void I[A-Za-z]+\.(Disconnect|Dispose|TearDown|Cleanup|Detach)[A-Za-z]*\(' --include=*.cs src | wc -l
