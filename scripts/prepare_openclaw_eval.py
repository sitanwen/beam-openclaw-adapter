#!/usr/bin/env python3
"""由 LoCoMo-like JSON 生成 openclaw-eval 工作区和 suite。

该脚本不修改用户现有 OpenClaw 配置，也不执行模型调用。它只生成：
- 每个 BEAM case 独立的 workspace；
- memory/beam/ 下按 session 切分的 Markdown 文件；
- 每个 case 对应的 openclaw-eval JSONL suite；
- 含 gold answer 与 rubric 的评分 sidecar；
- 可复制执行的命令清单。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def safe_name(value: str) -> str:
    """生成安全的目录名。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_session(date_time: str, messages: list[dict[str, Any]]) -> str:
    """将会话渲染成便于 OpenClaw memory 索引的 Markdown。"""
    lines = ["# BEAM 对话记忆", ""]
    if date_time:
        lines.extend([f"时间：{date_time}", ""])

    for message in messages:
        lines.append(
            f"## {message['speaker']} [{message['dia_id']}]\n\n{message['text']}\n"
        )
    return "\n".join(lines).rstrip() + "\n"


def prepare_sample(sample: dict[str, Any], output_root: Path) -> dict[str, Any]:
    sample_id = safe_name(sample["sample_id"])
    workspace = output_root / "workspaces" / sample_id
    memory_directory = workspace / "memory" / "beam"
    suite_path = output_root / "suites" / f"{sample_id}.jsonl"
    judging_path = output_root / "judging" / f"{sample_id}.jsonl"

    memory_directory.mkdir(parents=True, exist_ok=True)
    conversation = sample["conversation"]

    session_keys = sorted(
        (
            key
            for key in conversation
            if key.startswith("session_") and not key.endswith("_date_time")
        ),
        key=lambda key: int(key.split("_")[1]),
    )

    for session_key in session_keys:
        session_number = int(session_key.split("_")[1])
        date_time = conversation.get(f"{session_key}_date_time", "")
        content = render_session(date_time, conversation[session_key])
        session_path = memory_directory / f"session_{session_number:04d}.md"
        session_path.write_text(content, encoding="utf-8", newline="\n")

    scenarios = []
    judging_rows = []
    for qa_index, qa in enumerate(sample["qa"]):
        scenario_id = f"{sample_id}-q{qa_index:02d}"
        scenarios.append(
            {
                "id": scenario_id,
                "prompt": qa["question"],
                "tags": ["beam", qa["question_type"], sample["metadata"]["chat_size"]],
                "source": sample_id,
                "notes": "使用 BEAM rubric 单独评分；openclaw-eval 内置检查仅标记为 manual。",
                "checks": [{"type": "manual"}],
            }
        )
        judging_rows.append(
            {
                "scenario_id": scenario_id,
                "sample_id": sample_id,
                "question_type": qa["question_type"],
                "question_index": qa["question_index"],
                "question": qa["question"],
                "gold_answer": qa["answer"],
                "rubric": qa["rubric"],
            }
        )

    write_jsonl(suite_path, scenarios)
    write_jsonl(judging_path, judging_rows)
    return {
        "sample_id": sample_id,
        "workspace": str(workspace.resolve()),
        "suite": str(suite_path.resolve()),
        "judging": str(judging_path.resolve()),
        "question_count": len(scenarios),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="准备 BEAM openclaw-eval 输入")
    parser.add_argument("input", help="转换后的 LoCoMo-like JSON")
    parser.add_argument("--out", default="generated", help="生成目录")
    args = parser.parse_args()

    with Path(args.input).open(encoding="utf-8") as file:
        samples = json.load(file)

    output_root = Path(args.out)
    manifest = [prepare_sample(sample, output_root) for sample in samples]

    manifest_path = output_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    commands_path = output_root / "run_commands.ps1"
    command_lines = [
        "# 运行前请确认 openclaw 与 openclaw-eval 已安装。",
        "# 每个case使用独立workspace，避免跨case记忆污染。",
        "# 如果你的OpenClaw记忆后端需要显式建索引，请先复用现有LoCoMo/LongMemEval的索引步骤。",
        "",
    ]
    for item in manifest:
        run_directory = str((output_root / "runs" / item["sample_id"]).resolve())
        command_lines.extend(
            [
                (
                    f'openclaw-eval run --setup "{item["sample_id"]}:{item["workspace"]}" '
                    f'--suite "{item["suite"]}" --out "{run_directory}"'
                ),
                "",
            ]
        )
    commands_path.write_text("\n".join(command_lines), encoding="utf-8")

    total_questions = sum(item["question_count"] for item in manifest)
    print(f"已生成 {len(manifest)} 个工作区、{total_questions} 道题")
    print(f"清单：{manifest_path}")
    print(f"命令：{commands_path}")


if __name__ == "__main__":
    main()
