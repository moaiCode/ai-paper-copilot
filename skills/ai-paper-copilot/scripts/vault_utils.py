#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享的只读路径、YAML 和笔记分区工具。

本模块不在导入时访问网络或写文件。所有路径均从调用者指定的 Vault
解析；拒绝借助绝对路径、上级目录或符号链接逃出 Vault 的元数据路径。
"""

import json
import re
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise ImportError("缺少 PyYAML；请在套件虚拟环境中安装 requirements.txt") from exc

KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
SCOPE_RE = re.compile(r"^(?:users/(?:0|[1-9][0-9]*)|groups/[1-9][0-9]*)$")
DEFAULT_PATHS = {
    "knowledge": "01knowledge", "notes": "02vault", "fulltext": "03fulltext",
    "projects": "04projects", "writing": "05writing", "inbox": "06inbox",
    "templates": "templates",
}
AI_START, AI_END = "<!-- AI:START -->", "<!-- AI:END -->"
HUMAN_START, HUMAN_END = "<!-- HUMAN:START -->", "<!-- HUMAN:END -->"


class UniqueLoader(yaml.SafeLoader):
    """保留 safe_load 的安全性，并拒绝会被静默覆盖的重复 YAML 键。"""


def _construct_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int, float, bool, type(None))):
            raise ValueError("YAML 映射键必须是标量")
        if key in result:
            raise ValueError("YAML 字段重复：{}".format(key))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def read_note(text):
    """返回元信息、正文和原正文起点；只接受顶端完整的 YAML frontmatter。"""
    match = re.match(r"\A---\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ValueError("缺少或未闭合 YAML frontmatter")
    try:
        metadata = yaml.load(match.group(1), Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError("YAML 无法解析：{}".format(exc)) from exc
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter 必须为映射")
    return metadata, text[match.end():], match.end()


def read_profile(vault):
    """缺省配置仍可用于检查旧库；存在的配置必须是合法对象。"""
    path = Path(vault) / "research-profile.json"
    if not path.exists():
        return {"paths": DEFAULT_PATHS.copy()}
    profile = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("research-profile.json 必须为 JSON 对象")
    paths = profile.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("配置 paths 必须为对象")
    profile["paths"] = dict(DEFAULT_PATHS, **paths)
    return profile


def inside_path(vault, relative):
    """路径必须以 Vault 为根，解析符号链接后也不能逃逸。"""
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("路径必须为非空字符串")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("只允许 Vault 内的相对路径：{}".format(relative))
    root = Path(vault).resolve()
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ValueError("路径通过符号链接越出 Vault：{}".format(relative))
    return path


def section_span(body, start, end):
    """返回分区内容边界；重复、缺失、反序标记均不可安全更新。"""
    if body.count(start) != 1 or body.count(end) != 1:
        raise ValueError("分区标记必须各出现一次：{} / {}".format(start, end))
    begin = body.index(start) + len(start)
    finish = body.index(end)
    if begin > finish:
        raise ValueError("分区结束标记在开始标记之前")
    return begin, finish


def note_regions(body):
    """同时验证 AI 和人工区域互不重叠，避免更新跨越人工内容。"""
    ai = section_span(body, AI_START, AI_END)
    human = section_span(body, HUMAN_START, HUMAN_END)
    if not (ai[1] < human[0] or human[1] < ai[0]):
        raise ValueError("AI 与 HUMAN 分区不能交叉或嵌套")
    return ai, human
