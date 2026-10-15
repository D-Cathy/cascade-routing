import json
from pathlib import Path
import pytest
from selection.replay import load_config, run
from selection.replay_data import load_dataset

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"configs/small_replay.json"

def copied(tmp_path):
    cfg,data=load_config(CONFIG)
    paths=[]
    for name in ["tasks","calls","labels"]:
        src=ROOT/"data/small_replay"/(name+".jsonl")
        dst=tmp_path/(name+".jsonl");dst.write_bytes(src.read_bytes());paths.append(dst)
    return cfg,paths

def edit(path, fn):
    rows=[json.loads(s) for s in path.read_text().splitlines()]
    fn(rows)
    path.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows))

def test_fixture_loads_and_splits():
    cfg,data=load_config(CONFIG)
    assert len(data.tasks)==10 and len(data.calls)==30 and len(data.labels)==30
    assert {t["source_group_id"] for t in data.tasks if t["split"]=="dev_fit"}.isdisjoint({t["source_group_id"] for t in data.tasks if t["split"]=="dev_eval"})

@pytest.mark.parametrize("kind", ["duplicate_task","group_leakage","negative_cost","nan_latency","false_provenance","future_environment","label_in_task","duplicate_call","invalid_quality","missing_call","empty_success","unknown_model","missing_quality_source","duplicate_label"])
def test_reject_bad_files(tmp_path,kind):
    cfg,paths=copied(tmp_path);tasks,calls,labels=paths
    mutations={
      "duplicate_task":(tasks,lambda rows:rows.append(rows[0])),
      "group_leakage":(tasks,lambda rows:rows[4].update(source_group_id=rows[0]["source_group_id"])),
      "negative_cost":(calls,lambda rows:rows[0].update(cost=-1)),
      "nan_latency":(calls,lambda rows:rows[0].update(latency_s=float("nan"))),
      "false_provenance":(calls,lambda rows:rows[0].update(latency_source="measured")),
      "future_environment":(tasks,lambda rows:rows[0].update(environment={"future_answer":"secret"})),
      "label_in_task":(tasks,lambda rows:rows[0].update(quality=.99)),
      "duplicate_call":(calls,lambda rows:rows.append(rows[0])),
      "invalid_quality":(labels,lambda rows:rows[0].update(quality=2)),
      "missing_call":(calls,lambda rows:rows.pop()),
      "empty_success":(calls,lambda rows:rows[0].update(answer="")),
      "unknown_model":(tasks,lambda rows:rows[0].update(allowed_models=["unknown"])),
      "missing_quality_source":(labels,lambda rows:rows[0].update(quality=None)),
      "duplicate_label":(labels,lambda rows:rows.append(rows[0])),
    }
    edit(*mutations[kind])
    with pytest.raises(ValueError):load_dataset(*paths,list(cfg["models"]))

def test_batch_artifacts_and_missing_labels(tmp_path):
    result=run(CONFIG,tmp_path/"run")
    assert len(result)==5
    assert all(v["n_requests"]==6 for v in result.values())
    assert all(v["service_failure_rate"] is None for v in result.values())
    manifest=json.loads((tmp_path/"run/manifest.json").read_text())
    assert manifest["original_cascade_predict_calls"]>0 and not manifest["risk_guarantee"]
    traces=[json.loads(s) for s in (tmp_path/"run/traces.jsonl").read_text().splitlines()]
    assert len(traces)==30
    assert all(len(t["model_calls"])<=3 for t in traces)
    with pytest.raises(FileExistsError):run(CONFIG,tmp_path/"run")

def test_seed_reproduces_semantics(tmp_path):
    a=run(CONFIG,tmp_path/"a");b=run(CONFIG,tmp_path/"b")
    assert a==b
    def normalize(path):
        rows=[json.loads(s) for s in path.read_text().splitlines()]
        for row in rows:row.pop("measured_controller_time")
        return rows
    assert normalize(tmp_path/"a/traces.jsonl")==normalize(tmp_path/"b/traces.jsonl")

def test_eval_labels_cannot_affect_baseline_routes(tmp_path):
    cfg,paths=copied(tmp_path)
    for name,path in zip(["tasks","calls","labels"],paths):cfg[name]=str(path)
    conf=tmp_path/"config.json";conf.write_text(json.dumps(cfg))
    run(conf,tmp_path/"a")
    def mutate(rows):
        for row in rows:
            if int(row["task_id"].split("-")[-1])>=4 and row["quality"] is not None:row["quality"]=1-row["quality"]
    edit(paths[2],mutate)
    run(conf,tmp_path/"b")
    def routes(path):
        rows=[json.loads(s) for s in path.read_text().splitlines()]
        return [(r["policy"],r["request_id"],r["decisions"],r["final_model"],r["final_answer"]) for r in rows]
    assert routes(tmp_path/"a/traces.jsonl")==routes(tmp_path/"b/traces.jsonl")

def test_unattempted_is_not_failure_or_free_response(tmp_path):
    cfg,paths=copied(tmp_path)
    edit(paths[1],lambda rows:rows[12].update(status="UNATTEMPTED",answer=None,latency_s=None,cost=None,latency_source="missing",cost_source="missing"))
    load_dataset(*paths,list(cfg["models"]))
    for name,path in zip(["tasks","calls","labels"],paths):cfg[name]=str(path)
    conf=tmp_path/"config.json";conf.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match="Replay unavailable"):run(conf,tmp_path/"out")
    assert not (tmp_path/"out").exists()
