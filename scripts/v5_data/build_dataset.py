"""Build a source-grounded CANDIDATE task corpus; never generate model labels.

Standard library only. Source groups are conservative provenance blocks, not a
claim of statistical independence. No formal fit/calibration/test split is made.
"""
import collections
import csv
import gzip
import hashlib
import html
import io
import json
import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/v5_public_20261013'
RAW = DATA / 'raw'
OUT = DATA / 'prepared'
CATEGORIES = {
    'log_summary': '结构化日志摘要', 'weather': '气象信息解读',
    'equipment': '设备故障辅助分析', 'communication': '船岸通信理解',
    'alternatives': '约束下的备选方案比较',
}

def dumps(x):
    return json.dumps(x, ensure_ascii=False, allow_nan=False)

def write_jsonl(path, rows):
    path.write_text(''.join(dumps(r) + '\n' for r in rows), encoding='utf-8')

def spread(rows, n):
    if len(rows) < n:
        raise ValueError(f'Need {n} distinct candidates, have {len(rows)}')
    return [rows[i * len(rows) // n] for i in range(n)]

def build():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'private').mkdir(exist_ok=True)
    tasks, refs = [], []
    counts = collections.Counter()
    def add(cat, group, source, locator, family, nature, question, evidence, reference):
        counts[cat] += 1
        tid = f'v5pub-{cat}-{counts[cat]:04d}'
        tasks.append(dict(dataset_version='v5-public-candidate-0.1', task_id=tid,
            category=cat, category_zh=CATEGORIES[cat], source_group_id=group,
            source_id=source, source_locator=locator, template_family=family,
            provenance=nature, split='unassigned', human_review_status='pending',
            question=question + ' 只依据给定证据作答；输出一个JSON对象，不添加无证据的事实。',
            evidence=dumps(evidence), allowed_models=['ship','shore','cloud']))
        refs.append(dict(task_id=tid, reference=reference, reference_origin='deterministic_derivation_from_fixed_evidence',
            human_verified=False, numeric_tolerance=0.005,
            rubric_version='v5-public-draft-0.1', score_dimensions=['correctness','completeness','instruction_following'],
            dimension_scale=[0,4], weights=[0.5,0.3,0.2],
            quality_rule='(0.5*correctness+0.3*completeness+0.2*instruction_following)/4; critical error or hard constraint violation => 0',
            validity_rule='Record separately; invalid JSON or missing required output fields is invalid.',
            review_note='Reference facts are computed, not human scores. Two independent reviewers and adjudication remain required.'))

    # Real ship records. Preserve raw units rather than invent undocumented units.
    windows = []
    for p in sorted((RAW/'polarfront').glob('pos-*.log')):
        lines = p.read_text(encoding='latin1').splitlines()
        rows = list(csv.DictReader(lines[1:]))
        for i in range(0, len(rows)-5, 10):
            chunk = rows[i:i+6]
            try:
                for r in chunk:
                    float(r['Speed'])
                windows.append((p.name,i+3,chunk))
            except (ValueError, KeyError, TypeError):
                continue
    for name,line,chunk in spread(windows,320):
        evidence={'source_note':'真实航次观测日志；Speed单位在所用文件头未声明，保留原始数值，不做单位推断。',
                  'records':[{k:r[k] for k in ['Date','Time','Latitude','Longitude','Speed']} for r in chunk]}
        ref={'date':chunk[0]['Date'],'start_time':chunk[0]['Time'],'end_time':chunk[-1]['Time'],
             'record_count':len(chunk),'mean_speed_raw':round(sum(float(r['Speed']) for r in chunk)/len(chunk),2),
             'start_position':[chunk[0]['Latitude'],chunk[0]['Longitude']],
             'end_position':[chunk[-1]['Latitude'],chunk[-1]['Longitude']]}
        add('log_summary','polarfront-cruise-202105','polarfront',f'raw/polarfront/{name}:lines {line}-{line+5}',
            'six_record_log_summary','real_observations_derived_task',
            '汇总六条日志，输出date、start_time、end_time、record_count、mean_speed_raw（算术平均保留两位小数）、start_position和end_position（各为纬度、经度原字符串数组）。',evidence,ref)

    # NDBC historical missing sentinels are field-specific; never treat as values.
    weather = []
    for p in sorted(RAW.glob('ndbc_*_2023.txt.gz')):
        station=p.name.split('_')[1]
        lines=gzip.decompress(p.read_bytes()).decode().splitlines()
        header=lines[0].lstrip('#').split()
        days=collections.defaultdict(list)
        for line_no,line in enumerate(lines[2:],3):
            row=dict(zip(header,line.split()))
            if len(row)!=len(header):
                continue
            if row['mm']!='10':
                continue
            day='-'.join(row[k] for k in ['YY','MM','DD'])
            entry={'time_utc':row['hh']+':'+row['mm']}
            for key,sentinel in [('WSPD',99),('WVHT',99),('PRES',9999)]:
                value=float(row[key]);entry[key]=None if value==sentinel else value
            days[day].append((line_no,entry))
        for day,rows in days.items():
            selected=rows[::4][:6]
            if len(selected)==6 and any(r['WSPD'] is not None for _,r in selected):
                weather.append((p.name,station,day,selected))
    for name,station,day,rows in spread(weather,320):
        values=[r['WSPD'] for _,r in rows if r['WSPD'] is not None]
        waves=[r['WVHT'] for _,r in rows if r['WVHT'] is not None]
        ref={'station':station,'date':day,'max_wind_m_s':max(values),'max_wave_m':max(waves) if waves else None,
             'wind_limit_exceeded':any(v>10 for v in values),'wave_limit_exceeded':any(v>2.5 for v in waves) if waves else None,
             'missing_cells':sum(r[k] is None for _,r in rows for k in ['WSPD','WVHT','PRES'])}
        add('weather',f'ndbc-{station}-{day[:7]}','ndbc',f'raw/{name}:lines '+','.join(str(n) for n,_ in rows),
            'weather_threshold_interpretation','real_observations_with_authored_task_limits',
            '解释这六个时点的观测：输出station、date、max_wind_m_s、max_wave_m、wind_limit_exceeded、wave_limit_exceeded和missing_cells。仅比较给出的样本；风速大于10m/s或浪高大于2.5m才算超限。某字段全部缺失时，其最大值和超限判断为null。统计WSPD/WVHT/PRES中的缺失格数。',
            {'station':station,'date':day,'units':{'WSPD':'m/s','WVHT':'m','PRES':'hPa'},
             'note':'这是历史观测，不是预报。阈值是本任务人为设定的练习约束，不是官方航行安全标准。null表示缺测。','records':[r for _,r in rows]},ref)

    z=zipfile.ZipFile(RAW/'uci_nav_propulsion.zip')
    for name in ['Features.txt','README.txt']:
        (RAW/('uci_'+name)).write_bytes(z.read('UCI CBM Dataset/'+name))
    matrix=[[float(v) for v in line.split()] for line in z.read('UCI CBM Dataset/data.txt').decode().splitlines() if line.strip()]
    # Group by simulator degradation pair; all speed variants remain together.
    by_pair=collections.defaultdict(list)
    for i,r in enumerate(matrix,1):
        by_pair[(r[16],r[17])].append((i,r))
    selected_pairs=spread(sorted(by_pair),320)
    for pair in selected_pairs:
        samples=sorted(by_pair[pair],key=lambda p:p[1][1]);line,r=samples[len(samples)//2]
        group=f'uci-decay-{pair[0]:.3f}-{pair[1]:.3f}'
        flags=[name for name,v,t in [('compressor',r[16],0.970),('turbine',r[17],0.985)] if v<t]
        add('equipment',group,'uci',f'raw/uci_nav_propulsion.zip!UCI CBM Dataset/data.txt:line {line}',
            'diagnostic_coefficient_rule','simulator_with_authored_diagnostic_rule',
            '根据已提供的仿真诊断系数和任务规则，输出flagged_components（compressor、turbine中需复核者，按此前后顺序）、compressor_margin、turbine_margin（各系数减对应阈值，保留三位小数）、next_step（有任一低于阈值则review，否则monitor）。这不是从传感器预测未知故障的任务。',
            {'speed_knots':r[1],'compressor_coefficient':r[16],'turbine_coefficient':r[17],
             'rule':{'compressor_threshold':0.970,'turbine_threshold':0.985,'trigger':'strictly_less'},
             'note':'UCI仿真系数明确作为已知证据；阈值是本项目练习规则，不是设备厂商标准，不能据此作真实故障诊断。'},
            {'flagged_components':flags,'compressor_margin':round(r[16]-0.970,3),'turbine_margin':round(r[17]-0.985,3),'next_step':'review' if flags else 'monitor'})
        # Compare actual simulator settings with explicitly constructed constraints.
        opts=[{'id':f'option-{i+1}','speed_knots':rr[1],'fuel_kg_s':rr[15]} for i,(_,rr) in enumerate(samples)]
        minimum=[6,12,18,24][len(tasks)%4]
        cap=[0.5,0.8,1.0,0.05][counts['alternatives']%4]
        feasible=[o for o in opts if o['speed_knots']>=minimum and o['fuel_kg_s']<=cap]
        best=min(feasible,key=lambda o:(o['fuel_kg_s'],o['id']))['id'] if feasible else None
        add('alternatives',group,'uci','raw/uci_nav_propulsion.zip!UCI CBM Dataset/data.txt:lines '+','.join(str(n) for n,_ in samples),
            'speed_fuel_constrained_comparison','simulator_with_authored_constraints',
            '比较给定工况，输出feasible_ids（按证据原顺序）、selected_id、reason_code。有资格的工况须同时满足航速不小于minimum_speed_knots和燃油流量不大于max_fuel_kg_s；从中选燃油最少者，相同则按id字典序取首项。无可行项时selected_id=null且reason_code=no_feasible_option，否则reason_code=min_fuel。',
            {'options':opts,'minimum_speed_knots':minimum,'max_fuel_kg_s':cap,
             'note':'约束为人为构造的离线比较题；只比较给定仿真工况，不包含真实航路或安全决策。'},
            {'feasible_ids':[o['id'] for o in feasible],'selected_id':best,'reason_code':'min_fuel' if feasible else 'no_feasible_option'})

    dialogs=[json.loads(s) for s in (RAW/'martts_scenarios.jsonl').read_text().splitlines() if s.strip()]
    candidates=[(d,'turns') for d in dialogs]+[(d,'questions') for d in dialogs]
    # 240 conversations + a second, distinct information task for 80 of them.
    for d,mode in candidates[:320]:
        base=re.sub(r'_[abc]$','',d['dialog_id'])
        us=d['utterances']
        if mode=='turns':
            counts_s=collections.Counter(str(u['speaker_id']) for u in us)
            ref={'speaker_order':list(dict.fromkeys(str(u['speaker_id']) for u in us)),
                 'turn_counts':dict(counts_s),'last_turn_by_speaker':{str(u['speaker_id']):u['turn'] for u in us}}
            question='还原通信参与者的轮次关系：输出speaker_order（按首次发言次序的speaker_id字符串数组）、turn_counts（各speaker_id发言次数）、last_turn_by_speaker（各speaker_id最后发言的turn）。'
        else:
            selected=[u for u in us if '?' in u['text']]
            ref={'question_turns':[u['turn'] for u in selected],
                 'questions':[{'turn':u['turn'],'speaker_id':str(u['speaker_id']),'text':u['text']} for u in selected],
                 'question_count':len(selected)}
            question='制作通信交接中的待核对问句清单：仅将含英文问号的完整发言计为问句，输出question_turns、questions（对象含turn、speaker_id字符串、text原文）和question_count。不得把疑问句当作已确认事实。'
        add('communication','martts-'+base,'martts',f'raw/martts_scenarios.jsonl:dialog_id={d["dialog_id"]}',
            'radio_'+mode,'upstream_llm_synthetic_dialogue',question,
            {'note':'公开MARTTS合成通信文本；可能存在语义或角色不一致，按提供的speaker_id和原文处理，不当作真实呼救或人工校验规范。','utterances':us},ref)

    # Export only 20 development tasks to the existing strict v1 task interface.
    dev=[]
    for cat in CATEGORIES:
        chosen=spread([t for t in tasks if t['category']==cat],4)
        for t in chosen:
            dev.append(dict(schema_version=1,task_id=t['task_id'],source_group_id=t['source_group_id'],
                source='engineering_cache',split='dev_eval',question=t['question'],evidence=t['evidence'],
                allowed_models=t['allowed_models'],service=dict(quality_threshold=0.8,deadline_s=12,budget=1.5,
                    cost_unit='v5_normalized_cost_unimplemented',risk_target=0.1),environment={},
                metadata={'category':cat,'original_provenance':t['provenance'],
                          'purpose':'offline task-interface validation; not live deployment or populated replay'}))
    reserved={t['source_group_id'] for t in dev}
    for t in tasks:
        if t['source_group_id'] in reserved:
            t['split']='development_reserved'
    write_jsonl(OUT/'tasks.jsonl',tasks)
    write_jsonl(OUT/'private/references.jsonl',refs)
    write_jsonl(OUT/'dev20.tasks.v1.jsonl',dev)
    write_jsonl(OUT/'private/labels.pending.jsonl',[
        {'task_id':t['task_id'],'model_name':m,'quality':None,'valid':None,'label_source':'missing','reviewers':[]}
        for t in tasks for m in t['allowed_models']])
    groups=collections.defaultdict(list)
    for t in tasks:groups[t['source_group_id']].append(t['task_id'])
    write_jsonl(OUT/'source_groups.jsonl',[{'source_group_id':g,'task_ids':ids,
        'disposition':'development_reserved' if g in reserved else 'unassigned',
        'independence_verified':False} for g,ids in sorted(groups.items())])
    stats={'dataset_status':'candidate_only_not_formal_v5_replication','tasks':len(tasks),'categories':dict(counts),
        'source_groups':len(groups),'groups_by_category':{c:len({t['source_group_id'] for t in tasks if t['category']==c}) for c in CATEGORIES},
        'split_counts':dict(collections.Counter(t['split'] for t in tasks)), 'dev_export_tasks':len(dev),
        'independent_calibration_units_verified':0,'model_calls':0,'human_quality_labels':0,
        'formal_split_ready':False,'human_verified_references':0,
        'uci_source_rows':len(matrix),'martts_source_dialogs':len(dialogs),
        'paper_target':{'formal_tasks':1500,'separate_development_tasks':100,
                        'formal_split_sizes':{'D_Q':400,'D_G':200,'D_V':200,'D_C':400,'D_T':300}},
        'warning':'1600 candidates are NOT 1500 formal tasks + 100 independent development tasks. Source/template diversity and human review remain insufficient.'}
    (OUT/'statistics.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
    # Offline reader shows a small review sample; never a runtime input file.
    cards=[]
    lookup={r['task_id']:r for r in refs}
    for t in dev:
        cards.append('<article><h2>'+html.escape(CATEGORIES[t['metadata']['category']])+'</h2><p>'+html.escape(t['task_id'])+'</p><p>'+html.escape(t['question'])+'</p><h3>固定证据</h3><pre>'+html.escape(json.dumps(json.loads(t['evidence']),ensure_ascii=False,indent=2))+'</pre><details><summary>审阅用参考答案（不能传给路由器）</summary><pre>'+html.escape(json.dumps(lookup[t['task_id']]['reference'],ensure_ascii=False,indent=2))+'</pre></details></article>')
    (OUT/'PREVIEW.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>v5 候选数据预览</title><style>body{font:17px/1.65 system-ui;max-width:1000px;margin:35px auto;padding:15px;background:#f5f7fa;color:#152537}article{background:white;padding:25px;margin:25px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}summary{cursor:pointer;color:#165c99}</style><h1>v5公开来源候选数据 · 20条审阅样例</h1><p>共1600条候选任务，五类各320条。尚非正式实验集：无模型回答、人工质量分或实测资源；全部参考答案待人工核验。数据含真实观测、仿真和合成通信，严格保留来源区别。</p>'+''.join(cards)+'</html>',encoding='utf-8')
    files={str(p.relative_to(DATA)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATA.rglob('*')) if p.is_file() and p.name!='file_hashes.json'}
    (DATA/'file_hashes.json').write_text(json.dumps(files,indent=2)+'\n')
    print(json.dumps(stats,ensure_ascii=False,indent=2))

if __name__=='__main__':
    build()
