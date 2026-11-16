#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线准备新的正式科研 Vault；默认预览，--apply 才创建文件。

只复制已预检的模板和两个 skill，不安装依赖或插件，不启动应用，不访问网络，
不探测真实 Zotero，不接收凭据。已有 Vault 必须走增量配置流程，不能覆盖合并。
退出码：0=预览/文件准备成功，1=内容冲突或安全预检失败，2=参数或资源错误。
"""

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


STATE_NAME = "setup-state.json"
SKILL_NAMES = ("ai-paper-copilot", "ai-paper-setup")
IGNORED_NAMES = {".DS_Store", "__pycache__", ".venv", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
REQUIRED_PATHS = {"knowledge", "notes", "fulltext", "projects", "writing", "inbox", "templates"}
PENDING_CHECKS = ("python_dependencies", "obsidian", "zotero_plugins", "agent_runtime", "mineru", "connections", "sample_validation")
PLACEHOLDER_RE = re.compile(r"[<>`$]|\{\{|\}\}|(?:^|/)(?:\.\.\.|YOUR_VAULT|VAULT_PATH|REPLACE_ME)(?:/|$)|/path/to(?:/|$)|/absolute/path(?:/|$)|用户确认的正式库绝对路径|请填写正式库绝对路径|正式Vault绝对路径", re.I)


class SetupError(Exception):
    def __init__(self, code, message, exit_code=1):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse 默认会回显未知参数和值；凭据误传时也不能把它们再次打印出来。
        raise SetupError("ARGUMENTS", "参数不合法；请用 --help 查看接口。本脚本不接受 Token、密钥或密码参数。", 2)


def inside(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def exists_any(path):
    """Path.exists() 不识别断开的符号链接，目标冲突检查必须使用 lexists。"""
    return os.path.lexists(str(path))


def no_symlink_segments(path):
    """检查词法路径每一段，再进行任何创建；不通过 resolve 隐藏符号链接。"""
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SetupError("SYMLINK_PATH", "路径包含符号链接段，未读取或写入该路径。")
        if exists_any(cursor) and cursor != path and not cursor.is_dir():
            raise SetupError("PARENT_NOT_DIRECTORY", "路径的上级位置不是目录。", 2)


def canonical_system_alias(path):
    """仅认可 macOS 确实存在的两个系统别名，不放宽普通用户 symlink 检查。

    macOS 的临时目录常以 /tmp 或 /var 表示，而实际路径位于 /private。
    只有顶层链接的目标与已知系统位置完全一致时才替换；之后仍逐段检查。
    """
    if sys.platform != "darwin" or len(path.parts) < 2:
        return path
    alias = "/" + path.parts[1]
    expected = {"/tmp": "/private/tmp", "/var": "/private/var"}.get(alias)
    if expected is not None and Path(alias).is_symlink():
        link = os.readlink(alias)
        if link in {expected, expected.lstrip("/")}:
            return Path(expected).joinpath(*path.parts[2:])
    return path


def target_path(raw, repo):
    if not isinstance(raw, str) or not raw.strip() or PLACEHOLDER_RE.search(raw):
        raise SetupError("TARGET_PLACEHOLDER", "请提供已经替换占位符的正式 Vault 绝对路径。")
    if any(ord(char) < 32 for char in raw) or "\\" in raw:
        raise SetupError("TARGET_PATH", "目标路径包含控制字符或不明确的路径分隔符。")
    expanded = os.path.expanduser(raw)
    if not Path(expanded).is_absolute():
        raise SetupError("TARGET_ABSOLUTE", "--vault 必须是绝对路径，可使用 ~ 表示当前用户目录。", 2)
    if any(part in {".", ".."} for part in expanded.split("/")):
        raise SetupError("TARGET_TRAVERSAL", "目标路径不能包含 . 或 .. 路径段。")
    target = canonical_system_alias(Path(expanded))
    if inside(target, repo) or inside(repo, target):
        raise SetupError("TARGET_IN_SOURCE", "正式 Vault 不能位于套件内部，也不能覆盖套件或它的上级目录。")
    if exists_any(target):
        raise SetupError("TARGET_EXISTS", "目标已存在（包括空目录或断开的符号链接）；请使用已有库的增量配置流程。")
    no_symlink_segments(target)
    return target


def valid_local_url(value):
    # 只保存服务器位置。查询、片段和 user:password@ 都可能携带凭据，禁止写入配置。
    if not isinstance(value, str) or not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise SetupError("LOCAL_URL", "自托管地址应为无凭据、无查询和无片段的 HTTP(S) 地址。", 2)
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or (port is not None and not 0 < port < 65536)):
            raise ValueError("invalid address")
    except ValueError:
        raise SetupError("LOCAL_URL", "自托管地址应为无凭据、无查询和无片段的 HTTP(S) 地址。", 2)
    return value.rstrip("/")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ignored(relative):
    return (any(part in IGNORED_NAMES for part in relative.parts)
            or relative.suffix.lower() in {".pyc", ".pyo"}
            or any((part == ".env" or part.startswith(".env.")) and part != ".env.example" for part in relative.parts))


def inspect_tree(source):
    """完整预检源树，保留 dotfile 和空目录；本地状态仅排除复制，不静默放过坏链接。

    在预览时即读取所有将复制文件的指纹；正式复制后再次比较，防止源文件在
    构建过程中变化而产生不一致安装。没有调用 Git 或其他 shell 命令。
    """
    if source.is_symlink():
        raise SetupError("SOURCE_SYMLINK", "模板或 skill 根目录不能是符号链接。")
    if not source.is_dir():
        raise SetupError("SOURCE_MISSING", "套件缺少完整的 ResearchVault 或 skill 源目录。", 2)
    directories, files = [], []
    for current, dirs, names in os.walk(str(source), followlinks=False):
        for name in sorted(dirs + names):
            path = Path(current) / name
            relative = path.relative_to(source)
            if path.is_symlink():
                raise SetupError("SOURCE_SYMLINK", "模板或 skill 源树包含符号链接。")
            mode = path.stat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise SetupError("SOURCE_SPECIAL_FILE", "模板或 skill 源树包含非常规文件。")
            if any(ord(char) < 32 for char in relative.as_posix()) or "\\" in relative.as_posix():
                raise SetupError("SOURCE_PATH", "源文件名包含不明确的路径字符。")
            if ignored(relative):
                continue
            if stat.S_ISDIR(mode):
                directories.append(relative)
            else:
                files.append({"path": relative.as_posix(), "sha256": file_hash(path)})
    return {"directories": sorted(directories), "files": sorted(files, key=lambda item: item["path"])}


def read_json_object(path, label):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise SetupError("SOURCE_PROFILE", label + "不是有效 JSON。")
    if not isinstance(data, dict):
        raise SetupError("SOURCE_PROFILE", label + "必须是 JSON 对象。")
    return data


def non_sensitive_profile(profile):
    """模板配置不应夹带真实连接或凭据；这里只检查配置字段，不扫描论文或代码正文。"""
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized in {"token", "api_key", "apikey", "password", "secret", "authorization", "cookie", "credentials"} and child:
                    raise SetupError("SOURCE_CREDENTIALS", "模板配置含有凭据字段，不能复制到新库。")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(profile)
    if not isinstance(profile.get("zotero"), dict) or not isinstance(profile.get("mineru"), dict):
        raise SetupError("SOURCE_PROFILE", "模板配置缺少 Zotero 或 MinerU 配置对象。")
    if profile["zotero"].get("data_dir") is not None or profile["zotero"].get("library_scope") != "users/0":
        raise SetupError("SOURCE_BOUND", "模板已绑定真实数据位置或库身份，请恢复未绑定模板后使用。")
    if profile["zotero"].get("api_base_url"):
        valid_local_url(profile["zotero"]["api_base_url"])
    mineru = profile["mineru"]
    # MinerU 的后端、自动解析和上传范围属于部署决定，模板不能偷偷继承
    # 维护者机器上的云端/自托管配置；安装时只接受命令行重新给出的选择。
    if (mineru.get("backend") is not None
            or mineru.get("automatic_parse") is not False
            or mineru.get("upload_policy") != "ask_before_upload"):
        raise SetupError("SOURCE_BOUND", "模板已绑定 MinerU 后端、自动解析或上传范围，请恢复未部署模板后使用。")
    if mineru.get("local_url"):
        valid_local_url(mineru["local_url"])
    paths = profile.get("paths")
    if not isinstance(paths, dict) or not REQUIRED_PATHS.issubset(paths):
        raise SetupError("SOURCE_PROFILE", "模板配置没有完整的七类资料路径。")
    for value in paths.values():
        path_parts = Path(value).parts if isinstance(value, str) else ()
        if (not isinstance(value, str) or not value or Path(value).is_absolute()
                or any(part in {".", ".."} for part in path_parts) or "\\" in value):
            raise SetupError("SOURCE_PROFILE", "模板资料路径必须是安全的相对路径。")


def source_commit(repo):
    """只读 Git HEAD/refs；兼容普通 checkout 和 .git 文件，不执行 Git 命令。

    HEAD 只提供来源版本线索，不证明当前工作区无修改；另记实际复制选择集摘要。
    """
    try:
        git = repo / ".git"
        if git.is_file():
            pointer = git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir: "):
                return "unknown"
            git = (repo / pointer[8:]).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", head):
            return head
        if not head.startswith("ref: refs/"):
            return "unknown"
        reference = head[5:]
        if ".." in Path(reference).parts or not re.fullmatch(r"refs/[A-Za-z0-9_./-]+", reference):
            return "unknown"
        ref_file = git / reference
        if ref_file.is_file():
            commit = ref_file.read_text(encoding="utf-8").strip()
        else:
            commit = next((line.split(" ", 1)[0] for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines()
                           if line.endswith(" " + reference) and not line.startswith(("#", "^"))), "unknown")
        return commit if re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", commit) else "unknown"
    except (OSError, UnicodeError, RuntimeError):
        return "unknown"


def preflight(args):
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise SetupError("REPO_MISSING", "套件目录不存在；已部署的副本需要显式提供原始套件 --repo。", 2)
    target = target_path(args.vault, repo)
    local_url = valid_local_url(args.local_url)
    template = repo / "ResearchVault"
    for reserved in (".obsidian", ".agents", ".git", STATE_NAME):
        if exists_any(template / reserved):
            raise SetupError("SOURCE_NOT_INITIAL", "模板包含应用、安装或版本管理状态，请恢复未部署的初始模板。")
    sources = {"template": template, **{name: repo / "skills" / name for name in SKILL_NAMES}}
    inventories = {name: inspect_tree(path) for name, path in sources.items()}
    if not (template / "AGENTS.md").is_file() or not (template / "research-profile.json").is_file():
        raise SetupError("SOURCE_INCOMPLETE", "Vault 模板缺少 AGENTS.md 或 research-profile.json。", 2)
    for name in SKILL_NAMES:
        if not (sources[name] / "SKILL.md").is_file():
            raise SetupError("SOURCE_INCOMPLETE", "skill 源目录缺少 SKILL.md：" + name, 2)
        if exists_any(template / ".agents" / "skills" / name):
            raise SetupError("SOURCE_SKILL_CONFLICT", "模板已含同名安装副本，请恢复初始模板。")
    profile = read_json_object(template / "research-profile.json", "模板 research-profile.json")
    non_sensitive_profile(profile)
    for relative in profile["paths"].values():
        if not (template / relative).is_dir():
            raise SetupError("SOURCE_INCOMPLETE", "模板缺少配置要求的资料目录。", 2)
    # 原文、项目、写作与收件箱应为空壳，正式文献只允许 _index 导航。
    # 根据 profile 映射检查，避免自定义目录名绕过未部署模板的约束。
    for row in inventories["template"]["files"]:
        file = Path(row["path"])
        for kind in ("fulltext", "projects", "writing", "inbox", "notes"):
            root = Path(profile["paths"][kind])
            if not inside(file, root):
                continue
            relative = file.relative_to(root)
            allowed = file.name == ".gitkeep"
            if kind == "notes" and relative.parts and relative.parts[0] == "_index" and file.suffix.lower() == ".md":
                allowed = True
            if not allowed:
                raise SetupError("SOURCE_NOT_INITIAL", "模板的正式资料目录含有阅读或运行内容，不能当作初始库复制。")
    # 两份模板同时复制，预检必须阻止源模板本身已经漂移的情况。
    source_templates = {row["path"]: row["sha256"] for row in inventories["ai-paper-copilot"]["files"] if row["path"].startswith("templates/")}
    vault_template_root = profile["paths"]["templates"].rstrip("/") + "/"
    copied_templates = {"templates/" + row["path"][len(vault_template_root):]: row["sha256"]
                        for row in inventories["template"]["files"] if row["path"].startswith(vault_template_root)}
    if not source_templates or source_templates != copied_templates:
        raise SetupError("SOURCE_TEMPLATE_MISMATCH", "skill 模板与 Vault 模板的文件集合或内容不一致。")
    profile["mineru"].update(backend=None if args.mineru_backend == "unconfigured" else args.mineru_backend,
                              upload_policy=args.upload_policy, automatic_parse=False, local_url=local_url)
    digest = hashlib.sha256(json.dumps({name: value["files"] for name, value in inventories.items()}, sort_keys=True).encode("utf-8")).hexdigest()
    return {"repo": repo, "target": target, "sources": sources, "inventories": inventories,
            "profile": profile, "source_commit": source_commit(repo), "snapshot_sha256": digest}


def installation_paths(target):
    """返回部署后的稳定文件位置，客户端无关，不生成任何插件专属入口。"""
    return {"vault": str(target), "agents": str(target / "AGENTS.md"), "profile": str(target / "research-profile.json"),
            "copilot_skill": str(target / ".agents/skills/ai-paper-copilot/SKILL.md"),
            "setup_skill": str(target / ".agents/skills/ai-paper-setup/SKILL.md"),
            "setup_state": str(target / STATE_NAME)}


def copy_selected(source, destination, inventory):
    destination.mkdir(parents=True, exist_ok=True)
    for relative in inventory["directories"]:
        (destination / relative).mkdir(parents=True, exist_ok=True)
    for row in inventory["files"]:
        original, copied = source / row["path"], destination / row["path"]
        no_symlink_segments(original)
        if not original.is_file() or not stat.S_ISREG(original.stat().st_mode):
            raise SetupError("SOURCE_CHANGED", "源文件在预检后变成非常规文件，已停止。")
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(original), str(copied))
        if file_hash(copied) != row["sha256"]:
            raise SetupError("SOURCE_CHANGED", "源文件在预检后发生变化，已停止，目标尚未发布。")


def publish_noreplace(stage, target):
    """使用系统提供的排他原子 rename，绝不以普通 rename 替代。

    Linux 的 RENAME_NOREPLACE=1 来自内核 uapi/linux/fs.h；macOS 的
    RENAME_EXCL=4 来自 Apple xnu/bsd/sys/stdio.h。两者都在目标并发出现时
    拒绝覆盖。底层文件系统不支持时保守失败，阶段目录仍由调用者回收。
    """
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        if function is None:
            raise SetupError("PUBLISH_UNSUPPORTED", "系统缺少无覆盖原子目录发布接口，目标未创建。", 2)
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(-100, os.fsencode(stage), -100, os.fsencode(target), 1)
    elif sys.platform == "darwin":
        function = getattr(library, "renamex_np", None)
        if function is None:
            raise SetupError("PUBLISH_UNSUPPORTED", "系统缺少无覆盖原子目录发布接口，目标未创建。", 2)
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(os.fsencode(stage), os.fsencode(target), 4)
    else:
        raise SetupError("PUBLISH_UNSUPPORTED", "当前仅支持具有无覆盖原子目录发布能力的 macOS/Linux；未使用覆盖式替代方案。", 2)
    if result != 0:
        code = ctypes.get_errno()
        if code in {errno.EEXIST, errno.ENOTEMPTY}:
            raise SetupError("TARGET_EXISTS", "发布前目标被其他操作创建，已保留该目标；请走已有库增量配置流程。")
        if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise SetupError("PUBLISH_UNSUPPORTED", "文件系统不支持无覆盖原子目录发布，目标未创建。", 2)
        raise OSError(code, os.strerror(code))


def create_missing_parents(parent, created=None):
    # 由调用者传入列表时逐项登记；中途 mkdir 失败也能回收此前由本次创建的空目录。
    created = [] if created is None else created
    missing = []
    cursor = parent
    while not exists_any(cursor):
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        no_symlink_segments(directory)
        try:
            directory.mkdir()
            info = directory.stat()
            created.append((directory, info.st_dev, info.st_ino))
        except FileExistsError:
            no_symlink_segments(directory)
            if not directory.is_dir():
                raise SetupError("PARENT_NOT_DIRECTORY", "目标上级位置在准备时被其他文件占用。", 2)
    return created


def prepare(args):
    checked = preflight(args)
    target, paths = checked["target"], installation_paths(checked["target"])
    remaining = [name for name in PENDING_CHECKS]
    planned = ["复制完整初始 Vault（保留模板与 dotfile）", "安装 ai-paper-copilot 和 ai-paper-setup 的独立文件副本",
               "记录解析后端与上传策略，关闭自动解析", "生成 files_prepared 状态，后续逐项实测"]
    result = {"status": "preview", "paths": paths, "planned_steps": planned, "remaining_steps": remaining,
              "decisions": {"mineru_backend": args.mineru_backend, "upload_policy": args.upload_policy,
                            "automatic_parse": False, "automatic_upload": False, "local_url": checked["profile"]["mineru"]["local_url"]},
              "message": "预览未创建文件；--apply 仅准备离线文件，不代表环境安装或连接已经完成。"}
    if not args.apply:
        return result
    parents, stage, stage_identity, published = [], None, None, False
    try:
        create_missing_parents(target.parent, parents)
        no_symlink_segments(target)
        if exists_any(target):
            raise SetupError("TARGET_EXISTS", "目标已由其他操作创建，未覆盖。")
        stage = Path(tempfile.mkdtemp(prefix=".ai-paper-setup-", dir=str(target.parent)))
        info = stage.stat()
        stage_identity = (info.st_dev, info.st_ino)
        copy_selected(checked["sources"]["template"], stage, checked["inventories"]["template"])
        for name in SKILL_NAMES:
            copy_selected(checked["sources"][name], stage / ".agents" / "skills" / name, checked["inventories"][name])
        (stage / "research-profile.json").write_text(json.dumps(checked["profile"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        checks = {name: "pending" for name in PENDING_CHECKS}
        checks["local_files"] = "verified"
        if args.mineru_backend == "unconfigured":
            checks["mineru"] = "not_selected"
        state = {"schema_version": 1, "stage": "files_prepared", "created_at": datetime.now(timezone.utc).isoformat(),
                 "source": {"repo": str(checked["repo"]), "commit": checked["source_commit"],
                            "snapshot_sha256": checked["snapshot_sha256"], "commit_matches_snapshot": "not_checked"},
                 "decisions": {"mineru_backend": args.mineru_backend, "upload_policy": args.upload_policy,
                               "automatic_parse": False, "automatic_upload": False, "local_url": checked["profile"]["mineru"]["local_url"]},
                 "paths": paths, "checks": checks,
                 "note": "只完成离线文件准备；目录存在不等于依赖、插件、服务、连接或论文样本已经安装并验证。"}
        (stage / STATE_NAME).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # 发布前再次检查父路径；目标是否出现最终由内核的排他 rename 原子裁决。
        no_symlink_segments(target.parent)
        publish_noreplace(stage, target)
        published = True
        stage = None
        result.update(status="created", stage="files_prepared", checks=checks,
                      message="已准备正式 Vault 和两个 skill 的本地文件；后续依赖、应用、插件、连接及样本验证仍待完成。")
        return result
    finally:
        # 仅回收本次 mkdtemp 得到的同一目录；不递归删除目标或并发创建的他人目录。
        if stage is not None and exists_any(stage) and not stage.is_symlink():
            info = stage.stat()
            if (info.st_dev, info.st_ino) == stage_identity:
                shutil.rmtree(str(stage))
        if not published:
            for directory, device, inode in reversed(parents):
                try:
                    info = directory.stat()
                    if not directory.is_symlink() and (info.st_dev, info.st_ino) == (device, inode):
                        directory.rmdir()
                except OSError:
                    # 并发写入使目录非空时保留它，不擅自删除他人的文件。
                    pass


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    wants_json = "--json" in arguments
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, help="用户明确指定的新正式 Vault 绝对路径，可使用 ~")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]), help="原始套件仓库路径")
    parser.add_argument("--mineru-backend", choices=("cloud", "local", "unconfigured"), default="unconfigured")
    parser.add_argument("--upload-policy", choices=("ask_before_upload", "public_papers_only"), default="ask_before_upload")
    parser.add_argument("--local-url", default="http://127.0.0.1:8000", help="不带凭据的本地或自托管 MinerU HTTP(S) 地址")
    parser.add_argument("--apply", action="store_true", help="执行离线文件准备；默认只预览")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    try:
        args = parser.parse_args(arguments)
        result, code = prepare(args), 0
    except SetupError as exc:
        code = exc.exit_code
        result = {"status": "error", "paths": {}, "planned_steps": [], "remaining_steps": list(PENDING_CHECKS),
                  "issues": [{"code": exc.code, "message": str(exc)}]}
    except (OSError, RuntimeError) as exc:
        code = 2
        result = {"status": "error", "paths": {}, "planned_steps": [], "remaining_steps": list(PENDING_CHECKS),
                  "issues": [{"code": "IO_ERROR", "message": str(exc)}]}
    if wants_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("状态：" + result["status"])
        if result.get("message"):
            print(result["message"])
        for step in result["planned_steps"]:
            print("- " + step)
        for row in result.get("issues", []):
            print("[" + row["code"] + "] " + row["message"])
        if result["paths"]:
            print("正式 Vault：" + result["paths"]["vault"])
            print("仍待配置与验证：" + ", ".join(result["remaining_steps"]))
    return code


if __name__ == "__main__":
    sys.exit(main())
