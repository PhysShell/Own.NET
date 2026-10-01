"""Append-only manifest lines for every semantic-coverage, h23, h24, h25 and h26 record (and the register) not yet listed; never rewrites lines."""
import hashlib, os, glob
P='/home/user/Own.NET-paperwork'; M=f'{P}/paper-eval/manifests/ownership-lab-v1.sha256'
have=set(l.split()[-1] for l in open(M) if l.strip())
add=[]
for f in sorted(glob.glob(f'{P}/paper-eval/semantic-coverage/*.json'))+sorted(glob.glob(f'{P}/paper-eval/h23/*.json'))+sorted(glob.glob(f'{P}/paper-eval/h24/*.json'))+sorted(glob.glob(f'{P}/paper-eval/h25/*.json'))+sorted(glob.glob(f'{P}/paper-eval/h26/*.json'))+[f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json']:
    rel=os.path.relpath(f,P); h=hashlib.sha256(open(f,'rb').read()).hexdigest()
    if f'{h}  {rel}' in set(l.strip() for l in open(M)): continue
    add.append(f'{h}  {rel}')
with open(M,'a') as o:
    for l in add: o.write(l+'\n')
print('manifest +%d lines'%len(add))
