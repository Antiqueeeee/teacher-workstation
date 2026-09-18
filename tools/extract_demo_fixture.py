#!/usr/bin/env python3
"""把旧应用内嵌的 SEED_DATA 抽成演示夹具。

旧应用把一份完整的示范班级数据（45 名学生 + 各表记录）内嵌在 HTML 里
（`window.SEED_DATA`）。那是**卖家给的假数据**，不迁进新系统，但值得留着做两件事：

1. 前后端联调与页面保真度对照（同一份数据比对新旧渲染结果）；
2. 分页、虚拟滚动、统计的压测数据。

用法：
    python tools/extract_demo_fixture.py

输出：
    backend/tests/fixtures/demo_dataset.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "raw-material" / "web-app" / "班主任工作台.html"
TARGET = REPO / "backend" / "tests" / "fixtures" / "demo_dataset.json"
MARKER = "window.SEED_DATA"
BACKSLASH = chr(92)  # 用 chr 而不是字面量，免得被别处的转义层吃掉


def extract_object(text: str, marker: str) -> str:
    """取 marker 之后第一个**完整**的 JSON 对象。

    不能用正则或 `index('</script>')` —— 数据里含引号、括号、中文，
    只有按括号配平（并跳过字符串内部）才可靠。
    """
    begin = text.index("{", text.index(marker))
    depth = 0
    in_string = False
    escaped = False
    for index in range(begin, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == BACKSLASH:
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[begin : index + 1]
    raise ValueError("没有找到完整的 JSON 对象，源文件可能已损坏")


# 学生档案的默认字段模板：旧应用把 26 条字段定义（含 Excel 别名 syn）写在
# `defaultStudentFields()` 里，属于**产品真实词表**，同样不该自己编。
FIELD_FUNCTION = "defaultStudentFields"
FIELD_CALL_RE = re.compile(r"f\(\{(?P<body>[^}]*)\}\)", re.S)


def _function_region(text: str, name: str) -> str:
    """取某个函数定义所在的文本区域（到下一个顶层 `function ` 为止）。

    比按行号取稳：源码行号会随任何编辑漂移。
    """
    start = text.index(f"function {name}")
    end = text.find("\nfunction ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _js_object_to_json(body: str) -> str:
    """把 JS 对象字面量的**键**加引号、单引号串换双引号，使其能当 JSON 解析。

    注意先补回被外层正则剥掉的 `{` —— 否则**第一个键**前面没有 `{` 或 `,`，
    加引号的替换会漏掉它，整条定义就解析不出来（踩过）。
    """
    wrapped = "{" + body + "}"
    quoted_keys = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', wrapped)
    return re.sub(r"'([^']*)'", lambda match: '"' + match.group(1).replace('"', '\\"') + '"', quoted_keys)


def extract_student_fields(text: str) -> list[dict[str, Any]]:
    """抽出学生档案的默认字段定义（key/label/type/options/inList/inForm/... /syn）。"""
    region = _function_region(text, FIELD_FUNCTION)
    fields = []
    for match in FIELD_CALL_RE.finditer(region):
        try:
            fields.append(json.loads(_js_object_to_json(match.group("body"))))
        except json.JSONDecodeError:
            continue  # 认不出的定义跳过，不要因为一条坏数据丢掉整份
    return fields


# 话术模板不是数据、而是硬编码在脚本里的（旧应用 `seedTemplatesOnce`），
# 所以只能从源码里抠出来。字段就四个：标题 / 场景 / 语气 / 正文。
TEMPLATE_RE = re.compile(
    r"\{title:'(?P<title>[^']*)',\s*scenario:'(?P<scenario>[^']*)',"
    r"\s*tone:'(?P<tone>[^']*)',\s*body:'(?P<body>[^']*)'\}",
)


def extract_templates(text: str) -> list[dict[str, str]]:
    """抽出旧应用内置的话术模板，转成新表的形状。

    旧表 → 新表：`scenario` → `category`（场景）、`body` → `content`、`tone` 原样保留
    （语气是老师挑模板时真正在用的维度，丢掉就少了一半信息）。
    """
    found = []
    for match in TEMPLATE_RE.finditer(text):
        found.append(
            {
                "title": match.group("title").replace(BACKSLASH + "'", "'"),
                "category": match.group("scenario"),
                "tone": match.group("tone"),
                "content": match.group("body").replace(BACKSLASH + "'", "'"),
            }
        )
    return found


def main() -> int:
    if not SOURCE.exists():
        print(f"X 找不到旧应用：{SOURCE}")
        return 1

    text = SOURCE.read_text(encoding="utf-8")
    data = json.loads(extract_object(text, MARKER))

    # 话术模板不在 SEED_DATA 里（硬编码在脚本中），单独抠出来合并进夹具
    templates = extract_templates(text)
    if templates:
        data["templates"] = templates

    # 学生档案的默认字段模板也是硬编码的，单独落到一个资源文件里：
    # 它是**应用数据**（新建档案时的默认字段集），不是测试夹具
    student_fields = extract_student_fields(text)
    if student_fields:
        # 落到 app/services/ 下：它是**应用数据**（新建档案时的默认字段集），不是测试夹具
        target = REPO / "backend" / "app" / "services" / "default_student_fields.json"
        target.write_text(json.dumps(student_fields, ensure_ascii=False, indent=1), encoding="utf-8")
        labels = "、".join(item.get("label", "?") for item in student_fields[:8])
        print(f"   学生字段模板（{len(student_fields)} 条）: {labels} …")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"OK 已抽取 {len(data)} 个根键 → {TARGET.relative_to(REPO)}")
    print(f"   体积 {TARGET.stat().st_size / 1024:.0f} KB")
    for key, value in data.items():
        if isinstance(value, list):
            print(f"   {key}: {len(value)} 条")

    if templates:
        scenarios = sorted({item["category"] for item in templates})
        tones = sorted({item["tone"] for item in templates})
        print(f"   模板场景（{len(scenarios)}）: {'、'.join(scenarios)}")
        print(f"   模板语气（{len(tones)}）: {'、'.join(tones)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
