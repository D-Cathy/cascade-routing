# 恢复、验收与小规模试验准备报告

日期：2026-09-23。主机GPU8；项目 `/home/guoqiuyuan/LLMresearch/cascade-routing`；论文 `/home/guoqiuyuan/LLMresearch/论文初稿_综合修订版_20260922.tex` 确认存在并已读取方法、基线、实验设计、数据隔离、来源卡和评分协议。最初cwd是项目的父工作区，所有项目修改均显式指向服务器项目。

## 结论与此前声明差异

原新增schema/executor/policies/metrics、测试、__init__和HANDOFF均存在。原CascadeRouter和BaselineCascader的空答案guard已在文件中。没有Git，也没有找到此前适用的祖先或项目AGENTS；本轮新建项目AGENTS。将修改的9个已有文件先备份到backup（不含大型数据）。源码基线没有被替换，cascade_router.py、baseline_cascader.py、__init__.py本轮未修改。

旧HANDOFF写的是6通过1失败并推测修复后会通过，不能作为验收证明。本轮修改前实际7通过，见before_tests.log；但仅7项测试不足以证明研究约束。发现并修复：参考quality直接进入状态/停止/最终选择；升级顺序依据输入列表且实际execute未阻止下降；invalid_after_answer未生效；失败/无效与无答案判断不全；只计CALL决策开销、回放延迟叠加本地墙钟；无未知账本；无真正原基线适配。

最终结果：50 passed、0 failed、0 errors、0 skipped，退出0。第一阶段最初扩展验收27通过，后续包含文件、批量、复现、边界共50通过。**只完成工程验收与准备，真实试验尚未执行，论文实证未完成，无风险保证。**

## 实际命令与退出状态

工作目录均为项目根，Python为 `/home/guoqiuyuan/miniconda3/bin/python`。

| 命令 | 退出 | 实际结果 |
|---|---:|---|
| `PYTHONPATH=src python -m pytest -q tests/test_unified_runtime.py` | 0 | 修改前7通过；before_tests.log |
| `PYTHONPATH=src python -m pytest -q tests/test_unified_runtime.py tests/test_runtime_contracts.py` | 0 | 第一阶段27通过；phase1_tests.log |
| `PYTHONPATH=src python -m pytest -q --junitxml=.../final_tests.xml` | 0 | 最终50通过、0失败/错误/跳过；final_tests.log/xml |
| `PYTHONPATH=src python -m selection.replay --config configs/small_replay.json --validate-only` | 0 | 10任务、30调用记录、30标签记录；validate.log |
| `PYTHONPATH=src python -m selection.replay --config configs/development_replay.template.json --validate-only` | 1（预期） | 未填来源组等字段被拒绝；draft_rejected.log，不是可运行真实数据 |
| `PYTHONPATH=src python -m selection.replay --config configs/small_replay.json --output reports/recovery_20260923_01/final_synthetic_run` | 0 | 6评价请求×5策略=30轨迹；final_replay.log |

完整参数、解释器绝对路径、实际退出码见verification_commands.json，采集脚本verify.py。验证器/回放器没有通过/失败/跳过测试数量接口，上表报告其实际记录数量，不冒充测试数。

中间失败也保留说明：新增测试第一次26通过1失败，原因是对原算法zero-lambda/gamma并列路径选择预期错误，随后以低预算明确验证停止；首次运行pytest -q误收集backup旧测试，退出2、1 collection error，已用pyproject的testpaths限定tests；一次环境核查忘设PYTHONPATH退出1（ModuleNotFoundError），重跑成功。最初两条沙箱命令因bubblewrap mountinfo错误退出1，后续经提权批准执行，没有换目录伪造环境。这些是实际过程记录，不计入最终50项统计。

## 已验证功能与限制

| 项目 | 证据/状态 |
|---|---|
| 空历史安全且初始允许调用 | 原select_answer不调用未fit估计器；适配器初始predict真正调用，测试通过 |
| 全失败/全无效/空ACCEPT | 无有效答案失败、参考质量0；无隐式重试 |
| 失败计费/顺序/权限/不可用 | execute级重复、向下、跳级开关、乱序模型列表、禁止模型、已知不可用测试通过 |
| 标签/未调用答案隔离 | 状态不包含hidden字段；逐步间谍检查；翻转评价标签后五策略路线/答案不变 |
| 终止与记账 | 模拟CALL和终止控制开销计一次；measured另一路径；失败成本保留；未知总量null+已知下界 |
| 失败并集 | 低质量/超时/超预算/无有效答案可同时记录；分母全部请求，未知结局不报0 |
| 原基线真实接通 | 原fit/predict/select_answer均运行，最终批量原predict调用次数 6；失败历史升级、权限子集测试通过 |
| 数据隔离与复现 | dev_fit/dev_eval来源组不相交；固定seed；重复运行汇总和语义轨迹相同，实测控制耗时除外 |
| 缺失/坏数据 | NaN、负数、标签混入任务、未来环境字段、重复键、缺失调用、假实测来源等拒绝 |

尚未覆盖或不能运行：真实API/本地推理、远程取消、在线完整墙钟账本、多时刻网络/排队反事实、真实能耗/传输成本、并发、真实任务标签可靠性、完整论文评分器与规划器、原估计器适配及调参、正式校准/测试。原仓库没有其他独立测试套件（原来仅test_unified_runtime.py）；未执行大型scripts/main.sh或付费generation脚本。pytest没有用skip隐藏这些缺项，均明确在此列出。

## 小规模文件结果（合成，不是论文结果）

