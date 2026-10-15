# RouterBench 到 v5：实施步骤与第一步验收

## 修改顺序

| 步骤 | 修改内容 | 验收产物 |
|---|---|---|
| 1 数据接入与开发边界（本轮完成） | RouterBench CSV 转旧 v1 契约，显式三档代理模型，任务/缓存/标签分离，来源组开发隔离，哈希和只读验证入口 | 20任务/60缓存/60标签；边界、缺失值、防覆盖测试通过 |
| 2 资源与环境模拟（已完成开发版） | 新增版本化环境配置、计算/排队/传输/控制时间与归一化费用；保留原缓存资源；正常/受限/中断外生轨迹 | 无重试、严格升级、失败计账、null传播及共享时间轨迹测试；10–20任务离线演示 |
| 3 正式协议与划分工具（工程工具已完成，正式数据未冻结） | 新增v5版本契约和开发/D_Q/D_G/D_V/D_C/D_T划分；近重复和模板组审计、独立样本数统计 | 冻结分区清单，禁止来源交叉；开发导出器不会自动升级为正式划分 |
| 4 表征与评分器（开发代理已接通，正式版未完成） | 问题/已返回答案特征、质量回归与达标分类；D_Q训练后冻结；有效性单独处理 | 预测与真实标签接口隔离、误差/校准诊断、冻结模型版本 |
| 5 收益模型与联合转移库（开发核心已完成） | 冻结评分器产生D_G状态；新增升级收益预测、近邻联合质量/时间/成本样本和支持不足回退 | 不读取未来答案；联合相关性与回退测试 |
| 6 v5规划器与基线 | 严格向上动作、四维前沿、终止选择；补齐一次路由、阈值级联和原超模型级联基线 | 手工可核验小例子、合法路径和标签泄漏测试；不把devmean当完整文献基线 |
| 7 调参与风险校准 | D_V选定候选后冻结，D_C执行完整请求风险检验，多候选修正；统计单位为审计后的独立来源组 | 校准集不回流训练；不足以独立校准时明确拒绝风险保证 |
| 8 实验与领域迁移 | 在冻结模拟协议下做主比较、消融和链路敏感性分析；领域数据另采指定三模型回答、人工评分和实测资源 | 先报告公开benchmark代理实验，后报告有证据支持的领域结果 |

依据原实施计划P0/P1先完成开发接入子步骤，P2资源工作与正式P1划分审计随后完成。本轮不是正式M0全部验收：没有五路正式划分、领域评分标准冻结或完整成本定义。v5算法核心仍按原计划实施。

## 第一轮实际改动

- `src/selection/routerbench_adapter.py`：可执行的离线导出/校验入口，复用原 `validate_tasks/load_dataset`，不放宽旧格式。
- `tests/test_routerbench_adapter.py`：11项测试，覆盖全错样本保留、缺失不补零、标签隔离、来源隔离、重复ID/跨来源重复问题拒绝、安全解析、异常数值、可复现、防覆盖和产物篡改。
- `data/routerbench_dev20_20261014/`：实际导出的任务、缓存、标签和manifest。原CSV未修改，原CascadeRouter核心未修改。

代理映射固定为 ship=Mistral-7B、shore=Mixtral-8x7B、cloud=GPT-4-1106-preview。这仅是开发角色，不是目标Qwen模型，也没有逐题质量单调性假设。没有按标签筛选模型或样本。

样例按seed+sample_id哈希抽取；按整个eval_name家族分组，再分dev_fit/dev_eval。它是保守开发隔离，不等于真实来源独立性证明。导出内跨家族相同规范化prompt会拒绝；全库近重复、0/5-shot关联尚未完成。当前入口只用于0-shot，切换数据版本必须另设数据标识和审核。

prompt与response的列表字符串用ast.literal_eval安全解析，按原顺序用空行连接。多消息角色结构未保留，当前仅做缓存接口开发，不能直接视为原推理请求的完整复现。

CSV分数作为 `routerbench_proxy` 标签单独保存；有效性标签保留null。缓存非空文本只按现有结构检查标SUCCESS，不表示回答正确或满足v5有效性。空回答标INVALID并注明历史执行状态未知，不伪造未调用或传输失败。

成本保留上游值，来源标derived（缓存转换），单位标 `routerbench_raw_cost_unverified`；延迟为null/missing。service中的12秒、0.8、1.5只是开发契约占位；1.5尚不能解释为已归一化预算。禁止用该产物宣称完整资源/风险实验成功。

任务文件不含答案、分数、oracle；缓存与标签只供受控后端/评估读取。文件分离不是操作系统权限隔离，后续控制器入口仍须白名单传参，只在选定调用后暴露该回答。

## 怎么运行验证

先进入项目目录：

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing
```

验证已导出的真实缓存，无模型调用：

```bash
PYTHONPATH=src python -m selection.routerbench_adapter \
  --output data/routerbench_dev20_20261014 --validate-only
```

预期status=validated，tasks=20、calls=60、labels=60，ready_for_resource_replay=false。

运行新增测试：

```bash
PYTHONPATH=src python -m pytest -q tests/test_routerbench_adapter.py
```

预期11 passed。运行全部回归：

```bash
PYTHONPATH=src python -m pytest -q
```

已有HTTP测试需允许绑定本机端口，不会调用外部模型服务。

重新导出到一个尚不存在的目录：

```bash
PYTHONPATH=src python -m selection.routerbench_adapter \
  --source data/routerbench_0shot.csv \
  --output data/routerbench_dev20_mycheck --limit 20 --seed 20261014
```

重复使用同一个输出目录会拒绝覆盖，这是预期保护。相同输入与seed导出的三份JSONL逐字节相同。当前limit限定10–20；扩大训练数据应在完成分组/协议工作后新增正式入口，而非把这批开发样例当正式测试集。

2026-10-14第2步更新：显式模拟入口、240条工程轨迹及103项全量测试已完成；运行命令和限制见 `docs/routerbench_simulation.md`。正式资源测量与风险实验仍未执行。

第3步更新：v2任务契约、六路草案分配、20条开发锁定、两CSV全量ID/完全重复审计已完成；正式五路样本尚未创建。见docs/v5_data_contract.md。全量115项测试通过。

第4步更新：轻量代理编码、PCA/HGB质量与benchmark达标预测、冻结存取和可见答案选择已接通；15/5开发训练评价，300模拟轨迹，全量126测试通过。正式MiniLM编码器、训练池和有效性标签尚缺，详见docs/v5_proxy_scorer.md。

第5步更新：收益标签/回归、来源去重检索与联合抽样开发核心完成，正式动态库及代理状态映射未完成。全量138测试通过；持续状态以根目录PROGRESS.md/PROGRESS.html为准。
