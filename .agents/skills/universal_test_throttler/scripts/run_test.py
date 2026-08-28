import sys
import os
import subprocess
import shutil

def run_pytest(test_file):
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", test_file]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
    
    if result.returncode == 0:
        print("[SUCCESS] All Python tests passed.")
        return True
    
    print("[FAIL] Python tests failed. Tracing failure details:")
    print("=" * 60)
    lines = result.stdout.split("\n")
    in_failure_section = False
    failure_log = []
    
    for line in lines:
        if line.startswith("==== FAILURES ===="):
            in_failure_section = True
            continue
        elif line.startswith("==== short test summary info ===="):
            in_failure_section = False
            failure_log.append("\nSummary:")
            continue
            
        if "[DEBUG_TRACE]" in line:
            failure_log.append(line.strip())
            continue

        if in_failure_section or line.startswith("FAILED "):
            if line.strip():
                failure_log.append(line)

    for log in failure_log:
        print(log)
    print("=" * 60)
    return False

def run_jest(test_file):
    # JS/TS tests with Jest
    jest_bin = shutil.which("jest") or shutil.which("npm")
    if not jest_bin:
        print("[ERROR] Neither jest nor npm was found in the system.")
        return False
        
    cmd = [jest_bin, "test", "--", "--silent", test_file] if "npm" in jest_bin else [jest_bin, "--silent", test_file]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
    
    if result.returncode == 0:
        print("[SUCCESS] All Jest tests passed.")
        return True
        
    print("[FAIL] Jest tests failed. Tracing failures:")
    print("=" * 60)
    # 僅過濾失敗堆疊 trace
    lines = result.stdout.split("\n")
    print_flag = False
    for line in lines:
        if "FAIL" in line or "●" in line or "[DEBUG_TRACE]" in line:
            print(line)
            print_flag = True
        elif print_flag and ("at " in line or "Error:" in line):
            print(line)
        elif line.startswith("Summary of all fails"):
            print_flag = False
    print("=" * 60)
    return False

def run_dotnet_test(test_file):
    # C# tests with dotnet test
    dotnet_bin = shutil.which("dotnet")
    if not dotnet_bin:
        print("[ERROR] dotnet CLI not found.")
        return False
        
    # dotnet test quiet mode
    cmd = [dotnet_bin, "test", "-v", "quiet", "/nologo"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore", cwd=os.path.dirname(test_file))
    
    if result.returncode == 0:
        print("[SUCCESS] All .NET tests passed.")
        return True
        
    print("[FAIL] .NET tests failed. Tracing failures:")
    print("=" * 60)
    # 過濾出失敗的測試方法和 Assert 訊息
    lines = result.stdout.split("\n")
    for line in lines:
        if "Failed" in line or "Error" in line or "Expected" in line or "[DEBUG_TRACE]" in line:
            print(line.strip())
    print("=" * 60)
    return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_test.py <path_to_test_file>")
        sys.exit(1)
        
    test_file = sys.argv[1]
    if not os.path.exists(test_file):
        print(f"[ERROR] Test file not found: {test_file}")
        sys.exit(1)
        
    ext = os.path.splitext(test_file)[1].lower()
    
    # 根據測試檔案後綴分流
    if ext == ".py":
        success = run_pytest(test_file)
    elif ext in [".js", ".ts"]:
        success = run_jest(test_file)
    elif ext == ".cs":
        success = run_dotnet_test(test_file)
    else:
        print(f"[WARNING] Unsupported test file extension: {ext}. Trying to run standard pytest...")
        success = run_pytest(test_file)
        
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
