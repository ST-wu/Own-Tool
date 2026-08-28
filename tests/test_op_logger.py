from datetime import datetime, timedelta
from pathlib import Path
from core.op_logger import OperationLogger
from config import settings


def test_op_logger_write_entry(tmp_path: Path):
    """驗證操作審計日誌之檔案生成與精簡格式"""
    logger = OperationLogger()
    action = "UNIT_TEST:ACTION"
    status = "SUCCESS"
    details = {"module": "auth", "target": "user_profile"}

    log_line = logger.log(action=action, status=status, details=details, duration_ms=45.2)

    assert "UNIT_TEST:ACTION" in log_line
    assert "SUCCESS" in log_line
    assert "duration=45.2ms" in log_line

    today_str = datetime.now().strftime("%Y-%m-%d")
    expected_file = logger.operations_dir / f"op_{today_str}.log"
    assert expected_file.exists()

    content = expected_file.read_text(encoding="utf-8")
    assert "UNIT_TEST:ACTION" in content


def test_op_logger_masking():
    """驗證敏感機敏字串之自動遮罩功能"""
    logger = OperationLogger()
    sensitive_payload = {
        "username": "johnson",
        "password": "super_secret_password",
        "api_key": "sec_1234567890",
        "user_token": "bearer_abc_xyz",
    }

    log_line = logger.log("TEST:MASK", "INFO", details=sensitive_payload)

    assert "johnson" in log_line
    assert "super_secret_password" not in log_line
    assert "sec_1234567890" not in log_line
    assert "bearer_abc_xyz" not in log_line
    assert "***MASKED***" in log_line


def test_op_logger_retention_cleanup(tmp_path: Path):
    """驗證 30 天歷史日誌自動清理功能"""
    logger = OperationLogger()
    ops_dir = logger.operations_dir

    # 1. 建立一個 35 天前的模擬過期日誌檔案
    old_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    old_file = ops_dir / f"op_{old_date}.log"
    old_file.write_text("old expired log content", encoding="utf-8")

    # 2. 建立一個當前的活躍日誌檔案
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_file = ops_dir / f"op_{today_str}.log"
    current_file.write_text("current active log content", encoding="utf-8")

    # 3. 執行過期日誌清理 (預設 30 天)
    deleted = logger.clean_expired_logs(max_days=30)

    # 4. 斷言舊檔案已被刪除，當前檔案依然安在
    assert any(p.name == old_file.name for p in deleted)
    assert not old_file.exists()
    assert current_file.exists()