四个合成来源组仅拟合工程均值估计器，六个不同合成来源组仅评价。拟合lambda固定0、gamma仅拟合侧估计，无参数搜索、无GroundTruth评价查表。labels与tasks/calls分文件。每条模型记录有版本、状态、回答、费用/耗时来源；模拟值明确simulated。

| 策略 | 全部请求 | 确定失败 | 未知结局 | 失败比例上下界（非置信区间） |
|---|---:|---:|---:|---:|
| fixed_ship | 6 | 5 | 1 | 0.833–1.000 |
| fixed_shore | 6 | 5 | 1 | 0.833–1.000 |
| fixed_cloud | 6 | 2 | 2 | 0.333–0.667 |
| fixed_cascade_fallback | 6 | 3 | 1 | 0.500–0.667 |
| cascade_router_devmean | 6 | 2 | 2 | 0.333–0.667 |

各策略都有缺失质量及费用/耗时诊断样本，故完整失败率、全体平均质量/成本/时间均为null；观测数量另列，逐请求原始质量与账本在traces.jsonl。这是故意验证缺失处理，不做完整样本性能排名，也不删缺失样本缩小分母。

fixed_cascade_fallback只是预测器未就绪时耗尽顺序并保留最近有效答案的规则。论文固定阈值级联未完成。cascade_router_devmean保留原核心搜索，但使用开发均值预测器，**不是原估计器完整复现、不是最终论文强基线**。两项限制均写入策略名、manifest和文档；其余未实现策略逐项列在manifest中，没有借用名字代替。

原data检查：RouterBench有sample_id/prompt/model_response/benchmark quality/total_cost，无完整真实端到端延迟与领域来源；其他GSM8K/MixEval/代码数学/SWE-Bench文件含queries/qualities等。能作为将来转换的工程缓存候选，不能冒充船岸云数据。本轮使用显式合成fixture，不声称完成缓存实证；文件结构见data_inventory.json、cache_structure.json。

## 一条实际轨迹

final_synthetic_run/traces.jsonl 的 synthetic-05 + fixed_cascade_fallback：

1. 空历史调用船端；失败，耗时1、费用1，次数已占用。
2. 调用岸端，同一原始问题/证据；有效答案，耗时2、费用2。
3. 调用云端，同一原始问题/证据；有效答案，耗时3、费用3。
4. 顺序耗尽后ACCEPT，按明确的最近有效答案替代规则选云端，不用真实质量选择。

共3次尝试、4次决策。模拟总时间1+2+3+4×0.01=6.04秒，成本1+2+3=6模拟单位，包含失败调用。终止后才读取评价标签Q=0.93；时限10、预算10、质量门槛0.8，因此这个合成请求不失败。该单例不提供风险保证。

synthetic-07同策略另演示失败并集：船→岸后停止，3.03秒、成本3，超出时限1.5/预算2.5；最终岸答案Q=0.78，三个原因LOW_QUALITY/TIMEOUT/BUDGET_EXCEEDED同时记录。

## 真实开发小试验准备与缺项

可立即开始收集/试标准备，但不能直接开始已验收的三模型真实执行。

- 已有：15任务槽位（可调整10—20）、45调用/45标签槽位、五类来源卡、评分量表和双人复核协议、部署登记、严格加载器/回放器/结果文件/测试。
- 待提供：真实材料及使用依据、独立来源组/近重复关系、领域复核人及任务级锚点、服务时限/预算依据。
- 待落实：船Qwen2.5-1.5B和岸Qwen2.5-7B的已部署路径/端点、版本/量化/框架/设备与生成参数；云模型/供应商/版本/费率与调用授权。
- 环境实查：GPU8有8×RTX4090（各24564MiB）；当前基础Python3.13.13。openai包未安装、APIQuery及三种任务估计器可选导入失败，CascadeRouter可导入；四个常用凭据环境变量均未设置，只记录布尔值。仅检查HF默认缓存和工作区models目录，未发现目标权重目录，不能据此断言服务器任何位置均无模型。
- 待实现/验收：单次无重试真实调用后端、费用/取消/验证时间记录与成本归一化尺度；原APIQuery默认max_retries=20且存在内外层重试，不能直接拿来采集。未尝试联网探测端点。
- 待后续研究：真实训练预测器、正式固定阈值基线、原估计器受限适配、完整规划器与独立校准。本轮工程均值预测器不能用于声称论文方法已实现。

下一项具体任务：补齐templates/development的来源卡、部署表和10—20条开发任务，先做无重试后端的单请求接口验收与2—3条双人试标；得到质量/时间/费用和完整日志后再运行开发批量回放，来源组隔离拟合与留出评价。付费调用、下载权重须有明确范围授权。不要借用正式校准或测试。

## 文件变更与保存

修改：schema.py（状态/评估/未知语义）、executor.py（统一执行）、policies.py（无标签规则）、metrics.py（缺失和全部请求统计）、test_unified_runtime.py（去掉过时hidden状态构造并加强断言）、pyproject.toml（Python>=3.10及testpaths）、README.md、HANDOFF.md。__init__.py和原CascadeRouter源文件未变。

新增：cascade_adapter.py、replay_data.py、replay.py；test_runtime_contracts.py、test_replay.py；configs两份；data/small_replay三文件；templates/development六份文件；docs/small_replay.md；AGENTS.md；本reports目录的报告、日志、环境清单、备份与最终结果。

final_synthetic_run为最终代码结果。synthetic_run是较早工程检查产物（保留、不覆盖），不能与最终结果混用。完整变更hash见changed_files.json；原基线hash见baseline_provenance.json；论文未修改。
