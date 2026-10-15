"""Conservative transitive grouping and deterministic draft split allocation."""
import hashlib
import unicodedata
from collections import Counter,defaultdict
from copy import deepcopy
from .data_contract import validate_tasks,SPLITS

TARGETS={'development':100,'D_Q':400,'D_G':200,'D_V':200,'D_C':400,'D_T':300}

def normalize(text):return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())
def shingles(text):
    return {text[i:i+5] for i in range(max(1,len(text)-4))}

def audit(tasks,threshold=.9):
    validate_tasks(tasks)
    if not 0<threshold<=1:raise ValueError('Invalid similarity threshold')
    if len(tasks)>2000:raise ValueError('Exhaustive near-duplicate audit capped at 2000 tasks; use a scalable audited index for larger pools')
    ordered=sorted(tasks,key=lambda t:t['task_id']);parent=list(range(len(ordered)));edges=[]
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def merge(i,j,reason):
        a,b=find(i),find(j)
        if a!=b:parent[max(a,b)]=min(a,b)
        edges.append({'left':ordered[i]['task_id'],'right':ordered[j]['task_id'],'reason':reason})
    keys={};texts=[]
    for i,t in enumerate(ordered):
        # Same source sample identifies 0/5-shot variants regardless of prompt prefix.
        ids=[('source_group',t['source_group_id']),('source_sample',t['source_id'],t['source_sample_id'])]
        if t['template_family']:ids.append(('template_family',t['source_id'],t['template_family']))
        text=normalize(t['question']+'\n'+t['evidence']);ids.append(('exact_text',text));texts.append(shingles(text))
        for key in ids:
            if key in keys:merge(i,keys[key],key[0])
            else:keys[key]=i
    comparisons=0
    for i in range(len(ordered)):
        for j in range(i):
            a,b=texts[i],texts[j]
            if min(len(a),len(b))/max(len(a),len(b))<threshold:continue
            comparisons+=1
            if len(a&b)/len(a|b)>=threshold:merge(i,j,'character_5gram_jaccard')
    groups=defaultdict(list)
    for i,t in enumerate(ordered):groups[find(i)].append(t)
    components=[]
    for members in groups.values():
        ids=sorted(t['task_id'] for t in members)
        gid='group-'+hashlib.sha256('\n'.join(ids).encode()).hexdigest()[:20]
        fixed={t['split'] for t in members if t['split']!='unassigned'}
        if len(fixed)>1:raise ValueError('Duplicate/source/template component crosses existing splits')
        components.append({'group_id':gid,'task_ids':ids,'locked_split':next(iter(fixed),None)})
    return {'components':components,'edges':edges,'near_pair_comparisons':comparisons,
            'threshold':threshold,'method':'NFKC+casefold+whitespace; exact keys and exhaustive char5 Jaccard',
            'semantic_paraphrase_audit_complete':False,'independent_units_verified':0}

def plan(tasks,targets=None,seed=20261014,threshold=.9):
    targets=dict(TARGETS if targets is None else targets)
    if set(targets)!=set(SPLITS) or any(type(v) is not int or v<0 for v in targets.values()) or sum(targets.values())==0:raise ValueError('Invalid six-way targets')
    result=audit(tasks,threshold);counts=Counter({k:0 for k in SPLITS});assignment={}
    components=result['components']
    for g in components:
        if g['locked_split']:
            counts[g['locked_split']]+=len(g['task_ids'])
            assignment[g['group_id']]=g['locked_split']
    order=sorted((g for g in components if not g['locked_split']),key=lambda g:(-len(g['task_ids']),hashlib.sha256(f'{seed}:{g["group_id"]}'.encode()).hexdigest()))
    for g in order:
        candidates=[s for s in SPLITS if targets[s]>0]
        choice=max(candidates,key=lambda s:((targets[s]-counts[s])/targets[s],-SPLITS.index(s)))
        counts[choice]+=len(g['task_ids']);assignment[g['group_id']]=choice
    by_id={tid:g for g in components for tid in g['task_ids']}
    output=deepcopy(tasks)
    for t in output:
        g=by_id[t['task_id']];t['source_group_id']=g['group_id'];t['split']=assignment[g['group_id']]
    validate_tasks(output)
    result.update(targets=targets,actual=dict(counts),target_delta={s:counts[s]-targets[s] for s in SPLITS},
        exact_counts_met=all(counts[s]==targets[s] for s in SPLITS),formal_ready=False,
        category_counts={s:dict(Counter(t['category'] for t in output if t['split']==s)) for s in SPLITS},
        note='Draft whole-group allocation; no category balance guarantee or statistical independence certification')
    return output,result
