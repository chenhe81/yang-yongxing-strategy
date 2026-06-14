#!/usr/bin/env python3
"""
杨永兴短线战法 - 环境安装脚本
自动检测系统环境，创建虚拟环境并安装依赖
"""

import subprocess
import sys
import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(SCRIPTS_DIR, "venv")


def run_cmd(cmd, cwd=None):
    """运行命令"""
    print(f"  执行: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 错误: {result.stderr}")
        return False
    return True


def main():
    print("=" * 50)
    print("杨永兴短线战法 - 环境安装")
    print("=" * 50)

    # 1. 检查 Python 版本
    print("\n1️⃣  检查 Python 版本...")
    py_version = sys.version_info
    print(f"  Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    if py_version < (3, 9):
        print("  ❌ 需要 Python 3.9+，请升级 Python")
        sys.exit(1)
    print("  ✅ Python 版本满足要求")

    # 2. 创建虚拟环境
    print("\n2️⃣  创建虚拟环境...")
    if os.path.exists(VENV_DIR):
        print("  虚拟环境已存在，跳过创建")
    else:
        if not run_cmd(f'"{sys.executable}" -m venv "{VENV_DIR}"'):
            print("  ❌ 创建虚拟环境失败")
            sys.exit(1)
        print("  ✅ 虚拟环境创建成功")

    # 3. 安装依赖
    print("\n3️⃣  安装依赖包...")
    pip_path = os.path.join(VENV_DIR, "bin", "pip")
    if os.name == "nt":  # Windows
        pip_path = os.path.join(VENV_DIR, "Scripts", "pip.exe")

    req_file = os.path.join(SCRIPTS_DIR, "requirements.txt")
    if not run_cmd(
        f'"{pip_path}" install -r "{req_file}" '
        f'-i https://mirrors.aliyun.com/pypi/simple/ '
        f'--trusted-host mirrors.aliyun.com'
    ):
        print("  ❌ 依赖安装失败")
        sys.exit(1)
    print("  ✅ 依赖安装成功")

    # 4. 验证
    print("\n4️⃣  验证安装...")
    python_path = os.path.join(VENV_DIR, "bin", "python")
    if os.name == "nt":
        python_path = os.path.join(VENV_DIR, "Scripts", "python.exe")

    result = subprocess.run(
        [python_path, "-c", "import akshare; print(f'akshare {akshare.__version__}')"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  ✅ {result.stdout.strip()} 安装验证通过")
    else:
        print(f"  ❌ 验证失败: {result.stderr}")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("✅ 安装完成！")
    print("=" * 50)
    print(f"\n使用方法：")
    print(f"  cd {SCRIPTS_DIR}")
    print(f'  ./venv/bin/python run.py scan          # 选股扫描')
    print(f'  ./venv/bin/python run.py sell-check     # 卖出检查')
    print(f'  ./venv/bin/python run.py portfolio      # 查看持仓')
    print(f'  ./venv/bin/python run.py add 000001 平安银行 15.50  # 添加持仓')


if __name__ == "__main__":
    main()
