import sys
import os
import shutil
import subprocess
import json
import py_compile

def check_encoding(file_path):
    # 偵測編碼並轉換為 UTF-8
    raw_data = None
    with open(file_path, "rb") as f:
        raw_data = f.read()

    decoded_content = None
    encoding_used = None

    # 嘗試用 UTF-8 解碼
    try:
        decoded_content = raw_data.decode("utf-8")
        encoding_used = "utf-8"
    except UnicodeDecodeError:
        pass

    # 若 UTF-8 失敗，嘗試用 CP950
    if decoded_content is None:
        try:
            decoded_content = raw_data.decode("cp950")
            encoding_used = "cp950"
        except UnicodeDecodeError:
            pass

    # 若都失敗，嘗試用 utf-8 with surrogateescape
    if decoded_content is None:
        try:
            decoded_content = raw_data.decode("utf-8", errors="surrogateescape")
            encoding_used = "utf-8_surrogate"
        except Exception:
            return False, None

    # 如果偵測到是 CP950，轉換為 UTF-8 並覆寫
    if encoding_used == "cp950":
        bak_path = file_path + ".bak"
        if not os.path.exists(bak_path):
            try:
                with open(bak_path, "wb") as bak_f:
                    bak_f.write(raw_data)
                print(f"[INFO] Backup created at: {bak_path}")
            except Exception as e:
                print(f"[WARNING] Failed to create backup: {e}")
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(decoded_content)
            print(f"[SUCCESS] Converted file encoding from CP950 to UTF-8: {file_path}")
        except Exception as e:
            print(f"[ERROR] Failed to write UTF-8 file: {e}")
            return False, None

    return True, decoded_content

def check_syntax(file_path, ext, content):
    if ext == ".py":
        try:
            py_compile.compile(file_path, doraise=True)
            print(f"[SUCCESS] Syntax check passed for Python file: {file_path}")
            return True
        except py_compile.PyCompileError as e:
            print("[SYNTAX_ERROR] Python syntax error:")
            err_msg = str(e).strip().replace(file_path, os.path.basename(file_path))
            print(err_msg)
            return False

    elif ext == ".json":
        try:
            json.loads(content)
            print(f"[SUCCESS] JSON format check passed: {file_path}")
            return True
        except json.JSONDecodeError as e:
            print(f"[SYNTAX_ERROR] JSON decoding failed at line {e.lineno}, col {e.colno}: {e.msg}")
            return False

    elif ext in [".js", ".ts", ".vue"]:
        # 嘗試尋找 npm/eslint 等工具
        eslint_bin = shutil.which("eslint")
        if eslint_bin:
            cmd = [eslint_bin, file_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if res.returncode == 0:
                print(f"[SUCCESS] ESLint check passed for JS/TS/Vue file: {file_path}")
                return True
            else:
                print("[SYNTAX_ERROR] ESLint check failed:")
                print(res.stdout)
                return False
        else:
            # 簡易括弧匹配與語法掃描
            print(f"[INFO] ESLint not found. Performing simple brace matching check: {file_path}")
            stack = []
            braces = {')': '(', '}': '{', ']': '['}
            for idx, char in enumerate(content):
                if char in braces.values():
                    stack.append((char, idx))
                elif char in braces.keys():
                    if not stack or stack[-1][0] != braces[char]:
                        print(f"[SYNTAX_ERROR] Unmatched bracket '{char}' detected in code.")
                        return False
                    stack.pop()
            if stack:
                print(f"[SYNTAX_ERROR] Unclosed bracket '{stack[-1][0]}' detected.")
                return False
            print("[SUCCESS] Simple brace matching passed.")
            return True

    elif ext == ".cs":
        dotnet_bin = shutil.which("dotnet")
        if dotnet_bin:
            # 尋找同級或上層的 csproj/sln，若無則對檔案本身做 dotnet build
            print(f"[INFO] dotnet build tool found. Running build check: {file_path}")
            cmd = [dotnet_bin, "build", "/v:q"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=os.path.dirname(file_path))
            if res.returncode == 0:
                print(f"[SUCCESS] Dotnet build passed.")
                return True
            else:
                print("[SYNTAX_ERROR] Dotnet build failed:")
                print(res.stdout)
                return False
        else:
            print(f"[WARNING] dotnet CLI not found. Skipped C# build compilation check for: {file_path}")
            return True

    else:
        print(f"[INFO] Unsupported file extension for compilation check: {ext}. Skipping syntax check.")
        return True

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_code.py <path_to_code_file>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"[ERROR] File not found: {file_path}")
        sys.exit(1)
        
    ext = os.path.splitext(file_path)[1].lower()
    
    # 1. 檢查並自動轉換編碼
    ok, content = check_encoding(file_path)
    if not ok:
        print("[ERROR] Encoding processing failed.")
        sys.exit(1)
        
    # 2. 檢查語法
    success = check_syntax(file_path, ext, content)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
