#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读检查科研 Vault 的结构、身份、引用接口及归档完整性。

结构通过不等于原文或科学结论正确。退出码：0=没有结构 ERROR，
1=发现结构错误，2=参数、路径或依赖错误。可重复 --path 做定向检查。
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEPENDENCY_ERROR = None
try:
    from vault_utils import KEY_RE, SCOPE_RE, inside_path, note_regions, read_note, read_profile
except ImportError as exc:
    # 让缺依赖的 --json 调用也能获得明确结果，不倾倒 traceback。
    DEPENDENCY_ERROR = str(exc)

MATERIAL_STATUSES = {"abstract", "pdf", "parsed"}
REVIEW_STATUSES = {"unreviewed", "partial", "reviewed"}
VERIFICATIONS = {"unverified", "agent_verified", "human_verified"}
NAVIGATION_NAMES = {"index.md", "log.md", "README.md", "说明.md"}
PLACEHOLDER = re.compile(r"\{\{[^}\n]+\}\}|<collection>|<短标题>|在此粘贴")
LEGACY_ITEM = re.compile(r"^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?(主要发现|原文引用)[ \t]*(\d+)(?:\*\*)?[ \t]*[：:][ \t]*(.*)$", re.M)
CITE_PATTERN = re.compile(r"\\(?:cite|citet|citep|citeauthor|citeyear|parencite|textcite|autocite|footcite)\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}")


