# BEAM 3-case 冒烟测试

本配置从官方 100K split 固定选择原始 case 索引 0、8、16，覆盖 Coding、Writing Assistant & Learning、Lifestyle。正式集为 3 cases / 60 QA，每种 BEAM question_type 6 题。

## 第一步：只跑3道题验证全链路

冒烟文件每个 case 只保留1题，分别覆盖 information_extraction、knowledge_update、temporal_reasoning：

```powershell
uv sync --extra dev
uv run python scripts/prepare_openclaw_eval.py data/converted/beam_100K_3cases_smoke.json --out generated-smoke
.\generated-smokeun_commands.ps1
```

运行前复用已有 LoCoMo/LongMemEval 的 memory backend 配置和索引步骤。确认3个 workspace 均成功索引、3题均生成答案、无 session lock/reset 冲突、results.json 字段完整。

## 第二步：合并结果

每个 case 分别执行；以下以第一个为例：

```powershell
uv run python scripts/merge_openclaw_results.py generated-smoke/runs/beam-100K-0/results.json generated-smoke/judging/beam-100K-0.jsonl -o generated-smoke/answers/beam-100K-0.jsonl
```

## 第三步：单 Judge 冒烟评分

将3条答案交给一个固定 BEAM rubric judge。criterion 只能取 0、0.5、1；本步骤只验证评分格式和聚合脚本，不作为正式成绩。

```powershell
uv run python scripts/aggregate_beam_scores.py generated-smoke/scored/all.jsonl -o generated-smoke/summary.json
```

## 第四步：正式运行60题

前三步通过后运行正式集：

```powershell
uv run python scripts/prepare_openclaw_eval.py data/converted/beam_100K_3cases_locomo.json --out generated-3cases
.\generated-3casesun_commands.ps1
```

每道 QA 使用独立 session。收到回答后不要立即 reset；建议等待 session idle 或全部问题完成后统一清理，并对 session lock 做指数退避重试。
