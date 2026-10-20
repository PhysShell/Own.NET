#!/usr/bin/env bash
# Extra C03/N1 searches. Output: data/search2.out
q() { echo "### $*"; gh search prs $@ --merged --limit 25 --json repository,number,title --jq '.[] | "\(.repository.nameWithOwner)#\(.number)\t\(.title)"'; sleep 7; }
q DisposeAsync leak failure catch IDisposable
q leaked client when exception dispose csharp
q "dispose on failure" IDisposable
