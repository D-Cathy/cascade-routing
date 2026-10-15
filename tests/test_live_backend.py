import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from selection.live_backend import AttemptLedger, LiveModel, SingleHTTPTransport
from selection.mock_backend import MockTransport
from selection.schema import CallNotStartedError, ModelLevel, ModelStatus, ServiceFailureReason
from selection.executor import UnifiedExecutor
from selection.policies import FixedOrderPolicy
from selection.single_task import collect, evaluate, load_inputs

ROOT=Path(__file__).resolve().parents[1]
PRICING={"input_per_million":1,"output_per_million":2,"currency":"USD","source":"test-only","usage_is_complete":True}

def model(tmp_path,scenario="success",**kw):
    return LiveModel("ship",ModelLevel.SHIP,"fake","fake-v1",kw.pop("transport",MockTransport(scenario)),
                     AttemptLedger(tmp_path/"attempts.sqlite3"),pricing=PRICING,
                     validation="json_fields",required_fields=["action","condition","deadline"],**kw)

def execute(m,task_id="test-task",deadline=5):
    return UnifiedExecutor([m],deadline,1,.8,policy=FixedOrderPolicy(["ship"]),decision_timing="measured",execution_timing="wall_clock").execute(
        {"task_id":task_id,"question":"original question","evidence":"fixed evidence"})

@pytest.mark.parametrize("scenario,status",[("success",ModelStatus.SUCCESS),("failure",ModelStatus.FAILED),("invalid",ModelStatus.INVALID),("timeout",ModelStatus.FAILED)])
def test_mock_status_time_fee_no_retry(tmp_path,scenario,status):
    m=model(tmp_path,scenario);t=execute(m);c=t.model_calls[0]
    assert c.status==status and m.transport.calls==1 and c.latency>0
    assert t.total_time>=c.latency and t.total_time>=t.decision_time
    if scenario=="timeout":assert c.cost is None and c.reason=="timeout" and c.metadata["remote_cancel_confirmed"] is False
    else:assert c.cost==pytest.approx(.00002) and t.total_cost==pytest.approx(.00002)
    if scenario=="success":assert t.service_failure is None and t.final_quality is None
    else:assert t.service_failure

def test_persistent_reservation_prevents_resend_after_restart(tmp_path):
    m=model(tmp_path);execute(m)
    fresh=model(tmp_path)
    with pytest.raises(CallNotStartedError):execute(fresh)
    assert fresh.transport.calls==0

def test_pending_attempt_never_retried(tmp_path):
    m=model(tmp_path);m.ledger.reserve("test-task","ship")
    with pytest.raises(CallNotStartedError):execute(m)
    assert m.transport.calls==0

def test_unique_reservation_under_concurrency(tmp_path):
    ledger=AttemptLedger(tmp_path/"ledger.sqlite");results=[]
    def reserve():
        try:ledger.reserve("t","ship");results.append(True)
        except CallNotStartedError:results.append(False)
    ts=[threading.Thread(target=reserve) for _ in range(4)]
    for t in ts:t.start()
    for t in ts:t.join()
    assert results.count(True)==1

@pytest.mark.parametrize("scenario,known",[("unknown_cost",0),("partial_cost",.00001)])
def test_unknown_bill_and_known_partial_fee(tmp_path,scenario,known):
    t=execute(model(tmp_path,scenario))
    assert t.total_cost is None and t.known_cost==pytest.approx(known)
    assert t.service_failure is None and "cost" in t.unknown_checks

def test_request_contains_no_history_or_labels(tmp_path):
    m=model(tmp_path);execute(m)
    p=m.transport.payloads[0]
    assert p["messages"]==[{"role":"user","content":json.dumps({"question":"original question","evidence":"fixed evidence"},ensure_ascii=False)}]
    assert set(p)=={"model","messages","max_tokens","temperature","stream","seed"}

def test_live_requires_wall_clock_and_stable_id(tmp_path):
    m=model(tmp_path)
    with pytest.raises(CallNotStartedError):UnifiedExecutor([m],1,1,.8,policy=FixedOrderPolicy(["ship"])).execute({"task_id":"t"})
    assert m.transport.calls==0
    with pytest.raises(CallNotStartedError):execute(m,task_id="anonymous")

