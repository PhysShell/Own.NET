#!/usr/bin/env bash
# Deep-check searches (gh search prs, words passed unquoted so gh does not phrase-quote them). Output: data/search.out
q() { echo "### $*"; gh search prs $@ --merged --limit 20 --json repository,number,title --jq '.[] | "\(.repository.nameWithOwner)#\(.number)\t\(.title)"'; sleep 7; }
q fire-and-forget ObjectDisposedException
q IServiceScopeFactory ObjectDisposedException
q ObjectDisposedException HttpContext background
q QueueBackgroundWorkItem ObjectDisposedException
q leak dispose exception rethrow client
q dispose on failure leak connect
