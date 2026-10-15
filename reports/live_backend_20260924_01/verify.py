"""Run backend acceptance and a MOCK single-task loop. Never invokes a real model."""
from pathlib import Path
import json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
records=[]
def run(name,args,expected=0):
 command=[sys.executable,*args]
 p=subprocess.run(command,cwd=ROOT,env={**os.environ,'PYTHONPATH':'src'},capture_output=True,text=True)
 (OUT/(name+'.log')).write_text('COMMAND: PYTHONPATH=src '+' '.join(command)+'\n'+p.stdout+p.stderr+f'\nEXIT_STATUS={p.returncode}\nEXPECTED_EXIT_STATUS={expected}\n')
 records.append({'name':name,'command':command,'exit_status':p.returncode,'expected':expected})
 (OUT/'commands.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
 print(name,p.returncode,p.stdout[-900:])
 if p.returncode!=expected:print(p.stderr);raise SystemExit(1)
run('tests',['-m','pytest','-q','--junitxml='+str(OUT/'tests.xml')])
config=json.loads((ROOT/'configs/single_task_mock.json').read_text());config['attempt_ledger']=str(OUT/'mock_attempts.sqlite3')
(OUT/'mock_deployment.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
task=str(ROOT/'examples/single_task/mock_task.json');cfg=str(OUT/'mock_deployment.json');collection=OUT/'mock_collection'
run('validate_mock',['-m','selection.single_task','validate','--mock','--task',task,'--deployment',cfg])
run('collect_mock',['-m','selection.single_task','collect','--mock','--task',task,'--deployment',cfg,'--output',str(collection)])
run('duplicate_rejected',['-m','selection.single_task','collect','--mock','--task',task,'--deployment',cfg,'--output',str(OUT/'forbidden_duplicate')],1)
run('live_draft_rejected',['-m','selection.single_task','validate','--live','--task','templates/development/single_task.draft.json','--deployment','configs/single_task_live.template.json'],1)
cards=[json.loads(s) for s in (collection/'annotation_cards.jsonl').read_text().splitlines()]
for card in cards:
 card['reference_evidence_locations']='MOCK ONLY: synthetic example sentence, not human annotation'
 card['reviews']=[{'reviewer':name,'scores':[4,4,4],'valid':True,'veto':False} for name in ['synthetic-rater-A','synthetic-rater-B']]
annotations=OUT/'synthetic_scoring_cards.jsonl';annotations.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cards))
run('evaluate_mock',['-m','selection.single_task','evaluate','--collection',str(collection),'--cards',str(annotations),'--output',str(OUT/'mock_evaluation')])
