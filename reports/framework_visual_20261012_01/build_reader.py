#!/usr/bin/env python3
"""Generate an offline reading edition; the Markdown remains canonical."""
from pathlib import Path
import importlib.util, re, html, hashlib, datetime, json

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'framework_reading_20261012_01/FRAMEWORK_GUIDE.md'
HELPER = Path('/home/guoqiuyuan/.codex/skills/render-html/scripts/render_html.py')
spec = importlib.util.spec_from_file_location('render_html', HELPER)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
source = SOURCE.read_text()
digest = hashlib.sha256(source.encode()).hexdigest()
stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

def formula(text):
    return '<span class="math">' + text + '</span>'

inline = {
    r'\hat q_i(x)': 'q̂<sub>i</sub>(x)', r'\hat c_i(x)': 'ĉ<sub>i</sub>(x)',
    r'\lambda_j': 'λ<sub>j</sub>', r'\lambda': 'λ', r'\lambda=0.5': 'λ = 0.5',
    r'\gamma': 'γ', r'\gamma=0': 'γ = 0', r'\tilde q': 'q̃',
    r'\mathbb E[\max Q_i]': 'E[max Q<sub>i</sub>]',
    r'\max\mathbb E[Q_i]': 'max E[Q<sub>i</sub>]',
}
def inline_math(m):
    expr = m.group(1)
    return formula(inline.get(expr, html.escape(expr).replace(r'\times', ' × ')))

display = [
    'τ<sub>i</sub>(x) = q̂<sub>i</sub>(x) − λ · ĉ<sub>i</sub>(x)',
    'q̂<sub>S</sub> = E[max<sub>i ∈ S</sub> q̃<sub>i</sub>]<br>ĉ<sub>S</sub> = ∑<sub>i ∈ S</sub> ĉ<sub>i</sub><br>τ<sub>S</sub> = q̂<sub>S</sub> − λ<sub>j</sub> · ĉ<sub>S</sub>',
    'γ = clip((B − C<sub>cheap</sub>) / (C<sub>expensive</sub> − C<sub>cheap</sub>), 0, 1)',
]
slots = []
def display_math(m):
    i = len(slots)
    slots.append('<div class="equation" role="math">' + display[i] + '</div>')
    return '\n\nMATHSLOT' + str(i) + 'END\n\n'

md = re.sub(r'\\\[([\s\S]*?)\\\]', display_math, source)
md = re.sub(r'\\\((.*?)\\\)', inline_math, md)
md = re.sub(r'```mermaid[\s\S]*?```', 'FLOWDIAGRAMSLOT', md)
md = re.sub(r'\]\(([^)]+\.py):\d+\)', r'](\1)', md)
md = re.sub(r'\]\(([^)#:\s]+\.(?:pdf|txt|py|json|xml))\)',
    lambda m: '](' + (m.group(1) if m.group(1).startswith('../../') else '../framework_reading_20261012_01/' + m.group(1)) + ')', md)
body, toc = renderer._render_blocks(renderer.parse_blocks(md.splitlines()), True)
for i, value in enumerate(slots):
    body = body.replace('<p>MATHSLOT'+str(i)+'END</p>', value)

flow = '''<div class="flow" aria-label="本地框架数据流">
<div class="node">任务与服务要求<small>加载 replay 数据 · 检查来源分组</small></div><b class="arrow">↓</b>
<div class="node">dev_fit 拟合工程均值适配器</div><b class="arrow">↓</b>
<div class="loop"><strong>UnifiedExecutor 的决策循环</strong><div class="node">构造 ObservableState<small>仅包含已发生的调用与可观测信息</small></div><b class="arrow">↓</b>
<div class="node">策略 decide / 原 CascadeRouter</div><b class="arrow">↓</b>
<div class="branches"><div class="node">CALL<small>权限 · 严格向上 · 单次尝试检查<br>→ OfflineModel / LiveModel<br>→ 记录结果、时间、费用<br>↶ 更新状态，再次决策</small></div>
<div class="node">ACCEPT / FAIL<small>终止循环<br>固定最终答案</small></div></div></div><b class="arrow">↓</b>
<div class="node evaluation">evaluate_terminal<small>此时才读取独立质量与有效性标签<br>→ 输出轨迹与 summary</small></div></div>'''
body = body.replace('<p>FLOWDIAGRAMSLOT</p>', flow)
nav = ''.join('<a href="#'+html.escape(t['id'])+'">'+html.escape(t['text'])+'</a>' for t in toc if t['level']==2)

