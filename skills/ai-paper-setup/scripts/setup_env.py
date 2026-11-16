#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在正式库内创建虚拟环境并安装 skill 依赖；默认只预览命令。

不修改系统 Python、不安装全局包、不访问除包索引外的服务。依赖清单来自已
安装的 ai-paper-copilot skill，因此升级 skill 后应重新运行一次。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MIN_PYTHON = (3, 9)
REQUIREMENTS_REL = Path(".agents") / "skills" / "ai-paper-copilot" / "requirements.txt"


class EnvError(Exception):
    """带稳定错误码的环境准备失败。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def venv_python(venv):
    """返回虚拟环境解释器路径；Windows 与 POSIX 均可用。"""
    return Path(venv) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def check_python(python):
    """只读取版本号，不执行安装。"""
    try:
        output = subprocess.run([python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvError("PYTHON_NOT_FOUND", "无法运行 Python 解释器：{}".format(exc))
    match = re.fullmatch(r"(\d+)\.(\d+)", output.stdout.strip())
    if output.returncode != 0 or not match:
        raise EnvError("PYTHON_INVALID", "无法识别 Python 版本：{}".format(python))
    version = (int(match.group(1)), int(match.group(2)))
    if version < MIN_PYTHON:
        raise EnvError("PYTHON_TOO_OLD", "需要 Python 3.9 或更新版本，当前 {}.{}".format(*version))
    return "{}.{}".format(*version)


def commands_for(vault, python):
    """构造可预览、可复现的命令列表，不包含任何凭据。"""
    vault = Path(vault)
    venv = vault / ".venv"
    target_python = venv_python(venv)
    requirements = vault / REQUIREMENTS_REL
    return venv, [
        [python, "-m", "venv", str(venv)],
        [str(target_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
        [str(target_python), "-c", "import yaml; print(yaml.__version__)"],
    ]


def plan(vault, python):
    """只读预览：报告解释器、环境位置、依赖清单与将要执行的命令。"""
    vault = Path(vault).expanduser()
    if not vault.is_dir():
        raise EnvError("VAULT_NOT_FOUND", "正式库目录不存在：{}".format(vault))
    requirements = vault / REQUIREMENTS_REL
    if not requirements.is_file():
        raise EnvError("REQUIREMENTS_MISSING", "未找到依赖清单：{}".format(requirements))
    version = check_python(python)
    venv, commands = commands_for(vault, python)
    exists = venv.is_dir()
    return {"status": "preview", "vault": str(vault.resolve()), "python": python,
            "python_version": version, "venv": str(venv), "requirements": str(requirements),
            "venv_exists": exists, "venv_usable": venv_python(venv).is_file(),
            "commands": commands,
            "message": "预览不执行命令；确认后用 --apply 创建环境并安装依赖。"}


def apply_env(vault, python, recreate=False):
    """创建或复用虚拟环境，安装依赖并验证 yaml 可导入。"""
    result = plan(vault, python)
    vault, venv = Path(result["vault"]), Path(result["venv"])
    target_python = venv_python(venv)
    if venv.is_dir() and not target_python.is_file():
        if not recreate:
            raise EnvError("VENV_BROKEN", "虚拟环境不完整：{}；确认后加 --recreate 重建。".format(venv))
        backup = venv.with_name(".venv.bak-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.move(str(venv), str(backup))
        result["recreated_from"] = str(backup)
    if venv.is_dir() and target_python.is_file():
        result["status"] = "reused"
        commands = commands_for(vault, python)[1][1:]
    else:
        result["status"] = "created"
        commands = commands_for(vault, python)[1]
        try:
            subprocess.run(commands[0], check=True, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.CalledProcessError, subprocess.SubprocessError) as exc:
            raise EnvError("VENV_FAILED", "创建虚拟环境失败：{}".format(exc))
        commands = commands[1:]
    for command in commands:
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.CalledProcessError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise EnvError("PIP_FAILED", "安装或验证依赖失败：{}".format(detail.strip()[:400]))
    result["yaml_version"] = getattr(completed, "stdout", "").strip()
    result["verified"] = True
    result["message"] = "依赖已安装并通过 import yaml 验证；后续命令使用该解释器。"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="在正式库内创建虚拟环境并安装项目依赖")
    parser.add_argument("--vault", required=True, help="正式库绝对路径")
    parser.add_argument("--python", default=sys.executable, help="用于创建环境的 Python 解释器")
    parser.add_argument("--apply", action="store_true", help="实际创建并安装；默认只预览")
    parser.add_argument("--recreate", action="store_true", help="备份并重建不完整的 .venv")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)
    try:
        result = apply_env(args.vault, args.python, args.recreate) if args.apply else plan(args.vault, args.python)
    except EnvError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "message": exc.message},
                         ensure_ascii=False, indent=2))
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("解释器：{}（Python {}）".format(result["python"], result["python_version"]))
        print("环境：{}".format(result["venv"]))
        print("依赖：{}".format(result["requirements"]))
        for command in result["commands"] if result["status"] == "preview" else []:
            print("  " + " ".join(command))
        print(result["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
