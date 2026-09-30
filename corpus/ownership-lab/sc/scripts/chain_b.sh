#!/usr/bin/env bash
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
for i in $(seq 1 120); do grep -q WHOLESRC_DONE $S/lab/sc/wholesrc.log && break; sleep 10; done
cd $S/lab/sc && python3 derive_whole.py
