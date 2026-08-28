// logs/all_log_config.js
// 專案全域日誌與操作審計配置檔案
// 定義操作總紀錄 (operations) 及各子工具模組專屬日誌的輪轉與清理政策

module.exports = {
  // 1. 專案操作總紀錄設定 (logs/operations/)
  // 紀錄專案的任何手動/外部操作事件（CLI 執行、API 訪問、任務觸發等）
  operations: {
    enabled: true,
    folder: "operations",           // 存放子目錄名稱: logs/operations/
    file_prefix: "op",              // 檔名前綴: op_YYYY-MM-DD.log
    retention_days: 30,             // 最長保留 30 天 (約 1 個月)，逾期自動清理
    max_records_per_day: 10000,     // 單日最大紀錄筆數防護
    max_file_size_mb: 10,           // 單一檔案容量上限 (MB)
    log_level: "INFO",              // 紀錄層級 (DEBUG, INFO, WARNING, ERROR)
    mask_sensitive_keys: true       // 自動遮罩 password, key, secret, token 等機敏資料
  },

  // 2. 子模組與未來工具專屬日誌預設設定 (供 logs/ 下其它專屬子目錄參考)
  submodules: {
    default_retention_days: 30,     // 預設保留天數
    max_file_size_mb: 10,           // 預設單檔上限
    auto_cleanup: true              // 是否納入每日自動過期清理掃描
  }
};
