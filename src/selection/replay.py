"""Small offline-only batch entry point: python -m selection.replay --config ..."""
import argparse
import hashlib
import json
import platform
import random
import sys
from pathlib import Path
from dataclasses import asdict
import numpy as np
from .replay_data import load_dataset, fields, number
from .executor import OfflineModel, UnifiedExecutor
from .schema import ModelLevel, ServiceFailureReason, RequestStatus
from .policies import FixedOrderPolicy
from .cascade_adapter import CascadeRouterAdapter
from .metrics import aggregate

POLICIES = ["fixed_ship", "fixed_shore", "fixed_cloud", "fixed_cascade_fallback", "cascade_router_devmean"]

def dump(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

def load_config(path):
    path=Path(path).resolve();cfg=json.loads(path.read_text())
    fields(cfg,["schema_version","seed","tasks","calls","labels","models","policies","decision_timing","decision_overhead_s","decision_cost","cascade_max_expected_cost","purpose"])
    if cfg["schema_version"]!=1 or type(cfg["seed"]) is not int:raise ValueError("Invalid configuration version/seed")
    if cfg["purpose"]!="engineering_validation_only":raise ValueError("This entry point has no calibrated paper-experiment mode")
    if cfg["models"]!={"ship":"ship","shore":"shore","cloud":"cloud"}:raise ValueError("Exactly three declared roles required")
    if not cfg["policies"] or len(set(cfg["policies"]))!=len(cfg["policies"]) or set(cfg["policies"])-set(POLICIES):raise ValueError("Unknown/duplicate policy; not silently substituted")
    if cfg["decision_timing"] not in {"simulated","measured"}:raise ValueError("Invalid timing mode")
    for key in ["decision_overhead_s","decision_cost","cascade_max_expected_cost"]:number(cfg[key],key)
    data=load_dataset(*(path.parent/cfg[k] for k in ["tasks","calls","labels"]),list(cfg["models"]))
    if len({t["service"]["cost_unit"] for t in data.tasks})!=1:raise ValueError("Incompatible cost units")
    return cfg,data

def fit_adapter(cfg,data):
    fit=[t for t in data.tasks if t["split"]=="dev_fit"]
    if not fit:raise ValueError("CascadeRouter engineering predictor requires separate dev_fit samples")
    qs,cs=[],[]
    names=list(cfg["models"])
    for t in fit:
        q,c=[],[]
        for name in names:
            key=(t["task_id"],name)
            record=data.calls.get(key); label=data.labels.get(key)
            if record is None or label is None or record["status"]!="SUCCESS" or label["valid"] is not True or label["quality"] is None or record["cost"] is None:
                raise ValueError("Mean-predictor demo fit needs complete valid labeled calls/resources")
            q.append(label["quality"]);c.append(record["cost"])
        qs.append(q);cs.append(c)
    return CascadeRouterAdapter.fit_development_means(names,qs,cs,cfg["cascade_max_expected_cost"])

def make_models(cfg,data,task):
    models=[]
    for name,level in cfg["models"].items():
        c=data.calls.get((task["task_id"],name))
        if c is None or c["status"]=="UNATTEMPTED":
            # A permitted but uncollected response is missing data, NOT a known outage.
            if name in task["allowed_models"]:raise ValueError(f"Replay unavailable for permitted {task['task_id']}/{name}; collect it or narrow permissions explicitly")
            models.append(OfflineModel(name,ModelLevel(level),None,None,available=False));continue
        models.append(OfflineModel(name,ModelLevel(level),c["latency_s"],c["cost"],
            fail_probability=int(c["status"]=="FAILED"),invalid_after_answer=c["status"]=="INVALID",
            response_text=c["answer"],model_version=c["model_version"],data_source=c["data_source"],
            latency_source=c["latency_source"],cost_source=c["cost_source"],use_default_answer=False,replay_reason=c["reason"]))
    return models

def run(config_path,output):
    cfg,data=load_config(config_path)
    random.seed(cfg["seed"]);np.random.seed(cfg["seed"])
    eval_tasks=[t for t in data.tasks if t["split"]=="dev_eval"]
    if not eval_tasks:raise ValueError("No evaluation tasks")
    # Validate all required replay records and fit readiness before creating outputs.
    for t in eval_tasks:make_models(cfg,data,t)
    adapter=fit_adapter(cfg,data) if "cascade_router_devmean" in cfg["policies"] else None
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    summaries={}; counts={};rows=[]
    for policy_name in cfg["policies"]:
        traces=[]
        for task in eval_tasks:
            if policy_name=="cascade_router_devmean": policy=adapter
            elif policy_name=="fixed_cascade_fallback":policy=FixedOrderPolicy(list(cfg["models"]))
            else:policy=FixedOrderPolicy([policy_name.removeprefix("fixed_")])
            svc=task["service"]
            executor=UnifiedExecutor(make_models(cfg,data,task),svc["deadline_s"],svc["budget"],svc["quality_threshold"],
                policy=policy,decision_overhead=cfg["decision_overhead_s"],decision_timing=cfg["decision_timing"],decision_cost=cfg["decision_cost"])
            # Whitelisted public request: metadata/reference fields never pass this boundary.
            public={k:task[k] for k in ["task_id","source_group_id","question","evidence","allowed_models"]}
            public["environment"]=task.get("environment",{})
            labels={n:data.labels.get((task["task_id"],n),{}).get("quality") for n in cfg["models"]}
            trace=executor.execute(public,evaluation_labels=labels)
            if trace.final_model is not None:
                label=data.labels.get((task["task_id"],trace.final_model),{})
                trace.final_valid = label.get("valid")
                if trace.final_valid is False:
                    trace.final_quality = 0.0
                    trace.mark_failure(ServiceFailureReason.NO_VALID_ANSWER)
                    if svc["quality_threshold"] > 0:trace.mark_failure(ServiceFailureReason.LOW_QUALITY)
                elif label.get("valid") is None:
                    trace.unknown_checks.append("evaluated_validity")
                    if not trace.failure_reasons:trace.status=RequestStatus.INDETERMINATE
            traces.append(trace)
            row=asdict(trace);row.update(policy=policy_name,source=task["source"],service=svc,service_failure=trace.service_failure)
            rows.append(row)
        summaries[policy_name]=aggregate(traces)
        counts[policy_name]=len(traces)
    with (output/"traces.jsonl").open("w",encoding="utf-8") as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n")
    dump(output/"summary.json",summaries)
    files=[Path(config_path).resolve(),*(Path(p) for p in data.paths)]
    code_files=sorted(Path(__file__).parent.glob("*.py"))
    manifest={"config":cfg,"input_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "code_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files},
        "host":platform.node(),"python":sys.version,"seed":cfg["seed"],"risk_guarantee":False,
        "fit_task_ids":[t["task_id"] for t in data.tasks if t["split"]=="dev_fit"],
        "eval_task_ids":[t["task_id"] for t in eval_tasks],
        "fit_groups":sorted({t["source_group_id"] for t in data.tasks if t["split"]=="dev_fit"}),
        "eval_groups":sorted({t["source_group_id"] for t in eval_tasks}),
        "policy_counts":counts,"original_cascade_predict_calls":adapter.predict_calls if adapter else 0,
        "limitations":["engineering validation only; no real experiment or calibration", "fixed cascade uses latest-valid fallback and exhausts its order, not the paper threshold baseline", "CascadeRouter uses original core with development-mean predictors; original estimator reproduction incomplete", "serial static replay; no time-indexed network or live cancellation", "decision cost/overhead are configured simulated values unless timing explicitly measured"],
        "not_implemented":["paper_fixed_threshold_with_trained_scorer","paper_original_estimator_adaptation","rule_router","learned_single_router","greedy_upgrade","full_planner","independent_calibration","live_no_retry_backend"]}
    if adapter:
        manifest["cascade_fit"]={"quality_means":adapter.router.quality_computer.means.tolist(),"cost_means":adapter.router.cost_computer.means.tolist(),"lambdas":adapter.router.lambdas,"gamma":float(adapter.router.gamma),"tuning":"none; fixed zero lambdas, fit gamma on dev_fit only"}
    dump(output/"manifest.json",manifest)
    print(json.dumps({"output":str(output),"requests_per_policy":len(eval_tasks),"policies":len(summaries),"risk_guarantee":False}))
    return summaries

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",required=True);p.add_argument("--output");p.add_argument("--validate-only",action="store_true")
    args=p.parse_args()
    if args.validate_only:
        cfg,data=load_config(args.config)
        print(json.dumps({"valid":True,"tasks":len(data.tasks),"calls":len(data.calls),"labels":len(data.labels)}));return
    if not args.output:p.error("--output required unless --validate-only")
    run(args.config,args.output)

if __name__=="__main__":main()
