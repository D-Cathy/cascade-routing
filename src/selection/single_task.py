"""One development task: validate -> collect once -> blind annotate -> evaluate.
Default validation is offline. Collection must explicitly choose --mock or --live.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
from dataclasses import asdict
from .schema import ModelLevel, ModelStatus, ModelCallRecord, TraceRecord
from .executor import UnifiedExecutor
from .policies import FixedOrderPolicy
from .live_backend import AttemptLedger, LiveModel, SingleHTTPTransport
from .mock_backend import MockTransport
from .replay_data import fields, number, strings, validate_tasks, load_dataset, read_jsonl
from .metrics import evaluate_terminal, aggregate

NAMES=["ship","shore","cloud"]

def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n")

def jsonl(path,rows):
    with Path(path).open("w") as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n")

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_inputs(task_path,deployment_path,mock=False):
    task=json.loads(Path(task_path).read_text());validate_tasks([task],NAMES)
    if task["allowed_models"]!=NAMES:raise ValueError("Independent three-model collection needs all three explicitly allowed roles")
    if task["source"]!=("synthetic" if mock else "real_development"):raise ValueError("Task provenance does not match mock/live collection")
    deployment=json.loads(Path(deployment_path).read_text())
    fields(deployment,["schema_version","mode","attempt_ledger","cost_scope","cost_unit","models","authorization"])
    if deployment["schema_version"]!=1 or deployment["mode"]!=("mock" if mock else "live"):raise ValueError("Invalid deployment mode/version")
    if deployment["cost_scope"]!="provider_token_fee_only" or deployment["cost_unit"]!=task["service"]["cost_unit"]:raise ValueError("Cost scope/unit mismatch")
    strings(deployment,["attempt_ledger","cost_unit"])
    if set(deployment["models"])!=set(NAMES):raise ValueError("All three model roles required")
    auth=deployment["authorization"]
    fields(auth,["approved","max_model_attempts","fee_limit","note"])
    if type(auth["approved"]) is not bool or type(auth["max_model_attempts"]) is not int or auth["max_model_attempts"]!=3:raise ValueError("Exactly three collection attempts required")
    number(auth["fee_limit"],"fee_limit",nullable=mock)
    if not mock and not auth["approved"]:raise ValueError("Live collection authorization incomplete")
    if not mock and auth["fee_limit"] <= 0:raise ValueError("Positive authorized fee limit required")
    if not mock and (not isinstance(auth["note"],str) or not auth["note"].strip()):raise ValueError("Record authorized fee scope and unknown-billing limitation")
    for name,cfg in deployment["models"].items():
        fields(cfg,["model_id","model_version","endpoint","api_key_env","timeout_s","max_tokens","temperature","seed","pricing","validation","required_fields"], ["scenario"])
        strings(cfg,["model_id","model_version","validation"])
        if not mock:
            strings(cfg,["endpoint"])
            # URL/credential configuration is checked WITHOUT any HTTP request.
            SingleHTTPTransport(cfg["endpoint"],cfg["api_key_env"])
        if cfg["pricing"] is not None and cfg["pricing"].get("currency")!=deployment["cost_unit"]:raise ValueError("Pricing currency mismatch")
        # Validate model configuration without opening a ledger or transport.
        LiveModel(name,ModelLevel(name),cfg["model_id"],cfg["model_version"],None,None,
                  **{k:cfg[k] for k in ["timeout_s","max_tokens","temperature","seed","pricing","validation","required_fields"]})
    return task,deployment

def collect(task_path,deployment_path,output,mock=False):
    task,deployment=load_inputs(task_path,deployment_path,mock)
    out=Path(output)
    if out.exists():raise FileExistsError("Output directory exists; do not overwrite or resend")
    ledger_path=(Path(deployment_path).resolve().parent/deployment["attempt_ledger"]).resolve()
    ledger=AttemptLedger(ledger_path)
    if any(ledger.contains(task["task_id"],n) for n in NAMES):raise ValueError("Task has reserved/completed attempts; recover artifacts from ledger, do not resend")
    out.mkdir(parents=True)
    dump(out/"task.json",task);jsonl(out/"tasks.jsonl",[task])
    traces=[];calls=[];spent=0.0;blocked=False
    public={k:task[k] for k in ["task_id","source_group_id","question","evidence","allowed_models"]}
    public["environment"]=task.get("environment",{})
    for name in NAMES:
        cfg=deployment["models"][name]
        # Collection is three INDEPENDENT fixed-model requests, not one routed path.
        # A known fee overrun or unknown bill stops the collection campaign.
        if deployment["authorization"]["fee_limit"] is not None and spent >= deployment["authorization"]["fee_limit"]:
            blocked=True
        if blocked:
            calls.append({"schema_version":1,"task_id":task["task_id"],"model_name":name,"model_version":cfg["model_version"],
                          "status":"UNATTEMPTED","answer":None,"latency_s":None,"cost":None,"latency_source":"missing","cost_source":"missing",
                          "data_source":task["source"],"reason":"collection_fee_guard","metadata":{}})
            continue
        transport=MockTransport(cfg.get("scenario","success")) if mock else SingleHTTPTransport(cfg["endpoint"],cfg["api_key_env"])
        model=LiveModel(name,ModelLevel(name),cfg["model_id"],cfg["model_version"],transport,ledger,
                        **{k:cfg[k] for k in ["timeout_s","max_tokens","temperature","seed","pricing","validation","required_fields"]},
                        data_source=task["source"])
        svc=task["service"]
        trace=UnifiedExecutor([model],svc["deadline_s"],svc["budget"],svc["quality_threshold"],
                              policy=FixedOrderPolicy([name]),decision_timing="measured",execution_timing="wall_clock").execute(
                              {**public,"allowed_models":[name]})
        traces.append({"role":name,"trace":asdict(trace)})
        if trace.model_calls:
            c=trace.model_calls[0]
            calls.append({"schema_version":1,"task_id":task["task_id"],"model_name":name,"model_version":c.model_version,
                          "status":c.status.value,"answer":c.answer,"latency_s":c.latency,"cost":c.cost,
                          "latency_source":c.latency_source,"cost_source":c.cost_source,"data_source":c.data_source,"reason":c.reason,
                          "metadata":{**c.metadata,"known_cost_lower_bound":c.known_cost,"collection_mode":"independent_fixed_model",
                                      "request_total_time_s":trace.total_time,"controller_time_s":trace.measured_controller_time}})
            spent+=c.cost if c.cost is not None else c.known_cost
            blocked=c.cost is None or (deployment["authorization"]["fee_limit"] is not None and spent>=deployment["authorization"]["fee_limit"])
        else:
            calls.append({"schema_version":1,"task_id":task["task_id"],"model_name":name,"model_version":cfg["model_version"],
                          "status":"UNATTEMPTED","answer":None,"latency_s":None,"cost":None,"latency_source":"missing","cost_source":"missing",
                          "data_source":task["source"],"reason":trace.stop_reason,"metadata":{}})
        # Incremental persistence after every result; pending attempts survive crashes.
        jsonl(out/"traces.jsonl",traces);jsonl(out/"calls.jsonl",calls)
    jsonl(out/"calls.jsonl",calls)
    labels=[{"schema_version":1,"task_id":task["task_id"],"model_name":n,"quality":None,"valid":None,"label_source":"missing","rubric_version":"paper-development-draft-v1"} for n in NAMES]
    jsonl(out/"labels.pending.jsonl",labels)
    shuffled=list(calls);random.Random(20260924).shuffle(shuffled)
    cards=[];mapping={}
    for i,c in enumerate(shuffled):
        blind_id=f"answer-{i+1:03d}"
        mapping[blind_id]={"task_id":task["task_id"],"model_name":c["model_name"],"status":c["status"]}
        cards.append({"blind_answer_id":blind_id,"question":task["question"],"evidence":task["evidence"],"answer":c["answer"],
                      "rubric_version":"paper-development-draft-v1","reference_evidence_locations":None,
                      "reviews":[{"reviewer":None,"scores":[None,None,None],"valid":None,"veto":None},
                                 {"reviewer":None,"scores":[None,None,None],"valid":None,"veto":None}],
                      "adjudication":None})
    jsonl(out/"annotation_cards.jsonl",cards)
    dump(out/"private_annotation_map.json",mapping)
    dump(out/"manifest.json",{"mode":"mock_backend_validation" if mock else "real_development_collection",
        "real_model_calls_executed":not mock,"risk_guarantee":False,"task_sha256":digest(task_path),"deployment_sha256":digest(deployment_path),
        "attempt_ledger":str(ledger_path),"attempted_models":[c["model_name"] for c in calls if c["status"]!="UNATTEMPTED"],
        "unattempted_models":[c["model_name"] for c in calls if c["status"]=="UNATTEMPTED"],
        "collection_complete":all(c["status"]!="UNATTEMPTED" for c in calls),
        "known_provider_fee_lower_bound":spent,"cost_scope":"provider_token_fee_only_not_paper_normalized_cost",
        "control_monetary_cost":"not_monetized; control time measured",
        "campaign_stopped_for_billing":blocked,"limitation":"independent model captures are not sequential network replay; remote cancellation/billing cap unverified",
        "code_sha256":{p.name:digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}})
    # Verify exports with the SAME loader used by offline experiments.
    load_dataset(out/"tasks.jsonl",out/"calls.jsonl",out/"labels.pending.jsonl",NAMES)
    return out

def grade(review):
    fields(review,["reviewer","scores","valid","veto"])
    strings(review,["reviewer"])
    scores=review["scores"]
    if not isinstance(scores,list) or len(scores)!=3 or any(type(s) is not int or not 0<=s<=4 for s in scores):raise ValueError("Three integer scores 0..4 required")
    if type(review["valid"]) is not bool or type(review["veto"]) is not bool:raise ValueError("Validity and veto required")
    return 0.0 if review["veto"] else (.5*scores[0]+.3*scores[1]+.2*scores[2])/4

def evaluate(collection,cards_path,output):
    folder=Path(collection);out=Path(output)
    if out.exists():raise FileExistsError("Evaluation output exists")
    task=json.loads((folder/"task.json").read_text());mapping=json.loads((folder/"private_annotation_map.json").read_text())
    cards=read_jsonl(cards_path);original={c["blind_answer_id"]:c for c in read_jsonl(folder/"annotation_cards.jsonl")}
    if len(cards)!=len(mapping) or {c["blind_answer_id"] for c in cards}!=set(mapping):raise ValueError("Annotation card IDs must match exactly")
    labels=[]
    for card in cards:
        key=card["blind_answer_id"];ref=original[key]
        for field in ["question","evidence","answer","rubric_version"]:
            if card[field]!=ref[field]:raise ValueError("Annotation input changed")
        reviews=card["reviews"]
        if len(reviews)!=2:raise ValueError("Two independent reviews required")
        qs=[grade(v) for v in reviews]
        if reviews[0]["reviewer"]==reviews[1]["reviewer"]:raise ValueError("Distinct reviewers required")
        if not card["reference_evidence_locations"]:raise ValueError("Evidence references required")
        disagree=any(reviews[0][k]!=reviews[1][k] for k in ["scores","valid","veto"])
        chosen=card.get("adjudication")
        if disagree and chosen is None:raise ValueError("Disagreement requires adjudication")
        chosen=chosen or reviews[0];q=grade(chosen)
        info=mapping[key]
        labels.append({"schema_version":1,"task_id":info["task_id"],"model_name":info["model_name"],"quality":q,
                       "valid":chosen["valid"],"label_source":"synthetic_diagnostic" if task["source"]=="synthetic" else "human_dual_review",
                       "rubric_version":card["rubric_version"],"metadata":{"reviews":reviews,"adjudication":card.get("adjudication"),
                       "evidence_locations":card["reference_evidence_locations"],"blind_answer_id":key}})
    out.mkdir(parents=True);jsonl(out/"labels.jsonl",labels)
    load_dataset(folder/"tasks.jsonl",folder/"calls.jsonl",out/"labels.jsonl",NAMES)
    quality={v["model_name"]:v["quality"] for v in labels};valid={v["model_name"]:v["valid"] for v in labels}
    traces=[];results={}
    for row in read_jsonl(folder/"traces.jsonl"):
        data=row["trace"];data["model_calls"]=[ModelCallRecord(**c) for c in data["model_calls"]]
        trace=TraceRecord(**data);svc=task["service"]
        evaluate_terminal(trace,svc["quality_threshold"],svc["deadline_s"],svc["budget"],quality,valid)
        traces.append({"role":row["role"],"trace":asdict(trace)});results[row["role"]]=aggregate([trace])
    jsonl(out/"evaluated_traces.jsonl",traces);dump(out/"summary.json",results)
    dump(out/"manifest.json",{"collection_manifest_sha256":digest(folder/"manifest.json"),"annotation_sha256":digest(cards_path),
                             "real_model_calls_executed_by_evaluation":False,"risk_guarantee":False,
                             "unevaluated_roles":[n for n in NAMES if n not in results]})
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    for name in ["validate","collect"]:
        p=sub.add_parser(name);p.add_argument("--task",required=True);p.add_argument("--deployment",required=True)
        mode=p.add_mutually_exclusive_group(required=True);mode.add_argument("--mock",action="store_true");mode.add_argument("--live",action="store_true")
        if name=="collect":p.add_argument("--output",required=True)
    p=sub.add_parser("evaluate");p.add_argument("--collection",required=True);p.add_argument("--cards",required=True);p.add_argument("--output",required=True)
    args=parser.parse_args()
    if args.command=="validate":
        load_inputs(args.task,args.deployment,args.mock);print("Validated locally; no model calls made")
    elif args.command=="collect":
        print(collect(args.task,args.deployment,args.output,args.mock))
    else:print(json.dumps(evaluate(args.collection,args.cards,args.output),ensure_ascii=False))

if __name__=="__main__":main()
