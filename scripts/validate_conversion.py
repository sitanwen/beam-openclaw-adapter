#!/usr/bin/env python3
"""校验转换后的5-case/100-QA数据是否完整。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from convert_beam_to_locomo import QUESTION_TYPE_TO_CATEGORY


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 BEAM 转换结果")
    parser.add_argument("input")
    parser.add_argument("--expected-cases", type=int, default=5)
    parser.add_argument("--expected-questions-per-case", type=int, default=20)
    args = parser.parse_args()

    with Path(args.input).open(encoding="utf-8") as file:
        samples = json.load(file)

    assert len(samples) == args.expected_cases, (
        f"case数量错误：期望{args.expected_cases}，实际{len(samples)}"
    )

    counts: Counter[str] = Counter()
    for sample in samples:
        assert len(sample["qa"]) == args.expected_questions_per_case, (
            f"{sample['sample_id']} QA数量不是{args.expected_questions_per_case}"
        )
        assert any(key.startswith("session_") for key in sample["conversation"])
        for qa in sample["qa"]:
            assert qa["question"], f"{sample['sample_id']} 存在空问题"
            assert qa["question_type"] in QUESTION_TYPE_TO_CATEGORY, (
                f"未知题型：{qa['question_type']}"
            )
            counts[qa["question_type"]] += 1

    expected_total = args.expected_cases * args.expected_questions_per_case
    assert sum(counts.values()) == expected_total
    assert set(counts) == set(QUESTION_TYPE_TO_CATEGORY), (
        f"题型覆盖不完整：{sorted(counts)}"
    )

    print(f"校验通过：{len(samples)} cases，{expected_total} QA")
    for question_type, count in sorted(counts.items()):
        print(f"  {question_type}: {count}")


if __name__ == "__main__":
    main()

