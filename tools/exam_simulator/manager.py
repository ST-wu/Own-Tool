import json
import random
import time
from pathlib import Path
from typing import Any
from core.logger import logger
from tools.exam_simulator.models import (
    Question,
    QuestionBankMeta,
    ExamSubmissionRequest,
    ExamEvaluationResponse,
    QuestionResult,
    UserProgress,
)


class ExamBankManager:
    """可插拔式題庫管理與評分引擎 (支援動態熱掃描、出題篩選與錯題本持久化)"""

    def __init__(
        self,
        banks_dir: Path | None = None,
        progress_file: Path | None = None,
    ) -> None:
        base_dir = Path(__file__).resolve().parent
        self.banks_dir = banks_dir or (base_dir / "data" / "question_banks")
        self.progress_file = progress_file or (base_dir / "data" / "exam_progress.json")
        self.banks_dir.mkdir(parents=True, exist_ok=True)
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)

        self._banks: dict[str, list[Question]] = {}
        self._metadata: dict[str, QuestionBankMeta] = {}
        self._progress: dict[str, UserProgress] = {}

        self.load_progress()
        self.scan_banks()

    def load_progress(self) -> None:
        """讀取使用者學習進度與錯題本記錄"""
        if not self.progress_file.exists():
            self._progress = {}
            return

        try:
            content = self.progress_file.read_text(encoding="utf-8")
            raw_data = json.loads(content)
            for bank_id, p_data in raw_data.items():
                self._progress[bank_id] = UserProgress(**p_data)
        except Exception as e:
            logger.warning(f"[ERROR_SUMMARY] 讀取題庫學習進度失敗: {type(e).__name__}: {e}")
            self._progress = {}

    def save_progress(self) -> None:
        """持久化保存使用者學習進度與錯題本記錄"""
        try:
            raw_data = {bank_id: p.model_dump() for bank_id, p in self._progress.items()}
            self.progress_file.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[ERROR_SUMMARY] 保存題庫學習進度失敗: {type(e).__name__}: {e}")

    def scan_banks(self) -> int:
        """動態掃描 data/question_banks/ 下的所有 JSON 題庫檔案"""
        self._banks.clear()
        self._metadata.clear()

        if not self.banks_dir.exists():
            return 0

        for json_file in self.banks_dir.glob("*.json"):
            bank_id = json_file.stem
            try:
                content = json_file.read_text(encoding="utf-8")
                raw_list = json.loads(content)
                if not isinstance(raw_list, list):
                    continue

                questions: list[Question] = []
                topics_set: set[str] = set()

                for item in raw_list:
                    q = Question(**item)
                    questions.append(q)
                    if q.topic:
                        topics_set.add(q.topic)

                self._banks[bank_id] = questions

                # 題庫展示標題格式：JSON檔名(不含副檔名) 模擬題庫
                title = f"{json_file.stem} 模擬題庫"

                stat = json_file.stat()
                user_prog = self._progress.get(bank_id, UserProgress(bank_id=bank_id))

                self._metadata[bank_id] = QuestionBankMeta(
                    bank_id=bank_id,
                    title=title,
                    total_questions=len(questions),
                    topics=sorted(list(topics_set)),
                    file_size_kb=round(stat.st_size / 1024, 1),
                    last_modified=stat.st_mtime,
                    wrong_count=len(user_prog.wrong_question_ids),
                )
            except Exception as e:
                logger.warning(f"[ERROR_SUMMARY] 解析題庫檔案 ({json_file.name}) 失敗: {type(e).__name__}: {e}")

        logger.info(f"動態探索題庫完成，共載入 {len(self._banks)} 組可用題庫: {list(self._banks.keys())}")
        return len(self._banks)

    def get_available_banks(self) -> list[QuestionBankMeta]:
        """獲取所有可用題庫之中繼資料清單"""
        self.scan_banks()
        return list(self._metadata.values())

    def get_bank_meta(self, bank_id: str) -> QuestionBankMeta | None:
        """獲取指定題庫之規格資料"""
        if bank_id not in self._metadata:
            self.scan_banks()
        return self._metadata.get(bank_id)

    def get_questions(
        self,
        bank_id: str,
        mode: str = "practice",
        topic: str | None = None,
        range_start: int | None = None,
        range_end: int | None = None,
        limit: int | None = None,
        shuffle: bool = False,
    ) -> list[Question]:
        """
        依據模式與條件過濾並提取題庫中的題目
        """
        if bank_id not in self._banks:
            self.scan_banks()

        all_q = self._banks.get(bank_id, [])
        if not all_q:
            return []

        user_prog = self._progress.get(bank_id, UserProgress(bank_id=bank_id))

        filtered: list[Question] = []
        for q in all_q:
            # 錯題本模式篩選
            if mode == "wrong" and q.id not in user_prog.wrong_question_ids:
                continue

            # 主題領域篩選
            if topic and topic != "ALL" and q.topic != topic:
                continue

            # 題號範圍篩選
            if range_start is not None and q.id < range_start:
                continue
            if range_end is not None and q.id > range_end:
                continue

            filtered.append(q)

        if shuffle:
            shuffled = list(filtered)
            random.shuffle(shuffled)
            filtered = shuffled

        if limit and limit > 0:
            filtered = filtered[:limit]

        return filtered

    def check_single_answer(
        self,
        bank_id: str,
        question_id: int,
        selected_options: list[int] = [],
        selected_dropdowns: list[int] = [],
    ) -> dict[str, Any]:
        """
        即時對答案：核對單一考題答案，並即時更新錯題本持久化檔案
        """
        if bank_id not in self._banks:
            self.scan_banks()

        q_map = {q.id: q for q in self._banks.get(bank_id, [])}
        q = q_map.get(question_id)
        if not q:
            return {"success": False, "message": f"找不到題目 #{question_id}"}

        user_prog = self._progress.setdefault(bank_id, UserProgress(bank_id=bank_id))
        is_correct = False
        correct_answer: Any = None

        if q.type == "drop_down":
            correct_dropdown_answers = [d.answer for d in q.dropdowns]
            correct_answer = correct_dropdown_answers
            is_correct = selected_dropdowns == correct_dropdown_answers
        else:
            correct_answer = q.answer
            is_correct = set(selected_options) == set(q.answer)

        # 即時更新錯題本
        if is_correct:
            if question_id in user_prog.wrong_question_ids:
                user_prog.wrong_question_ids.remove(question_id)
        else:
            if question_id not in user_prog.wrong_question_ids:
                user_prog.wrong_question_ids.append(question_id)

        self.save_progress()
        if bank_id in self._metadata:
            self._metadata[bank_id].wrong_count = len(user_prog.wrong_question_ids)

        return {
            "success": True,
            "question_id": question_id,
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "explanation": q.explanation,
            "wrong_count": len(user_prog.wrong_question_ids),
        }

    def submit_exam(self, bank_id: str, submission: ExamSubmissionRequest) -> ExamEvaluationResponse:
        """
        全真模擬考或批次交卷答案核對評分，並更新錯題本持久化記錄
        """
        if bank_id not in self._banks:
            self.scan_banks()

        q_map = {q.id: q for q in self._banks.get(bank_id, [])}
        user_prog = self._progress.setdefault(bank_id, UserProgress(bank_id=bank_id))

        results: list[QuestionResult] = []
        correct_count = 0
        topic_breakdown: dict[str, dict[str, int]] = {}

        for ans in submission.answers:
            q = q_map.get(ans.question_id)
            if not q:
                continue

            topic_stats = topic_breakdown.setdefault(q.topic, {"total": 0, "correct": 0})
            topic_stats["total"] += 1

            is_correct = False
            user_val: Any = None
            correct_val: Any = None

            if q.type == "drop_down":
                correct_dropdown_answers = [d.answer for d in q.dropdowns]
                user_val = ans.selected_dropdowns
                correct_val = correct_dropdown_answers
                is_correct = ans.selected_dropdowns == correct_dropdown_answers
            elif q.type in ("single_choice", "multiple_choice", "case_study"):
                user_val = sorted(ans.selected_options)
                correct_val = sorted(q.answer)
                is_correct = set(ans.selected_options) == set(q.answer)

            if is_correct:
                correct_count += 1
                topic_stats["correct"] += 1
                if submission.mode == "exam" and q.id in user_prog.wrong_question_ids:
                    user_prog.wrong_question_ids.remove(q.id)
            else:
                if q.id not in user_prog.wrong_question_ids:
                    user_prog.wrong_question_ids.append(q.id)

            results.append(
                QuestionResult(
                    question_id=q.id,
                    is_correct=is_correct,
                    user_answer=user_val,
                    correct_answer=correct_val,
                    explanation=q.explanation,
                    topic=q.topic,
                )
            )

        total_submitted = len(submission.answers)
        score_pct = round((correct_count / total_submitted * 100), 1) if total_submitted > 0 else 0.0
        is_passed = score_pct >= 70.0

        user_prog.exam_history.append(
            {
                "timestamp": time.time(),
                "mode": submission.mode,
                "score_pct": score_pct,
                "total": total_submitted,
                "correct": correct_count,
                "is_passed": is_passed,
                "time_spent_seconds": submission.time_spent_seconds,
            }
        )
        self.save_progress()

        if bank_id in self._metadata:
            self._metadata[bank_id].wrong_count = len(user_prog.wrong_question_ids)

        return ExamEvaluationResponse(
            bank_id=bank_id,
            total_submitted=total_submitted,
            correct_count=correct_count,
            wrong_count=total_submitted - correct_count,
            score_percentage=score_pct,
            is_passed=is_passed,
            time_spent_seconds=submission.time_spent_seconds,
            topic_breakdown=topic_breakdown,
            results=results,
        )

    def remove_wrong_question(self, bank_id: str, question_id: int) -> bool:
        """手動將題目自錯題本移出 (標記為已精通)"""
        user_prog = self._progress.get(bank_id)
        if not user_prog or question_id not in user_prog.wrong_question_ids:
            return False

        user_prog.wrong_question_ids.remove(question_id)
        if question_id not in user_prog.mastered_question_ids:
            user_prog.mastered_question_ids.append(question_id)

        self.save_progress()
        if bank_id in self._metadata:
            self._metadata[bank_id].wrong_count = len(user_prog.wrong_question_ids)

        logger.info(f"已將題目 #{question_id} 自題庫 [{bank_id}] 錯題本中移出")
        return True


# 全域單例管理器
exam_manager = ExamBankManager()
