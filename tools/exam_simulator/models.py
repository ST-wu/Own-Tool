from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    DROP_DOWN = "drop_down"
    CASE_STUDY = "case_study"


class DropdownItem(BaseModel):
    placeholder: str = Field(..., description="填空佔位符，例如 [Box 1]")
    options: list[str] = Field(default_factory=list, description="該格之候選項目清單")
    answer: int = Field(0, description="正確選項索引 (0-indexed)")


class Question(BaseModel):
    id: int = Field(..., description="題目唯一編號")
    topic: str = Field("General", description="主題領域分類")
    type: str = Field(QuestionType.SINGLE_CHOICE.value, description="題型識別碼")
    question: str = Field(..., description="題目主體文本")
    options: list[str] = Field(default_factory=list, description="單/複選題之選項清單")
    answer: list[int] = Field(default_factory=list, description="正確答案索引 (0-indexed)")
    explanation: str = Field("", description="題目解析與說明")
    dropdowns: list[DropdownItem] = Field(default_factory=list, description="下拉填空題之個別設定")
    case_study_title: str | None = Field(None, description="情境案例標題")


class QuestionBankMeta(BaseModel):
    bank_id: str = Field(..., description="題庫唯一識別碼 (如 ai-103)")
    title: str = Field(..., description="題庫展示名稱 (如 Azure AI-103 題庫)")
    total_questions: int = Field(0, description="題目總數")
    topics: list[str] = Field(default_factory=list, description="包含之主題清單")
    file_size_kb: float = Field(0.0, description="題庫檔案大小 (KB)")
    last_modified: float = Field(0.0, description="最後修改時間戳記")
    wrong_count: int = Field(0, description="該科目當前錯題累積數")


class UserAnswer(BaseModel):
    question_id: int = Field(..., description="題目 ID")
    selected_options: list[int] = Field(default_factory=list, description="選擇的選項索引清單")
    selected_dropdowns: list[int] = Field(default_factory=list, description="下拉選單各格選擇索引")


class ExamSubmissionRequest(BaseModel):
    mode: str = Field("exam", description="交卷模式: exam (全真) 或 practice (即時)")
    time_spent_seconds: int = Field(0, description="測驗花費時間 (秒)")
    answers: list[UserAnswer] = Field(default_factory=list, description="作答清單")


class QuestionResult(BaseModel):
    question_id: int
    is_correct: bool
    user_answer: Any
    correct_answer: Any
    explanation: str
    topic: str


class ExamEvaluationResponse(BaseModel):
    bank_id: str
    total_submitted: int
    correct_count: int
    wrong_count: int
    score_percentage: float
    is_passed: bool
    time_spent_seconds: int
    topic_breakdown: dict[str, dict[str, int]]
    results: list[QuestionResult]


class UserProgress(BaseModel):
    bank_id: str
    wrong_question_ids: list[int] = Field(default_factory=list, description="錯題本 ID 清單")
    mastered_question_ids: list[int] = Field(default_factory=list, description="已精通移出錯題本之 ID")
    exam_history: list[dict[str, Any]] = Field(default_factory=list, description="歷史模擬考成績記錄")
