# 项目接手与研究约束

每次开始先读 HANDOFF.md、docs/small_replay.md 和 `/home/guoqiuyuan/LLMresearch/论文初稿_综合修订版_20260922.tex` 的方法/实验设计。论文缺失时先搜索父工作区，不能编造方法；用户本轮范围优先。工作结束更新HANDOFF及独立reports目录，记录实际命令、退出状态、测试数量和限制。无Git时先备份将修改的小量文件，不复制大型数据或重新克隆覆盖。

1. 初始可选任一获准模型，后续仅严格向更高层升级、可跳级；每模型最多尝试一次，失败也占次数。禁止隐式重试。
2. 所有模型读取相同原始问题/固定证据，不读取前模型答案。控制器可读取已经发生的回答反馈和可观测状态。
3. 真实标签、参考答案、未调用输出及未来资源与控制器隔离；不能按真实标签停止或选择最终答案。预测器未就绪的替代规则必须显式命名。
4. 区分UNATTEMPTED、FAILED、INVALID、SUCCESS。失败已发生时间/费用保留；计入控制开销，不重叠重复计时。未知费用/延迟使用null，不能当零。
5. 服务失败是低质量、超时、超预算、无有效答案的并集；分母为全部请求。缺失标签不得称完整失败率为零。资源未知与失败要区别。
6. 保留原CascadeRouter源码与核心选择机制，增加适配层；简化规则不得冒充原算法或论文强基线。当前devmean仅工程变体，论文原估计器适配未完成。
7. 按真实来源组隔离开发拟合/评价、正式训练/调参/校准/测试。合成回放只验证软件；GroundTruth仅可用于标明的合成诊断；无独立校准无真实风险保证。
8. 不自动调用付费API、下载大模型或启动大型实验。原APIQuery多层重试不满足当前协议；真实后端必须先核验单次尝试、失败费用和取消。
9. 本轮小试验仅开发10—20条，不使用正式校准/测试。论文规划器、真实系统保证和正式实证需另行完成。

验证入口：`PYTHONPATH=src python -m pytest -q`。pytest只扫描tests，reports中的备份不应被收集。离线演示：`PYTHONPATH=src python -m selection.replay --config configs/small_replay.json --output <全新目录>`。输出目录禁止覆盖。

## 单条开发任务调用约束（2026-09-24）

后端使用single_task/LiveModel/SingleHTTPTransport，禁止回退到原APIQuery的多层重试链。真实调用必须使用UnifiedExecutor的wall_clock+measured模式；不要将分项延迟再次加到总墙钟。attempt_ledger的(task_id, model_name)唯一记录在发送前持久化；PENDING也不得自动重发，不得删账本或换任务ID规避一次尝试限制。费用未知停止后续采集，已知部分保留；当前费用仅provider token fee，不能冒充论文归一化开销。

读取docs/single_task_loop.md后操作。collect和evaluate分离；人工评分不能改变已经选择的答案。当前仅模拟和本机假HTTP服务通过测试；本机11434的模型清单已读到，但真实生成、目标1.5B/7B部署及云接口仍未验收。
