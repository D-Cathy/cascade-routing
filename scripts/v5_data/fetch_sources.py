"""Fetch public data with bounded size, hashes and preserved upstream metadata."""
import argparse, datetime, hashlib, json, pathlib, urllib.request
from concurrent.futures import ThreadPoolExecutor
ROOT=pathlib.Path(__file__).resolve().parents[2]
DATA=ROOT/'data/v5_public_20261013'
def fetch(url, relative, limit=20_000_000):
    dst=DATA/relative;dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        print('EXISTS',relative);return
    record={'url':url,'path':relative,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'v5-academic-dataset-audit/1.0'})
        with urllib.request.urlopen(req,timeout=45) as r:
            content=r.read(limit+1)
            if len(content)>limit:raise ValueError('response exceeds size limit')
            record.update(final_url=r.geturl(),content_type=r.headers.get('Content-Type'),last_modified=r.headers.get('Last-Modified'))
        dst.write_bytes(content)
        record.update(status='downloaded',bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        print('OK',relative,len(content))
    except Exception as e:
        record.update(status='failed',error=str(e));print('FAIL',relative,str(e))
    with (DATA/'download_manifest.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--list',required=True);p.add_argument('--workers',type=int,default=4);args=p.parse_args()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda item: fetch(**item),json.loads(pathlib.Path(args.list).read_text())))
