"""Re-run acceptance with logs; pass a new --output for a fresh experiment directory."""
from pathlib import Path
import subprocess,sys,os,json,argparse
ROOT=Path(__file__).resolve().parents[2]
REPORT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--output',default='reports/recovery_20260923_01/final_synthetic_run');args=p.parse_args()
commands=[
 ('final_tests',[sys.executable,'-m','pytest','-q','--junitxml='+str(REPORT/'final_tests.xml')],0),
 ('validate',[sys.executable,'-m','selection.replay','--config','configs/small_replay.json','--validate-only'],0),
 ('draft_rejected',[sys.executable,'-m','selection.replay','--config','configs/development_replay.template.json','--validate-only'],1),
 ('final_replay',[sys.executable,'-m','selection.replay','--config','configs/small_replay.json','--output',args.output],0),
]
records=[]
for name,cmd,expected in commands:
 run=subprocess.run(cmd,cwd=ROOT,env={**os.environ,'PYTHONPATH':'src'},capture_output=True,text=True)
 log='COMMAND: PYTHONPATH=src '+' '.join(cmd)+'\n'+run.stdout+run.stderr+f'\nEXIT_STATUS={run.returncode}\nEXPECTED_EXIT_STATUS={expected}\n'
 (REPORT/(name+'.log')).write_text(log)
 records.append({'name':name,'command':cmd,'exit_status':run.returncode,'expected_exit_status':expected,'log':name+'.log'})
 print(name,run.returncode,run.stdout[-1500:])
 if run.returncode!=expected:
  print(run.stderr);(REPORT/'verification_commands.json').write_text(json.dumps(records,indent=2));sys.exit(1)
(REPORT/'verification_commands.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
