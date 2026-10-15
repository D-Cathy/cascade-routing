"""Validate generated document structure and PDF text without model calls."""
from pathlib import Path
from html.parser import HTMLParser
import re, hashlib, json
root = Path(__file__).resolve().parent
source = root.parent / 'framework_reading_20261012_01/FRAMEWORK_GUIDE.md'
page = (root/'FRAMEWORK_GUIDE.html').read_text()
pdf = (root/'pdf_text_check.txt').read_text()
class Audit(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=[]; self.links=[]; self.scripts=0
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if 'id' in a: self.ids.append(a['id'])
        if tag=='a': self.links.append(a.get('href',''))
        if tag=='script': self.scripts+=1
parser=Audit(); parser.feed(page)
checks={
 'source_sha256_matches': hashlib.sha256(source.read_bytes()).hexdigest() in page,
 'all_12_original_chapters': all(f'{i}. ' in pdf for i in range(1,13)),
 'unique_heading_ids': len(parser.ids)==len(set(parser.ids)),
 'internal_anchors_resolve': all(s[1:] in parser.ids for s in parser.links if s.startswith('#')),
 'local_links_resolve': all((root/s).is_file() for s in parser.links if not s.startswith(('http','#'))),
 'no_raw_tex_or_placeholders': not re.search(r'\\[\[\]()]|MATHSLOT|FLOWDIAGRAMSLOT|[\ue000\ue001]',page),
 'no_scripts_or_external_assets': parser.scripts==0 and not re.search(r'<(?:script|link|img)[^>]+(?:src|href)=["\x27]https?://',page),
 'pdf_includes_expanded_gamma_example': '假设并列最优' in pdf,
 'pdf_includes_final_chapter': '12. 推荐的源码学习顺序' in pdf,
}
(root/'verification.json').write_text(json.dumps({'checks':checks,'passed':sum(checks.values()),'total':len(checks),'software_tests_run':0,'model_calls':0},ensure_ascii=False,indent=2))
print(json.dumps(checks,ensure_ascii=False,indent=2))
assert all(checks.values())
