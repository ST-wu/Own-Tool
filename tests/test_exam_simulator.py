import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from tools.exam_simulator.manager import exam_manager
from tools.exam_simulator.models import ExamSubmissionRequest, UserAnswer


def test_exam_manager_scans_and_discovers_banks():
    """驗證 ExamBankManager 能全自動動態掃描並載入題庫"""
    banks_count = exam_manager.scan_banks()
    assert banks_count >= 1

    banks = exam_manager.get_available_banks()
    bank_ids = [b.bank_id for b in banks]
    assert "ai-103" in bank_ids

    ai103_meta = exam_manager.get_bank_meta("ai-103")
    assert ai103_meta is not None
    assert ai103_meta.total_questions >= 180
    assert len(ai103_meta.topics) > 0


def test_exam_manager_question_filtering():
    """驗證題目篩選器 (範圍、主題領域、模式)"""
    # 1. 範圍過濾
    range_questions = exam_manager.get_questions("ai-103", range_start=1, range_end=10)
    assert len(range_questions) == 10
    assert all(1 <= q.id <= 10 for q in range_questions)

    # 2. 主題領域過濾
    meta = exam_manager.get_bank_meta("ai-103")
    assert meta is not None
    if meta.topics:
        target_topic = meta.topics[0]
        topic_questions = exam_manager.get_questions("ai-103", topic=target_topic)
        assert len(topic_questions) > 0
        assert all(q.topic == target_topic for q in topic_questions)


def test_exam_submission_and_scoring():
    """驗證交卷評分、領域分析與錯題本歸檔機制"""
    questions = exam_manager.get_questions("ai-103", range_start=1, range_end=2)
    assert len(questions) == 2

    # 構造作答 (一題答對，一題答錯)
    q1 = questions[0]
    q2 = questions[1]

    # q1 正確作答
    ans1_opts = q1.answer if q1.type != "drop_down" else []
    ans1_dds = [d.answer for d in q1.dropdowns] if q1.type == "drop_down" else []

    # q2 刻意答錯
    ans2_opts = [999] if q2.type != "drop_down" else []
    ans2_dds = [999] * len(q2.dropdowns) if q2.type == "drop_down" else []

    submission = ExamSubmissionRequest(
        mode="exam",
        time_spent_seconds=60,
        answers=[
            UserAnswer(question_id=q1.id, selected_options=ans1_opts, selected_dropdowns=ans1_dds),
            UserAnswer(question_id=q2.id, selected_options=ans2_opts, selected_dropdowns=ans2_dds),
        ],
    )

    result = exam_manager.submit_exam("ai-103", submission)
    assert result.total_submitted == 2
    assert result.correct_count == 1
    assert result.wrong_count == 1
    assert result.score_percentage == 50.0
    assert result.is_passed is False

    # 驗證 q2 被自動歸檔至錯題本
    user_prog = exam_manager._progress.get("ai-103")
    assert user_prog is not None
    assert q2.id in user_prog.wrong_question_ids


def test_remove_wrong_question():
    """驗證已精通題目可自錯題本中移出"""
    # 先確保錯題本中有資料
    user_prog = exam_manager._progress.setdefault("ai-103", exam_manager._progress.get("ai-103"))
    user_prog.wrong_question_ids.append(9999)
    exam_manager.save_progress()

    assert 9999 in exam_manager._progress["ai-103"].wrong_question_ids
    removed = exam_manager.remove_wrong_question("ai-103", 9999)
    assert removed is True
    assert 9999 not in exam_manager._progress["ai-103"].wrong_question_ids


@pytest.mark.asyncio
async def test_exam_api_endpoints():
    """驗證 FastAPI 模擬測驗系統端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 查詢所有題庫
        banks_res = await client.get("/api/v1/exam/banks")
        assert banks_res.status_code == 200
        banks = banks_res.json()
        assert len(banks) >= 1
        assert any(b["bank_id"] == "ai-103" for b in banks)

        # 2. 查詢特定題庫中繼資料
        meta_res = await client.get("/api/v1/exam/banks/ai-103")
        assert meta_res.status_code == 200
        meta = meta_res.json()
        assert meta["total_questions"] >= 180

        # 3. 取得考題 (限制 5 題)
        q_res = await client.get("/api/v1/exam/banks/ai-103/questions?limit=5")
        assert q_res.status_code == 200
        questions = q_res.json()
        assert len(questions) == 5

        # 4. 交卷測試
        submit_payload = {
            "mode": "practice",
            "time_spent_seconds": 30,
            "answers": [
                {
                    "question_id": questions[0]["id"],
                    "selected_options": questions[0]["answer"],
                    "selected_dropdowns": [d["answer"] for d in questions[0].get("dropdowns", [])],
                }
            ],
        }
        submit_res = await client.post("/api/v1/exam/banks/ai-103/submit", json=submit_payload)
        assert submit_res.status_code == 200
        eval_data = submit_res.json()
        assert eval_data["total_submitted"] == 1
        assert eval_data["correct_count"] == 1

        # 5. 單題即時對答案測試
        check_payload = {
            "question_id": questions[0]["id"],
            "selected_options": questions[0]["answer"],
            "selected_dropdowns": [d["answer"] for d in questions[0].get("dropdowns", [])],
        }
        check_res = await client.post("/api/v1/exam/banks/ai-103/check", json=check_payload)
        assert check_res.status_code == 200
        check_data = check_res.json()
        assert check_data["is_correct"] is True
