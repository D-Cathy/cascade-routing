# 第5步：收益模型与联合转移库（开发核心）

持续进度入口：项目根目录PROGRESS.md及PROGRESS.html。HANDOFF.md保留逐轮日志，reports/保留不可覆盖的运行证据。

本轮新增history.py、gain.py、transition_library.py、demo_transition.py。实现的是收益/检索/联合抽样核心接口，不是完整论文动态模型或规划器；尚未接入线上策略，也没有在正式D_G训练。

## 本轮已完成

1. 用同一个冻结预测Selector分别选择调用前后保留的答案。收益标签为两者参考质量之差，无答案按0；负收益不截断，缺失参考标签报错。不能改成真实最高质量之差。
2. 每动作一个HGB收益回归器；按来源组平衡样本权重。已训练且允许的动作给出收益预测，其他槽位为0并返回独立动作掩码。模型已拟合后拒绝原地重训。
3. 在线库导出剔除gain_target等参考标签，严格白名单校验，包括嵌套outcome。保留的是完整联合结果：状态、预测质量摘要、时延、成本、调用后带宽。
4. 按动作和有序尝试历史（模型及结果类型）精确过滤，标准化状态/收益特征计算距离，每来源组只留最近一条，最多20组；默认少于5组或距离超限标为不支持。支持不足不生成伪造场景。
5. 按权重抽取4条完整供体记录，重复供体合并，场景权重为次数/4；保留质量摘要/时间/费用的联合关系，不独立打乱各分量。固定请求ID、查询、种子可复现抽样。返回donor_record_id只用于审计，未来规划器不能把它加入可观察状态区分场景。

## 演示与边界

本轮使用12个明确合成的来源组：8组拟合、4组查询。评分器为固定数字解析夹具，标签与资源均为合成；未读取或重新利用RouterBench dev_eval。四个训练标签为负，四个查询均获得支持。这仅验证软件，没有实证意义，不增加独立校准样本。

九维状态是三档已返回预测分、三档尝试标志、剩余时间、剩余预算和当前带宽，尚未加入论文任务嵌入或完整状态表示。后环境必须由调用者显式提供；演示仅使用不变化带宽。未知资源明确拒绝进入库，不当作零。

当前Gaussian核是工程选项，尚未核实为论文公式3.12；max_distance=10为演示常数，未使用D_V的0.99分位数。数值序列化使用固定JSON键序和PCG64，尚未实现论文浮点hex规范状态键。源组标准差缩放来自拟合记录；正式权重、尺度及任务等权定义还需按正式协议落实。

未完成：正式D_G训练、D_V支持阈值/残差缓冲、将供体摘要映射回当前任务并重新评分、代理状态去重及后续动作一致性、规划器接入。不能把本模块的预测摘要直接当作当前问题的真实答案或真实质量。

## 产物

`reports/routerbench_step5_20261014_01/demo_final/`为最终演示：

- private/training_transitions.jsonl：含收益参考标签，训练侧专用。
- library.jsonl：剔除参考标签的联合转移库。
- gain_models.joblib：本机可信生成的合成演示收益模型，不加载未知来源pickle。
- retrieval_config.json：尺度、支持参数、来源标识。
- queries.jsonl：邻居、联合场景和抽样权重。
- manifest.json：数据性质、组数、局限与文件哈希。

同报告demo/是添加配置导出前的首次演示，保留追踪；使用demo_final作为最终结果。

## 运行验证

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing

# 新增12项测试
PYTHONPATH=src python -m pytest -q tests/test_v5_transitions.py

# 全量回归，本轮138 passed；既有HTTP测试需要本机端口
PYTHONPATH=src python -m pytest -q

# 12组合成演示，使用尚不存在的目录
PYTHONPATH=src python -m selection.v5.demo_transition \
  --output reports/transition_demo_mycheck
```

预期source_groups=12、fit_groups=8、query_groups=4、negative_targets=4、supported_queries=4、model_calls=0。测试覆盖负收益、标签隔离、组支持、状态过滤、距离拒绝、联合相关性、确定性抽样、动作掩码、严格升级和未知资源。

下一步为第6步规划器工程接口；在论文完整实现之前，还必须补齐本页所列动态模型、正式数据和评分器前提。用户暂不需要运行常规测试，助手已完成；真实数据审核/评分仍需人工参与。
