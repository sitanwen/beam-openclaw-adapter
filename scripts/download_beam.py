#!/usr/bin/env python3
"""下载 BEAM 原始数据，并按固定索引保存5个 case。

默认下载 Hugging Face 上 Mohammadta/BEAM 的 100K split：
- 完整 split：20个 case
- 固定样本：5个 case，正常情况下共100道 probing questions

用法：
    uv run python scripts/download_beam.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from datasets import load_dataset


def write_json(path: Path, value: Any) -> None:
    """以便于人工查看的 UTF-8 JSON 格式写入文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 BEAM 数据集")
    parser.add_argument("--dataset", default="Mohammadta/BEAM")
    parser.add_argument("--split", default="100K")
    parser.add_argument(
        "--config",
        default="configs/sample_cases.json",
        help="固定抽样配置文件",
    )
    parser.add_argument(
        "--raw-output",
        default="data/raw/beam_100K_all.json",
        help="完整原始 split 输出路径",
    )
    parser.add_argument(
        "--sample-output",
        default="data/raw/beam_100K_5cases.json",
        help="5个原始 case 输出路径",
    )
    args = parser.parse_args()

    with Path(args.config).open(encoding="utf-8") as file:
        sample_config = json.load(file)

    print(f"正在下载 {args.dataset} / {args.split} ...")
    dataset = load_dataset(args.dataset, split=args.split)
    rows = [dict(row) for row in dataset]

    indices = sample_config["indices"]
    invalid = [index for index in indices if not 0 <= index < len(rows)]
    if invalid:
        raise ValueError(f"抽样索引越界：{invalid}，数据集共有 {len(rows)} 个 case")

    selected = []
    for index in indices:
        row = dict(rows[index])
        # 保存原始行索引，转换后仍可追溯到官方数据集。
        row["_beam_row_index"] = index
        row["_beam_split"] = args.split
        selected.append(row)

    write_json(Path(args.raw_output), rows)
    write_json(Path(args.sample_output), selected)

    print(f"完整数据：{len(rows)} cases -> {args.raw_output}")
    print(f"抽样数据：{len(selected)} cases -> {args.sample_output}")
    print(f"固定索引：{indices}")


if __name__ == "__main__":
    main()

