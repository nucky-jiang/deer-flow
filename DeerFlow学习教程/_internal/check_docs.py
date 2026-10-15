#!/usr/bin/env python3
"""DeerFlow 学习教程 · 文档体检脚本（内部工具，全书完成后会删除）

用法（在仓库根目录执行；Windows 下建议先 `chcp 65001` 或直接用 python 即可）:

    python DeerFlow学习教程/_internal/check_docs.py                         # 检查全部章节
    python DeerFlow学习教程/_internal/check_docs.py 03-后端核心篇/04-中间件链.md   # 只查某一章(路径相对于教程根目录)
    python DeerFlow学习教程/_internal/check_docs.py --rebuild               # 重建符号缓存后再检查

检查项:
  [E] 相对链接指向的文件/目录不存在
  [E] 行内代码里的仓库路径不存在 (如 `backend/app/gateway/app.py`)
  [E] 代码围栏没有闭合 / 一级标题不是恰好 1 个
  [E] 代码块里残留了读文件工具的行号前缀 (形如 `  123| code`)
  [W] 行内代码里的标识符在整个仓库里搜不到 (疑似杜撰的函数/类/配置名)
        -> 如果是你"有意"编造的示例名(比如实战章节里的 my_new_tool)，把它加到
           DeerFlow学习教程/_internal/allow_symbols.txt (一行一个) 即可。
  [W] "来源"引用块中的代码行在源文件里找不到 (疑似改写了源码)
  [W] 锚点 (#xxx) 在目标文件里找不到
  [I] 含有"待核实 / TODO"标记
"""

from __future__ import annotations

import argparse
import os
import pickle
import re
import sys
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
TUT = HERE.parent
REPO = TUT.parent
CACHE = HERE / ".symbols.pkl"
ALLOW_FILE = HERE / "allow_symbols.txt"

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".deer-flow", "logs", ".turbo",
    "coverage", ".cache", "htmlcov", "site-packages", TUT.name,
}
SKIP_FILES = {"pnpm-lock.yaml", "uv.lock", "package-lock.json", "yarn.lock"}
TEXT_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".toml",
    ".sh", ".cmd", ".bat", ".ps1", ".md", ".mdx", ".txt", ".ini", ".cfg", ".conf", ".sql",
    ".mako", ".html", ".css", ".example", ".tpl", ".env",
}
TEXT_NAMES = {"Makefile", "Dockerfile", "Procfile", ".gitignore", ".dockerignore"}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# 仓库顶层目录/文件 —— 行内代码如果以它们开头并带 "/"，就当作"仓库路径"去核对
REPO_TOP = {
    "backend", "frontend", "docker", "scripts", "skills", "docs", "examples", "contracts",
    "deploy", ".github", "tests", "plans", ".agent",
}
# 运行时才会生成的路径(仓库里本来就没有)，不报错
RUNTIME_PATH_HINTS = (".deer-flow", "node_modules", ".venv", ".next", "logs/", "__pycache__", ".pytest_cache", "dist/")
RUNTIME_FILES = {
    "config.yaml", "extensions_config.json", ".env", ".env.local", "frontend/.env", "backend/.env",
    "frontend/.env.local", ".deer-flow", "logs",
}

FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
LINK_RE = re.compile(r"(?<!\!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMG_RE = re.compile(r"\!\[([^\]]*)\]\(([^)\s]+)\)")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
LINENO_PREFIX_RE = re.compile(r"^\s*\d{1,6}\|( |$)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
UNSURE_RE = re.compile(r"待核实|TODO|FIXME|待补充|XXX")


def _is_text_file(p: Path) -> bool:
    return p.suffix in TEXT_EXT or p.name in TEXT_NAMES


def build_symbols() -> dict:
    tokens: set[str] = set()
    basenames: set[str] = set()
    count = 0
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for d in dirnames:
            tokens.update(TOKEN_RE.findall(d))
        for fn in filenames:
            basenames.add(fn)
            tokens.update(TOKEN_RE.findall(fn))
            if fn in SKIP_FILES:
                continue
            p = Path(dirpath) / fn
            if not _is_text_file(p):
                continue
            try:
                if p.stat().st_size > 3_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            tokens.update(TOKEN_RE.findall(text))
            count += 1
    return {"tokens": tokens, "basenames": basenames, "files": count}


def load_symbols(rebuild: bool) -> dict:
    if CACHE.exists() and not rebuild:
        try:
            with CACHE.open("rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    print("[info] 正在建立仓库符号索引(首次约需几十秒)...", file=sys.stderr)
    data = build_symbols()
    with CACHE.open("wb") as f:
        pickle.dump(data, f)
    print(f"[info] 已索引 {data['files']} 个文本文件, {len(data['tokens'])} 个标识符", file=sys.stderr)
    return data


def load_allow() -> set[str]:
    if not ALLOW_FILE.exists():
        return set()
    out = set()
    for line in ALLOW_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def slugify(heading: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = text.replace("`", "")
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


_heading_cache: dict[Path, set[str]] = {}


def headings_of(path: Path) -> set[str]:
    if path in _heading_cache:
        return _heading_cache[path]
    slugs: set[str] = set()
    try:
        in_fence = False
        fence = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            m = FENCE_RE.match(line)
            if m:
                marker = m.group(2)
                if not in_fence:
                    in_fence, fence = True, marker[0]
                elif marker[0] == fence and not m.group(3).strip():
                    in_fence = False
                continue
            if in_fence:
                continue
            hm = HEADING_RE.match(line)
            if hm:
                slugs.add(slugify(hm.group(2)))
    except OSError:
        pass
    _heading_cache[path] = slugs
    return slugs


_source_lines_cache: dict[Path, set[str]] = {}


def norm_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def source_lines(path: Path) -> set[str]:
    if path in _source_lines_cache:
        return _source_lines_cache[path]
    lines: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            n = norm_line(line)
            if n:
                lines.add(n)
    except OSError:
        pass
    _source_lines_cache[path] = lines
    return lines


def looks_like_code_identifier(tok: str) -> bool:
    if len(tok) < 4:
        return False
    if "_" in tok.strip("_"):
        return True
    if tok.startswith("_") and len(tok.strip("_")) >= 4:
        return True
    if re.search(r"[a-z][A-Z]", tok):
        return True
    if re.fullmatch(r"[A-Z][a-z]+[A-Z][A-Za-z]*", tok):
        return True
    return False


def check_repo_path(span: str) -> tuple[bool, str] | None:
    """若 span 像仓库路径则返回 (是否存在, 规范化后的路径)，否则返回 None。"""
    s = span.strip()
    s = re.sub(r"::.*$", "", s)
    s = re.sub(r"#L?\d+(-L?\d+)?$", "", s)
    s = re.sub(r":\d+(-\d+)?$", "", s)
    s = s.rstrip(".,;)")
    s = s.replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    if s.startswith("/"):
        return None
    if re.search(r"\s", s):
        return None
    first = s.split("/", 1)[0]
    if first not in REPO_TOP and s not in {"Makefile", "config.example.yaml", "extensions_config.example.json", "AGENTS.md", "CONTRIBUTING.md", "Install.md", "README.md", "RELEASING.md", "SECURITY.md", ".env.example", ".pre-commit-config.yaml", "CHANGELOG.md", "CLAUDE.md"}:
        return None
    if "/" not in s and not Path(s).suffix:
        return None
    if any(h in s for h in RUNTIME_PATH_HINTS) or s in RUNTIME_FILES:
        return True, s
    # 通配符/占位符：只核对到通配符之前的目录
    m = re.search(r"[\*\{\<\[…]|\.\.\.", s)
    if m:
        prefix = s[: m.start()]
        if "/" in prefix:
            prefix = prefix.rsplit("/", 1)[0]
        else:
            prefix = ""
        if not prefix:
            return True, s
        return (REPO / prefix).exists(), s
    return (REPO / s).exists(), s


def check_file(md: Path, symbols: dict, allow: set[str]) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    infos: list[str] = []
    rel = md.relative_to(TUT).as_posix()
    try:
        text = md.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        errors.append(f"{rel}: 文件不是合法的 UTF-8")
        return errors, warns, infos
    lines = text.splitlines()

    in_fence = False
    fence_char = ""
    fence_len = 0
    fence_open_line = 0
    fence_lang = ""
    fence_buf: list[tuple[int, str]] = []
    pending_source: Path | None = None  # 最近的"来源"引用
    h1_count = 0
    tokens = symbols["tokens"]
    basenames = symbols["basenames"]
    reported_symbols: set[str] = set()

    def flush_fence_check(lang: str, buf: list[tuple[int, str]], src: Path | None) -> None:
        # 行号前缀残留
        for ln, content in buf:
            if LINENO_PREFIX_RE.match(content):
                errors.append(f"{rel}:{ln}: 代码块内残留行号前缀(疑似直接粘贴了读文件工具的输出): {content.strip()[:60]!r}")
                break
        if src is None:
            return
        if lang in {"text", "mermaid", "console", "diff", "markdown", "md"}:
            return
        sl = source_lines(src)
        if not sl:
            return
        miss = []
        for ln, content in buf:
            n = norm_line(content)
            if not n:
                continue
            if re.fullmatch(r"(#|//|--|/\*|\*/|\*)?\s*(\.\.\.|…|省略.*|\.\.\. ?省略.*)\s*(\*/)?", n):
                continue
            if n in sl:
                continue
            # 去掉行尾含中文的解释性注释再试一次
            stripped = re.sub(r"\s+(#|//)\s+.*$", "", n) if CJK_RE.search(n) else n
            if stripped and stripped in sl:
                continue
            if CJK_RE.search(n) and re.match(r"^(#|//)", n):
                continue  # 整行都是中文注释，视为作者标注
            if n in {"...", "…", "# ...", "// ..."}:
                continue
            miss.append((ln, n))
        if miss:
            sample = "; ".join(f"L{ln}: {txt[:70]!r}" for ln, txt in miss[:3])
            warns.append(f"{rel}:{buf[0][0]}: “来源”代码块中有 {len(miss)} 行在源文件 {src.relative_to(REPO).as_posix()} 里找不到(是否改写/拼接了源码?): {sample}")

    for idx, line in enumerate(lines, start=1):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(2)
            rest = m.group(3)
            if not in_fence:
                in_fence = True
                fence_char, fence_len = marker[0], len(marker)
                fence_open_line = idx
                fence_lang = rest.strip().split()[0].lower() if rest.strip() else ""
                fence_buf = []
                continue
            elif marker[0] == fence_char and len(marker) >= fence_len and not rest.strip():
                in_fence = False
                flush_fence_check(fence_lang, fence_buf, pending_source)
                pending_source = None
                continue
        if in_fence:
            fence_buf.append((idx, line))
            continue

        # ---- 非围栏内的普通行 ----
        hm = HEADING_RE.match(line)
        if hm and len(hm.group(1)) == 1:
            h1_count += 1

        if UNSURE_RE.search(line):
            infos.append(f"{rel}:{idx}: 含有待核实/TODO 标记: {line.strip()[:80]}")

        # “来源”引用块
        if "来源" in line and line.lstrip().startswith(">"):
            for lm in LINK_RE.finditer(line):
                target = unquote(lm.group(2)).split("#")[0]
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                cand = (md.parent / target).resolve()
                if cand.is_file():
                    pending_source = cand
                    break
        elif line.strip() and not line.lstrip().startswith(">") and pending_source is not None and not line.strip().startswith("<"):
            # 来源行之后出现了别的正文，来源引用失效
            pending_source = None

        # 链接
        masked = INLINE_CODE_RE.sub(lambda mm: " " * len(mm.group(0)), line)
        for lm in list(LINK_RE.finditer(masked)) + list(IMG_RE.finditer(masked)):
            target_raw = lm.group(2)
            if target_raw.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            anchor = ""
            target = unquote(target_raw)
            if "#" in target:
                target, anchor = target.split("#", 1)
            if not target:
                if anchor and slugify(anchor) not in headings_of(md) and anchor not in headings_of(md):
                    warns.append(f"{rel}:{idx}: 同文锚点 #{anchor} 找不到对应标题")
                continue
            cand = (md.parent / target).resolve()
            if not cand.exists():
                errors.append(f"{rel}:{idx}: 链接目标不存在: {target_raw}")
                continue
            if anchor and cand.suffix == ".md" and cand.is_file():
                hs = headings_of(cand)
                if anchor not in hs and slugify(anchor) not in hs:
                    warns.append(f"{rel}:{idx}: 锚点 #{anchor} 在 {target} 中找不到")

        # 行内代码
        for cm in INLINE_CODE_RE.finditer(line):
            span = cm.group(1).strip()
            if not span:
                continue
            res = check_repo_path(span)
            if res is not None:
                ok, norm = res
                if not ok:
                    errors.append(f"{rel}:{idx}: 行内代码里的仓库路径不存在: `{span}`")
                continue
            # 单个文件名(无目录)
            if re.fullmatch(r"[\w\-\.]+\.(py|ts|tsx|yaml|yml|json|md|toml|sh|cmd|conf|sql)", span) and span not in RUNTIME_FILES:
                if span not in basenames and span not in allow and span not in reported_symbols:
                    reported_symbols.add(span)
                    warns.append(f"{rel}:{idx}: 文件名在仓库里找不到: `{span}`")
                continue
            # 标识符
            head = re.sub(r"\(.*$", "", span)  # foo(bar) -> foo
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\.]*", head):
                continue
            for part in head.split("."):
                if not part or not looks_like_code_identifier(part):
                    continue
                if part in tokens or part in allow or part in reported_symbols:
                    continue
                reported_symbols.add(part)
                warns.append(f"{rel}:{idx}: 标识符在仓库里搜不到(疑似杜撰?): `{part}`  (出自 `{span[:60]}`)")

    if in_fence:
        errors.append(f"{rel}:{fence_open_line}: 代码围栏未闭合")
    if h1_count != 1:
        errors.append(f"{rel}: 一级标题数量应为 1，实际为 {h1_count}")
    return errors, warns, infos


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="相对教程根目录的 md 路径；缺省检查全部")
    ap.add_argument("--rebuild", action="store_true", help="重建仓库符号缓存")
    ap.add_argument("--no-symbols", action="store_true", help="跳过标识符检查(更快)")
    ap.add_argument("--quiet-info", action="store_true", help="不打印 [I] 级别信息")
    ap.add_argument("--no-warn", action="store_true", help="只打印错误")
    args = ap.parse_args()

    if args.files:
        targets = []
        for f in args.files:
            p = (TUT / f)
            if not p.exists():
                p = Path(f)
            if not p.exists():
                print(f"[E] 文件不存在: {f}")
                return 2
            targets.append(p.resolve())
    else:
        targets = sorted(p for p in TUT.rglob("*.md") if "_internal" not in p.parts)

    if args.no_symbols:
        # 只做链接/围栏/路径检查：用"什么都包含"的哨兵集合，使标识符检查全部放行
        class _All(set):
            def __contains__(self, item):  # type: ignore[override]
                return True

        symbols = {"tokens": _All(), "basenames": _All(), "files": 0}
    else:
        symbols = load_symbols(args.rebuild)
    allow = load_allow()

    total_e = total_w = total_i = 0
    for md in targets:
        e, w, i = check_file(md, symbols, allow)
        total_e += len(e)
        total_w += len(w)
        total_i += len(i)
        lines_n = len(md.read_text(encoding="utf-8").splitlines())
        status = "OK " if not e else "ERR"
        print(f"[{status}] {md.relative_to(TUT).as_posix()}  ({lines_n} 行, E={len(e)} W={len(w)} I={len(i)})")
        for x in e:
            print(f"    [E] {x}")
        if not args.no_warn:
            for x in w:
                print(f"    [W] {x}")
        if not args.quiet_info and not args.no_warn:
            for x in i:
                print(f"    [I] {x}")

    # 孤儿检查(仅全量检查时)
    if not args.files:
        readme = TUT / "README.md"
        if readme.exists():
            linked = set()
            for lm in LINK_RE.finditer(readme.read_text(encoding="utf-8")):
                t = unquote(lm.group(2)).split("#")[0]
                if t and not t.startswith(("http://", "https://")):
                    linked.add((readme.parent / t).resolve())
            for md in targets:
                if md.resolve() not in linked and md.name != "README.md":
                    print(f"[W] 孤儿文件(README 目录里没有链接): {md.relative_to(TUT).as_posix()}")

    print(f"\n汇总: 文件 {len(targets)} 个, 错误 {total_e}, 警告 {total_w}, 提示 {total_i}")
    return 1 if total_e else 0


if __name__ == "__main__":
    sys.exit(main())
