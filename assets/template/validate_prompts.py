# -*- coding: utf-8 -*-
"""机械核对 提示词/001.txt–044.txt。退出码 0 表示无硬错误。
002 全段没有人，不生成、不检查。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PROMPT = os.path.join(ROOT, "提示词")
SECTIONS = [
    "subject_definitions:",
    "summary:",
    "retention_analysis:",
    "detailed_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
]
# 当前参考图校验配置：这里只检查提示词是否写出了当前图片的身份特征，
# 不用外貌反推人物编号。更换参考图时只更新这里的可变描述；CAST 和提交脚本的
# 文件名映射保持不变。
CURRENT_REFERENCE_CHECKS = {
    "一": {
        "label": "当前一号参考图",
        "required": (("crimson-red hair", ("crimson-red",)),
                     ("gold-rimmed glasses", ("gold-rimmed glasses",)),
                     ("white collared shirt", ("white collared button-up shirt",)),
                     ("red necktie", ("red necktie",)),
                     ("pleated mini skirt", ("pleated mini skirt",))),
        "forbidden": (("gray hair", ("gray hair", "grey hair")),
                      ("brown hair", ("brown hair", "dark hair")),
                      ("black-framed glasses", ("black-framed glasses",)),
                      ("leather jacket", ("leather jacket",)),
                      ("suit jacket", ("suit jacket", "black suit"))),
    },
    "二": {
        "label": "当前二号参考图",
        "required": (("silver-white hair", ("silver-white",)),
                     ("blue-violet eyes", ("blue-violet eyes",)),
                     ("no glasses", ("no glasses",)),
                     ("shirt dress", ("shirt dress",)),
                     ("choker", ("choker",)),
                     ("thigh-high stocking", ("thigh-high stocking",))),
        "forbidden": (("gray hair", ("gray hair", "grey hair")),
                      ("brown hair", ("brown hair", "dark hair")),
                      ("black-framed glasses", ("black-framed glasses",)),
                      ("leather jacket", ("leather jacket",)),
                      ("suit jacket", ("suit jacket", "black suit")),
                      ("necktie", ("necktie",))),
    },
}
# 004、007、017 已按用户决定改用原片，不做替换，不在这里。
CAST = {
    "001": "一二", "003": "一二", "005": "二", "006": "一二",
    "008": "一二", "009": "一二", "010": "一二", "011": "一二", "012": "一二",
    "013": "一二", "014": "一二", "015": "一二", "016": "一二", "018": "一二",
    "019": "一二", "020": "一二", "021": "一二", "022": "一二", "023": "一二", "024": "一二",
    "025": "一二", "026": "一二", "027": "一", "028": "一二", "029": "一二",
    "030": "一二", "031": "一二", "032": "一二", "033": "一二", "034": "一二",
    "035": "一二", "036": "一二", "037": "一二", "038": "一二", "039": "一二",
    "040": "一二", "041": "一二", "042": "二", "043": "一二", "044": "一二",
}
DUAL = {n for n, c in CAST.items() if c == "一二"}
# 只有局部、没有身体的段：Subject 定义行只写画面里真能看见的部分，
# 不挂看不见的裤子、鞋，避免把身体带出来。
LOCAL_ONLY = {"004", "005", "006", "007", "017", "042", "044"}


def subject_definition_blocks(text):
    """Return only the Subject definitions, excluding later action prose."""
    start = text.find("subject_definitions:")
    end = text.find("summary:")
    if start < 0 or end < 0 or end <= start:
        return {}
    section = text[start:end]
    blocks = {}
    matches = list(re.finditer(
        r"(?ms)^<Subject (\d+)>.*?(?=^<Subject \d+>|^<Video \d+>|\Z)",
        section,
    ))
    for match in matches:
        blocks[match.group(1)] = match.group(0)
    return blocks


def check_current_identity(num, text, errors, warns):
    """Check current reference appearance per Subject, without inferring its number."""
    if num in LOCAL_ONLY:
        return
    blocks = subject_definition_blocks(text)
    roles = {"1": CAST[num][0]}
    if CAST[num] == "一二":
        roles["2"] = CAST[num][1]
    for subject_num, role in roles.items():
        block = blocks.get(subject_num)
        if block is None:
            continue
        low = block.lower()
        checks = CURRENT_REFERENCE_CHECKS[role]
        missing = [label for label, alternatives in checks["required"]
                   if not any(term in low for term in alternatives)]
        if missing:
            warns.append(
                f"{num}: Subject {subject_num} missing current {checks['label']} identity: "
                + ", ".join(missing)
            )
        mixed = [label for label, alternatives in checks["forbidden"]
                 if any(term in low for term in alternatives)]
        if mixed:
            errors.append(
                f"{num}: Subject {subject_num} mixes other current identity: "
                + ", ".join(mixed)
            )


def main():
    errors = []
    warns = []
    for i in range(1, 45):
        num = f"{i:03d}"
        if num not in CAST:
            continue
        path = os.path.join(PROMPT, num + ".txt")
        if not os.path.isfile(path):
            errors.append(f"{num}: missing file")
            continue
        text = open(path, encoding="utf-8").read()
        if text.startswith("﻿"):
            errors.append(f"{num}: BOM")
            text = text.lstrip("﻿")
        if not text.startswith("subject_definitions:"):
            errors.append(f"{num}: does not start with subject_definitions:")
        if "```" in text:
            errors.append(f"{num}: code fence")
        if re.search(r"一号|二号|\.png", text):
            errors.append(f"{num}: forbidden 一号/二号/png")
        if "attribute_transfer" in text:
            errors.append(f"{num}: attribute_transfer")
        idxs = []
        for s in SECTIONS:
            k = text.find(s)
            idxs.append(k)
            if k < 0:
                errors.append(f"{num}: missing {s}")
        if all(k >= 0 for k in idxs) and idxs != sorted(idxs):
            errors.append(f"{num}: section order wrong")
        if "[video editing + reference generation]" not in text:
            errors.append(f"{num}: missing summary prefix")
        if "fully_preserved" not in text:
            errors.append(f"{num}: missing fully_preserved")
        if "partially_preserved" not in text:
            errors.append(f"{num}: missing partially_preserved")
        if "watermark" not in text.lower():
            errors.append(f"{num}: missing watermark removal")
        pics = re.findall(r"<Picture (\d+)>", text)
        subj = re.findall(r"<Subject (\d+)>", text)
        expected_subject_pictures = [("1", "1")]
        if num in DUAL:
            expected_subject_pictures.append(("2", "2"))
            if pics.count("1") != 1 or pics.count("2") != 1:
                errors.append(f"{num}: Picture 1/2 counts {pics}")
            if "1" not in subj or "2" not in subj:
                errors.append(f"{num}: missing Subject 1 or 2")
        else:
            if pics != ["1"]:
                errors.append(f"{num}: Picture refs {pics}, want only one Picture 1")
            if "2" in subj:
                errors.append(f"{num}: unexpected Subject 2")
        blocks = subject_definition_blocks(text)
        for subject_num, picture_num in expected_subject_pictures:
            refs = re.findall(r"<Picture (\d+)>", blocks.get(subject_num, ""))
            if refs != [picture_num]:
                errors.append(
                    f"{num}: Subject {subject_num} Picture refs {refs}, "
                    f"want only Picture {picture_num}"
                )
        check_current_identity(num, text, errors, warns)
        if re.search(r"\bthe a \b", text):
            errors.append(f"{num}: doubled article")

    print(f"errors {len(errors)}, warns {len(warns)}")
    for e in errors:
        print("ERR", e)
    for w in warns:
        print("WARN", w)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
