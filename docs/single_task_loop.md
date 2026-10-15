# 单条真实开发任务闭环

状态：单次HTTP后端、采集/评分入口已实现，81项测试通过；仅模拟后端与本机模拟HTTP测试经过验证。真实模型生成未执行。对本机11434只做了GET元数据读取，不能视作生成接口或指定模型验收。

## 后端与重试链

旧路径为 APIQuery → 外层run_sequential_queries/_run_with_rate_limiting循环 → LangChain供应商封装 → SDK → HTTP。当前基础环境在api.py:4导入langchain_openai即失败，__init__.py的可选导入捕获异常后设APIQuery=None；其他LangChain供应商组件也缺失。vive环境虽有openai包，同样缺少这些LangChain组件。没有安装依赖或修改旧基线/API实现。

旧APIQuery默认max_retries=20；部分SDK透传同值，其他供应商分支未显式覆盖默认值；completion路径也不是统一关闭重试。因此单改参数不能证明所有分支无重试。新的采集路径不使用旧APIQuery、LangChain或任何SDK：

`single_task.collect → UnifiedExecutor → LiveModel → SingleHTTPTransport → 独立Python标准库worker → HTTPConnection.request（一次POST）`

- SQLite以(task_id, model_name)唯一约束在发送前占用尝试，成功、失败、超时、崩溃后PENDING均不能自动重发。同一真实任务不应通过换输出目录、删账本或换ID绕过限制。
- 无客户端重试、无HTTP重定向跟随、不读取HTTP_PROXY等代理环境变量。429/500/断连均一次结束。JSON解析和输出校验不重新请求。
- HTTP超时同时由socket和父进程监控；父进程超时会kill并回收本地worker。远端可能继续生成/计费，remote_cancel_confirmed=false，不能声称远程硬取消或硬预算。
- 服务端、反向代理、网关是否重试尚需部署方确认。当前只验证客户端代码链，不能证明未提供配置的远端只生成一次。
- 同一原始问题/证据被编码为user消息中的JSON对象；不包含历史回答、参考答案或质量标签。max_tokens、temperature、seed按配置固定；不支持的参数导致一次失败，不自动换参数重试。

## 时间与费用口径

真实后端必须通过执行器wall_clock模式运行。总时间为execute接收请求至终止的单调时钟差，包含控制、序列化、模型调用、解析/校验、账本持久化等；不再把组件时长加到墙钟上。模型latency和controller_time是分项诊断。配置/人工填写/模型预热在请求前完成；磁盘结果报表写出不是用户答案服务时间。离线回放原语义保留。

目前真实适配仅实现provider_token_fee_only：按提供的币种、输入/输出每百万token费率和用量推导费用，标derived，不称实际付款。paid_fee仍为null，需账单/收据核对。它不是论文费用—能耗—传输归一化成本。控制计算记录时间，不暗称已计量GPU或控制货币成本。

usage_is_complete表示部署方确认该接口的用量覆盖全部适用计费项；否则总费用保持null。仅部分用量已知时保留known_cost下界。错误响应中的已知用量也保留；超时/断连没有账单时不能填0。数据源是synthetic时费用/时延标为模拟，仅验证代码流程。

采集总费用超过或达到授权范围、或任一次费用未知时，后续模型保持UNATTEMPTED，不冒充调用失败。这是调用后的停止守卫，无法保证远端单次请求绝不超支；必须在实际授权范围中确认最大输出与费用风险。失败调用仍占一次机会。PENDING账本不能当零费用，可人工从账本及服务端收据恢复，不自动续跑。

## 操作步骤

