# 项目交接（2026-09-24，GPU8）

## 2026-10-15：老师关于历史库与开销的反馈

- 修改v5/transition_library.py：默认10000条、32 MiB JSON载荷上限，超限构造拒绝，要求校准前离线重建；按动作/有序历史分桶并向量化精确距离。保持来源去重/支持拒绝/联合抽样。库无自动在线追加，全文本和标签不入库；没有清理AttemptLedger。
- 新增10测试，全量沙箱172 passed/7 socket errors；获准本机HTTP fixture后179 passed（5.87s），退出0。定向22 passed。真实模型调用0。
- 新增scripts/benchmark_transition_overhead.py，100/1000/10000条合成微基准，完整证据和实际命令在reports/history_overhead_20261015_01/REPORT.md；万条抽样p50 10.17ms、p95 103.74ms，不能忽视尾部抖动或当作完整规划耗时。
- docs/v5_history_overhead.md说明摘要/离线档案/审计账本边界、容量不是RSS限制、日志尚无TTL、冻结后换库须重新校准、完整控制计时与净费用摊销。未改论文，尚未证明节省不会被抵消；正式容量消融和控制器实测继续待办。更新PROGRESS并重建HTML。

先读AGENTS.md、本文、docs/single_task_loop.md及父目录论文的方法/实验设计。最近验收：[单条后端报告](reports/live_backend_20260924_01/ACCEPTANCE.md)；前阶段：[回放验收](reports/recovery_20260923_01/ACCEPTANCE.md)。

## 当前状态

- 论文要求：船岸云初始任一获准层，后续严格向上、可跳级、每模型至多尝试一次；固定原始问题/证据，控制器无标签/未来答案；失败并集及全部请求分母；失败与控制开销记账；独立来源组与独立校准。
- 已实现：统一回放框架、原CascadeRouter工程均值适配；本轮新增单次HTTP后端、持久化尝试账本、wall_clock执行模式、独立三模型采集、匿名双人评分文件与独立评价入口。所有路径复用UnifiedExecutor和共享evaluate_terminal。
- 已验证：81通过、0失败/错误/跳过，退出0。包括原50项和31项新后端测试；成功/失败/超时/无效、无隐式重试、部分费用、重复与崩溃后PENDING保护、HTTP假服务器和评分闭环均通过。
- 未执行：真实模型生成、真实材料采集与人工标注、付费API；没有下载模型/启动服务/扩展规划器。模拟评分卡由脚本填入，不是人工评分。没有风险保证。

## 关键新发现与环境

主机GPU8，项目仍 `/home/guoqiuyuan/LLMresearch/cascade-routing`，论文在父目录。无Git，旧文件备份在本轮report/backup。沙箱仍报bubblewrap mountinfo错误，命令按权限流程执行。

APIQuery具体导入错误：api.py:4缺langchain_openai；基础环境其他LangChain组件及openai也缺。__init__捕获异常导致APIQuery=None。vive环境虽有openai，同样缺LangChain组件。旧链存在外层循环+SDK重试，保持原样但新采集不使用它；没有安装依赖。

**不能再说服务器没模型。** 本机11434正在服务，只读GET /api/tags及/v1/models均200，九模型包括qwen2.5:3b、qwen3:4b/8b/14b、deepseek等。完整名字/digest/量化见本轮local_service_probe.json。该服务清单未见论文Qwen2.5 1.5B/7B；不代表其他目录/服务不存在。没有POST生成验证，没有擅自改变研究模型角色。云模型/端点/费率未填，检查的凭据变量未设置。

## 实现文件与限制

- live_backend.py / http_once_worker.py：单次标准库HTTP请求，不用SDK、不重试、不跟随重定向、不使用环境代理；父进程超时kill/reap本地worker。远端取消/继续计费未知，服务端/网关内部重试需核验。
- AttemptLedger：发送前SQLite(task_id,model_name)唯一占用，失败或PENDING也不得重发。换输出目录仍会阻止同任务再次生成；不能删账本或换ID绕过。尚无自动崩溃恢复/补账单工具。
- executor.py：wall_clock+measured计真实整体时长，不与分项叠加；回放旧逻辑保留。已知费用部分累计，未知不当零。新增后端仅对兼容chat/completions HTTP服务；不直接加载模型权重。
- single_task.py：validate本地校验；collect明确--mock或--live；三个模型分别固定一次独立采集，不是一条级联路由。费用未知或达到范围会停止后续，未调用记录UNATTEMPTED。
- evaluate读取独立人工评分卡，复用失败并集，不重新调用模型或改变原答案。无标签仍未知，双人分歧需裁定；模拟评分明显标synthetic。
- 费用当前仅provider token fee，derived不等于paid，控制耗时已计但货币未折算；不是论文归一化综合成本。已发送的远程单次请求没有硬费用保证。

