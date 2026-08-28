import os
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from config import settings
from core.logger import logger

# 機敏欄位遮罩關鍵字清單
SENSITIVE_KEY_PATTERNS = ["password", "secret", "token", "key", "auth", "credential"]


class OperationLogger:
    """
    專案專屬操作審計日誌器
    專職記錄專案所有觸發操作（CLI、API 調用、系統排程等），採每日分檔與過期自動清理
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or (settings.LOG_DIR / "operations" / "all_log_config.js")
        self.config = self._load_config()
        self.operations_dir = settings.LOG_DIR / self.config.get("folder", "operations")
        self.operations_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict[str, Any]:
        """讀取 logs/all_log_config.js 設定，具備自動容錯與預設值退避 (Guard clause 優先)"""
        default_config = {
            "enabled": True,
            "folder": "operations",
            "file_prefix": "op",
            "retention_days": 30,
            "max_records_per_day": 10000,
            "max_file_size_mb": 10,
            "log_level": "INFO",
            "mask_sensitive_keys": True,
        }

        if not self.config_path.exists():
            return default_config

        try:
            content = self.config_path.read_text(encoding="utf-8")
            # 去除單行註解 (// ...)
            cleaned = re.sub(r"//.*", "", content)
            # 擷取 module.exports = { ... }; 或純 JSON 物件
            match = re.search(r"=\s*(\{[\s\S]*\})\s*;?", cleaned)
            raw_json = match.group(1) if match else cleaned
            # 轉換 JS 鍵名 (若無雙引號則補齊)
            raw_json = re.sub(r"(\b\w+\b)(?=\s*:)", r'"\1"', raw_json)
            # 去除結尾逗號
            raw_json = re.sub(r",\s*([\}\]])", r"\1", raw_json)
            data = json.loads(raw_json)
            ops_config = data.get("operations", {})
            return {**default_config, **ops_config}
        except Exception as e:
            logger.warning(f"[ERROR_SUMMARY] 解析 {self.config_path.name} 失敗，使用預設安全配置: {type(e).__name__}: {e}")
            return default_config

    def _mask_sensitive_data(self, data: Any) -> Any:
        """遮蔽字典或字串中的機敏資訊"""
        if not self.config.get("mask_sensitive_keys", True):
            return data

        if isinstance(data, dict):
            masked = {}
            for k, v in data.items():
                if any(pat in str(k).lower() for pat in SENSITIVE_KEY_PATTERNS):
                    masked[k] = "***MASKED***"
                else:
                    masked[k] = self._mask_sensitive_data(v)
            return masked
        if isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        if isinstance(data, str):
            # 若字串中包含 key= 或 token= 等型態，進行局部遮蔽
            pattern = r"((?:api[_-]?key|token|secret|password)\s*[:=]\s*)([^\s&,]+)"
            return re.sub(pattern, r"\1***MASKED***", data, flags=re.IGNORECASE)
        return data

    def log(
        self,
        action: str,
        status: str = "INFO",
        details: dict[str, Any] | str | None = None,
        duration_ms: float | None = None,
    ) -> str:
        """
        寫入單筆操作審計日誌
        :param action: 操作名稱 (如 CLI:run-task, API:POST_task_run)
        :param status: 結果狀態 (DEBUG, INFO, SUCCESS, WARNING, ERROR)
        :param details: 業務摘要資訊或參數
        :param duration_ms: 操作耗時 (毫秒)
        :return: 產生的日誌單行字串
        """
        # Guard clause: 檢查是否啟用
        if not self.config.get("enabled", True):
            return ""

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        date_str = now.strftime("%Y-%m-%d")

        # 整理 details 欄位
        detail_str = ""
        if details:
            safe_details = self._mask_sensitive_data(details)
            if isinstance(safe_details, dict):
                detail_str = " | " + " ".join(f"{k}={v}" for k, v in safe_details.items())
            else:
                detail_str = f" | {safe_details}"

        # 整理耗時欄位
        dur_str = f" | duration={duration_ms:.1f}ms" if duration_ms is not None else ""

        # 組合精簡單行格式
        log_line = f"[{timestamp_str}] [{status: <7}] [{action}]{detail_str}{dur_str}\n"

        # 寫入每日分檔: logs/operations/op_YYYY-MM-DD.log
        prefix = self.config.get("file_prefix", "op")
        target_file = self.operations_dir / f"{prefix}_{date_str}.log"

        try:
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"[ERROR_SUMMARY] 操作日誌寫入失敗: {type(e).__name__}: {e}")

        return log_line.strip()

    def clean_expired_logs(self, max_days: int | None = None) -> list[Path]:
        """
        安全清理超過保留天數的歷史日誌檔案 (Guard clause 優先)
        :param max_days: 自訂天數，預設讀取 all_log_config.js 中的 retention_days
        :return: 已被清除的檔案清單
        """
        retention_days = max_days if max_days is not None else self.config.get("retention_days", 30)
        if retention_days <= 0:
            logger.info("日誌保留天數 <= 0，略過過期清理")
            return []

        cutoff_time = time.time() - (retention_days * 86400)
        deleted_files: list[Path] = []

        # 遍歷 logs/operations/ 及 logs/ 下的子資料夾
        search_dirs = [self.operations_dir, settings.LOG_DIR]
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for file_path in search_dir.glob("*.log"):
                try:
                    # 優先從檔名解析日期 (如 op_2026-08-28.log)
                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", file_path.name)
                    is_expired = False
                    if date_match:
                        file_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                        is_expired = (datetime.now() - file_date).days > retention_days
                    else:
                        # 降級使用檔案最後修改時間
                        is_expired = file_path.stat().st_mtime < cutoff_time

                    if is_expired:
                        file_path.unlink()
                        deleted_files.append(file_path)
                        logger.info(f"[LOG_RETENTION] 已清理過期歷史日誌: {file_path.name} (超過 {retention_days} 天)")
                except Exception as e:
                    logger.warning(f"[ERROR_SUMMARY] 清理日誌檔 {file_path.name} 異常: {type(e).__name__}: {e}")

        return deleted_files


# 全域單例
op_logger = OperationLogger()
