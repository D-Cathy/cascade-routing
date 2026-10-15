# 第2步：RouterBench时间索引资源模拟

第2步工程实现已完成：20个开发任务 × 3种链路环境 × 4种工程策略，产生240条请求轨迹。全部离线复用回答缓存，不发送真实模型请求。正式资源测量、训练预测器和风险校准未执行。

## 实现文件

- `src/selection/resource_simulation.py`：分段链路、按任务/模型固定的排队样本、计算与传输耗时、失败检测和取消、模拟费用账本。
- `src/selection/simulation_replay.py`：严格配置检查、输入哈希检查、批量回放、事后标签评估、分环境/策略统计。
- `src/selection/executor.py`：新增可选environment_observer和call_at接口；模拟调用读取控制开销计入后的实际累计时间，原有静态/真实调用接口保持兼容。
- `configs/routerbench_simulation.json`：所有模拟假设集中配置。
- `tests/test_resource_simulation.py`：11项新测试，含带宽切换、部分传输断连、恢复、超时、费用保留、船端独立、累计时钟及重试约束。

## 资源计算逻辑

远端调用按顺序执行：上传 → 排队 → 计算 → 下载。船端仅排队和计算。耗时模型为串行、不重叠设计，各分项直接相加；控制耗时由执行器每轮另记一次。实际Python控制器耗时保留作诊断，不重复加进模拟总时间。

计算时间 = 模型基础时间 + 回答UTF-8字节数 × 每字节时间系数。这是明确的代理模型，不是实测推理时间，也不把字节当token。回答长度仅在后端模拟器内部使用，控制器不能提前看到未来输出长度或答案。

排队时间由seed、task_id、模型角色的哈希确定，因此不同策略在同一任务/模型上使用相同排队样本。当前是外生排队假设，尚未实现受调用行为影响的共享服务器队列；不能报告真实拥塞效果。

传输按UTF-8问题、固定证据和回答字节计算，不含真实HTTP/TLS协议开销。带宽在传输过程中跨越时间节点时分段积分；传输只计实际完成字节。单程传播延迟按该传输阶段开始时采样，传输阶段遇到零带宽立即进入失败检测，没有自动等待恢复或重发。

三个环境：正常1Mbps/单程0.03秒；受限0.2Mbps/单程0.15秒；中断环境0–1秒正常、1–8秒断连、8秒后恢复。船端不经过链路。各策略共用同一条外生时间表，从请求接收时刻t=0开始，按各自累计时间读状态；控制器只能看到当前状态和观测时间，不能看到未来节点。

断连如果发生在远端计算期间，在下次通信时检测，不假设远端计算会自动取消。单次调用超时15秒；失败检测最多0.5秒并受单次超时剩余时间限制；取消再记0.1秒。这是每次调用超时机制，**不是请求12秒时限的硬取消**：当前请求时限仍在决策边界检查，越限如实评为失败。

## 成本和质量边界

模拟计算费用 = 已发生计算秒数 × 模型模拟费率。

归一化成本 = 0.5 × 模拟计算费用/1.0 + 0.5 × 已传输字节/10000。

模型模拟费率、参考量和权重均为工程配置，不是实测费率或训练数据估计。每次控制决策额外记0.001模拟归一化单位。当前不另收模拟排队/取消费用，时间仍计入；能耗项为零权重。原RouterBench成本保存到调用metadata中，仅作对照，不参与新账单，避免把单位未核验的旧值直接冒充v5归一化费用。

失败时保留已发生计算与已传字节费用，无完整回答则不暴露缓存答案。成功、内容未变的回答继续使用原benchmark代理质量，标签只在请求终止后读取。有效性标签仍为null，没有把非空文本自动当作v5有效性标签；因此完整服务失败率可能为null，输出确定失败下界/可能失败上界。这两个界限不是置信区间或风险保证。

四策略是fixed_ship、fixed_shore、fixed_cloud、fixed_cascade_fallback。最后一项耗尽合法顺序、返回最近有效答案，不是论文阈值级联。不运行cascade_router_devmean：现有拟合接口要求完整有效性标签，而本数据尚缺该标签；不能为了运行而填true。后续评分器和完整基线按第4/6步完成。

## 验证命令

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing

# 配置和输入校验，不运行回放
PYTHONPATH=src python -m selection.simulation_replay \
  --config configs/routerbench_simulation.json --validate-only

# 新增测试：预期11 passed
PYTHONPATH=src python -m pytest -q tests/test_resource_simulation.py

# 完整回归：本轮103 passed；旧HTTP测试需要本机端口权限
PYTHONPATH=src python -m pytest -q

# 离线回放：使用一个尚不存在的目录，预期240条轨迹
PYTHONPATH=src python -m selection.simulation_replay \
  --config configs/routerbench_simulation.json \
  --output reports/routerbench_simulation_mycheck
```

预期输出status=completed、tasks=20、regimes=3、policies=4、traces=240、model_calls_executed=0、risk_guarantee=false。输出目录已存在会拒绝覆盖。

本轮已运行结果在 `reports/routerbench_step2_20261014_01/run/`：

- traces.jsonl：240条请求，含当前可见状态、决策、逐调用资源分解、终止结果。
- summary.json：12组统计，每组20请求；均使用全部请求作分母。
- manifest.json：输入/代码哈希、配置、来源和局限。

轨迹中的simulated资源和决策可复现；measured_controller_time是宿主机实测诊断值，不保证逐字节复现。所有20条（含原dev_fit和dev_eval）仅做接口烟雾测试，不能将汇总数作为独立测试成绩。工程回放中出现31次模拟断连调用，没有真实网络断连或真实模型调用。

第1步导出器中的ready_for_resource_replay=false继续保留：原缓存自身仍没有资源数据；新入口在不改写原缓存的情况下提供了显式模拟资源。下一步是正式数据契约、来源/近重复审计及五路划分工具，然后才能训练和冻结评分器。