## 可执行命令

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m selection.single_task validate --mock --task examples/single_task/mock_task.json --deployment configs/single_task_mock.json
PYTHONPATH=src python -m selection.single_task collect --mock --task examples/single_task/mock_task.json --deployment configs/single_task_mock.json --output reports/my_single_mock
```

collect输出目录必须新建；同task的持久化尝试不可重复。上面默认mock账本未被本轮验收占用（验收使用report内独立账本）；用户执行一次后重复被拒绝属于预期。真实草稿未填，validate --live应失败；不得自动补假值或发送真实生成。

评分操作：`PYTHONPATH=src python -m selection.single_task evaluate --collection <采集目录> --cards <填好双人评分卡> --output <新评价目录>`。真实完整步骤见docs/single_task_loop.md。原批量回放入口selection.replay仍保留，完整规划器与原估计器最终适配未完成。

## 本轮证据位置

reports/live_backend_20260924_01/ 下：

- ACCEPTANCE.md、tests.log、tests.xml：81项统计、范围与缺项。
- commands.json、verify.py：完整实际命令；verify脚本不宜原地重跑覆盖证据，内部账本会拒绝重发，复制到新报告目录做新的纯模拟诊断。
- api_import.log、legacy_retry_source.txt、stdlib_http_path.txt：精确阻碍与重试来源。
- environment_audit.json、local_service_probe.json、local_compatible_models_probe.json：脱敏配置/模块检查及本机只读模型清单，生成请求0。
- mock_collection/：一个合成任务、三个模拟输出、资源/轨迹、待评分标签与匿名卡；mock_attempts.sqlite3为独立诊断账本。
- synthetic_scoring_cards.jsonl、mock_evaluation/：脚本构造评分及闭环计算，不是真实人工标注。
- duplicate_rejected.log、live_draft_rejected.log：退出1为预期，分别证明防重发和未填部署不会开始调用。

## 下一项具体任务

先集中让用户提供/决定：目标1.5B/7B的路径或端点和版本；或明确另立诊断配置采用本机已安装模型；云模型/兼容接口/凭据变量名和上游无重试依据；一条真实材料、来源组、固定问题证据、输出硬约束和双人评分安排；时限/币种/费率/三次最大尝试总费用范围及授权（不索要密钥）。本轮不等待这些信息阻塞工程实现，依赖它们的真实生成仍未执行。

得到信息后先完成部署本地校验，再在授权范围执行单条独立三模型采集和人工双人试标，评价与调用分离。论文1.5B/7B不能由其他模型默默替代；真实采集不足时不能借用正式校准/测试。后续每轮更新本交接与新的独立报告。

## 2026-10-12：论文与代码框架阅读

- 新增独立阅读报告：[FRAMEWORK_GUIDE.md](reports/framework_reading_20261012_01/FRAMEWORK_GUIDE.md)，已下载官方 ICML 2025 论文并对照原选择核心、估计器、回放、适配、执行器及采集评分链。未修改 src 算法、配置或数据。更新前 HANDOFF 备份在同报告 backup/。
- 本次验证：沙箱内 pytest 为 74 passed/7 errors（本机 HTTP fixture socket 权限）；允许 loopback socket 后全套 81 passed、0 errors/failures/skips，退出 0。validate 退出 0（10 任务、30 调用记录、30 标签）；离线演示退出 0（4 拟合、6 评价、5 策略、30 轨迹）。实际命令、退出状态、日志和 XML 均在独立报告目录。
- 原核心教学脚本 trace_native_router.py 使用显式合成预测、手设 lambda=0.5/gamma=0，展示船端→岸端→停止，退出 0；不是拟合基线或真实实验，无真实模型调用。
- 当前 devmean 的拟合质量均值 [0.55,0.78,0.93]、成本均值 [1,2,3]、lambda=[0,0,0]、gamma=1/3；本次六条评价任务均直接调用云端。说明核心接通，不代表任务/答案感知估计器或 v5 完整方法已实现。
- 阅读发现：replay.py 的 manifest.not_implemented 仍列 live_no_retry_backend，但该模块及测试已存在，清单陈旧；原 CascadeRouter force_order=False 分支中的 best_models[model] 值得另行审计。均未在本轮修改，81 项测试不覆盖原论文全部无序、调参及任务估计器分支。
- 完整预测器、收益增强近邻、联合轨迹采样、四维多目标规划与独立风险校准仍未完成。原始 API 重试链与新单次 HTTP 后端分开；真实部署与费用限制仍按前文约束。

## 2026-10-12：框架报告可视化阅读版

- 用户反馈 Markdown 版式与公式难读，新增 `reports/framework_visual_20261012_01/FRAMEWORK_GUIDE.html` 和同名 PDF（18 页 A4）。HTML 离线可读，包含目录、四角色框架、中文公式及符号解释、期望最大值例子、预算混合例子、三轮决策算例、重绘执行流程图和原报告全部 12 章。
- 原 Markdown 仍为事实来源；`build_reader.py` 调用 render-html skill 解析器生成阅读版，记录源 SHA256 与时间；未修改 src、配置、数据或原阅读报告。HANDOFF 更新前备份在新报告 backup/。
- 本轮文档验证 9/9 通过；Chrome 实际渲染 HTML 并打印 PDF，目视检查浏览器首页、PDF 公式页及流程图页。沙箱首次 Chrome 退出 133（socket 限制），获准本机运行后导出退出 0；实际命令和结果见新报告 commands.json。软件 pytest 本轮运行 0 项；未调用模型或付费 API，旧报告的 81 passed 属于上一轮证据。
- HTML 渲染独立审阅 sidecar 与 trace 放在新报告目录；该审阅只核对转换忠实度与结构，不代表重新验证论文结论。阅读优先推荐 HTML，PDF 供直接阅读和打印。

## 2026-10-13：v5 代码修改与创新实验计划

- 用户要求先提供详细修改计划 PDF，不执行代码改造。交付位于 `reports/v5_implementation_plan_20261013_01/`：`V5_IMPLEMENTATION_PLAN.pdf`（16 页）、同名 HTML、完整 `IMPLEMENTATION_PLAN.md`、实验摘要与 15 项 TODO tracker。摘要和 tracker 已按 experiment-plan skill 保存到 `refine-logs/`，并记录版本与 MANIFEST。
- 以 papers/v5_eng.pdf、v5_zh.pdf 为主规范；明确与较早 TeX 的候选数/实验方案差异。主计划为九方法+两消融、H=11、E1–E6、Qwen2.5-1.5B/7B/14B（14B 自托管）、12 秒/1.50/质量0.80/风险0.10。计划建议与 PDF 原报告缺项明确分开。
- 实施路线：保留原 CascadeRouter 核心与强文献基线，复用执行/账本，新增 v5 评分、收益、近邻联合转移、四维前沿与校准子包；P0–P9 工单与 M0–M6 门槛详见 PDF。公开缓存不替代领域数据，独立三模型采集不伪装顺序网络执行。
- 本轮未修改 src/配置/正式数据；模型调用0、实验0、软件 pytest0。文档验证12/12，Chrome 导出与 pdftotext 均退出0，目视检查表格页。主要命令/结果见新报告 commands.json，论文与代码哈希见 source_snapshot.json；HANDOFF 修改前备份在同目录 backup/。独立渲染审阅 sidecar 仅核对转换保真。
- 下一步若进入实施，从 P0/P1 协议与数据契约开始，再以10–20开发任务完成M1；先评分冻结，再收益/动态库、调参、校准和测试。不得根据计划自动启动4800次预采集或真实E6；正式部署/数据与资源范围仍需落实。

## 2026-10-13：v5 公开数据检索、候选构建与旧缓存复用

- 已完成公开检索并落地 `data/v5_public_20261013/`：UCI 动力仿真完整11934行、NOAA两站2023观测、PolarFront 15/23文件子集、MARTTS 240段合成通信文本；下载URL/哈希/失败状态均保留。原有CSV/JSON和src未修改。HANDOFF修改前备份在 `reports/v5_dataset_20261013_01/backup/`。
- 构建1600候选任务，五类各320；425来源组不代表独立样本。日志仅一航次，模板和诊断任务偏简单；未完成正式划分、人工审阅、三模型输出和实测资源。4800标签槽位均null，禁止称已复现论文1500+100数据设计。
- 导出20条engineering_cache开发任务，通过现有v1校验；其同组亲属共397条标development_reserved，其余1203条unassigned。参考单独放private，开发导出不能直接当真实采集输入或完整回放缓存。
- 新脚本 `scripts/v5_data/fetch_sources.py`、`build_dataset.py`、`audit_dataset.py`；11项数据审计通过，20任务接口验证通过，15个PolarFront文件核对上游校验。pytest0、模型调用0、付费调用0、算法实验0。命令/状态见同报告commands.json和validation.json。
- 用户询问能否先复用旧数据：可以，优先RouterBench答案文本/质量/成本，用代理模型和显式simulated环境验证方法；不能把旧标签当v5三维人工评分，也不能把模拟当实海事结果。SWE-Bench本地model_answers已检查为数值对而非答案正文；改变旧题意后必须重新生成/评分。
- 可读报告 `reports/v5_dataset_20261013_01/DATASET_AND_REUSE_GUIDE.html`，样例 `data/v5_public_20261013/prepared/PREVIEW.html`。下一步建议实现RouterBench适配与10–20条离线模拟开发，保留源组/标签隔离；完整v5方法和校准仍未实现。本轮没有据问询自动启动新模拟实验。

## 2026-10-14：RouterBench开发适配第一步

- 用户授权开始方案第一步。新增 `src/selection/routerbench_adapter.py` 和11项测试，复用旧v1校验，不改原选择算法/CSV。实际导出 `data/routerbench_dev20_20261014/`：20任务、60缓存、60代理标签；按eval_name家族保守开发隔离，缺失延迟和有效性保留null，成本保留未核验单位的原值。非空缓存SUCCESS仅表示结构有效，不表示v5达标。
- 三档代理Mistral-7B/Mixtral-8x7B/GPT-4，保留真实模型ID，不假称目标Qwen。抽样不依赖标签；正式来源/近重复审计、五路划分、资源模拟尚未完成，ready_for_resource_replay=false。本次完成的是P0/P1开发接入子步骤，不是正式M0全部验收。
- 新增测试11 passed；允许本机HTTP测试端口后全套92 passed（4.81秒）；导出与只读验证均退出0。真实模型调用0、付费0。实际命令、XML、统计与HANDOFF备份在reports/routerbench_step1_20261014_01。
- 运行说明：docs/routerbench_v5_steps.md；可读版reports/routerbench_step1_20261014_01/STEPS_AND_VALIDATION.html。下一步补充显式资源/外生链路模拟，随后正式分组工具、评分器、收益/转移库、规划器、调参/校准与测试。不要直接用占位预算和缺失延迟报告完整服务失败率。

## 2026-10-14：第2步时间索引链路与资源模拟

- 新增resource_simulation.py、simulation_replay.py、configs/routerbench_simulation.json和11项测试。执行器增加可选environment_observer及call_at模拟接口，按已计控制开销的累计时间发起调用；原核心选择算法未改，修改前executor/HANDOFF及步骤文档备份在reports/routerbench_step2_20261014_01/backup。
- 三环境：正常、受限、1–8秒断连后恢复；分段积分传输字节与时间，任务/模型固定哈希排队，按回答UTF-8字节估算计算时间。控制器只见当前链路，不见未来节点、标签或未调用答案。失败保留计算/通信费用和检测/取消时间；单次超时后不重试。
- 模拟成本使用显式计算费率、费用/字节参考尺度，不使用单位未核验的原缓存费用；原费用另存metadata。原始缓存和标签不改，有效性仍null。当前为串行外生队列模型、通信时检测断连、请求时限决策边界检查，不声称真实拥塞/硬取消/实测海事资源。
- 完成20任务×3环境×4策略=240工程轨迹、360模拟调用，其中31断连；真实模型调用0。四策略为三固定模型和耗尽顺序fallback；没有伪装训练好的阈值级联或完整v5。20条含dev_fit/dev_eval仅作烟雾检查，非独立测试成绩。
- 新测试11 passed，全量103 passed（4.83秒，允许既有本机HTTP测试）；配置只读验证和回放退出0。所有轨迹审计通过：严格向上/唯一尝试、标签隔离、时间/成本分项守恒。commands.json、tests.xml、validation.json及run/在同报告目录。
- docs/routerbench_simulation.md 与报告SIMULATION_GUIDE.html给出配置含义、运行命令和边界。原step1 ready_for_resource_replay=false保持正确，新入口单独补模拟资源。下一步正式契约与来源/近重复/五分区审计，再评分器和收益/联合转移等模块；独立风险保证尚未实现。

## 2026-10-14：第3步v2任务契约与分组划分工具

- 新增selection/v5/data_contract.py、splits.py、prepare.py、audit_csv.py；不放宽旧v1、不修改CSV或旧模拟执行器。v2严格任务字段、控制器白名单、训练阶段D_Q/D_G/D_V过滤；私有缓存仍v1，非操作系统访问控制。
- 分组以来源、原题ID（跨shot）、来源内模板、规范化完全重复、字符5-gram Jaccard>=0.9的传递闭包为准。近重复穷举上限2000，语义改写审计不完整；草案贪心整体分组分配，不保证类别/数量精确配额，不认证独立性。锁定组不重新分配，冲突报错。
- data/routerbench_v5_contract_20261014含20条v2任务、8组件、公开白名单、私有原缓存和标签、audit/manifest。已用20条全部development；正式D_Q/D_G/D_V/D_C/D_T均0，formal_ready=false。六路工具通过独立合成单元测试，不将开发数据回收为正式测试。
- 两CSV只读全量审计：0-shot36497行、重复ID0、规范化prompt重复额外16；5-shot36511行、重复ID额外14、prompt重复额外14；共享36497个原题ID、9665个prompt哈希。禁止把两文件直接分作训练/测试，未自动删除重复记录。
- 新测试12 passed；全量115 passed（7.24秒，本机HTTP测试授权）；迁移、只读校验和CSV审计退出0。模型调用0、训练0、正式实验0。报告与命令、XML和备份在reports/routerbench_step3_20261014_01。
- 可读说明DATA_CONTRACT_GUIDE.html，源docs/v5_data_contract.md。下一步需扩充未开发的候选训练池并完成来源/重复审查，再实现评分器；五路正式数据冻结、评分和独立风险保证仍未完成。

## 2026-10-14：第4步开发代理评分器

- 新增v5/features.py、scorers.py、selector.py、train_proxy.py和11项测试；simulation_replay增加可选--scorer，不传参数保持旧4策略。备份和报告在reports/routerbench_step4_20261014_01。
- 字符hash代理编码（每字段前512字符，非论文MiniLM/128token），训练集PCA<=32，HGB回归+benchmark质量>=0.8分类。仅原dev_fit15任务45答案拟合，dev_eval5任务15答案评价；没有扩充/重分正式D_Q。有效性未知，service_pass_probability为null，正式状态级服务分类尚未实现。
- 拟合冻结/保存/哈希检查重载已运行，scorer产物在同报告scorer/。MAE0.473246对比训练均值基线0.473333，Brier0.418652；无明显有效性改善，不宣称可靠泛化。PCA维度12/19。
- 可见答案selector取最大预测质量，同分最早；预测阈值策略单独命名predicted_threshold_proxy。20任务×3环境×5策略300工程轨迹，新增策略60轨迹174模拟调用；拟合任务也参加烟雾回放，不报告独立性能。真实模型调用0。
- 新11测试通过，全量126 passed（5.73秒，本机HTTP测试权限）；训练、回放退出0。commands.json/tests.xml/code_snapshot.json保存证据；SCORER_GUIDE.html和docs/v5_proxy_scorer.md提供运行命令。
- 用户无需手动重复常规测试，后续领域人工审核/评分和真实部署需其参与。第4步完成开发代理闭环，正式训练池、MiniLM版本、有效性标签和正式评分器仍未完成；下一步可开发收益/转移接口，不能宣称论文已复现或风险已保证。

## 2026-10-14：进度总表与第5步收益/联合转移核心

- 用户要求持续记录。新增根目录PROGRESS.md及PROGRESS.html，汇总1–4步操作、历史验证和正式缺项；本轮结束更新第5步。新增scripts/render_progress.py用于每轮重建HTML，非后台监控。今后每轮同时更新总表、HANDOFF和独立报告。
- 新增v5/history.py、gain.py、transition_library.py、demo_transition.py。同一冻结预测Selector生成前后实际保留答案收益，保留负值；分动作HGB、来源组权重、显式动作掩码；在线库标签剥离和嵌套字段校验。按动作/有序历史过滤、每来源最近一条、至少5组支持、标准化状态和收益距离、4次联合抽样频率权重。
- 仅12个合成组开发验证（8拟合4查询），4个负收益标签、4查询支持；未使用RouterBench dev_eval或正式D_G，不产生领域/风险实证。最终产物在reports/routerbench_step5_20261014_01/demo_final，含私有训练表、无标签库、模型、检索配置和查询。
- 状态为九维简化代理，没有任务嵌入；Gaussian工程核和常数距离阈值未复现/校准论文公式；正式D_G/D_V、代理状态映射/重新评分和规划器接入未完成。未来不得把donor_record_id放入可观察状态来区分场景。
- 新增12测试通过，全量138 passed（5.37秒，本机HTTP测试权限）；演示两次退出0，真实模型调用0。commands.json/tests.xml/code_snapshot.json及备份在同报告目录。说明docs/v5_transitions.md和TRANSITION_GUIDE.html。
- 下一步第6步规划器开发接口；正式数据、评分器和动态模型缺项继续显式跟踪。用户不必重复常规验证，助手已执行。

## 2026-10-15：第6步规划器与执行器接通

- 接续上轮planner.py、demo_planner.py和14测试；上轮全量测试因自动审批服务用量不足未执行，相关文档补丁也未执行。本轮重新完成验证和记录。
- 新增planner_policy.py（滚动执行适配及显式联合库query/mapper桥接）、demo_planner_runtime.py和5适配测试。无需修改原UnifiedExecutor；实测控制耗时计一次。不能用benchmark代理概率代替service概率；不支持映射明确返回空场景。
- 相关19测试通过，全量157通过。20合成请求通过UnifiedExecutor执行ship→shore→ACCEPT，共40模拟调用，真实模型调用0。报告routerbench_step6_20261015_01保存commands/tests/runtime/code_snapshot和修改前备份。
- 工程核心已连接，正式供体映射、完整状态与前沿压缩、服务分类器、全部强文献基线仍未完成。根PROGRESS.md/HTML及docs/v5_planner.md明确边界；不能把本轮合成结果当论文实证或直接进入正式风险校准。

## 2026-10-15：收尾校准检查与就绪清单

- 新增v5/calibration.py、final_checks.py及12项测试：冻结候选文件和D_C单位，拒绝重复/漏报/错误分区/未知候选/文件变更，未知标签阻断参考上界；单侧Clopper–Pearson用delta/H修正。不自动选策略，不认证统计独立、事前冻结或完整服务失败语义。
- 20条合成零失败fixture，H=1、delta=.05、alpha=.1，参考上界0.13910834066826522，未通过。真实数据仍development20、正式五分区均0；没有重分开发数据，没有真实模型调用。
- 定向12 passed（1.64秒）；全量169 passed（5.81秒，本机HTTP测试获准），退出0；final_checks入口退出0。报告reports/final_checks_20261015_01含commands.json、tests.xml、run、code_snapshot.json和修改前备份。
- 更新PROGRESS.md/HTML及新增docs/v5_final_checks.md、FINAL_GUIDE.html。第7步只有校准基础工具，第8步只有分区统计和人工维护缺项清单；正式数据、评分/动态模型、完整前沿/强基线和E1–E6均待完成，不能称整个论文实验完成。

## 2026-10-15：GitHub 首次上传准备

- 目标账号 D-Cathy，准备 cascade-routing 首次 Git 提交；保留原 LICENSE 和上游 README 署名。排除 data/（约14GB）、凭据、缓存、运行账本、报告备份及本次上传准备报告。
- GitHub 连接器已确认账号，但不支持创建仓库；SSH 已认证为 D-Cathy。目标 D-Cathy/cascade-routing 的 ls-remote 退出128（Repository not found），需要先创建空仓库。首次准备时尚未上传；用户创建仓库后已成功推送 main（代码提交 9098b87）。
- 本轮仅版本管理准备，pytest运行0项、模型调用0次。命令与限制见 reports/github_upload_20261015_01/STATUS.md。

- 上传完成续记：用户确认已创建仓库后，`git push -u origin main` 退出0，main已跟踪origin/main；仓库 https://github.com/D-Cathy/cascade-routing 。本轮未运行测试或模型调用。

## 2026-10-26：框架核查与 GitHub 同步

- fetch确认远端最新仍为2026-10-15的eb893ec，上传前本地/远端提交一致；历史库容量限制、向量化检索及配套测试/文档尚未提交，本轮纳入更新。
- 本轮全量179 passed（8.93秒），退出0；沙箱初次172 passed/7 socket权限错误，允许本机HTTP fixture后全部通过。报告reports/github_review_20261026_01/REPORT.md及日志/XML保存证据。
- 代码已具备开发工程闭环，正式数据五分区、完整论文基线及真实风险校准仍未完成；未调用模型或付费API。
