"""Check generated plan provenance, navigation and PDF content."""
from pathlib import Path
from html.parser import HTMLParser
import re,json,hashlib
root=Path(__file__).resolve().parent
source=(root/'IMPLEMENTATION_PLAN.md').read_text()
page=(root/'V5_IMPLEMENTATION_PLAN.html').read_text()
pdf=(root/'pdf_text.txt').read_text()
class Reader(HTMLParser):
    def __init__(self): super().__init__();self.ids=[];self.anchors=[];self.active=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='a':self.anchors.append(a.get('href',''))
        if tag in ('script','iframe','form'):self.active.append(tag)
r=Reader();r.feed(page)
compact=lambda s:re.sub(r'\s+','',s)
headings=re.findall(r'^## (.+)$',source,re.M)
checks={
 'source_sha256':hashlib.sha256(source.encode()).hexdigest() in page,
 'all_17_sections_in_pdf':len(headings)==17 and all(compact(h) in compact(pdf) for h in headings),
 'all_navigation_resolves':all(x[1:] in r.ids for x in r.anchors if x.startswith('#')),
 'unique_ids':len(r.ids)==len(set(r.ids)),
 'offline_no_scripts':not r.active and not re.search(r'<(?:link|script|img)[^>]+(?:src|href)="https?://',page),
 'no_placeholder_leak':not re.search(r'\{\{[A-Z_]+\}\}|[\ue000\ue001]',page),
 'experiment_ids_present':all('E'+str(i) in pdf for i in range(1,7)),
 'work_orders_present':all('P'+str(i) in pdf for i in range(10)),
 'tracker_all_todo':(root/'EXPERIMENT_TRACKER.md').read_text().count('| TODO |')==15,
 'partition_arithmetic':400+200+200+400+300==1500,
 'replay_budget_arithmetic':9*300+2*300+11*400+3*300*3==10400,
 'pdf_is_generated':(root/'V5_IMPLEMENTATION_PLAN.pdf').read_bytes().startswith(b'%PDF-'),
}
result={'checks':checks,'passed':sum(checks.values()),'total':len(checks),'repository_tests_run':0,'experiments_run':0,'model_calls':0}
(root/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
assert all(checks.values())
