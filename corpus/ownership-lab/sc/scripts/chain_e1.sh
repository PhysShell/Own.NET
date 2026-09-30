#!/usr/bin/env bash
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
for i in $(seq 1 240); do [ -f $S/lab/sc/usage-share.json ] && break; sleep 15; done
cd $S/lab/sc && python3 e1pool.py