intro = '''<section id="map"><p class="eyebrow">先建立整体印象</p><h2>四个角色，一条闭环</h2>
<p>可以把系统理解为：先预测，再做决定，再执行，最后评价。原论文主要解决前两个环节；本地工程还管理执行约束、资源和事后评分。</p>
<div class="roles"><div><span>01</span><h3>估计器</h3><p>“每个模型可能答得多好？要花多少资源？”</p><code>quality / cost computer</code></div><div><span>02</span><h3>选择算法</h3><p>“下一步调用谁？还是现在停止？”</p><code>CascadeRouter</code></div><div><span>03</span><h3>执行器</h3><p>检查动作，发起调用，保留时间和费用。</p><code>UnifiedExecutor</code></div><div><span>04</span><h3>终局评估</h3><p>答案固定之后，再用独立标签判断是否达标。</p><code>evaluate_terminal</code></div></div>
<div class="note">控制器可以读取已经返回的回答；不能读取真实质量标签、未调用模型的答案或未来资源。这里的“预测质量”与事后评分是两种信息。</div></section>
<section id="math-guide"><p class="eyebrow">公式翻译成中文</p><h2>先记住一句话：质量收益 − 成本惩罚</h2>
<div class="equation words"><span>方案得分</span><b>=</b><span>预测质量</span><b>−</b><span>成本重视程度 × 预测成本</span></div>
<div class="equation">τ<sub>i</sub>(x) = q̂<sub>i</sub>(x) − λ · ĉ<sub>i</sub>(x)</div>
<table><thead><tr><th>符号</th><th>怎么读</th><th>实际含义</th></tr></thead><tbody>
<tr><td>x / i</td><td>问题 / 模型编号</td><td>正在处理哪个问题、考虑哪个模型</td></tr>
<tr><td>q̂ / ĉ</td><td>预测质量 / 预测成本</td><td>上方的小帽子表示估计值，并非已知真实结果</td></tr>
<tr><td>λ</td><td>lambda，成本权重</td><td>把成本换成可与质量比较的惩罚；数值越大越节省</td></tr>
<tr><td>τ</td><td>tau，方案得分</td><td>用于比较方案，越高越优；并不是成功概率</td></tr>
<tr><td>S / H</td><td>候选模型集合 / 已调用集合</td><td>候选方案必须包含已调用模型，即 H ⊆ S</td></tr>
<tr><td>j / λ<sub>j</sub></td><td>当前阶段 / 该阶段的权重</td><td>调用后进入下一阶段，可以使用不同成本权重</td></tr>
<tr><td>B / γ</td><td>平均成本预算 / 混合概率</td><td>本类 γ 是并列最优时选择较贵方案的概率</td></tr>
</tbody></table>
<h3>“超模型”就是一组候选模型</h3><p>例如 S = {船端，岸端}：方案成本是两个模型成本之和，方案质量是“从两份答案中选最好”的预测价值。当前轮只调用其中一个尚未运行的模型，拿到回答后重新决策。</p>
<div class="equation">集合成本 = 各模型预测成本相加<br>集合质量 = “取最高质量”之后，再求平均<br>集合得分 = 集合质量 − 当前阶段成本权重 × 集合成本</div>
<h3>为什么“先取最大值，再平均”顺序不能交换？</h3><p>下面是解释计算顺序的假想例子，两个情形各占一半：</p>
<table><thead><tr><th>假想情形</th><th>模型 A</th><th>模型 B</th><th>该情形的最大值</th></tr></thead><tbody><tr><td>情形 1</td><td>0.90</td><td>0.50</td><td>0.90</td></tr><tr><td>情形 2</td><td>0.50</td><td>0.90</td><td>0.90</td></tr></tbody></table>
<p><strong>先取最大值，再平均：</strong>(0.90 + 0.90) ÷ 2 = <strong>0.90</strong>。<br><strong>先对每个模型平均，再取最大值：</strong>max(0.70, 0.70) = <strong>0.70</strong>。</p>
<div class="note">这解释的是预测分布中的互补价值，不表示在线可以偷看真实质量。实际输出仍由已返回答案的质量预测决定；本地均值适配器没有协方差，集合质量退化为预测均值中的最大值。</div>
<details open><summary>γ 的公式如何理解？点击看一个预算例子</summary><p>假设并列最优的便宜方案平均成本为 1，较贵方案为 3，目标平均预算 B = 1.5。选择较贵方案的概率 γ = (1.5 − 1) ÷ (3 − 1) = 0.25。</p><p>这样混合的平均成本为 0.75 × 1 + 0.25 × 3 = 1.5。clip(..., 0, 1) 表示把计算结果限制在 0 到 1 之间。这个解释要求两个成本不同；相同时不能直接做除法，代码另行处理。</p><p>它用于并列最优方案的预算混合，不是任意随机调用模型，也不是每条请求的硬预算保证。</p></details></section>
<section id="walkthrough"><p class="eyebrow">把公式真正算一遍</p><h2>船端 → 岸端 → 停止</h2><p>以下沿用已运行的合成教学轨迹：λ = 0.5，γ = 0，无协方差；船／岸／云预测成本为 0.10／0.40／1.00。没有调用真实模型。</p>
<article class="step"><span class="badge">第 0 轮 · 没有回答</span><h3>先调用船端</h3><p>船端：0.70 − 0.5 × 0.10 = <strong>0.65</strong><br>岸端：0.85 − 0.5 × 0.40 = <strong>0.65</strong><br>云端：0.90 − 0.5 × 1.00 = <strong>0.40</strong></p><p>船端与岸端并列；γ = 0 时选择便宜方案，所以先调用船端。包含多个模型的集合也没有更高得分。</p></article>
<article class="step"><span class="badge">第 1 轮 · 船端已回答</span><h3>新反馈让船端质量预测降至 0.40</h3><table><thead><tr><th>候选集合</th><th>代入公式</th><th>得分</th></tr></thead><tbody><tr><td>仅船端（停止）</td><td>0.40 − 0.5 × 0.10</td><td>0.35</td></tr><tr class="winner"><td>船端 + 岸端</td><td>0.85 − 0.5 × (0.10 + 0.40)</td><td>0.60 ← 最优</td></tr><tr><td>船端 + 云端</td><td>0.90 − 0.5 × (0.10 + 1.00)</td><td>0.35</td></tr><tr><td>船端 + 岸端 + 云端</td><td>0.90 − 0.5 × 1.50</td><td>0.15</td></tr></tbody></table><p>最优集合含有尚未调用的岸端，于是下一步调用岸端。船端已花成本仍保留在集合中。</p></article>
<article class="step"><span class="badge">第 2 轮 · 船端、岸端已回答</span><h3>新增云端的收益不足以抵消成本</h3><p>停止：0.86 − 0.5 × 0.50 = <strong>0.61</strong><br>加云端：0.90 − 0.5 × 1.50 = <strong>0.15</strong></p><p>继续调用的得分更低，因此停止。随后 <code>select_answer()</code> 在已返回答案中选择岸端答案。</p></article>
<div class="note">“停止调用”与“选择已有答案”是两个步骤。当前固定均值回放中六条任务都直接调用云端，不能将此教学轨迹当成该回放的实验结果。</div></section>
<section id="full-report"><p class="eyebrow">完整内容 · 逐章对照源码</p><h2>原报告全文阅读版</h2><p>以下保留原报告的全部章节、表格、代码与验证边界。公式已转换为浏览器可直接显示的符号，流程图已重绘；源码链接打开对应文件，原行号仍可在 Markdown 中查阅。</p></section>'''

