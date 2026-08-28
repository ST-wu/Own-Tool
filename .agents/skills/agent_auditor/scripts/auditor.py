import os
import sys
import json
import argparse
from datetime import datetime
from typing import List, Dict, Any

# 匯入審計規則
from rules import (
    BackupRule, TokenWasteRule, ToolLoopRule, DependencySafetyRule,
    TroubleshootingChaosRule, DefensiveCodingRule
)

def find_latest_conversation(base_dir: str) -> str:
    """自動尋找最近修改的對話 ID"""
    brain_dir = os.path.join(base_dir, "brain")
    if not os.path.exists(brain_dir):
        raise FileNotFoundError(f"找不到腦部日誌目錄: {brain_dir}")
        
    subfolders = [
        os.path.join(brain_dir, f) for f in os.listdir(brain_dir)
        if os.path.isdir(os.path.join(brain_dir, f)) and f != "scratch"
    ]
    
    if not subfolders:
        raise FileNotFoundError(f"在 {brain_dir} 下找不到任何對話目錄")
        
    subfolders.sort(key=lambda d: os.path.getmtime(d), reverse=True)
    return subfolders[0]

def parse_transcript(conv_dir: str) -> List[Dict[str, Any]]:
    """解析 transcript.jsonl"""
    log_path = os.path.join(conv_dir, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(log_path):
        log_path = os.path.join(conv_dir, "transcript.jsonl")
        if not os.path.exists(log_path):
            raise FileNotFoundError(f"找不到對話日誌檔案: {log_path}")

    transcript = []
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        transcript.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"[警告] 解析日誌第 {line_num} 行出錯: {e}")
    except Exception as e:
        print(f"[錯誤] 無法讀取日誌檔案: {e}")
    return transcript

def generate_markdown_report(results: List[Dict[str, Any]], total_score: float, conv_id: str) -> str:
    """生成 Markdown 格式的審計診斷報告"""
    grade = "A"
    if total_score < 60: grade = "F"
    elif total_score < 75: grade = "C"
    elif total_score < 90: grade = "B"

    report = []
    report.append(f"# Agent 行為審計與弱點診斷報告")
    report.append(f"對話 ID: `{conv_id}` | 產出時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\n## 總體診斷評級: **{grade}** (得分: **{total_score:.1f}/100**)")
    
    if grade == "A":
        report.append(f"> [!NOTE]\n> Agent 在本次 Session 中表現優異，基本遵循了備份安全、節流與依賴防範規則。")
    elif grade == "B":
        report.append(f"> [!TIP]\n> 表現良好，但仍有部分細節不合規（如 Token 浪費或備份檔案殘留）。")
    else:
        report.append(f"> [!WARNING]\n> 診斷出嚴重行為缺失！請盡快更新 AGENTS.md 規則設定以防代碼損毀。")

    report.append("\n## 各項診斷指標細分")
    
    for r in results:
        status_icon = "✅ 通過" if r["passed"] else "❌ 警告"
        report.append(f"### {r['name']}：**{r['score']}分** ({status_icon})")
        report.append(f"*{r['description']}*")
        
        if r["warnings"]:
            report.append("\n**偵測到的具體缺失：**")
            for w in r["warnings"]:
                sev = w["severity"]
                prefix = "⚠️" if sev == "MEDIUM" else "🛑" if sev == "HIGH" else "ℹ️"
                report.append(f"- {prefix} `[{sev}]` {w['message']}")
        else:
            report.append("\n*無偵測到任何缺失。*")
        
        report.append("\n---")

    report.append("\n## 🎯 針對性規則補丁建議 (建議複製加入 AGENTS.md)")
    
    any_high_warning = any(w["severity"] == "HIGH" for r in results for w in r["warnings"])
    has_backup_issue = any("備份" in r["name"] and r["score"] < 100 for r in results)
    has_token_issue = any("Token" in r["name"] and r["score"] < 100 for r in results)
    has_loop_issue = any("重複" in r["name"] and r["score"] < 100 for r in results)
    has_dep_issue = any("依賴" in r["name"] and r["score"] < 100 for r in results)
    has_chaos_issue = any("除錯" in r["name"] and r["score"] < 100 for r in results)
    has_defensive_issue = any("防禦" in r["name"] and r["score"] < 100 for r in results)

    if has_backup_issue:
        report.append("""
### 1. 備份防禦補丁 (Backup Defences)
```markdown
* 修改任何檔案前，必須建立對應的 .bak 備份檔案。
* 任務測試成功後，必須在同一回合內以指令徹底刪除所有臨時 .bak 備份，維持工作區乾淨。
```""")
    if has_token_issue:
        report.append("""
### 2. Token 節約補丁 (Token Saving)
```markdown
* 禁止無行數限制讀取超過 100 行的大檔案，必須帶入 StartLine/EndLine 參數精準讀取目標區間。
```""")
    if has_loop_issue:
        report.append("""
### 3. 自我容錯與終止補丁 (Failure Loops)
```markdown
* 當任意工具連續調用失敗達 2 次時，禁止盲目重複調用。必須暫停 1 步重新推導出錯原因並寫出自我修正方案後，再行測試。
```""")
    if has_dep_issue:
        report.append("""
### 4. 依賴導入防護補丁 (Dependency Imports)
```markdown
* 在代碼中新增外部依賴模組 (Import) 時，必須優先核對 package.json 或 requirements.txt。若未寫入，禁止執行修改以防環境崩潰。
```""")
    if has_chaos_issue:
        report.append("""
### 5. 錯誤定位與除錯規範補丁 (Bug Localization)
```markdown
* 當編譯或單元測試出錯時，禁止立即修改多個檔案。必須優先讀取 traceback 指出的特定出錯行數，每次修改僅限單點修復，並立即執行預檢命令驗證，嚴防試錯與盲目擴大修改範圍。
```""")
    if has_defensive_issue:
        report.append("""
### 6. 異常安全與防禦性編程補丁 (Defensive Programming)
```markdown
* 執行 JSON 解析 (loads) 或外部檔案讀寫操作時，必須以 try-except 進行異常保護，嚴防 runtime 出現未預期崩潰。
```""")

    if not any_high_warning and total_score == 100:
        report.append("\n*目前 Agent 行為極佳，暫無急迫需要添加的補丁規則。*")

    return "\n".join(report)

