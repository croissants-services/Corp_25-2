import json
import re
from collections import OrderedDict

# ===== 1. JSON 로드 =====
import os
input_json_path = "/Users/jaehwayang/DSL/Projects/Corp/workspace/Data/raw/log.json"
with open(input_json_path, "r", encoding="utf-8") as f:
    data = json.load(f)
    # 파일명에서 확장자 제외하고 uid 추출
    filename = os.path.basename(input_json_path)
    uid, _ = os.path.splitext(filename)

current_page = None

# ===== 2. inferText 필드 추출 =====
def extract_inferText(obj):
    """모든 inferText 문자열을 재귀적으로 수집하되, 페이지 번호(예: 1/7)는 건너뜀"""
    texts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "inferText" and isinstance(v, str):
                txt = v.strip()
                # 페이지 번호 패턴 (예: 1/7, 2/10 등) 인식 시 건너뜀
                if re.match(r"^\s*(\d+)\s*/\s*\d+\s*$", txt):
                    continue
                if txt:
                    texts.append((txt, current_page, False))
            elif isinstance(v, (dict, list)):
                texts.extend(extract_inferText(v))
    elif isinstance(obj, list):
        for e in obj:
            texts.extend(extract_inferText(e))
    return texts


# ===== 3. inferText 병합 =====
words = extract_inferText(data)
# 페이지 번호 텍스트는 이후 조항 파싱 시점에서 제거하므로, 여기서는 모두 포함하여 병합
text = " ".join([w[0] for w in words if not w[2]])  # 페이지 번호 텍스트는 제외하고 병합
text = re.sub(r"\s+", " ", text).strip()

# ===== 4. 조항 탐지 (참조 조항 예외 포함) =====
# 패턴: 괄호 안의 제목이 반드시 있는 경우("제x조 (제목)")에만 매칭
article_pattern = re.compile(
    r"(?<![의에를와및])\s*(제\s*\d+\s*조\s*\([^)]+\))"
)
parts = article_pattern.split(text)


def normalize_article_key(hdr):
    """조항명에서 번호 및 제목 분리"""
    if re.match(r"^제\s*\d+\s*조\s*$", hdr):
        return "", None, ""
    num_m = re.search(r"제\s*(\d+)\s*조", hdr)
    num = int(num_m.group(1)) if num_m else None
    title_m = re.search(r"제\s*\d+\s*조\s*\(?([^)]+)\)?", hdr)
    title = title_m.group(1).strip() if title_m else ""
    return hdr.strip(), num, title


# ===== 5. 1차 항목 분리 (1., 2. 등) =====
def split_items(body_text):
    """'1 ', '2 ', ... 공백이 뒤따르는 숫자 패턴을 기준으로 항목 분리하여 딕셔너리 {item_name: item_text} 반환"""
    item_pattern = re.compile(r"(\b\d)\s+")
    items = {}
    last_label = None
    last_pos = 0

    for match in item_pattern.finditer(body_text):
        label = match.group(1)
        start = match.start()
        if last_label is not None:
            # 이전 항목 텍스트 저장
            items[last_label] = body_text[last_pos:start].strip()
        last_label = label
        last_pos = match.end()
    if last_label is not None:
        items[last_label] = body_text[last_pos:].strip()
    else:
        # 항목 패턴이 없으면 전체 본문을 하나의 항목으로 처리
        items["1"] = body_text.strip()
    return items


# ===== 6. 2차 세부항목 탐지 (1. , 2. , 3. ... with dot) =====
def extract_subitems(item_text):
    """
    세부항목: '1.', '2.' 등 마침표가 뒤따르는 숫자 패턴으로 분리하여 딕셔너리 {subitem_name: subitem_text} 반환
    (단, 3자리 이상 숫자나 연도(20xx)는 제외)
    main_text와 subitems를 분리하여 반환
    """
    sub_pattern = re.compile(r"(\b\d{1,2}\.)\s")
    matches = list(sub_pattern.finditer(item_text))
    if not matches:
        return item_text, {}

    main_text = item_text[:matches[0].start()].strip()
    subitems = {}
    for i, match in enumerate(matches):
        label = match.group(1).rstrip(".")
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(item_text)
        content = item_text[start:end].strip()
        # 3자리 이상 숫자 (ex. 2021) → 하위항목으로 인식하지 않음
        if re.match(r"20\d{2}", content) or re.match(r"\d{3,}", content):
            # 이전 subitem에 붙임
            if label in subitems:
                subitems[label] += " " + content
            else:
                subitems[label] = content
        else:
            subitems[label] = content

    return main_text, subitems


# ===== 7. 조항별 파싱 =====
clauses = []
for i in range(1, len(parts), 2):
    header = parts[i].strip()
    body = parts[i + 1].strip() if i + 1 < len(parts) else ""
    name, num, title = normalize_article_key(header)
    if not name:
        continue
    items_dict = split_items(body)

    # 조항 이름이 "제x조"로만 되어 있고 괄호나 제목이 없는 경우, 이전 clause에 병합
    if not title:
        if clauses:
            # 이전 clause의 items에 병합
            # 병합: items_dict를 각 항목별로 세부항목 분리 후 이전 clause의 items에 이어붙이기
            for item_name, item_text in items_dict.items():
                main_text, subitems_dict = extract_subitems(item_text)
                if item_name in clauses[-1]["clause"]["items"]:
                    # 기존 항목이 있으면 서브아이템 병합
                    existing_subitems = clauses[-1]["clause"]["items"][item_name].get("subitems", {})
                    for sub_name, sub_text in subitems_dict.items():
                        if sub_name in existing_subitems:
                            existing_subitems[sub_name] += " " + sub_text
                        else:
                            existing_subitems[sub_name] = sub_text
                    clauses[-1]["clause"]["items"][item_name]["subitems"] = existing_subitems
                else:
                    clauses[-1]["clause"]["items"][item_name] = {
                        "text": item_text,
                        "subitems": subitems_dict
                    }
        # clauses가 비어 있으면 건너뜀
        continue

    if not items_dict:
        continue  # items가 없는 조항은 제외

    # 각 항목 내부에서 세부항목 분리
    structured_items = {}
    for item_name, item_text in items_dict.items():
        main_text, subitems_dict = extract_subitems(item_text)
        structured_items[item_name] = {
            "text": item_text,
            "subitems": subitems_dict
        }

    clause_entry = {
        "uid": uid,
        "clause": {
            "name": name,
            "title": title,
            "text": "",
            "items": structured_items,
            "page": current_page
        }
    }
    clauses.append(clause_entry)

# ===== 5. 저장 =====
with open("/Users/jaehwayang/DSL/Projects/Corp/workspace/Data/proc/parsed_contract.json", "w", encoding="utf-8") as f:
    json.dump(clauses, f, ensure_ascii=False, indent=2)

print(f"✅ 변환 완료. 총 {len(words)}개의 단어를 병합했습니다.")