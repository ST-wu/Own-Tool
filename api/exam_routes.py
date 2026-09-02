import json
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from core.logger import logger
from core.op_logger import op_logger
from tools.exam_simulator.manager import exam_manager
from tools.exam_simulator.models import (
    Question,
    QuestionBankMeta,
    ExamSubmissionRequest,
    ExamEvaluationResponse,
)

exam_router = APIRouter(prefix="/api/v1/exam", tags=["Exam Simulator"])


@exam_router.get("/banks", response_model=list[QuestionBankMeta])
async def list_question_banks_endpoint() -> list[QuestionBankMeta]:
    """獲取所有可用題庫清單 (全自動動態掃描 tools/exam_simulator/data/question_banks/ 目錄)"""
    return exam_manager.get_available_banks()


@exam_router.get("/banks/{bank_id}", response_model=QuestionBankMeta)
async def get_bank_metadata_endpoint(bank_id: str) -> QuestionBankMeta:
    """獲取特定題庫之詳細中繼資料與主題列表"""
    meta = exam_manager.get_bank_meta(bank_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到指定之題庫: {bank_id}",
        )
    return meta


@exam_router.get("/banks/{bank_id}/questions", response_model=list[Question])
async def get_questions_endpoint(
    bank_id: str,
    mode: str = Query("practice", description="模式: practice (練習), exam (全真), wrong (錯題本)"),
    topic: str | None = Query(None, description="主題分類篩選 (如 Topic 1)"),
    range_start: int | None = Query(None, description="題號起始範圍"),
    range_end: int | None = Query(None, description="題號結束範圍"),
    limit: int | None = Query(None, description="最多回傳題數"),
    shuffle: bool = Query(False, description="是否隨機打亂題目順序"),
) -> list[Question]:
    """依據條件過濾並讀取題目清單"""
    meta = exam_manager.get_bank_meta(bank_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到指定之題庫: {bank_id}",
        )

    questions = exam_manager.get_questions(
        bank_id=bank_id,
        mode=mode,
        topic=topic,
        range_start=range_start,
        range_end=range_end,
        limit=limit,
        shuffle=shuffle,
    )
    return questions


class SingleCheckRequest(BaseModel):
    question_id: int
    selected_options: list[int] = Field(default_factory=list)
    selected_dropdowns: list[int] = Field(default_factory=list)


@exam_router.post("/banks/{bank_id}/check")
async def check_single_question_endpoint(bank_id: str, payload: SingleCheckRequest):
    """即時對答案：核對單題答案並即時同步更新錯題本檔案"""
    result = exam_manager.check_single_answer(
        bank_id=bank_id,
        question_id=payload.question_id,
        selected_options=payload.selected_options,
        selected_dropdowns=payload.selected_dropdowns,
    )
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("message"))
    return result


@exam_router.post("/banks/{bank_id}/submit", response_model=ExamEvaluationResponse)
async def submit_exam_endpoint(
    bank_id: str,
    payload: ExamSubmissionRequest,
) -> ExamEvaluationResponse:
    """提交測驗並即時計算總分、各領域分析與錯題本歸檔"""
    meta = exam_manager.get_bank_meta(bank_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到指定之題庫: {bank_id}",
        )

    eval_result = exam_manager.submit_exam(bank_id, payload)
    op_logger.log(
        "TOOL:EXAM_SUBMIT",
        "INFO" if eval_result.is_passed else "WARNING",
        details=f"測驗交卷 [{bank_id}] | 總題數: {eval_result.total_submitted} | 正確率: {eval_result.score_percentage}% | 通過: {eval_result.is_passed}",
    )
    return eval_result


@exam_router.delete("/banks/{bank_id}/wrong/{question_id}")
async def remove_wrong_question_endpoint(bank_id: str, question_id: int):
    """將已熟練題目自錯題本移出"""
    success = exam_manager.remove_wrong_question(bank_id, question_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"錯題本中未找到題目 #{question_id}",
        )
    return {"success": True, "message": f"題目 #{question_id} 已成功移出錯題本"}