def main():
    parser = argparse.ArgumentParser(description="Agent Behavior Auditor & Diagnoser")
    parser.add_argument("--app-dir", default="C:\\Users\\U\\.gemini\\antigravity-ide", help="Gemini App Data 目錄")
    parser.add_argument("--conv-id", help="特定對話 ID (預設為最新對話)")
    parser.add_argument("--workspace", default="d:\\Agent\\Tools", help="當前工作區目錄")
    parser.add_argument("--output", help="輸出報告路徑 (預設為對話目錄下)")
    
    args = parser.parse_args()

    try:
        if args.conv_id:
            conv_dir = os.path.join(args.app_dir, "brain", args.conv_id)
            if not os.path.exists(conv_dir):
                raise FileNotFoundError(f"找不到指定的對話 ID 目錄: {conv_dir}")
        else:
            conv_dir = find_latest_conversation(args.app_dir)
            args.conv_id = os.path.basename(conv_dir)
    except Exception as e:
        print(f"[錯誤] 無法定位對話日誌: {e}")
        sys.exit(1)

    # 預設輸出路徑
    if not args.output:
        args.output = os.path.join(conv_dir, "agent_diagnosis_report.md")

    print(f"[資訊] 開始分析對話: {args.conv_id}")
    print(f"[資訊] 對話路徑: {conv_dir}")

    try:
        transcript = parse_transcript(conv_dir)
    except Exception as e:
        print(f"[錯誤] 讀取日誌出錯: {e}")
        sys.exit(1)

    rules = [
        BackupRule(),
        TokenWasteRule(),
        ToolLoopRule(),
        DependencySafetyRule(),
        TroubleshootingChaosRule(),
        DefensiveCodingRule()
    ]

    results = []
    total_score = 0.0
    for rule in rules:
        try:
            res = rule.audit(transcript, args.workspace)
            results.append(res)
            total_score += res["score"]
        except Exception as e:
            print(f"[錯誤] 規則 '{rule.name}' 執行失敗: {e}")

    if rules:
        total_score /= len(rules)

    report_content = generate_markdown_report(results, total_score, args.conv_id)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report_content)
    except Exception as e:
        print(f"[錯誤] 無法寫入診斷報告: {e}")

    print(f"[成功] 診斷完成，分數: {total_score:.1f}/100. 報告已輸出至: {args.output}")

if __name__ == "__main__":
    main()
