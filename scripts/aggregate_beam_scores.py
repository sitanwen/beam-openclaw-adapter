#!/usr/bin/env python3
"""聚合已经由 BEAM rubric judge 打分的 JSONL。

输入文件每行至少需要：
- question_type：BEAM 题型；
- rubric_score：0 到 1 的题目分数。

可选字段 latency_seconds、input_tokens、output_tokens 会一并聚合。
本脚本不调用 LLM，只负责可复现的统计计算。
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def mean_or_none(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize(rows: list[dict[str, Any]], pass_threshold: float = 0.5) -> dict[str, Any]:
    """计算 overall、分题型和运行成本指标。"""
    valid_rows = [row for row in rows if isinstance(row.get("rubric_score"), (int, float))]
    if not valid_rows:
        raise ValueError("没有找到包含数值 rubric_score 的记录")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in valid_rows:
        grouped[str(row["question_type"])].append(row)

    def group_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        scores = [float(item["rubric_score"]) for item in items]
        return {
            "count": len(items),
            "mean_rubric_score": statistics.fmean(scores),
            "binary_pass_rate": sum(score >= pass_threshold for score in scores) / len(scores),
        }

    latencies = [
        float(row["latency_seconds"])
        for row in valid_rows
        if isinstance(row.get("latency_seconds"), (int, float))
    ]
    input_tokens = [
        float(row["input_tokens"])
        for row in valid_rows
        if isinstance(row.get("input_tokens"), (int, float))
    ]
    output_tokens = [
        float(row["output_tokens"])
        for row in valid_rows
        if isinstance(row.get("output_tokens"), (int, float))
    ]

    return {
        "question_count": len(valid_rows),
        "pass_threshold": pass_threshold,
        **group_summary(valid_rows),
        "by_question_type": {
            question_type: group_summary(items)
            for question_type, items in sorted(grouped.items())
        },
        "performance": {
            "mean_latency_seconds": mean_or_none(latencies),
            "median_latency_seconds": statistics.median(latencies) if latencies else None,
            "total_input_tokens": sum(input_tokens) if input_tokens else None,
            "total_output_tokens": sum(output_tokens) if output_tokens else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="聚合 BEAM rubric 评分结果")
    parser.add_argument("input", help="包含 rubric_score 的 JSONL")
    parser.add_argument("-o", "--output", default="summary.json")
    parser.add_argument("--pass-threshold", type=float, default=0.5)
    args = parser.parse_args()

    with Path(args.input).open(encoding="utf-8") as file:
        rows = [json.loads(line) for line in file if line.strip()]

    summary = summarize(rows, args.pass_threshold)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

