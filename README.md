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
│  └─ merge_openclaw_results.py      # 合并openclaw-eval结果与BEAM rubric
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

## 从头复现

### 1. 下载官方数据

```bash
uv run python scripts/download_beam.py
```

脚本会保存完整 `100K` split，并根据 `configs/sample_cases.json` 提取固定5个 case。
Hugging Face 对该 split 的名称是 `100K`；BEAM 论文和一些文档也会称其为128K档。

### 2. 转换为 LoCoMo-like JSON

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

### 3. 校验转换结果

```bash
uv run python scripts/validate_conversion.py \
  data/converted/beam_100K_5cases_locomo.json
```

期望结果：

```text
校验通过：5 cases，100 QA
每种 question_type：10题
```

### 4. 生成 openclaw-eval 输入

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

### 5. 运行 openclaw-eval

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
