"""Render the maintained progress Markdown as a dependency-free local reader."""
from pathlib import Path
import html

def render(source):
    parts=[];table=[];code=False
    for line in source.splitlines()+['']:
        if line.startswith('```'):
            parts.append('</code></pre>' if code else '<pre><code>');code=not code;continue
        if code:parts.append(html.escape(line)+'\n');continue
        if line.startswith('|'):
            if not set(line.replace('|','').replace(' ','')).issubset({'-',':'}):table.append([v.strip() for v in line.strip('|').split('|')])
            continue
        if table:
            parts.append('<table>'+''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in row)+'</tr>' for row in table)+'</table>');table=[]
        if line.startswith('# '):parts.append('<h1>'+html.escape(line[2:])+'</h1>')
        elif line.startswith('## '):parts.append('<h2>'+html.escape(line[3:])+'</h2>')
        elif line:parts.append('<p>'+html.escape(line)+'</p>')
    return '<!doctype html><html lang="zh"><meta charset="utf-8"><title>v5实施进度</title><style>body{font:17px/1.8 system-ui;max-width:1200px;margin:30px auto;padding:20px;color:#183147}table{border-collapse:collapse;width:100%;font-size:15px}td{padding:12px;border:1px solid #ccd8e4;vertical-align:top}tr:first-child{background:#eaf3fb}pre{background:#f0f5fa;padding:18px;overflow:auto}p{overflow-wrap:anywhere}</style>'+''.join(parts)+'</html>'

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    (root/'PROGRESS.html').write_text(render((root/'PROGRESS.md').read_text()),encoding='utf-8')
