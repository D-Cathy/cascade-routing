"""Read-only exact-overlap inventory across RouterBench prompt variants."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from ..routerbench_adapter import digest,text_cell
from .splits import normalize

def inventory(paths):
    tables=[];sets=[]
    for path in paths:
        ids=Counter();prompts=Counter();categories=Counter();empty=0
        with Path(path).open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                ids[row['sample_id']]+=1;categories[row['eval_name']]+=1
                text=normalize(text_cell(row['prompt']))
                if not text:empty+=1
                prompts[hashlib.sha256(text.encode()).hexdigest()]+=1
        tables.append({'path':str(path),'sha256':digest(path),'rows':sum(ids.values()),
            'unique_sample_ids':len(ids),'duplicate_id_excess':sum(v-1 for v in ids.values()),
            'exact_prompt_duplicate_excess':sum(v-1 for v in prompts.values()),'empty_prompts':empty,
            'categories':dict(categories)})
        sets.append((set(ids),set(prompts)))
    pairs=[]
    for i in range(len(paths)):
        for j in range(i):pairs.append({'left':str(paths[j]),'right':str(paths[i]),
            'shared_sample_ids':len(sets[j][0]&sets[i][0]),'shared_normalized_prompt_hashes':len(sets[j][1]&sets[i][1])})
    return {'files':tables,'pairwise_overlap':pairs,'full_corpus_near_duplicate_audit_complete':False,
            'note':'Exact inventory only; shared IDs must remain grouped across prompt variants. No independence certification.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sources',nargs='+',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise FileExistsError('Do not overwrite audit')
    result=inventory(a.sources);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'files':len(result['files']),'pairwise_overlap':result['pairwise_overlap']}))

if __name__=='__main__':main()
