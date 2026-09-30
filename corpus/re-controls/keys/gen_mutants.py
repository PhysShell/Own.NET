#!/usr/bin/env python3
"""Stage 1 NAME-RULE MUTANT keys, generated from a fixture by name alone (the extractor never contains a name rule).
M1: a method whose name starts with Create/Open/New and whose declared return type is a disposable-looking type -> return_fresh_owned.
M2: a method named Delete/Close/Free/Release/Destroy -> receiver_terminal_release."""
import json, re, sys
DISP={'CancellationTokenSource','R','FileStream','CngKey','Handle','Bucket','Stream'}
src=open(sys.argv[1]).read(); out=sys.argv[2]
cls=None; m1=[]; m2=[]
for line in src.splitlines():
    c=re.search(r'\b(?:class|struct)\s+(\w+)',line)
    if c: cls=c.group(1); continue
    d=re.match(r'^\s*(?:(?:public|private|internal|static|override)\s+)*([\w<>\[\]?.]+)\s+(\w+)\s*\(',line)
    if not d or cls is None: continue
    rt,name=d.group(1),d.group(2)
    if rt in ('if','for','while','return','new','using','switch','catch','foreach'): continue
    if re.match(r'(Create|Open|New)',name) and rt in DISP: m1.append(f'{cls}.{name}')
    if name in ('Delete','Close','Free','Release','Destroy'): m2.append(f'{cls}.{name}')
key={'schema':'own.net/re-oracle/v1','label':f'NAME-RULE MUTANT key for {sys.argv[1].split("/")[-1]} (must fail)','entries':
     [{'callable':c,'effect':'return_fresh_owned'} for c in m1]+[{'callable':c,'effect':'receiver_terminal_release'} for c in m2]}
json.dump(key,open(out,'w'),indent=1); print(out,'M1',m1,'M2',m2)