class Checker:
    """汇总各类只读检查，单个坏笔记不会中断整库诊断。"""

    def __init__(self, vault, profile, selected=False):
        self.vault, self.profile, self.selected = vault, profile, selected
        self.paths = {name: inside_path(vault, value) for name, value in profile["paths"].items()}
        if any(path == vault for path in self.paths.values()):
            raise ValueError("资料子目录不能直接配置为 Vault 根目录")
        self.issues, self.identities, self.citekeys = [], {}, {}
        self.notes, self.documents = 0, 0
        self.checked_archives = set()
        self.resource_index = self.build_resource_index()

    @staticmethod
    def is_within(path, directory):
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def add(self, level, code, path, message):
        relative = Path(path).relative_to(self.vault).as_posix() if self.is_within(Path(path), self.vault) else str(path)
        self.issues.append({"level": level, "code": code, "path": relative, "message": message})

    def build_resource_index(self):
        """仅索引文件名解析 wikilink，不读取全文资料包正文。"""
        resources = []
        for directory, dirs, names in os.walk(str(self.vault), followlinks=False):
            dirs[:] = [name for name in dirs if name not in {".git", ".venv", ".obsidian", ".trash", "__pycache__"}]
            for name in names:
                path = Path(directory) / name
                try:
                    if self.is_within(path.resolve(), self.vault):
                        resources.append(path)
                except (OSError, RuntimeError):
                    # 符号链接环等坏路径交给文档检查报告，不让索引阶段崩溃。
                    continue
        return resources

    def check_sections(self, path, body, required=False):
        if required or "<!-- AI:" in body or "<!-- HUMAN:" in body:
            try:
                ai, _ = note_regions(body)
                if required and not body[ai[0]:ai[1]].strip():
                    self.add("ERROR", "AI_SECTION_EMPTY", path, "正式文献笔记的 AI 内容区为空")
            except ValueError as exc:
                self.add("ERROR", "NOTE_REGIONS", path, str(exc))

    def check_claims(self, path, metadata):
        claims = metadata.get("claims")
        if claims is None or claims == []:
            self.add("WARN", "CLAIMS_MISSING", path, "未记录结构化核心主张；不能将结构检查当成阅读核验")
            if metadata.get("review_status") == "reviewed":
                self.add("ERROR", "REVIEW_WITHOUT_CLAIMS", path, "reviewed 笔记没有可核查的核心主张记录")
            return
        if not isinstance(claims, list):
            self.add("ERROR", "CLAIMS_TYPE", path, "claims 必须为列表")
            return
        seen = set()
        for number, claim in enumerate(claims, 1):
            if not isinstance(claim, dict):
                self.add("ERROR", "CLAIM_TYPE", path, f"第 {number} 条 claim 必须为对象")
                continue
            claim_id = claim.get("id")
            label = claim_id if isinstance(claim_id, str) and claim_id.strip() else str(number)
            if not isinstance(claim_id, str) or not claim_id.strip() or re.search(r"\s", claim_id):
                self.add("ERROR", "CLAIM_ID", path, f"第 {number} 条 claim 的 id 缺失或含空白")
            elif claim_id in seen:
                self.add("ERROR", "CLAIM_DUPLICATE", path, f"claim id 重复：{claim_id}")
            else:
                seen.add(claim_id)
            if not isinstance(claim.get("text"), str) or not claim["text"].strip():
                self.add("ERROR", "CLAIM_EMPTY", path, f"主张 {label} 的 text 为空")
            verification = claim.get("verification")
            if not isinstance(verification, str) or verification not in VERIFICATIONS:
                self.add("ERROR", "CLAIM_VERIFICATION", path, f"主张 {label} 的 verification 无效")
            source = claim.get("source")
            if source is not None and not isinstance(source, str):
                self.add("ERROR", "CLAIM_SOURCE_TYPE", path, f"主张 {label} 的 source 应为字符串")
            if isinstance(verification, str) and verification in {"agent_verified", "human_verified"}:
                if not isinstance(source, str) or not source.strip() or re.fullmatch(r"(?:未核验|未定位|待核查|待定位|unknown|pending)", source.strip(), re.I):
                    self.add("ERROR", "VERIFIED_WITHOUT_SOURCE", path, f"已核验主张 {label} 缺少明确来源位置")
            if "quote" in claim and (not isinstance(claim["quote"], str) or not claim["quote"].strip()):
                self.add("ERROR", "QUOTE_EMPTY", path, f"主张 {label} 显式设置了空 quote；没有摘录时应省略该字段")
            if metadata.get("review_status") == "reviewed" and verification != "human_verified":
                self.add("ERROR", "REVIEW_STATUS_CONFLICT", path, f"reviewed 笔记的主张 {label} 尚未 human_verified")

    def check_legacy_pairs(self, path, body):
        """旧编号相等不代表内容存在；显式识别旧版空结论和空引用。"""
        matches = list(LEGACY_ITEM.finditer(body))
        seen = {"主要发现": [], "原文引用": []}
        for index, match in enumerate(matches):
            kind, number, inline = match.groups()
            seen[kind].append(number)
            tail = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
            tail = re.split(r"\n[ \t]*(?:#{1,6}\s|[-*]\s)", tail, maxsplit=1)[0]
            payload = re.sub(r"<!--.*?-->", "", inline + "\n" + tail, flags=re.S)
            if not payload.strip(" \t\r\n>*_\"'`“”‘’"):
                self.add("ERROR", "LEGACY_EMPTY_EVIDENCE", path, f"旧版 {kind} {number} 没有实际内容")
        if matches and set(seen["主要发现"]) != set(seen["原文引用"]):
            self.add("ERROR", "LEGACY_EVIDENCE_PAIR", path, "旧版主要发现与原文引用编号不匹配")

    def literature(self, path, metadata, body):
        self.notes += 1
        for field in ("library_scope", "zotero_key", "citekey", "material_status", "review_status"):
            if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                self.add("ERROR", "REQUIRED_FIELD", path, "缺少正式文献字段：" + field)
        scope, key, citekey = metadata.get("library_scope"), metadata.get("zotero_key"), metadata.get("citekey")
        if scope and (not isinstance(scope, str) or not SCOPE_RE.fullmatch(scope)):
            self.add("ERROR", "LIBRARY_SCOPE", path, "library_scope 应为 users/<ID> 或 groups/<ID>")
        if key and (not isinstance(key, str) or not KEY_RE.fullmatch(key)):
            self.add("ERROR", "ZOTERO_KEY", path, "zotero_key 应为 8 位大写字母数字")
        if isinstance(scope, str) and isinstance(key, str) and KEY_RE.fullmatch(key):
            self.identities.setdefault((scope, key), []).append(path)
        if isinstance(citekey, str) and citekey.strip():
            if re.search(r"[\s{},\\]", citekey):
                self.add("ERROR", "CITEKEY_FORMAT", path, "citekey 包含会破坏引用语法的空白或分隔字符")
            if isinstance(scope, str) and isinstance(key, str):
                self.citekeys.setdefault(citekey, []).append((scope, key, path))
        material, review = metadata.get("material_status"), metadata.get("review_status")
        if not isinstance(material, str) or material not in MATERIAL_STATUSES:
            self.add("ERROR", "MATERIAL_STATUS", path, "material_status 应为 abstract、pdf 或 parsed")
        if not isinstance(review, str) or review not in REVIEW_STATUSES:
            self.add("ERROR", "REVIEW_STATUS", path, "review_status 应为 unreviewed、partial 或 reviewed")
        pdf_key = metadata.get("pdf_key")
        if isinstance(material, str) and material in {"pdf", "parsed"} and not pdf_key:
            self.add("ERROR", "PDF_KEY_MISSING", path, "PDF/parsed 材料需记录 pdf_key")
        if pdf_key and (not isinstance(pdf_key, str) or not KEY_RE.fullmatch(pdf_key)):
            self.add("ERROR", "PDF_KEY", path, "pdf_key 应为 8 位大写字母数字")
        fulltext = metadata.get("fulltext_path")
        if material == "parsed" and not fulltext:
            self.add("ERROR", "FULLTEXT_REQUIRED", path, "parsed 状态需指向实际归档全文")
        if fulltext:
            self.check_fulltext(path, metadata, fulltext)
        elif fulltext is not None and not isinstance(fulltext, str):
            self.add("ERROR", "FULLTEXT_PATH", path, "fulltext_path 应为字符串或 null")
        if "evidence_level" in metadata:
            self.add("WARN", "LEGACY_EVIDENCE_LEVEL", path, "旧 E0–E5 字段需迁移为材料、主张核验和实验记录，不能用等级推断质量")
        if PLACEHOLDER.search(str(metadata) + "\n" + body):
            self.add("ERROR", "TEMPLATE_PLACEHOLDER", path, "正式笔记仍包含模板占位符")
        self.check_sections(path, body, required=True)
        self.check_claims(path, metadata)
        self.check_legacy_pairs(path, body)

    def check_fulltext(self, note_path, metadata, relative):
        try:
            fulltext = inside_path(self.vault, relative)
        except ValueError as exc:
            self.add("ERROR", "FULLTEXT_PATH", note_path, str(exc))
            return
        if not fulltext.is_file():
            self.add("ERROR", "FULLTEXT_MISSING", note_path, "全文文件不存在：" + str(relative))
            return
        package, source_file = fulltext.parent, fulltext.parent / "provenance.json"
        if not source_file.is_file():
            level = "ERROR" if metadata.get("material_status") == "parsed" else "WARN"
            self.add(level, "ARCHIVE_PROVENANCE_MISSING", note_path, "全文没有独立资料包 provenance.json；不能认定完整归档")
            return
        try:
            source_file = inside_path(self.vault, source_file.relative_to(self.vault).as_posix())
            data = json.loads(source_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("来源清单必须为对象")
        except (ValueError, OSError, RuntimeError) as exc:
            self.add("ERROR", "ARCHIVE_PROVENANCE", note_path, "来源清单无效：" + str(exc))
            return
        for field in ("library_scope", "zotero_key", "pdf_key"):
            if data.get(field) != metadata.get(field):
                self.add("ERROR", "ARCHIVE_IDENTITY", note_path, f"全文资料包的 {field} 与笔记不一致")
        if package in self.checked_archives:
            return
        self.checked_archives.add(package)
        source = data.get("source_pdf")
        if not isinstance(source, dict):
            self.add("ERROR", "ARCHIVE_PDF", source_file, "来源清单缺少 source_pdf")
        else:
            self.check_hashed_resource(package, source.get("relative_path"), source.get("sha256"), source_file, "ARCHIVE_PDF")
        files = data.get("files", [])
        if not isinstance(files, list):
            self.add("ERROR", "ARCHIVE_FILES", source_file, "files 必须为文件清单")
        else:
            for entry in files:
                if not isinstance(entry, dict):
                    self.add("ERROR", "ARCHIVE_FILES", source_file, "文件清单条目必须为对象")
                else:
                    self.check_hashed_resource(package, entry.get("path"), entry.get("sha256"), source_file, "ARCHIVE_FILE")
        images = data.get("images", [])
        if not isinstance(images, list):
            self.add("ERROR", "ARCHIVE_IMAGES", source_file, "images 必须为列表")
        else:
            for image in images:
                if not isinstance(image, dict):
                    self.add("ERROR", "ARCHIVE_IMAGES", source_file, "images 条目必须为对象")
                    continue
                try:
                    image_path = inside_path(package, image.get("path"))
                    if not image_path.is_file():
                        raise ValueError("图像文件不存在：" + str(image.get("path")))
                except ValueError as exc:
                    self.add("ERROR", "ARCHIVE_IMAGE_MISSING", source_file, str(exc))
        mapping = data.get("page_mapping")
        if not isinstance(mapping, dict) or mapping.get("status") != "available":
            self.add("WARN", "PAGE_MAPPING_MISSING", source_file, "没有明确页码映射；不得猜测 PDF 页码")
        for row in data.get("issues", []) if isinstance(data.get("issues", []), list) else []:
            if isinstance(row, dict) and row.get("level") == "WARN" and row.get("code") != "PAGE_MAPPING_MISSING":
                self.add("WARN", "EXPORT_" + str(row.get("code", "WARNING")), source_file, str(row.get("message", "归档时存在未解决问题")))

    def check_hashed_resource(self, package, relative, expected_hash, report_path, prefix):
        try:
            path = inside_path(package, relative)
            if not path.is_file():
                raise ValueError("文件不存在：" + str(relative))
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash):
                raise ValueError("缺少有效 SHA-256：" + str(relative))
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected_hash.lower():
                self.add("ERROR", prefix + "_HASH", report_path, "文件内容与来源清单指纹不同：" + str(relative))
        except (ValueError, OSError) as exc:
            self.add("ERROR", prefix, report_path, str(exc))

    def check_links(self, path, body):
        # 代码块与行内代码中的链接是示例语法，不作为导航链接检查。
        stripped = re.sub(r"^\s*(```|~~~).*?^\s*\1\s*$", "", body, flags=re.M | re.S)
        stripped = re.sub(r"`[^`\n]*`", "", stripped)
        for match in re.finditer(r"!?\[\[([^\]\n]+)\]\]", stripped):
            target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
            if target:
                self.resolve_link(path, target, wiki=True)
        for match in re.finditer(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+[^)\n]*)?\)", stripped):
            self.resolve_link(path, match.group(1).strip("<>"), wiki=False)

    def resolve_link(self, current, target, wiki):
        try:
            parsed = urlsplit(target)
        except ValueError:
            self.add("ERROR", "LINK_INVALID", current, "无法解析链接：" + target)
            return
        if parsed.scheme or parsed.netloc:
            return
        relative = unquote(parsed.path)
        if not relative:
            return
        candidates = []
        raw = [current.parent / relative, self.vault / relative]
        if wiki and not Path(relative).suffix:
            raw += [path.with_suffix(".md") for path in raw]
        try:
            for candidate in raw:
                resolved = candidate.resolve()
                if self.is_within(resolved, self.vault) and candidate.exists():
                    candidates.append(resolved)
        except (OSError, ValueError, RuntimeError):
            self.add("ERROR", "LINK_INVALID", current, "无效文件链接：" + target)
            return
        if wiki and "/" not in relative and "\\" not in relative:
            for resource in self.resource_index:
                if resource.name == relative or (not Path(relative).suffix and resource.stem == relative and resource.suffix.lower() == ".md"):
                    candidates.append(resource.resolve())
        matches = set(candidates)
        if not matches:
            code = "LINK_MISSING"
            try:
                if not any(self.is_within(candidate.resolve(), self.vault) for candidate in raw):
                    code = "LINK_OUTSIDE_VAULT"
            except (OSError, ValueError, RuntimeError):
                code = "LINK_INVALID"
            self.add("ERROR", code, current, "未找到 Vault 内链接目标：" + target)
        elif len(matches) > 1:
            self.add("WARN", "LINK_AMBIGUOUS", current, "链接命中多个文件，请使用含目录的路径：" + target)

    def check_tex(self, path, body):
        """只核查引用键和 bib 的结构关系，不模拟 LaTeX 编译。"""
        text = re.sub(r"(?<!\\)%[^\n]*", "", body)
        keys = {key.strip() for match in CITE_PATTERN.finditer(text) for key in match.group(1).split(",") if key.strip()}
        declarations = []
        for match in re.finditer(r"\\bibliography\{([^}]+)\}|\\addbibresource(?:\[[^\]]*\])?\{([^}]+)\}", text):
            declarations.extend(value.strip() for value in (match.group(1) or match.group(2)).split(",") if value.strip())
        bibs = []
        for value in declarations:
            candidate = path.parent / value
            if candidate.suffix.lower() != ".bib":
                candidate = Path(str(candidate) + ".bib")
            candidate = candidate.resolve()
            if not self.is_within(candidate, self.vault) or not candidate.is_file():
                self.add("ERROR", "BIB_MISSING", path, "引用声明的 bib 不在 Vault 内或不存在：" + value)
            else:
                bibs.append(candidate)
        if not declarations:
            for candidate in path.parent.glob("*.bib"):
                try:
                    if not self.is_within(candidate.resolve(), self.vault) or not candidate.is_file():
                        self.add("ERROR", "BIB_MISSING", path, "附近 bib 通过符号链接越出 Vault 或不是文件：" + candidate.name)
                    else:
                        bibs.append(candidate)
                except (OSError, RuntimeError) as exc:
                    self.add("ERROR", "BIB_READ", path, str(exc))
        if not keys:
            return
        if not bibs:
            self.add("WARN", "BIB_UNAVAILABLE", path, "有 LaTeX 引用，但附近未提供 bib，本轮无法核查引用键")
            return
        available = set()
        for bib in bibs:
            try:
                available.update(re.findall(r"@\w+\s*\{\s*([^\s,]+)\s*,", bib.read_text(encoding="utf-8")))
            except (OSError, UnicodeError) as exc:
                self.add("ERROR", "BIB_READ", path, str(exc))
        for key in sorted(keys - available):
            self.add("ERROR", "CITEKEY_MISSING", path, "LaTeX 引用键未在附近 bib 中出现：" + key)

    def check_document(self, path):
        self.documents += 1
        try:
            resolved = inside_path(self.vault, path.relative_to(self.vault).as_posix())
            text = resolved.read_text(encoding="utf-8")
        except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
            self.add("ERROR", "DOCUMENT_READ", path, str(exc))
            return
        if path.suffix.lower() == ".tex":
            self.check_tex(path, text)
            return
        formal = self.is_within(path, self.paths["notes"]) and "_index" not in path.relative_to(self.paths["notes"]).parts
        navigation = path.name in NAVIGATION_NAMES or "_index" in path.parts
        metadata, body = None, text
        if text.startswith("---") or formal or not navigation:
            try:
                metadata, body, _ = read_note(text)
            except ValueError as exc:
                self.add("ERROR", "FRONTMATTER", path, str(exc))
        if metadata is not None:
            for field in ("type", "title"):
                if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                    self.add("ERROR", "REQUIRED_FIELD", path, "缺少字段：" + field)
            if metadata.get("type") == "literature-note":
                self.literature(path, metadata, body)
            else:
                if formal:
                    self.add("WARN", "NON_LITERATURE_IN_NOTES", path, "文献目录出现其他类型，临时阅读可放收件箱")
                self.check_sections(path, body)
        self.check_links(path, body)

    def finish(self):
        for (scope, key), paths in self.identities.items():
            if len(paths) > 1:
                self.add("ERROR", "DUPLICATE_IDENTITY", paths[0], f"同一父条目存在多篇正式笔记：{scope}/{key}；" + ", ".join(str(path.relative_to(self.vault)) for path in paths))
        for citekey, entries in self.citekeys.items():
            if len({(scope, key) for scope, key, _ in entries}) > 1:
                self.add("WARN", "CITEKEY_CONFLICT", entries[0][2], "不同条目使用同一 citekey，合并到项目 bib 前须消歧：" + citekey)
        errors = sum(row["level"] == "ERROR" for row in self.issues)
        warnings = sum(row["level"] == "WARN" for row in self.issues)
        status = "invalid_structure" if errors else "empty_vault" if not self.selected and self.notes == 0 else "structure_ok"
        return {"vault": str(self.vault), "status": status, "documents": self.documents, "notes": self.notes,
                "errors": errors, "warnings": warnings, "issues": self.issues,
                "content_verified": False, "scientific_quality_verified": False,
                "check_scope": "selected_documents" if self.selected else "vault"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, help="Vault 根目录")
    parser.add_argument("--path", action="append", help="Vault 相对文档路径，可重复指定 .md 或 .tex")
    parser.add_argument("--quiet", action="store_true", help="仅显示汇总")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)
    try:
        if DEPENDENCY_ERROR:
            raise ValueError(DEPENDENCY_ERROR)
        vault = Path(args.vault).expanduser().resolve()
        if not vault.is_dir():
            raise ValueError("Vault 不存在：" + str(vault))
        checker = Checker(vault, read_profile(vault), selected=bool(args.path))
        documents = set()
        if args.path:
            for relative in args.path:
                document = inside_path(vault, relative)
                if not document.is_file() or document.suffix.lower() not in {".md", ".tex"}:
                    raise ValueError("--path 必须指向存在的 .md 或 .tex 文档：" + relative)
                if checker.is_within(document, checker.paths["fulltext"]) or checker.is_within(document, checker.paths["templates"]):
                    raise ValueError("--path 不检查模板或来源全文，请指定笔记、知识、课题或写作文档")
                documents.add(document)
        else:
            for name in ("knowledge", "notes", "projects", "writing", "inbox"):
                directory = checker.paths[name]
                if not directory.is_dir():
                    checker.add("WARN", "DIRECTORY_MISSING", directory, "资料子目录尚不存在")
                    continue
                for current, dirs, names in os.walk(str(directory), followlinks=False):
                    dirs[:] = [name for name in dirs if name not in {".git", ".obsidian", ".trash", "__pycache__"}]
                    for filename in names:
                        if Path(filename).suffix.lower() in {".md", ".tex"}:
                            documents.add(Path(current) / filename)
        for document in sorted(documents):
            checker.check_document(document)
        report = checker.finish()
        code = 1 if report["errors"] else 0
    except (ValueError, OSError, RuntimeError) as exc:
        code = 2
        report = {"status": "configuration_error", "errors": 1, "warnings": 0,
                  "issues": [{"level": "ERROR", "code": "CHECK_CONFIGURATION", "path": str(args.vault), "message": str(exc)}],
                  "content_verified": False, "scientific_quality_verified": False}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if not args.quiet:
            for row in report["issues"]:
                print(f"[{row['level']}] {row['code']} {row['path']} :: {row['message']}")
        print(f"状态：{report['status']}；文献笔记 {report.get('notes', 0)}；文档 {report.get('documents', 0)}；ERROR {report['errors']}；WARN {report['warnings']}")
        if report["status"] == "empty_vault":
            print("库内尚无正式文献笔记，这不是完整科研流程验收通过。")
        else:
            print("本次仅检查结构与本地引用接口，不证明原文、人工核查记录或科学结论正确。")
    return code


if __name__ == "__main__":
    sys.exit(main())
