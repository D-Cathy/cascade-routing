"""No network, no LLM: transport test double for the live adapter."""
import json
import time

class MockTransport:
    def __init__(self,scenario="success"):
        if scenario not in {"success","failure","timeout","invalid","unknown_cost","partial_cost"}:raise ValueError("Invalid mock scenario")
        self.scenario=scenario;self.calls=0;self.payloads=[]
    def send(self,payload,timeout_s):
        self.calls+=1;self.payloads.append(payload)
        if self.scenario=="timeout":
            time.sleep(min(timeout_s,0.02))
            return {"error":"transport_timeout","remote_cancel_confirmed":False}
        body={"choices":[{"message":{"content":json.dumps({"action":"发送","condition":"收到确认后","deadline":"18:00"},ensure_ascii=False)}}],
              "usage":{"prompt_tokens":10,"completion_tokens":5}}
        if self.scenario=="invalid":body["choices"][0]["message"]["content"]="not structured JSON"
        if self.scenario=="unknown_cost":body.pop("usage")
        if self.scenario=="partial_cost":body["usage"].pop("completion_tokens")
        if self.scenario=="failure":return {"http_status":500,"body":json.dumps({"error":"simulated","usage":body["usage"]})}
        return {"http_status":200,"body":json.dumps(body)}