css = '''
:root{--ink:#203432;--muted:#5b706d;--teal:#17675f;--line:#d8e3df;--paper:#fffefa;--wash:#f1f5f1}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--wash);color:var(--ink);font:18px/1.85 "Noto Sans CJK SC","Microsoft YaHei","PingFang SC",sans-serif}a{color:var(--teal);text-underline-offset:4px}aside{position:fixed;left:0;top:0;bottom:0;width:270px;padding:30px 24px;background:#e6eeea;overflow:auto;font-size:14px;line-height:1.6}aside strong{display:block;font-size:20px;margin-bottom:18px}aside a{display:block;text-decoration:none;padding:7px 0}aside a:hover{text-decoration:underline}main{max-width:1190px;margin-left:270px;padding:48px 64px 90px;background:var(--paper);min-height:100vh}header{border-bottom:2px solid var(--teal);padding-bottom:30px;margin-bottom:40px}h1{font-size:40px;line-height:1.35;letter-spacing:-1px;margin:10px 0 18px}h2{font-size:28px;line-height:1.5;margin:48px 0 22px;border-bottom:1px solid var(--line);padding-bottom:12px}h3{font-size:21px;margin:30px 0 10px}p{margin:14px 0}section{margin-bottom:48px}.eyebrow{font-size:13px;font-weight:700;color:var(--teal);letter-spacing:2px}.lead{font-size:21px}.meta{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.roles{display:grid;grid-template-columns:1fr 1fr;gap:16px}.roles>div{padding:22px;background:#edf4ef;border:1px solid var(--line);border-radius:12px}.roles span{color:var(--teal);font-size:14px}.roles h3{margin:6px 0}.roles p{font-size:17px}.note{background:#fff4dc;border-left:4px solid #ba8730;padding:18px 22px;margin:24px 0;font-size:17px}.equation{font-family:"STIX Two Math","Cambria Math","DejaVu Serif",serif;font-size:23px;line-height:2;background:#eaf3ef;padding:22px 28px;border-radius:10px;margin:24px 0;overflow-x:auto}.words{font:20px/1.9 inherit;display:flex;gap:12px;flex-wrap:wrap}.math{font-family:"Cambria Math","DejaVu Serif",serif;white-space:nowrap}.math sub,.equation sub{font-size:.68em}table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.8;margin:24px 0;table-layout:auto}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#e6efea;color:#234f49}tr:nth-child(even){background:#f7f8f3}.winner{background:#dcf0e5!important;font-weight:600}code{font:0.86em/1.7 "DejaVu Sans Mono",monospace;background:#eef1ec;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}pre{padding:22px;background:#edf1ec;border:1px solid var(--line);border-radius:10px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:14px}pre code{background:none;padding:0}.step{border:1px solid var(--line);padding:26px 30px;margin:20px 0;border-radius:12px}.badge{font-size:14px;color:var(--teal);font-weight:700}.step h3{margin-top:12px}details{padding:20px 24px;background:#f0f3e9;border:1px solid var(--line);border-radius:8px}summary{cursor:pointer;font-weight:700}.flow{max-width:720px;margin:32px auto;text-align:center}.node{border:1px solid #94b5a8;background:#eaf4ed;border-radius:10px;padding:16px;font-weight:600}.node small{display:block;font-size:14px;line-height:1.8;font-weight:400;margin-top:8px}.arrow{display:block;font-size:26px;color:var(--teal);line-height:1.7}.loop{border:2px dashed #7ca995;border-radius:14px;padding:20px}.loop>strong{display:block;margin-bottom:16px}.branches{display:grid;grid-template-columns:1fr 1fr;gap:14px}.evaluation{background:#fff1d8;border-color:#c4a26a}li{padding:4px 0}footer{margin-top:64px;padding-top:24px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}button{font:inherit}.print-link{display:inline-block;margin-right:16px}#full-report{border-top:3px solid var(--teal);padding-top:20px}
@media(max-width:1050px){aside{position:static;width:auto;max-height:none}aside a{display:inline-block;margin-right:16px}aside .chapters{display:none}main{margin-left:0;padding:30px 24px;max-width:none}h1{font-size:32px}}@media(max-width:600px){body{font-size:17px}.roles,.branches{grid-template-columns:1fr}th,td{padding:9px 7px;font-size:13px}.equation{font-size:19px;padding:18px}.step{padding:20px 15px}h2{font-size:24px}}
@media print{@page{size:A4;margin:17mm 14mm}body{background:white;font-size:11pt;line-height:1.7}aside,.print-link{display:none}main{margin:0;padding:0;max-width:none}h1{font-size:27pt}h2{font-size:19pt;break-after:avoid}h3{font-size:14pt;break-after:avoid}p,li{orphans:3;widows:3}table{font-size:9pt}thead{display:table-header-group}tr,.node,.roles>div{break-inside:avoid}pre{font-size:8pt}.equation{font-size:16pt;padding:12px}.note{font-size:10pt}a{color:inherit;text-decoration:none}.meta{font-size:8pt}.eyebrow{font-size:9pt}details{display:block}details>summary{display:none}.step{padding:16px}.flow{break-inside:avoid}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
'''
out = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cascade Routing · 可视化阅读版</title><meta name="source-path" content="{html.escape(str(SOURCE))}"><meta name="source-sha256" content="{digest}"><meta name="generated-at" content="{stamp}"><style>{css}</style></head><body>
<aside><strong>Cascade Routing<br>框架阅读指南</strong><a href="#map">① 四个角色</a><a href="#math-guide">② 看懂公式</a><a href="#walkthrough">③ 分步计算</a><a href="#full-report">④ 原报告全文</a><div class="chapters">{nav}</div></aside>
<main><header><p class="eyebrow">论文 × 代码 · 中文可视化阅读版</p><h1>Cascade Routing<br>代码框架是怎样运转的？</h1><p class="lead">从整体框架，到公式含义，再到一次完整的模型选择。</p><p>本页可以离线阅读。建议先读前三部分，再按目录进入完整报告。</p><p><a class="print-link" href="FRAMEWORK_GUIDE.pdf">下载 / 打开 PDF 版</a><a href="../framework_reading_20261012_01/FRAMEWORK_GUIDE.md">查看原始 Markdown</a></p><div class="meta">来源：{html.escape(str(SOURCE))}<br>SHA256：{digest}<br>生成时间：{stamp} · 内容依据 2026-10-12 阅读报告</div></header>
{intro}{body}<footer>由 render-html skill 的 Markdown 解析器与本目录 build_reader.py 生成。新增中文说明和教学算例用于辅助理解；原报告的验证结果与实现边界保留。单文件 HTML，无 CDN、无脚本、无需联网。</footer></main></body></html>'''
assert not re.search(r'\\[\[\]()]|MATHSLOT|FLOWDIAGRAMSLOT|[\ue000\ue001]', out)
assert '<script' not in out
(HERE/'FRAMEWORK_GUIDE.html').write_text(out)
(HERE/'build_manifest.json').write_text(json.dumps({'source':str(SOURCE),'source_sha256':digest,'generated_at':stamp,'source_display_formulas':len(slots),'source_h2':len([t for t in toc if t['level']==2]),'external_assets':0,'model_calls':0},ensure_ascii=False,indent=2))
print('Generated FRAMEWORK_GUIDE.html; original sections:',len([t for t in toc if t['level']==2]),'; formulas:',len(slots))
