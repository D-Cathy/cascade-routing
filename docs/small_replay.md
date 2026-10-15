# 小规模回放格式与解释边界

当前入口只做离线工程验证，不访问网络、不加载大模型、不自动付费。复用 `UnifiedExecutor`，五种策略共用记账、动作守卫与评估。完整论文规划器与校准未实现。

## 命令

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m selection.replay --config configs/small_replay.json --validate-only
PYTHONPATH=src python -m selection.replay --config configs/small_replay.json --output "reports/replay_$(date +%Y%m%d_%H%M%S)"
```

输出目录必须不存在，避免覆盖。配置路径按配置文件所在目录解析；输出路径按当前工作目录解析。Python>=3.10，当前实际验证Python3.13.13；离线核心依赖numpy/scipy/scikit-learn/loguru/hyperopt，测试用pytest，实际版本见恢复报告。未安装/升级依赖。原项目其他可选推理依赖不代表本轮均可用。

## 文件边界（schema_version=1）

| 文件 | 必填字段/规则 |
|---|---|
| tasks.jsonl | task_id、source_group_id、source、split、question、evidence、allowed_models、service；source仅synthetic/engineering_cache/real_development；split仅dev_fit/dev_eval |
| service | quality_threshold与risk_target在[0,1]；deadline_s、budget有限非负；cost_unit须同批一致 |
| calls.jsonl | task_id、model_name、model_version、status、answer、latency_s、cost、latency_source、cost_source、data_source、reason；每任务模型唯一 |
| labels.jsonl | task_id、model_name、quality、valid、label_source、rubric_version；quality在[0,1]或null，valid为布尔或null；评估侧独立加载 |

三类文件允许 metadata 保存采集细节，但 metadata 不传给控制器。environment仅接受 network_regime、bandwidth_mbps、queue_depth、observed_at_s；不接受真实标签、参考答案或未来信息。来源组不能跨拟合/评价。字符串/数值、重复键、未知模型、缺失记录与来源不一致会报错。

调用状态：SUCCESS指在线检查有效且非空；FAILED指已尝试但失败；INVALID指已尝试但回答检查无效；UNATTEMPTED指没有发生调用。UNATTEMPTED不能伪装成可用回放答案；若它仍在该任务允许池，执行前会报缺失数据，不擅自改成节点不可用。运行轨迹中未出现的模型保持未尝试。

资源值null必须标missing；非null标measured/derived/simulated。合成资源不允许标measured。缓存没有真实延迟时保持missing，不补造实测值。SUCCESS但没有标签可以运行；最终质量未知时输出null。known_time/known_cost是已知部分下界；total_time/total_cost任一组成未知即null。缺失资源会停止后续花费。

模型调用不添加本地回放函数墙钟，防止双重计时。每轮含终止决策的控制开销只计一次；simulated模式采用固定开销，measured模式采用实测控制器时间，两者不相加。measured_controller_time另列诊断，模拟模式下不纳入总时延。decision_cost为显式配置的工程假设，示例0不是实测免费。当前不是带硬取消的在线执行器，不能宣称远程硬时限/硬预算保证。

## 五策略与原基线适配

- fixed_ship / fixed_shore / fixed_cloud：仅一次指定模型，不升级；未获允许或已知不可用时无答案失败。
- fixed_cascade_fallback：按船、岸、云耗尽合法顺序，返回最近有效答案；这是预测器未就绪的明确替代规则。论文固定阈值级联尚未完成，不能以本规则替代其结果。
- cascade_router_devmean：真实调用原 `CascadeRouter.fit/predict/select_answer`，保留初始选模、超模型质量成本比较和回答后的续行/停止。估计器为仅用dev_fit训练的逐模型均值，不读取评价标签或未来费用；lambda固定0、gamma在dev_fit拟合，无调参搜索。这是原核心的工程接通变体，不是原估计器完整复现，也不是论文强基线最终结果。

适配限制：模型按船岸云排序；每步过滤权限/不可用/已跳过的低层候选。失败或无效尝试用内部非空哨兵标识，并赋极低预测质量，避免原算法将其视作未尝试或选作答案。哨兵不传给模型。最终答案仅在已调用有效答案中由原select_answer按拟合预测均值选择。空历史select_answer不会调用估计器，但初始predict照常决定第一次调用。适配器当前只接受工程均值估计器，其他估计器需另行完成适配和验证，不静默回退。

每种策略的全部请求进入分母。service_failure为质量不足/超时/超预算/无有效答案的并集；无已知失败但任一必要检查未知则为null。汇总输出完整率null及确定失败下界、可能失败上界；这些不是置信区间或风险保证。质量、成本、时间只在全体请求该字段完整时输出均值，另给观测数量，避免仅成功样本均值。

逐请求traces.jsonl保存动作前可见状态、决策、实际调用、累计账本、终止原因、预测选择规则与评估结果。manifest记录种子、输入/代码SHA256、拟合/评价任务和组、原predict次数、未实现策略清单。重复运行语义轨迹与汇总可复现；独立实测控制耗时自然会变化。

## 数据与真实试验

原data包含RouterBench、GSM8K、MixEval、代码/数学与SWE-Bench等缓存。RouterBench有prompt、response、benchmark quality、total_cost字段，但缺少端到端延迟与本领域来源/标注；其他目录有queries/qualities等。只能作为engineering_cache，需要显式转换、确认费用单位和标注含义后使用，本轮未转换或声称它们是领域数据。样本结构核查见 reports/recovery_20260923_01/data_inventory.json 和 cache_structure.json。

本轮演示10个合成任务：4个独立组拟合、6个独立组评价，五策略共30条轨迹。包含失败、无效、资源越限及缺失值。开发模板见 templates/development/README.md。真实试验尚未执行。
