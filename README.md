# BEAM → OpenClaw Eval 适配项目

这个项目把 [BEAM 长期记忆评测数据集](https://huggingface.co/datasets/Mohammadta/BEAM)
的 `100K` split 转换成两类可复用产物：

1. 与现有 LoCoMo/LongMemEval 管线兼容的 **LoCoMo-like JSON**；
2. 按 BEAM case 隔离的 **OpenClaw workspace + openclaw-eval suite**。

项目已经包含下载好的官方 `100K` 原始数据、固定抽样的5个 case、转换后的100道题，
以及下载、转换、校验和生成 openclaw-eval 输入的完整脚本。

## 当前数据规模

| 文件 | 内容 | 大小约 |
|---|---|---:|
| `data/raw/beam_100K_all.json` | 官方100K split，20个 case | 15.3 MB |
| `data/raw/beam_100K_5cases.json` | 固定抽样5个原始 case | 3.4 MB |
| `data/converted/beam_100K_5cases_locomo.json` | LoCoMo-like 转换结果 | 2.9 MB |

固定抽样索引为 `0、4、8、12、16`，覆盖以下5个领域：

- Coding
- Math
- Writing Assistant & Learning
- Asking Recommendation
- Lifestyle

每个 case 有20道 probing questions，共100道题。BEAM 的10种能力各有10道题：

- abstention
- contradiction resolution
- event ordering
- information extraction
- instruction following
- knowledge update
- multi-session reasoning
- preference following
- summarization
- temporal reasoning

## 为什么一个 case 只生成一个 sample

LongMemEval 通常是一道题携带一套 haystack，因此可以“一题一个 sample”。BEAM 不同：
一个约100K/128K token 的 conversation 关联20道题。

本项目采用：

```text
1个 BEAM case
  ├─ 1份 conversation
  ├─ 多个按时间顺序排列的 session
  └─ 20道 QA
```

这样 OpenClaw 对每个 case 只需写入和建立一次记忆，20道题复用同一个只读记忆库，
不会将同一份长对话重复索引20次。

## 项目结构

```text
beam-openclaw-adapter/
├─ configs/
│  └─ sample_cases.json              # 固定5-case抽样配置
├─ data/
│  ├─ raw/
│  │  ├─ beam_100K_all.json          # 下载后的完整100K split
│  │  └─ beam_100K_5cases.json       # 5个原始case
│  ├─ converted/
│  │  └─ beam_100K_5cases_locomo.json
│  ├─ CHECKSUMS.sha256
│  └─ DATA_LICENSE.md
├─ scripts/
│  ├─ download_beam.py               # 下载与固定抽样
│  ├─ convert_beam_to_locomo.py      # 转换为LoCoMo-like格式
│  ├─ validate_conversion.py         # 校验5 cases / 100 QA / 10类能力
│  ├─ prepare_openclaw_eval.py       # 生成workspace、suite和rubric sidecar
│  ├─ merge_openclaw_results.py      # 合并openclaw-eval结果与BEAM rubric
│  └─ aggregate_beam_scores.py       # 聚合rubric得分与运行成本
├─ examples/
│  └─ scored_answers.example.jsonl   # 已评分结果格式示例
├─ tests/
│  └─ test_converter.py
├─ pyproject.toml
└─ uv.lock
```

## 环境准备

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra dev
```

如果需要实际运行 agent，还需安装并配置：

- OpenClaw
- openclaw-eval
- 你需要对比的 OpenClaw memory backend

## 使用方法

### 先选择你的使用方式

本项目支持两条路线：

| 路线 | 适用情况 | 需要做什么 |
|---|---|---|
| A：复用已有 runner | 你已经能用同一套程序运行 LoCoMo 和 LongMemEval | 将输入文件换成转换后的 JSON，并为 BEAM 分流评分 |
| B：原生 openclaw-eval | 你希望把每个 BEAM case 生成独立 workspace 和 scenario suite | 执行 `prepare_openclaw_eval.py`，再逐 case 运行 |

### 路线 A：复用现有 LoCoMo/LongMemEval runner

可以直接使用：

```text
data/converted/beam_100K_5cases_locomo.json
```

假设你原来的命令类似：

```bash
python your_existing_runner.py --input locomo10_small.json
```

现在改成：

```bash
python your_existing_runner.py \
  --input data/converted/beam_100K_5cases_locomo.json
```

这里的 `your_existing_runner.py` 是你当前已经运行 LoCoMo/LongMemEval 的程序名，
不是本项目提供的新命令。

runner 中需要保持下面的执行层级：

```python
for sample in dataset:
    # 一个BEAM case只写入、建索引一次
    prepare_memory(sample["conversation"])

    # 同一个case的20道题复用该记忆库
    for qa in sample["qa"]:
        answer = ask_openclaw(qa["question"])
        save_result(
            sample_id=sample["sample_id"],
            question_type=qa["question_type"],
            answer=answer,
            gold_answer=qa["answer"],
            rubric=qa["rubric"],
        )
```

评分器必须根据数据集分流：

```python
if sample["metadata"]["dataset"] == "BEAM":
    score = beam_rubric_judge(
        question=qa["question"],
        reference_answer=qa["answer"],
        rubric=qa["rubric"],
        response=answer,
    )
else:
    score = existing_locomo_judge(...)
```

如果不做这个分流，OpenClaw 仍然可以回答100道题，但 LoCoMo 的 F1、exact match 或
二元 judge 无法表达 BEAM rubric 中的多项要求，最终数字不能称为 BEAM 得分。

### 路线 B：生成原生 openclaw-eval workspace 和 suite

下面的步骤会从官方数据重新生成完整产物。如果仓库中的转换文件已经满足需要，
可以直接从第4步开始。

#### 1. 下载官方数据

```bash
uv run python scripts/download_beam.py
```

脚本会保存完整 `100K` split，并根据 `configs/sample_cases.json` 提取固定5个 case。
Hugging Face 对该 split 的名称是 `100K`；BEAM 论文和一些文档也会称其为128K档。

#### 2. 转换为 LoCoMo-like JSON

```bash
uv run python scripts/convert_beam_to_locomo.py \
  data/raw/beam_100K_5cases.json \
  -o data/converted/beam_100K_5cases_locomo.json
```

转换后每个 sample 的主要结构为：

```json
{
  "sample_id": "beam-100K-0",
  "metadata": {
    "dataset": "BEAM",
    "chat_size": "100K",
    "case_index": 0
  },
  "conversation": {
    "speaker_a": "User",
    "speaker_b": "Assistant",
    "session_1": [],
    "session_1_date_time": ""
  },
  "qa": [
    {
      "question": "...",
      "answer": "...",
      "evidence": [],
      "category": 1,
      "question_type": "information_extraction",
      "question_index": 0,
      "rubric": ["..."]
    }
  ]
}
```

数字 `category` 只是为了兼容已有 LoCoMo-like runner。统计和报表应使用字符串
`question_type`，不要将 BEAM 的数字类别解释成 LoCoMo 原有类别。

#### 3. 校验转换结果

```bash
uv run python scripts/validate_conversion.py \
  data/converted/beam_100K_5cases_locomo.json
```

期望结果：

```text
校验通过：5 cases，100 QA
每种 question_type：10题
```

#### 4. 生成 openclaw-eval 输入

```bash
uv run python scripts/prepare_openclaw_eval.py \
  data/converted/beam_100K_5cases_locomo.json
```

默认生成到 `generated/`：

```text
generated/
├─ workspaces/<sample-id>/memory/beam/*.md
├─ suites/<sample-id>.jsonl
├─ judging/<sample-id>.jsonl
├─ manifest.json
└─ run_commands.ps1
```

每个 case 都是独立 workspace，避免不同 conversation 之间发生记忆污染。

生成的一条 suite 示例：

```json
{
  "id": "beam-100K-0-q00",
  "prompt": "How did the user feedback influence the UI/UX improvements?",
  "tags": ["beam", "abstention", "100K"],
  "source": "beam-100K-0",
  "checks": [{"type": "manual"}]
}
```

对应的 rubric 不塞进 prompt，而是单独保存在 judging sidecar 中，避免把参考答案泄漏给
被测 OpenClaw：

```json
{
  "scenario_id": "beam-100K-0-q00",
  "question_type": "abstention",
  "question": "How did the user feedback influence the UI/UX improvements?",
  "gold_answer": "There is not enough information in the conversation.",
  "rubric": ["The response states that the information is unavailable"]
}
```

#### 5. 运行 openclaw-eval

脚本会生成 `generated/run_commands.ps1`，其中每个 case 对应一个命令，例如：

```powershell
openclaw-eval run `
  --setup "beam-100K-0:C:\path\to\generated\workspaces\beam-100K-0" `
  --suite "C:\path\to\generated\suites\beam-100K-0.jsonl" `
  --out "C:\path\to\generated\runs\beam-100K-0"
```

`openclaw-eval` 会对每道问题创建新的 agent session，避免上一道问题的回答泄漏到下一题。
但是20道题仍读取同一个 case workspace 中的静态 memory 文件。

不同 OpenClaw 版本和 memory plugin 的显式索引方式可能不同。本项目不硬编码某个
`openclaw memory index` 命令；请在运行 suite 前复用你现有 LoCoMo/LongMemEval
适配中的索引或预构建步骤。

## BEAM rubric 评分

原版 openclaw-eval 的 `contains`、`not_contains` 和 `manual` 检查不足以得到官方 BEAM
分数。因此 suite 中使用 `manual` 占位，真正的参考答案与 rubric 保存在：

```text
generated/judging/<sample-id>.jsonl
```

运行完成后，将 OpenClaw 答案与 BEAM rubric 合并：

```bash
uv run python scripts/merge_openclaw_results.py \
  generated/runs/beam-100K-0/results.json \
  generated/judging/beam-100K-0.jsonl \
  -o generated/answers/beam-100K-0.jsonl
```

合并后的每条记录包含：

- question、gold answer、rubric
- OpenClaw response
- question type
- latency
- prompt/input/output/context tokens
- tool calls
- read files

随后可交给 BEAM 官方 rubric judge 或你现有的 LLM Judge。BEAM 的主要指标应至少包括：

1. overall rubric score；
2. 10种 question type 的分项均分；
3. binary pass rate；
4. latency、token、tool calls、read files；
5. completion/error/timeout rate。

为了结果可比，报告中必须同时记录 answer model、judge model、prompt、数据索引、
OpenClaw 版本和 memory backend 配置。

### rubric judge 到底怎样评分

假设一道知识更新题包含两个 rubric criterion：

```json
{
  "question": "What database does the user currently plan to use?",
  "gold_answer": "PostgreSQL",
  "rubric": [
    "The response says the current plan is PostgreSQL",
    "The response does not present the old SQLite plan as current"
  ],
  "response": "The latest plan is PostgreSQL; SQLite was the earlier option."
}
```

judge 分别判断两个 criterion，每项只能是 `0、0.5、1`：

```json
{
  "criterion_scores": [1.0, 1.0],
  "rubric_score": 1.0,
  "judge_reason": "使用了最新信息，并正确区分旧方案。"
}
```

题目分数计算：

```text
rubric_score = 所有 criterion score 的平均值
             = (1.0 + 1.0) / 2
             = 1.0
```

再例如 `[1、0.5、0]` 的题目：

```text
rubric_score = (1 + 0.5 + 0) / 3 = 0.5
```

整体主分数是全部题目 `rubric_score` 的平均值；每种能力分数是该
`question_type` 下题目得分的平均值。二元通过率是额外派生指标，项目示例默认将
`rubric_score >= 0.5` 记为通过；发表或对比结果时必须声明该阈值。

已评分 JSONL 的完整格式参见：

```text
examples/scored_answers.example.jsonl
```

聚合命令：

```bash
uv run python scripts/aggregate_beam_scores.py \
  examples/scored_answers.example.jsonl \
  -o generated/example_summary.json
```

示例输出：

```json
{
  "question_count": 3,
  "mean_rubric_score": 0.6666666666666666,
  "binary_pass_rate": 0.6666666666666666,
  "by_question_type": {
    "information_extraction": {
      "count": 1,
      "mean_rubric_score": 1.0,
      "binary_pass_rate": 1.0
    },
    "knowledge_update": {
      "count": 1,
      "mean_rubric_score": 1.0,
      "binary_pass_rate": 1.0
    },
    "temporal_reasoning": {
      "count": 1,
      "mean_rubric_score": 0.0,
      "binary_pass_rate": 0.0
    }
  }
}
```

### 哪些部分已经完成，哪些需要你的运行环境

已经完成并提交的部分：

- 官方100K原始数据下载；
- 固定5-case抽样；
- 5 cases / 100 QA 的 LoCoMo-like 转换；
- 十类题型和 rubric 保留；
- OpenClaw workspace、suite、judging sidecar 生成；
- openclaw-eval results 与 rubric 合并；
- 已评分结果的聚合。

需要在你的 OpenClaw 环境中执行的部分：

- 使用你现有 memory backend 写入或建立索引；
- 调用 OpenClaw 回答100道问题；
- 使用你选定的 judge model 对 rubric 打分。

原因是 memory backend、answer model、judge model、API 地址和密钥都属于具体实验配置，
不能在公开仓库里替你硬编码。

## 测试

```bash
uv run pytest -q
```

当前测试覆盖：

- 题型名称标准化；
- BEAM batch/session 转换；
- probing questions、gold answer 和 rubric 保留。

数据文件的 SHA-256 校验值保存在 `data/CHECKSUMS.sha256`，用于确认下载和转换结果
没有发生意外变化。

## 数据与代码许可

- 本项目代码：MIT License。
- `data/` 内 BEAM 原始和派生数据：遵循原数据的 CC BY-SA 4.0。
- 详细说明见 `data/DATA_LICENSE.md`。

使用数据时请引用 BEAM 原论文：

> Beyond a Million Tokens: Benchmarking and Enhancing Long-Term Memory in LLMs.
