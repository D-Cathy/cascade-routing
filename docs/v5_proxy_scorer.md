# 第4步：开发版特征、质量预测器与答案选择

本轮完成离线训练→冻结保存→重载预测→接入模拟回放的工程闭环。使用15条dev_fit任务、45份缓存回答训练；5条dev_eval任务、15份回答评价。未扩充正式训练池，没有把development改标为D_Q，也没有执行正式训练或校准。该实现是明确命名的开发代理，不是论文评分器完整复现。

## 新增模块与输入输出

- `selection/v5/features.py`：问题/固定证据与答案分别编码，训练集拟合PCA，模型角色、全文字符长度和空答案标志作为附加特征。
- `selection/v5/scorers.py`：HistGradientBoostingRegressor预测质量，HistGradientBoostingClassifier预测原benchmark分数达到0.8的概率，保存/加载带哈希的冻结产物。
- `selection/v5/selector.py`：仅对已经返回且结构有效的答案评分，保留预测质量最大者，同分保留最早答案；达到预测质量阈值后停止。
- `selection/v5/train_proxy.py`：仅开发模式入口，分组/重复检查，训练评价分离，保存实际训练ID和输入哈希。
- `selection/simulation_replay.py --scorer`：在原四策略之外增加predicted_threshold_proxy，未提供scorer时仍是原四策略。

预测接口只接收question、evidence、answer、model_name，拒绝包含quality等额外字段。输出predicted_quality、proxy_score_pass_probability及service_pass_probability=null。空答案输出质量/代理概率0。调用前没有答案时selector返回None，不读取未调用缓存，不假装已有可接受答案。

## 与论文方案的差别

当前编码器是字符2–4gram HashingVectorizer（256维），问题+证据、答案分别截前512个Unicode字符；不是512 token，也不是论文的MiniLM前128 token编码。使用此代理避免在开发接口验证时下载或加载新大模型。后续需核验MiniLM权重版本/哈希，替换编码器并重新拟合PCA和预测器；不得直接加载旧代理权重当正式模型。

PCA只拟合训练样本，最多32维并按训练秩下调。本轮问题PCA12维、答案19维。HGB使用50轮、最大深度3、最小叶样本5、关闭内部随机提前停止；这是小样本开发参数，与论文200轮等初值不同，正式参数仍需按预声明方案落实。

质量标签是RouterBench代理分数。有效性标签缺失，所以分类目标只是“benchmark质量>=0.8”，并非“有效且达标”，也不是当前最优保留答案在历史状态下的服务成功概率。分类器本轮按单个答案训练；正式状态级达标分类及有效性规则还未完成。单类别训练目标采用显式常数概率回退，不虚构两类数据。

threshold策略使用predicted_quality作为开发停止条件，不把proxy概率当风险保证。完整v5规划器、原论文强基线和收益模型尚未实现。

## 训练隔离与产物

dev_fit用于文本变换和模型训练，dev_eval只在保存模型后评价。加载器检查产物SHA256和scikit-learn版本，已拟合对象拒绝再次fit；新训练必须用新目录。joblib只应加载本机可信生成的产物，哈希不等于签名，也不能使不可信pickle安全。

本轮产物在 `reports/routerbench_step4_20261014_01/scorer/`：scorer.joblib、manifest.json、evaluation.json、predictions.jsonl。predictions中的reference_proxy_quality仅用于离线评价，不能把该文件传给控制器。

评价MAE=0.473246，训练均值基线MAE=0.473333，代理Brier=0.418652。小评价集仅5任务，且三模型回答相关；这些指标不能证明有效泛化、校准或方法优越性。当前改善几乎为零，不能因代码能运行就认为评分器已可用于正式决策。

接入后回放20任务×3环境×5策略=300轨迹；新增代理策略60轨迹、174次模拟调用。回放包含开发拟合任务，仅用于接口/资源检查，不当作独立性能结果。真实模型调用0，GPU训练0，付费0。

## 怎么运行验证

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing

# 新增测试，本轮11 passed
PYTHONPATH=src python -m pytest -q tests/test_v5_scorers.py

# 全量回归，本轮126 passed；旧HTTP测试需要本机端口
PYTHONPATH=src python -m pytest -q

# 重新训练小型开发预测器，目录必须尚不存在
PYTHONPATH=src python -m selection.v5.train_proxy \
  --dataset data/routerbench_dev20_20261014 \
  --output reports/proxy_scorer_mycheck

# 使用本轮已训练产物回放，输出目录必须尚不存在
PYTHONPATH=src python -m selection.simulation_replay \
  --config configs/routerbench_simulation.json \
  --scorer reports/routerbench_step4_20261014_01/scorer \
  --output reports/proxy_scorer_replay_mycheck
```

训练输出应显示fit_tasks=15、fit_pairs=45、eval_tasks=5、eval_pairs=15；回放应显示policies=5、traces=300、model_calls_executed=0。重新训练结果不以模型准确率达到某值作为“修改完成”条件；首先检查数据隔离、存取一致性、预测范围和运行结果。

## 是否需要用户运行

目前不需要。代码修改、CPU开发训练、离线回放和自动测试已由助手运行；以上命令用于用户自查。后续需要人工参与的是领域题目/评分规则审核、实际评分，以及真实部署和资源范围确认，不是替助手重复执行常规测试。

进入正式评分训练前仍需扩充未用于开发的候选池并完成来源/近重复审计，落实论文编码器、目标模型和有效性标签。不能用目前20条训练出“正式可靠预测器”。下一模块可继续开发收益/联合转移接口，但任何正式结果都必须等待这些数据前提完成。
