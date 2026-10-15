"""Single-attempt HTTP adapter; no model loading, SDK, automatic retries or billing probes."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from urllib.parse import urlsplit
from .schema import CallNotStartedError, ModelCallRecord, ModelLevel, ModelStatus

class AttemptLedger:
    """Reserve before dispatch, persist completion. Pending attempts are never retried."""
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS attempts (request_id TEXT, model_name TEXT, attempt_id TEXT, status TEXT, record TEXT, PRIMARY KEY(request_id, model_name))")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.execute("PRAGMA synchronous=FULL")
        return db
    def reserve(self,request_id,model_name):
        attempt_id=str(uuid.uuid4())
        try:
            with self.connect() as db:
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,?)",(request_id,model_name,attempt_id,"PENDING",None))
        except sqlite3.Error as exc:
            raise CallNotStartedError("Attempt already reserved or ledger unavailable; do not resend") from exc
        return attempt_id
    def finish(self,request_id,model_name,record):
        with self.connect() as db:
            db.execute("UPDATE attempts SET status=?, record=? WHERE request_id=? AND model_name=?",
                       ("COMPLETE",json.dumps(asdict(record),ensure_ascii=False,allow_nan=False),request_id,model_name))
    def contains(self,request_id,model_name):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM attempts WHERE request_id=? AND model_name=?",(request_id,model_name)).fetchone() is not None

class SingleHTTPTransport:
    def __init__(self,endpoint,api_key_env=None,max_response_bytes=2_000_000):
        url=urlsplit(endpoint)
        if url.scheme not in {"http","https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Endpoint must be a full HTTP(S) completion URL without credentials/query/fragment")
        if url.scheme=="http":
            try:local=ipaddress.ip_address(url.hostname).is_loopback
            except ValueError:local=url.hostname=="localhost"
            if not local:raise ValueError("Use HTTPS for non-loopback endpoints")
        if api_key_env and not os.getenv(api_key_env):raise CallNotStartedError("Configured credential environment variable is unset")
        self.endpoint,self.api_key_env,self.max_response_bytes=endpoint,api_key_env,max_response_bytes
    def send(self,payload,timeout_s):
        config={"endpoint":self.endpoint,"api_key_env":self.api_key_env,"payload":payload,
                "timeout_s":timeout_s,"max_response_bytes":self.max_response_bytes}
        worker=Path(__file__).with_name("http_once_worker.py")
        try:
            result=subprocess.run([sys.executable,"-I",str(worker)],input=json.dumps(config),text=True,
                                  capture_output=True,timeout=timeout_s,check=False)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and reaps the local worker. Remote generation/billing
            # may continue: no cancellation guarantee and no inferred zero cost.
            return {"error":"transport_timeout","local_worker_reaped":True,"remote_cancel_confirmed":False}
        if result.returncode!=0:return {"error":"worker_failed"}
        try:return json.loads(result.stdout)
        except ValueError:return {"error":"worker_protocol_error"}


def finite_nonnegative(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and value>=0

class LiveModel:
    def __init__(self,name,level,model_id,model_version,transport,ledger,timeout_s=30,
                 max_tokens=512,temperature=0,seed=20260924,pricing=None,
                 validation="nonempty",required_fields=(),data_source="real_development"):
        if not all(isinstance(v,str) and v.strip() for v in [name,model_id,model_version]):raise ValueError("Model IDs/version required")
        if not finite_nonnegative(timeout_s) or timeout_s<=0:raise ValueError("Positive timeout required")
        if type(max_tokens) is not int or max_tokens<=0:raise ValueError("Positive max_tokens required")
        if not finite_nonnegative(temperature) or (seed is not None and type(seed) is not int):raise ValueError("Invalid decoding settings")
        if validation not in {"nonempty","json_fields"}:raise ValueError("Unknown output validator")
        if not isinstance(required_fields,(list,tuple)) or any(not isinstance(v,str) or not v for v in required_fields):raise ValueError("Invalid required fields")
        if pricing is not None:
            if set(pricing)!={"input_per_million","output_per_million","currency","source","usage_is_complete"}:raise ValueError("Invalid pricing fields")
            if any(not finite_nonnegative(pricing[k]) for k in ["input_per_million","output_per_million"]):raise ValueError("Invalid rates")
            if not pricing["currency"] or not pricing["source"] or type(pricing["usage_is_complete"]) is not bool:raise ValueError("Pricing provenance/completeness required")
        self.name,self.level,self.model_id,self.model_version=name,ModelLevel(level),model_id,model_version
        self.transport,self.ledger,self.timeout_s=transport,ledger,timeout_s
        self.max_tokens,self.temperature,self.seed=max_tokens,temperature,seed
        self.pricing,self.validation,self.required_fields=pricing,validation,list(required_fields)
        self.available=True;self.data_source=data_source
    def _billing(self,body):
        usage=body.get("usage",{}) if isinstance(body,dict) else {}
        if not isinstance(usage,dict):usage={}
        tokens={k:usage.get(k) if type(usage.get(k)) is int and usage[k]>=0 else None for k in ["prompt_tokens","completion_tokens"]}
        known=0.0;cost=None
        if self.pricing:
            for token,rate in [("prompt_tokens","input_per_million"),("completion_tokens","output_per_million")]:
                if tokens[token] is not None:known+=tokens[token]*self.pricing[rate]/1e6
            if self.pricing["usage_is_complete"] and all(v is not None for v in tokens.values()):cost=known
        return cost,known,tokens
    def _valid(self,answer):
        if not isinstance(answer,str) or not answer.strip():return False
        if self.validation=="json_fields":
            try:value=json.loads(answer)
            except ValueError:return False
            return isinstance(value,dict) and all(k in value and value[k] is not None for k in self.required_fields)
        return True
    def call_with_context(self,question,evidence,*,request_id,timeout_s):
        if not isinstance(request_id,str) or not request_id or request_id=="anonymous":raise CallNotStartedError("Stable request ID required")
        if not isinstance(question,str) or not isinstance(evidence,str):raise CallNotStartedError("Original question/evidence must be text")
        if not finite_nonnegative(timeout_s) or timeout_s<=0:raise CallNotStartedError("No remaining call time")
        started=time.perf_counter();limit=min(timeout_s,self.timeout_s)
        attempt_id=self.ledger.reserve(request_id,self.name)
        # No history, reference answer, quality label, or controller state in payload.
        prompt=json.dumps({"question":question,"evidence":evidence},ensure_ascii=False)
        payload={"model":self.model_id,"messages":[{"role":"user","content":prompt}],
                 "max_tokens":self.max_tokens,"temperature":self.temperature,"stream":False}
        if self.seed is not None:payload["seed"]=self.seed
        metadata={"attempt_id":attempt_id,"retry_count":0,"transport_attempts":0,
                  "call_started_monotonic_s":started,"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),
                  "evidence_sha256":hashlib.sha256(evidence.encode()).hexdigest(),"timeout_s":limit,
                  "pricing":self.pricing,"paid_fee":None,"paid_fee_source":"missing",
                  "cost_scope":"provider_token_fee_only_not_paper_normalized_cost",
                  "validation_rule":self.validation,"required_fields":self.required_fields,
                  "model_id":self.model_id,"remote_cancel_confirmed":None}
        body={};answer=None;status=ModelStatus.FAILED;reason=None
        try:
            metadata["transport_attempts"]=1
            wire=self.transport.send(payload,max(0.000001,limit-(time.perf_counter()-started)))
            metadata["response_received_monotonic_s"]=time.perf_counter()
            metadata["http_status"]=wire.get("http_status")
            metadata["remote_cancel_confirmed"]=wire.get("remote_cancel_confirmed")
            metadata["provider_request_id"]=wire.get("provider_request_id")
            if isinstance(wire.get("body"),str):
                try:body=json.loads(wire["body"])
                except ValueError:reason="invalid_response_json"
            if not isinstance(body,dict):body={};reason="invalid_response_schema"
            if wire.get("error"):
                # Transport errors are codes, not arbitrary provider error text.
                reason=wire["error"] if wire["error"] in {"transport_timeout","response_too_large","worker_failed","worker_protocol_error"} else "transport_error"
            elif not 200<=wire.get("http_status",0)<300:
                reason="http_error"
            elif reason is None:
                try:answer=body["choices"][0]["message"]["content"]
                except (KeyError,IndexError,TypeError):reason="invalid_response_schema"
                if reason is None:
                    status=ModelStatus.SUCCESS if self._valid(answer) else ModelStatus.INVALID
                    if status==ModelStatus.INVALID:reason="invalid_output"
                    if not isinstance(answer,str):answer=None
            if reason in {"invalid_response_schema","invalid_response_json"}:status=ModelStatus.INVALID
            if time.perf_counter()-started>limit or reason=="transport_timeout":
                metadata["late_answer"]=answer;answer=None;status=ModelStatus.FAILED;reason="timeout"
                if metadata["remote_cancel_confirmed"] is None:metadata["remote_cancel_confirmed"]=False
        except Exception as exc:
            reason="backend_"+type(exc).__name__  # never log exception messages/credentials
        cost,known,tokens=self._billing(body)
        metadata["usage"]=tokens
        metadata["verification_finished_monotonic_s"]=time.perf_counter()
        record=ModelCallRecord(self.name,self.level.value,status,time.perf_counter()-started,cost,
            answer=answer,reason=reason,model_version=self.model_version,data_source=self.data_source,
            latency_source="simulated" if self.data_source=="synthetic" else "measured",
            cost_source=("simulated" if self.data_source=="synthetic" else "derived") if cost is not None else "missing",known_cost=known,metadata=metadata)
        try:
            self.ledger.finish(request_id,self.name,record)
        except sqlite3.Error as exc:
            # Preserve the already-known bill in memory; PENDING still blocks resend.
            record.metadata["completion_persistence_error"] = type(exc).__name__
        # Full executor wall-clock also includes durable completion bookkeeping.
        return record
