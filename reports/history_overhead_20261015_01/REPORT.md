# 老师问题对应的工程修改

新增在线摘要库的双重容量拒绝、动作/历史索引与向量化精确距离；新增10项容量与检索一致性测试和可重复微基准。原始问题/回答本来就不在在线库中，继续保留这一边界。没有删除训练数据、报告或防重发账本，没有模型调用。

实际命令（工作目录cascade-routing）：

| 命令 | 退出状态 | 结果 |
|---|---|---|
| PYTHONPATH=src python -m pytest -q tests/test_v5_library_capacity.py tests/test_v5_transitions.py --junitxml=reports/history_overhead_20261015_01/targeted.xml | 0 | 22 passed |
| PYTHONPATH=src python scripts/benchmark_transition_overhead.py --output reports/history_overhead_20261015_01/benchmark.json | 0 | 与全量测试并发运行 |
| PYTHONPATH=src python -m pytest -q --junitxml=reports/history_overhead_20261015_01/tests.xml | 1 | 172 passed, 7 errors；沙箱拒绝本机socket |
| PYTHONPATH=src python -m pytest -q --junitxml=reports/history_overhead_20261015_01/tests_with_loopback.xml | 0 | 允许本机假HTTP服务后179 passed，5.87s |
| PYTHONPATH=src python scripts/benchmark_transition_overhead.py --output reports/history_overhead_20261015_01/benchmark_isolated.json | 0 | 无并发测试重新测量 |

单独测量中100/1000/10000条库检索与抽样p50约1.01/1.66/10.17 ms，p95约1.74/1.69/103.74 ms。万条JSON约2.87 MB，索引数组0.40 MB，tracemalloc建库峰值15.41 MB，建库约2.63s。尾部抖动明显，不能只引用均值说明实时性。MB为十进制，默认容量MiB为二进制。

这些数据只证明合成开发条件下开销可测量，不证明真实领域节省；没有正式容量消融、完整控制器基准、硬RSS限制或日志TTL。讨论与完整净收益口径见docs/v5_history_overhead.md。未修改论文正文或预填实验结论。
