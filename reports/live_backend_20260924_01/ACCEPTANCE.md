# 单条开发任务后端验收（2026-09-24）

项目：/home/guoqiuyuan/LLMresearch/cascade-routing；主机GPU8。已读取AGENTS、HANDOFF、最近recovery_20260923_01/ACCEPTANCE及论文资源核算/模型输入/实验设计。无Git；修改前备份见backup，原api.py、completion_llms.py、__init__.py及CascadeRouter未改。

## 结论

实现了最小单次HTTP调用后端，并复用统一执行器、加载器和终止评价完成单条任务的采集→匿名评分卡→评价文件闭环。**模拟验证通过，真实模型生成尚未执行；无付费API调用、无模型下载、无完整规划器扩展、无论文实证或风险保证。**

最终测试 81 项、失败 0、错误 0、跳过 0，退出0。原50项保留并通过，新增31项。测试含内存模拟和本机临时HTTP服务器，不是实际LLM。

## 旧调用链和具体阻碍

- 当前Python直接 `PYTHONPATH=src python -c 'import selection.api'` 退出1，精确错误为api.py:4 `ModuleNotFoundError: No module named 'langchain_openai'`，完整栈见api_import.log。
- __init__.py宽泛捕获可选导入异常并置APIQuery=None，掩盖了原始栈。基础环境也缺langchain_core、anthropic/together/google_genai/huggingface封装与openai包；不是单一导入名拼写错误。
- vive环境Python3.10.20有openai，但同样缺所需LangChain组件；未切换环境或自动安装依赖。只做find_spec，不宣称未实际导入的第三方组件运行兼容。
- 旧APIQuery默认max_retries=20；api.py约413/444行的外层重试，加上ChatOpenAI透传SDK重试，其余供应商/completion分支未统一禁用SDK默认重试。sequential=False分支还设置times=[0]。来源摘录见legacy_retry_source.txt。旧路径不用于新采集。

## 实际模型/端点检查

| 角色 | 项目配置事实 | 当前是否可用 |
|---|---|---|
| 船 | 论文起点Qwen2.5-1.5B；部署模板路径/端点/版本为空 | 目标模型未确认，不等于服务器没有模型 |
| 岸 | 论文起点Qwen2.5-7B；部署模板路径/端点/版本为空 | 目标模型未确认，不等于服务器没有模型 |
| 云 | 云模型/供应商/端点/费率未确定，检查的凭据变量未设置 | 尚未配置或验收，未调用外部接口 |

项目脚本存在模型ID和供应商示例URL，但无船岸云明确部署映射或实际本地权重路径。只检查项目代码/配置、指定环境变量和两个已存在Python环境，不做“全服务器无权重”的推断。

新发现：本机11434端口在监听；只读GET `/api/tags` 和 `/v1/models` 均HTTP200，列出9个已安装模型：qwen2.5:3b, artifish/llama3.2-uncensored:latest, hopephoto/Qwen3-4B-Instruct-2507_q8:latest, deepseek-r1:14b, deepseek-r1:latest, qwen3:14b, qwen3:8b, llama3.1:8b, qwen3:4b。摘要及digest/量化见local_service_probe.json，兼容模型列表见local_compatible_models_probe.json。这推翻“常见目录没发现就可能没模型”的简单判断。该服务清单不含指定的1.5B/7B，但不推及其他服务/路径。没有发送POST生成请求；模型实际推理、参数支持、服务端重试均仍未验证。没有擅自把3B/其他模型改名为船岸目标。

环境变量仅保存存在性布尔值，无密钥。两次实际服务请求均为本机只读元数据GET；外部端点探测0，实际模型生成0。测试中的临时HTTP请求仅向本机假服务器发送假模型ID。

## 实现与验证边界

新增live_backend.py：发送前SQLite唯一占用一次尝试，完成时落盘；失败/超时/PENDING不自动重发。费用未知仍保存known_cost下界，持久化完成异常也保留内存中已知费用。重复任务即使换输出目录也拒绝。

新增http_once_worker.py：独立标准库进程，一次POST，不调用SDK、不跟随重定向、不使用代理环境变量、不重试429/500/断连。父进程超时kill/reap本地工作进程，不声称远端取消或费用归零。标准库路径证据见stdlib_http_path.txt。远端网关内部重试需要部署提供者确认。

复用UnifiedExecutor：新增wall_clock模式，控制与调用分项不重复相加；deadline向后端传剩余时间；原回放模式保持。已知失败资源照记，cost=None不会默认为0。新增CallNotStartedError将重复/未通过预检与真正已尝试失败区分。

schema扩展known_cost、metadata；metrics提取共享evaluate_terminal；replay_data抽取validate_tasks供采集与原回放共用。没有再造执行器或改变原CascadeRouter。