def test_whole_wall_clock_not_component_sum(tmp_path):
    class SlowPolicy(FixedOrderPolicy):
        def decide(self,s):time.sleep(.01);return super().decide(s)
    m=model(tmp_path)
    outer=time.perf_counter()
    t=UnifiedExecutor([m],5,1,.8,policy=SlowPolicy(["ship"]),decision_timing="measured",execution_timing="wall_clock").execute({"task_id":"t"})
    elapsed=time.perf_counter()-outer
    assert t.total_time<=elapsed and t.total_time>=.02
    assert t.total_time>=sum(c.latency for c in t.model_calls)+t.decision_time

def test_deadline_includes_control_before_dispatch(tmp_path):
    class SlowPolicy(FixedOrderPolicy):
        def decide(self,s):time.sleep(.01);return super().decide(s)
    m=model(tmp_path)
    t=UnifiedExecutor([m],.001,1,.8,policy=SlowPolicy(["ship"]),decision_timing="measured",execution_timing="wall_clock").execute({"task_id":"t"})
    assert m.transport.calls==0 and ServiceFailureReason.TIMEOUT in t.failure_reasons

@pytest.fixture
def local_server():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.count+=1
            self.server.payloads.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if self.path=="/disconnect":self.connection.close();return
            if self.path=="/slow":time.sleep(.3)
            status={"/error":500,"/limited":429,"/redirect":307}.get(self.path,200)
            body={"choices":[{"message":{"content":'{"action":"a","condition":"c","deadline":"d"}'}}],"usage":{"prompt_tokens":10,"completion_tokens":5}}
            if self.path in {"/error","/limited"}:body={"error":"DO_NOT_LOG_FAKE_SECRET","usage":{"prompt_tokens":10,"completion_tokens":5}}
            raw=b"not JSON" if self.path=="/badjson" else json.dumps(body).encode()
            try:
                self.send_response(status)
                if self.path=="/redirect":self.send_header("Location","/target")
                self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
        def log_message(self,*a):pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);server.count=0;server.payloads=[];server.daemon_threads=True
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True);thread.start()
    yield server
    server.shutdown();server.server_close();thread.join()

@pytest.mark.parametrize("path,status",[("/ok",ModelStatus.SUCCESS),("/error",ModelStatus.FAILED),("/limited",ModelStatus.FAILED),("/redirect",ModelStatus.FAILED),("/disconnect",ModelStatus.FAILED),("/badjson",ModelStatus.INVALID)])
def test_actual_http_worker_one_post_only(tmp_path,local_server,path,status,monkeypatch):
    monkeypatch.setenv("HTTP_PROXY","http://127.0.0.1:1")
    transport=SingleHTTPTransport(f"http://127.0.0.1:{local_server.server_port}"+path)
    t=execute(model(tmp_path,transport=transport,timeout_s=3))
    assert local_server.count==1 and t.model_calls[0].status==status
    assert "DO_NOT_LOG_FAKE_SECRET" not in repr(t)
    if path in {"/error","/limited"}:assert t.total_cost==pytest.approx(.00002)

def test_actual_worker_timeout_no_background_local_retry(tmp_path,local_server):
    transport=SingleHTTPTransport(f"http://127.0.0.1:{local_server.server_port}/slow")
    t=execute(model(tmp_path,transport=transport,timeout_s=.15))
    assert t.model_calls[0].reason=="timeout" and t.total_cost is None
    assert local_server.count==1
    time.sleep(.35)
    assert local_server.count==1

@pytest.mark.parametrize("endpoint",["https://user:password@example.com/v1","https://example.com/v1?key=secret","ftp://example.com","http://example.com/v1"])
def test_unsafe_endpoint_configuration_rejected(endpoint):
    with pytest.raises(ValueError):SingleHTTPTransport(endpoint)

def fixture_config(tmp_path,scenario=None):
    cfg=json.loads((ROOT/"configs/single_task_mock.json").read_text());cfg["attempt_ledger"]=str(tmp_path/"ledger.sqlite")
    if scenario:cfg["models"]["ship"]["scenario"]=scenario
    path=tmp_path/"deployment.json";path.write_text(json.dumps(cfg));return ROOT/"examples/single_task/mock_task.json",path

