"""Versioned strict JSONL boundaries; labels are a separate evaluation-side table."""
import json
import math
from pathlib import Path
from dataclasses import dataclass

SOURCES = {"synthetic", "engineering_cache", "real_development"}
PROVENANCE = {"simulated", "measured", "derived", "missing"}

def read_jsonl(path):
    records = []
    with Path(path).open(encoding="utf-8") as f:
        for i, line in enumerate(f,1):
            if not line.strip(): continue
            try: records.append(json.loads(line))
            except ValueError as exc: raise ValueError(f"{path}:{i}: invalid JSON") from exc
    return records

def fields(record, required, optional=()):
    if not isinstance(record,dict) or set(required)-record.keys() or record.keys()-set(required)-set(optional):
        raise ValueError(f"Invalid fields; required={required}, received={list(record) if isinstance(record,dict) else type(record)}")

def number(value, name, nullable=False, maximum=None):
    if value is None and nullable:return
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (maximum is not None and value>maximum):
        raise ValueError(f"Invalid {name}: expected finite nonnegative number" )

def strings(record, names):
    for name in names:
        if not isinstance(record[name],str) or not record[name].strip():raise ValueError(f"Missing string: {name}")

@dataclass
class ReplayDataset:
    tasks: list
    calls: dict
    labels: dict
    paths: list

def validate_tasks(tasks, model_names):
    if not tasks: raise ValueError("No tasks")
    task_map, group_splits = {}, {}
    for t in tasks:
        fields(t, ["schema_version","task_id","source_group_id","source","split","question","evidence","allowed_models","service"], ["environment","metadata"])
        strings(t,["task_id","source_group_id","question"])
        if t["schema_version"]!=1 or t["source"] not in SOURCES or t["split"] not in {"dev_fit","dev_eval"}:raise ValueError("Only version 1 development/engineering splits accepted")
        if not isinstance(t["evidence"],str):raise ValueError("Evidence must be fixed text")
        if t["task_id"] in task_map:raise ValueError("Duplicate task ID")
        task_map[t["task_id"]]=t
        group=t["source_group_id"]
        if group in group_splits and group_splits[group]!=t["split"]:raise ValueError("Source-group leakage across fit/eval")
        group_splits[group]=t["split"]
        allowed=t["allowed_models"]
        if not isinstance(allowed,list) or any(not isinstance(n,str) for n in allowed) or len(allowed)!=len(set(allowed)) or set(allowed)-set(model_names):raise ValueError("Invalid allowed models")
        fields(t["service"],["quality_threshold","deadline_s","budget","cost_unit","risk_target"])
        number(t["service"]["quality_threshold"],"quality_threshold",maximum=1)
        number(t["service"]["risk_target"],"risk_target",maximum=1)
        for key in ("deadline_s","budget"):number(t["service"][key],key)
        strings(t["service"],["cost_unit"])
        # Only predeclared observable environment fields can reach the controller.
        env=t.get("environment",{})
        fields(env,[],["network_regime","bandwidth_mbps","queue_depth","observed_at_s"])
        for key in ("bandwidth_mbps","queue_depth","observed_at_s"):
            if key in env:number(env[key],key,nullable=True)
        if "network_regime" in env and not isinstance(env["network_regime"],str):raise ValueError("Invalid regime")
    return task_map

def load_dataset(tasks_path, calls_path, labels_path, model_names):
    tasks, calls, labels = read_jsonl(tasks_path), read_jsonl(calls_path), read_jsonl(labels_path)
    task_map = validate_tasks(tasks, model_names)
    indexed={}
    for c in calls:
        fields(c,["schema_version","task_id","model_name","model_version","status","answer","latency_s","cost","latency_source","cost_source","data_source","reason"], ["metadata"])
        strings(c,["task_id","model_name","model_version"])
        key=(c["task_id"],c["model_name"])
        if c["schema_version"]!=1 or key in indexed or key[0] not in task_map or key[1] not in model_names:raise ValueError("Invalid/duplicate call key")
        if c["status"] not in {"UNATTEMPTED","SUCCESS","FAILED","INVALID"} or c["data_source"] not in SOURCES:raise ValueError("Invalid call status/source")
        if c["data_source"]!=task_map[key[0]]["source"]:raise ValueError("Task/call provenance mismatch")
        if c["answer"] is not None and not isinstance(c["answer"],str):raise ValueError("Answer must be text or null")
        if c["status"]=="SUCCESS" and not (c["answer"] or "").strip():raise ValueError("SUCCESS requires nonempty observed-valid answer")
        if c["status"] in {"FAILED","UNATTEMPTED"} and c["answer"] is not None:raise ValueError("Failed/unattempted record cannot contain answer")
        if c["status"]=="UNATTEMPTED" and (c["cost"] is not None or c["latency_s"] is not None):raise ValueError("Unattempted is not an executed zero-cost call")
        for field,source in [("latency_s","latency_source"),("cost","cost_source")]:
            number(c[field],field,nullable=True)
            if c[source] not in PROVENANCE or ((c[field] is None)!=(c[source]=="missing")):raise ValueError("Resource provenance/missing mismatch")
            if c["data_source"]=="synthetic" and c[source]=="measured":raise ValueError("Synthetic resources cannot be measured")
        indexed[key]=c
    # An absent counterfactual record cannot silently turn into availability=false.
    expected={(t["task_id"],n) for t in tasks for n in t["allowed_models"]}
    if expected-indexed.keys():raise ValueError("Missing replay record; explicit UNATTEMPTED required")
    label_map={}
    for label in labels:
        fields(label,["schema_version","task_id","model_name","quality","valid","label_source","rubric_version"],["metadata"])
        strings(label,["label_source","rubric_version"])
        key=(label["task_id"],label["model_name"])
        if label["schema_version"]!=1 or key in label_map or key not in indexed:raise ValueError("Invalid/duplicate label key")
        number(label["quality"],"quality",nullable=True,maximum=1)
        if label["valid"] is not None and type(label["valid"]) is not bool:raise ValueError("Invalid validity label")
        if label["quality"] is None and label["label_source"]!="missing":raise ValueError("Unobserved quality must be marked missing")
        if label["quality"] is not None and label["label_source"]=="missing":raise ValueError("Observed quality has missing provenance")
        label_map[key]=label
    return ReplayDataset(tasks,indexed,label_map,[str(tasks_path),str(calls_path),str(labels_path)])