新增single_task.py：明确validate/collect/evaluate，collect --mock默认不接触模型；真实collect需显式--live与完整授权配置。三个模型通过统一执行器分别单次固定采集，共同原始问题与证据。标签文件不读入采集端；评分卡隐藏模型/状态/成本，私有映射只在评价侧。

当前成本仅按提供费率推导provider token fee，明确derived，paid_fee缺失；不是实际付款或论文综合成本。未知账单或采集总费用达到/超过范围后，后续保持UNATTEMPTED。守卫不保证已经发送的远程单次请求硬性不超支。

## 实际命令、退出及产物

工作目录为项目根；完整绝对参数见commands.json。

| 命令 | 退出 | 数量/结果 |
|---|---:|---|
| `PYTHONPATH=src python -m pytest -q --junitxml=.../tests.xml` | 0 | 81通过、0失败/错误/跳过；tests.log/xml |
| `python -m selection.single_task validate --mock ...` | 0 | 本地配置通过，无模型请求；validate_mock.log |
| `python -m selection.single_task collect --mock ...` | 0 | 一条合成任务，三个模拟模型各一次；collect_mock.log |
| 同task再次collect到不同目录 | 1（预期） | 持久化账本拒绝；duplicate_rejected.log |
| `python -m selection.single_task validate --live` 使用未填草稿 | 1（预期） | 缺失来源组/部署被拒绝，无真实请求；live_draft_rejected.log |
| `python -m selection.single_task evaluate ...` | 0 | 三份模拟双人评分计算及评估文件；evaluate_mock.log |

验证/采集/评分CLI不提供pytest式通过失败跳过数量，不编造此类数字。刚开始沙箱命令因bubblewrap mountinfo问题退出1，后续命令按权限流程执行；无其他测试失败。

mock_collection/保存tasks/calls/labels.pending、traces、annotation_cards、private_annotation_map和manifest。模拟阶段三个答案质量未知，未声称完成真实标注。synthetic_scoring_cards.jsonl中评分由脚本填入synthetic-rater-A/B，**不是人工评分**；mock_evaluation/的零失败和Q=1只验证计算逻辑，不能当实证结果。各模拟调用费用2e-5模拟单位、合计6e-5；计时是本机软件和SQLite开销，不是模型推理延迟。

81项测试覆盖原50项及新增成功/失败/超时/无效输出、部分/缺失费用、同ID跨对象防重发、PENDING、并发唯一预占、墙钟不重复、控制前超时、真实worker对本机假HTTP的429/500/断连/重定向/坏JSON处理、假错误内容不进日志、未知费用停止采集、评分分歧拒绝与否决、评价不改原执行轨迹。mock_backend仅为模拟传输，不冒充真实模型。

## 一条真实任务的下一步

按docs/single_task_loop.md执行：填原始问题/固定证据/来源组/服务要求 → 填三模型部署及费用授权 → validate本地校验 → 授权后collect独立采集三输出及资源 → 仅给标注者匿名cards → 双人0—4分/有效性/否决与裁定 → evaluate只在评估侧计算质量和完整失败并集。未填或分歧未裁定拒绝评价；不使用人工标签决定已经发生的路由。

当前仍需用户集中提供：

1. 是否坚持论文Qwen2.5-1.5B/7B；如坚持，提供实际本地路径或服务地址、精确版本/量化/框架；若使用当前本机已安装模型做另立配置的开发诊断，须明确指定角色并记录研究配置改变，不能沿用论文模型名。
2. 云供应商、完整兼容chat/completions端点、model_id/版本、凭据环境变量名（不提供密钥），以及上游代理/服务无模型级重试的配置依据。
3. 一条真实开发材料及来源/日期/来源组、问题、固定证据、输出要求/硬约束、参考与评分锚点、两位复核人员；不占用校准/测试。
4. 服务时限、费用币种、输入/输出费率及适用计费项、用量完整性、最多三次尝试的总费用范围与授权。若本地调用无API收费，仍须明确这是provider fee为零，不能声称GPU/能耗成本为零。

仅有权重路径但无HTTP服务时，还需明确本地推理部署方案；本轮不启动服务或加载大模型。真实生成、远程超时取消、供应商账单一致性、真实三模型评分与研究模型池互补性均未验证。完整规划器/风险校准不在本轮范围。

## 文件清单

修改schema.py、executor.py、metrics.py、replay_data.py；更新README、AGENTS、HANDOFF及开发模板README。新增live_backend.py、http_once_worker.py、mock_backend.py、single_task.py、test_live_backend.py、两份single_task配置、一个模拟任务、一个单条真实任务草稿、docs/single_task_loop.md及本报告目录。完整旧文件before/after hash见changed_files.json。原API/基线来源hash见unchanged_legacy_hashes.json。