def fill_cards(folder,path):
    cards=[json.loads(line) for line in (folder/"annotation_cards.jsonl").read_text().splitlines()]
    for card in cards:
        card["reference_evidence_locations"]="synthetic source sentence"
        card["reviews"]=[{"reviewer":name,"scores":[4,4,4],"valid":True,"veto":False} for name in ["mock-rater-1","mock-rater-2"]]
    path.write_text("".join(json.dumps(c,ensure_ascii=False)+"\n" for c in cards));return cards

def test_mock_collect_blind_grade_and_no_resend(tmp_path):
    task,cfg=fixture_config(tmp_path);folder=collect(task,cfg,tmp_path/"collection",mock=True)
    assert len((folder/"calls.jsonl").read_text().splitlines())==3
    cards=json.loads((folder/"annotation_cards.jsonl").read_text().splitlines()[0])
    assert not {"model_name","cost","model_version","status"}.intersection(cards)
    with pytest.raises(ValueError,match="reserved/completed"):collect(task,cfg,tmp_path/"duplicate",mock=True)
    graded=tmp_path/"graded.jsonl";fill_cards(folder,graded)
    summary=evaluate(folder,graded,tmp_path/"evaluation")
    assert all(s["service_failure_rate"]==0 for s in summary.values())
    assert all(s["risk_guarantee"] is False for s in summary.values())
    assert len((folder/"labels.pending.jsonl").read_text().splitlines())==3

def test_collection_unknown_bill_stops_campaign(tmp_path):
    task,cfg=fixture_config(tmp_path,"unknown_cost");folder=collect(task,cfg,tmp_path/"collection",mock=True)
    calls=[json.loads(s) for s in (folder/"calls.jsonl").read_text().splitlines()]
    assert [c["status"] for c in calls]==["SUCCESS","UNATTEMPTED","UNATTEMPTED"]

def test_partial_or_conflicting_reviews_rejected(tmp_path):
    task,cfg=fixture_config(tmp_path);folder=collect(task,cfg,tmp_path/"collection",mock=True)
    with pytest.raises(ValueError):evaluate(folder,folder/"annotation_cards.jsonl",tmp_path/"invalid")
    graded=tmp_path/"graded.jsonl";cards=fill_cards(folder,graded)
    cards[0]["reviews"][1]["scores"]=[3,3,3]
    graded.write_text("".join(json.dumps(c)+"\n" for c in cards))
    with pytest.raises(ValueError,match="adjudication"):evaluate(folder,graded,tmp_path/"invalid2")

def test_live_template_rejected_without_calls():
    with pytest.raises(ValueError):load_inputs(ROOT/"templates/development/single_task.draft.json",ROOT/"configs/single_task_live.template.json")


def test_journal_finish_failure_preserves_known_fee(tmp_path,monkeypatch):
    import sqlite3
    m=model(tmp_path)
    def fail(*a):raise sqlite3.OperationalError("fake disk failure")
    monkeypatch.setattr(m.ledger,"finish",fail)
    t=execute(m)
    assert t.total_cost==pytest.approx(.00002)
    assert t.model_calls[0].metadata["completion_persistence_error"]=="OperationalError"
    assert m.ledger.contains("test-task","ship")

def test_campaign_fee_limit_stops_without_retry(tmp_path):
    task,cfg=fixture_config(tmp_path)
    data=json.loads(cfg.read_text());data["authorization"]["fee_limit"]=.000001;cfg.write_text(json.dumps(data))
    folder=collect(task,cfg,tmp_path/"collection",mock=True)
    manifest=json.loads((folder/"manifest.json").read_text())
    assert manifest["attempted_models"]==["ship"]
    assert manifest["unattempted_models"]==["shore","cloud"] and not manifest["collection_complete"]

def test_veto_and_adjudication_are_evaluation_only(tmp_path):
    task,cfg=fixture_config(tmp_path);folder=collect(task,cfg,tmp_path/"collection",mock=True)
    graded=tmp_path/"graded.jsonl";cards=fill_cards(folder,graded)
    for card in cards:
        card["reviews"][1]["veto"]=True
        card["adjudication"]={"reviewer":"adjudicator","scores":[4,4,4],"valid":True,"veto":True}
    graded.write_text("".join(json.dumps(c)+"\n" for c in cards))
    before=(folder/"traces.jsonl").read_bytes()
    summary=evaluate(folder,graded,tmp_path/"evaluation")
    assert all(v["mean_quality"]==0 and v["service_failure_rate"]==1 for v in summary.values())
    assert (folder/"traces.jsonl").read_bytes()==before
