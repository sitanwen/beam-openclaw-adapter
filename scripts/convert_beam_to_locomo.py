#!/usr/bin/env python3
"""将 BEAM 转换为现有 LoCoMo-like 中间格式。

设计原则：
1. 一个 BEAM conversation/case 对应一个 sample；
2. 每个 sample 保留全部20道 probing questions；
3. conversation 只写入并索引一次，避免128K历史被重复处理20次；
4. 保留 BEAM 的 question_type、rubric 和原始问题序号，供后续官方评分。

用法：
    uv run python scripts/convert_beam_to_locomo.py \
        data/raw/beam_100K_5cases.json \
        -o data/converted/beam_100K_5cases_locomo.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable


# 数字 category 仅用于兼容已有 LoCoMo-like runner。
# 报表展示必须优先使用 question_type，不能套用 LoCoMo 原有 category 名称。
QUESTION_TYPE_TO_CATEGORY = {
    "information_extraction": 1,
    "multi_session_reasoning": 2,
    "knowledge_update": 3,
    "temporal_reasoning": 4,
    "abstention": 5,
    "contradiction_resolution": 6,
    "event_ordering": 7,
    "instruction_following": 8,
    "preference_following": 9,
    "summarization": 10,
}

# 兼容数据集中可能出现的不同命名写法。
QUESTION_TYPE_ALIASES = {
    "multi_hop_reasoning": "multi_session_reasoning",
    "multi_session": "multi_session_reasoning",
    "knowledge_updates": "knowledge_update",
    "preference_following": "preference_following",
    "preferences_following": "preference_following",
}


def normalize_question_type(value: str) -> str:
    """将题型名称统一成 snake_case。"""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return QUESTION_TYPE_ALIASES.get(normalized, normalized)


def parse_probing_questions(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """解析 BEAM 的 probing_questions。

    Hugging Face 当前版本将该字段保存为 Python 字面量字符串，
    因此使用 ast.literal_eval，而不是不安全的 eval。
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = ast.literal_eval(raw)
        if not isinstance(parsed, dict):
            raise TypeError("probing_questions 解析后不是字典")
        return parsed
    raise TypeError(f"不支持的 probing_questions 类型：{type(raw)!r}")


def get_gold_answer(question: dict[str, Any]) -> Any:
    """兼容不同题型使用的参考答案字段。"""
    for key in (
        "ideal_response",
        "ideal_answer",
        "answer",
        "ideal_summary",
        "expected_compliance",
    ):
        value = question.get(key)
        if value not in (None, "", []):
            return value
    return ""


def iter_sessions(chat: Any) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    """将 BEAM chat 统一迭代为 (时间, turns) 会话。

    官方数据可能是：
    - 多个 batch，每个 batch 含 turns；
    - 已展开的 turn list。
    本函数同时兼容两种结构。
    """
    if not isinstance(chat, list):
        raise TypeError(f"chat 应为列表，实际为 {type(chat)!r}")

    # 已展开的 turn list：整个列表作为一个会话。
    if chat and all(isinstance(item, dict) and "role" in item for item in chat):
        date_time = str(chat[0].get("time_anchor", ""))
        yield date_time, chat
        return

    for batch in chat:
        if isinstance(batch, dict):
            turns = batch.get("turns", [])
            date_time = str(batch.get("time_anchor") or "")
        elif isinstance(batch, list):
            turns = batch
            date_time = ""
        else:
            raise TypeError(f"不支持的 chat batch 类型：{type(batch)!r}")

        # 个别版本的 turns 可能多嵌套一层。
        if len(turns) == 1 and isinstance(turns[0], list):
            turns = turns[0]
        yield date_time, turns


def convert_turn(session_index: int, turn_index: int, turn: dict[str, Any]) -> dict[str, str]:
    """将单条 BEAM turn 转为 LoCoMo 消息。"""
    role = str(turn.get("role", "")).lower()
    if role == "user":
        speaker = "User"
    elif role == "assistant":
        speaker = "Assistant"
    else:
        speaker = role.title() or "Unknown"

    original_id = turn.get("id")
    suffix = original_id if original_id is not None else turn_index
    return {
        "speaker": speaker,
        "dia_id": f"D{session_index}:{suffix}",
        "text": str(turn.get("content", "")),
    }


def convert_conversation(chat: Any) -> dict[str, Any]:
    """将完整 BEAM chat 转换成 session_1、session_2 等字段。"""
    conversation: dict[str, Any] = {
        "speaker_a": "User",
        "speaker_b": "Assistant",
    }

    for session_index, (date_time, turns) in enumerate(iter_sessions(chat), start=1):
        converted_turns = [
            convert_turn(session_index, turn_index, turn)
            for turn_index, turn in enumerate(turns, start=1)
        ]
        conversation[f"session_{session_index}"] = converted_turns
        conversation[f"session_{session_index}_date_time"] = date_time

    return conversation


def convert_questions(raw_questions: Any) -> list[dict[str, Any]]:
    """转换一个 case 的全部 probing questions。"""
    probing_questions = parse_probing_questions(raw_questions)
    result: list[dict[str, Any]] = []

    for raw_type, questions in probing_questions.items():
        question_type = normalize_question_type(raw_type)
        category = QUESTION_TYPE_TO_CATEGORY.get(question_type, 0)

        for question_index, question in enumerate(questions):
            result.append(
                {
                    "question": question.get("question", ""),
                    "evidence": question.get("evidence", question.get("source_ids", [])),
                    "category": category,
                    "question_type": question_type,
                    "question_index": question_index,
                    "answer": get_gold_answer(question),
                    "rubric": question.get("rubric", ""),
                    "difficulty": question.get("difficulty", ""),
                }
            )
    return result


def convert_one_case(case_index: int, item: dict[str, Any], split: str) -> dict[str, Any]:
    """一个 BEAM case 转换为一个 LoCoMo-like sample。"""
    source_index = item.get("_beam_row_index", case_index)
    source_split = item.get("_beam_split", split)
    seed = item.get("conversation_seed") or {}

    return {
        "sample_id": f"beam-{source_split}-{source_index}",
        "metadata": {
            "dataset": "BEAM",
            "source_dataset": "Mohammadta/BEAM",
            "chat_size": source_split,
            "case_index": source_index,
            "category": seed.get("category", ""),
            "title": seed.get("title", ""),
            "theme": seed.get("theme", ""),
        },
        "conversation": convert_conversation(item["chat"]),
        "qa": convert_questions(item["probing_questions"]),
    }


def convert_dataset(data: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    """转换整个抽样数据集。"""
    return [convert_one_case(index, item, split) for index, item in enumerate(data)]


def main() -> None:
    parser = argparse.ArgumentParser(description="将 BEAM 转为 LoCoMo-like 格式")
    parser.add_argument("input", help="download_beam.py 生成的原始 JSON")
    parser.add_argument("-o", "--output", default="data/converted/beam_100K_5cases_locomo.json")
    parser.add_argument("--split", default="100K")
    args = parser.parse_args()

    with Path(args.input).open(encoding="utf-8") as file:
        data = json.load(file)

    samples = convert_dataset(data, args.split)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(samples, file, ensure_ascii=False, indent=2)

    total_questions = sum(len(sample["qa"]) for sample in samples)
    total_sessions = sum(
        len(
            [
                key
                for key in sample["conversation"]
                if key.startswith("session_") and not key.endswith("_date_time")
            ]
        )
        for sample in samples
    )
    print(
        f"转换完成：{len(samples)} cases，{total_questions} QA，"
        f"{total_sessions} sessions -> {output_path}"
    )


if __name__ == "__main__":
    main()