1. **准备真实材料。** 复制templates/development/single_task.draft.json到新的私有工作文件。填写task_id、真实source_group_id、问题、固定证据、来源与日期、任务类型、近重复关系。仅使用开发样本，不挪用正式校准/测试。把模型应遵守的输出要求和硬约束写入问题；参考答案、评分锚点留在评估侧。
2. **固定任务服务要求。** 填deadline_s、budget、币种。当前只做费用口径的开发接口诊断，不能套用论文归一化成本结论。质量0.8/风险0.1是研究起点，不是已证实业务要求。
3. **填写部署。** 复制configs/single_task_live.template.json；每角色填真实model_id、版本、完整chat/completions URL、api_key_env变量名、超时、生成参数、在线格式校验规则和可靠费率。密钥只在运行环境设置，不写JSON、命令参数或评分卡。只有权重路径而无服务的模型尚需另行部署/接入；此适配器不加载权重、不下载、不启动服务。
4. **核验授权与上游重试。** 填三次最大尝试、总费用范围和说明，确认供应商/代理无隐含模型级重试。当前真实模板approved=false；本轮没有给出或使用真实付费授权。默认账本路径独立于输出目录，可阻止同task重复采集。
5. **离线校验。** 运行下面validate命令，只查本地文件、URL格式和凭据变量是否存在，不发HTTP请求。null草稿会拒绝。确认三个角色确为获准模型；本机其他模型不能擅自映射成论文1.5B/7B。
6. **获得明确执行范围后采集一次。** collect --live分别对船、岸、云运行三个固定单模型请求，共用UnifiedExecutor，最多三次。每个模型接收同一原始输入；这是独立模型采集，不是一条级联路线。若费用守卫触发，结果会明确标不完整。
7. **保存与核对。** 查看calls.jsonl的状态、原始回答、版本、原因、时间、用量、费用来源、已知费用下界、retry_count与尝试ID；traces.jsonl保留服务端点之外的控制轨迹和完整请求时间。pending/失败费用应核对服务端日志/账单，不发第二次生成请求。独立模型耗时不得直接当作真实序贯网络耗时。
8. **人工双人评分。** 仅把annotation_cards.jsonl给两位标注者，不给private_annotation_map.json、调用日志或成本。填写证据位置、两位不同reviewer、三个0—4整数分、valid和veto。Q=(0.5s1+0.3s2+0.2s3)/4，veto=true时Q=0；valid独立。评分/有效性/否决存在分歧时必须填写adjudication（同一评分对象格式）。任务锚点和领域复核资格由真实材料确定，本轮没有人工完成真实评分。
9. **只在评估侧合并标签。** evaluate读取评分卡和私有映射，输出labels.jsonl、evaluated_traces.jsonl、summary.json；复用统一失败并集，不重跑模型、不改变原答案、不改原轨迹。未填评分会拒绝。未调用角色另记未评价，不把它们伪装成成功结果。
10. **后续回放。** 导出的tasks/calls/labels使用既有加载器格式。没有三模型完整调用记录时不能完整回放；补账单不是重试生成。当前一条样本不用于训练预测器或校准，不形成风险保证。后续10—20条按真实来源组拆开发拟合/评价。

## 命令

先运行不需部署的模拟路径（不要把模拟材料或评分当真实数据）：

```bash
cd /home/guoqiuyuan/LLMresearch/cascade-routing
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m selection.single_task validate --mock \
  --task examples/single_task/mock_task.json --deployment configs/single_task_mock.json
PYTHONPATH=src python -m selection.single_task collect --mock \
  --task examples/single_task/mock_task.json --deployment configs/single_task_mock.json \
  --output reports/my_single_mock
```

重复同一task_id会被账本拒绝，即使换输出目录。新的纯模拟诊断可使用新的合成task_id和独立账本；真实任务不可用这个方式绕过一次尝试限制。

真实文件填好后，下列validate仍是只读本地校验：

```bash
PYTHONPATH=src python -m selection.single_task validate --live \
  --task /path/to/filled_task.json --deployment /path/to/filled_deployment.json
```

仅在实际部署与调用范围获准后，将validate改为collect并加`--output <新目录>`才会发送真实请求。本轮未执行此操作。

评分操作不发送任何模型请求：

```bash
PYTHONPATH=src python -m selection.single_task evaluate \
  --collection reports/my_single_collection \
  --cards /path/to/human_completed_cards.jsonl \
  --output reports/my_single_evaluation
```

## 输出边界

- tasks.jsonl、calls.jsonl、labels.pending.jsonl：原有loader可加载；标签未完成不报零失败。
- annotation_cards.jsonl：待真实双人标注；private_annotation_map.json仅评估人员使用。
- traces.jsonl：执行时不知道真实质量；模型调用/控制开销/终止守卫可复核。
- manifest.json：输入与代码hash、模式、尝试/未尝试模型、费用口径、缺项。模拟成功只证明程序流程。
- SQLite账本：含原始输出与敏感任务材料，按项目数据权限保存；不包含密钥。COMPLETE记录可人工导出；本轮未实现自动崩溃恢复/补账单工具。

## 已知部署信息

2026-09-24只读GET本机http://127.0.0.1:11434/api/tags和/v1/models均返回200，列出9模型（详见最新报告）。包含qwen2.5:3b及qwen3:4b/8b/14b等，不含该服务清单中的论文Qwen2.5 1.5B/7B。没有对/v1/chat/completions发送生成请求，所以模型推理能力、API参数兼容性和服务端无重试仍未验证。不能据此断言其他目录、服务或机器没有目标模型。
