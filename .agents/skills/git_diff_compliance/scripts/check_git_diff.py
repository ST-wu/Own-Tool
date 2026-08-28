import sys
import subprocess
import shutil

def check_git_diff():
    git_bin = shutil.which("git")
    if not git_bin:
        print("[WARNING] Git executable not found. Cannot perform diff check.")
        return True

    # 執行 git diff 與 git diff --cached 合併分析
    cmd_unstaged = [git_bin, "diff", "--stat"]
    cmd_staged = [git_bin, "diff", "--cached", "--stat"]
    
    res_unstaged = subprocess.run(cmd_unstaged, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    res_staged = subprocess.run(cmd_staged, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    
    output = (res_unstaged.stdout or "") + "\n" + (res_staged.stdout or "")
    output = output.strip()
    
    if not output or "files changed" not in output:
        print("[SUCCESS] No local git modifications detected. Diff is empty.")
        return True
        
    print("[INFO] Analyzing local git diff modifications:")
    print("=" * 60)
    print(output)
    print("=" * 60)
    
    # 簡單分析異動規模
    total_insertions = 0
    total_deletions = 0
    lines = output.split("\n")
    
    for line in lines:
        if "insertion" in line or "deletion" in line:
            # 範例格式:  1 file changed, 1 insertion(+), 1 deletion(-)
            parts = line.strip().split(",")
            for part in parts:
                part = part.strip()
                if "insertion" in part:
                    try:
                        total_insertions += int(part.split()[0])
                    except Exception:
                        pass
                elif "deletion" in part:
                    try:
                        total_deletions += int(part.split()[0])
                    except Exception:
                        pass

    print(f"Total Insertions: +{total_insertions} lines | Total Deletions: -{total_deletions} lines")
    
    # 若變更規模過大發出警告（例如大於 150 行）
    LIMIT = 150
    if total_insertions + total_deletions > LIMIT:
        print(f"[WARNING] Large code changes detected (> {LIMIT} lines).")
        print("Please review if you are rewriting unrelated methods, formatting code unnecessarily,")
        print("or introducing redundant comments. Ensure changes conform to Git Diff Minimization!")
        return False
    else:
        print("[SUCCESS] Change scale is within optimal limits (Git Diff Minimization compliant).")
        return True

if __name__ == "__main__":
    success = check_git_diff()
    sys.exit(0 if success else 1)
