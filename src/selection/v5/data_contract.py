"""Task-only v2 contract. Labels and cached future responses are never inputs."""
from copy import deepcopy
from ..replay_data import fields, strings

SPLITS=('development','D_Q','D_G','D_V','D_C','D_T')
REQUIRED=('schema_version','task_id','source_group_id','source_id','source_sample_id',
          'template_family','category','question','evidence','allowed_models','split','provenance')

def validate_tasks(tasks):
    if not tasks:raise ValueError('Empty dataset')
    seen=set();groups={}
    for t in tasks:
        fields(t,REQUIRED)
        strings(t,['task_id','source_group_id','source_id','source_sample_id','category','question','provenance'])
        if type(t['schema_version']) is not int or t['schema_version']!=2:raise ValueError('Expected schema_version=2')
        if not isinstance(t['evidence'],str):raise ValueError('Evidence must be fixed text')
        if t['template_family'] is not None and (not isinstance(t['template_family'],str) or not t['template_family'].strip()):raise ValueError('Invalid template family')
        if t['split'] not in (*SPLITS,'unassigned'):raise ValueError('Unknown split')
        if t['task_id'] in seen:raise ValueError('Duplicate task ID')
        seen.add(t['task_id'])
        allowed=t['allowed_models']
        if not isinstance(allowed,list) or not allowed or any(n not in ['ship','shore','cloud'] for n in allowed) or len(set(allowed))!=len(allowed):raise ValueError('Invalid model roles')
        g=t['source_group_id']
        if t['split']!='unassigned':
            if g in groups and groups[g]!=t['split']:raise ValueError('Source group crosses splits')
            groups[g]=t['split']
    return tasks

def controller_input(task):
    validate_tasks([task])
    return deepcopy({k:task[k] for k in ['task_id','source_group_id','question','evidence','allowed_models']})

def training_tasks(tasks,stage):
    """Narrow training boundary; calibration/test never accepted as training stages."""
    validate_tasks(tasks)
    permitted={'score':'D_Q','dynamics':'D_G','tuning':'D_V'}
    if stage not in permitted:raise ValueError('Unsupported training stage')
    return deepcopy([t for t in tasks if t['split']==permitted[stage]])
