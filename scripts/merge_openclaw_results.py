#!/usr/bin/env python3
"""合并 openclaw-eval 结果与 BEAM gold/rubric sidecar。

openclaw-eval 负责执行问题并记录答案、延迟、token、工具调用；
本脚本把这些运行结果与 BEAM 的参考答案、题型和 rubric 合并，
输出可交给现有 BEAM LLM Judge 的 answers.jsonl。

用法：
    uv run python scripts/merge_openclaw_results.py \
        generated/runs/beam-100K-0/results.json \
        generated/judging/beam-100K-0.jsonl \
        -o generated/answers/beam-100K-0.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="合并 openclaw-eval 与 BEAM 评分字段")
    parser.add_argument("results", help="openclaw-eval 生成的 results.json")
    parser.add_argument("judging", help="prepare_openclaw_eval.py 生成的 judging JSONL")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    with Path(args.results).open(encoding="utf-8") as file:
        result_bundle = json.load(file)

    judging_rows = read_jsonl(Path(args.judging))
    judging_by_id = {row["scenario_id"]: row for row in judging_rows}

    merged_rows = []
    missing = []
    for run in result_bundle.get("runs", []):
        scenario_id = run.get("scenarioId")
        judging = judging_by_id.get(scenario_id)
        if judging is None:
            missing.append(scenario_id)
            continue

        merged_rows.append(
            {
                **judging,
                "setup_id": run.get("setupId"),
                "response": run.get("answer", ""),
                "status": run.get("status"),
                "error": run.get("error"),
                "latency_seconds": run.get("latencySeconds"),
                "prompt_tokens": run.get("promptTokens"),
                "input_tokens": run.get("inputTokens"),
                "output_tokens": run.get("outputTokens"),
                "context_tokens": run.get("contextTokens"),
                "tool_calls": run.get("toolCalls", []),
                "tool_call_counts": run.get("toolCallCounts", {}),
                "read_files": run.get("readFiles", []),
            }
        )

    if missing:
        raise ValueError(f"以下 scenario_id 在 judging sidecar 中不存在：{missing}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for row in merged_rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"已合并 {len(merged_rows)} 条答案 -> {output_path}")


if __name__ == "__main__":
    main()

