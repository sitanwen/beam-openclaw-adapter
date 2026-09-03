from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from convert_beam_to_locomo import (  # noqa: E402
    convert_conversation,
    convert_questions,
    normalize_question_type,
)
from aggregate_beam_scores import summarize  # noqa: E402


def test_normalize_question_type() -> None:
    assert normalize_question_type("Knowledge Update") == "knowledge_update"
    assert normalize_question_type("Multi-Hop Reasoning") == "multi_session_reasoning"


def test_convert_batched_chat() -> None:
    chat = [
        {
            "time_anchor": "2026-01-01",
            "turns": [
                {"role": "user", "content": "你好", "id": 10},
                {"role": "assistant", "content": "你好！", "id": 11},
            ],
        }
    ]
    converted = convert_conversation(chat)
    assert converted["session_1_date_time"] == "2026-01-01"
    assert converted["session_1"][0]["dia_id"] == "D1:10"
    assert converted["session_1"][1]["speaker"] == "Assistant"


def test_convert_questions() -> None:
    raw = str(
        {
            "Information Extraction": [
                {
                    "question": "用户叫什么？",
                    "ideal_response": "小明",
                    "rubric": "回答出小明",
                },
                {
                    "question": "用户住在哪里？",
                    "ideal_response": "上海",
                    "rubric": "回答出上海",
                },
            ]
        }
    )
    questions = convert_questions(raw)
    assert len(questions) == 2
    assert questions[0]["question_type"] == "information_extraction"
    assert questions[0]["answer"] == "小明"
    assert questions[0]["rubric"] == "回答出小明"


def test_aggregate_scores() -> None:
    rows = [
        {"question_type": "information_extraction", "rubric_score": 1.0},
        {"question_type": "information_extraction", "rubric_score": 0.5},
        {"question_type": "temporal_reasoning", "rubric_score": 0.0},
    ]
    summary = summarize(rows, pass_threshold=0.5)
    assert summary["question_count"] == 3
    assert summary["mean_rubric_score"] == 0.5
    assert summary["binary_pass_rate"] == 2 / 3
    assert summary["by_question_type"]["information_extraction"]["count"] == 2
