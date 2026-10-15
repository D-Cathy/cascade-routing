"""Isolated stdlib transport. Exactly one HTTP request, no SDK, proxy, redirect or retry.
Invoked by file path with -I; deliberately does not import selection/__init__.py.
"""
import http.client
import json
import os
import sys
import time
from urllib.parse import urlsplit


def send_once(config):
    url=urlsplit(config["endpoint"])
    cls=http.client.HTTPSConnection if url.scheme=="https" else http.client.HTTPConnection
    conn=cls(url.hostname,url.port,timeout=config["timeout_s"])
    headers={"Content-Type":"application/json","Connection":"close"}
    key_name=config.get("api_key_env")
    if key_name:headers["Authorization"]="Bearer "+os.environ[key_name]
    payload=json.dumps(config["payload"],ensure_ascii=False).encode("utf-8")
    try:
        # http.client does not retry POST requests, follow redirects, or read proxy env.
        conn.request("POST",url.path or "/",body=payload,headers=headers)
        response=conn.getresponse()
        raw=response.read(config["max_response_bytes"]+1)
        if len(raw)>config["max_response_bytes"]:
            return {"error":"response_too_large","http_status":response.status}
        return {"http_status":response.status,"body":raw.decode("utf-8"),
                "provider_request_id":response.getheader("x-request-id"),
                "response_received_monotonic_s":time.perf_counter()}
    finally:
        conn.close()

if __name__=="__main__":
    try:
        result=send_once(json.load(sys.stdin))
    except Exception as exc:
        # No exception messages: they may contain endpoint credentials or response text.
        result={"error": "transport_timeout" if isinstance(exc, TimeoutError) else "transport_"+type(exc).__name__}
    json.dump(result,sys.stdout,allow_nan=False)
