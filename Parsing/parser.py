import json
import re
from collections import OrderedDict

# ===== 1. JSON 로드 =====
with open("/Users/jaehwayang/DSL/Projects/Corp/workspace/Data/raw/log.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# ===== 2. inferText 필드 추출 =====
def extract_inferText(obj):
    """모든 inferText 문자열을 재귀적으로 수집하되, 페이지 번호(예: 1/7)는 제외"""
    texts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "inferText" and isinstance(v, str):
                txt = v.strip()
                # 페이지 번호 패턴 (예: 1/7, 2/10 등) 제외
                if re.match(r"^\d+\s*/\s*\d+$", txt):
                    continue
                if txt:
                    texts.append(txt)
            elif isinstance(v, (dict, list)):
                texts.extend(extract_inferText(v))
    elif isinstance(obj, list):
        for e in obj:
            texts.extend(extract_inferText(e))
    return texts


# ===== 3. inferText 병합 =====
words = extract_inferText(data)
text = " ".join(words)
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
    """'1 ', '2 ', ... 공백이 뒤따르는 숫자 패턴을 기준으로 항목 분리"""
    item_pattern = re.compile(r"(?=(?:\b\d\s))")
    segments = item_pattern.split(body_text)
    segments = [seg.strip() for seg in segments if seg.strip()]

    items = []
    current = ""
    for seg in segments:
        label_match = re.match(r"^(\d)\s+", seg)
        if label_match:
            # 새로운 항목 시작
            if current:
                items.append(current.strip())
            current = seg[label_match.end():].strip()
        else:
            current += " " + seg.strip()
    if current:
        items.append(current.strip())
    return items


# ===== 6. 2차 세부항목 탐지 (1. , 2. , 3. ... with dot) =====
def extract_subitems(item_text):
    """
    세부항목: '1.', '2.' 등 마침표가 뒤따르는 숫자 패턴으로 분리
    """
    sub_pattern = re.compile(r"(?=(?:\d+\.\s|[①-⑳]\.))")
    parts = sub_pattern.split(item_text)
    parts = [p.strip() for p in parts if p.strip()]

    # 첫 번째는 상위 항목 본문일 수도 있음
    main_text = parts[0]
    subitems = []
    for seg in parts[1:]:
        label_match = re.match(r"^(\d+\.)", seg)
        if label_match:
            subitems.append(seg[len(label_match.group(1)):].strip())
        else:
            subitems.append(seg.strip())

    return main_text, subitems


# ===== 7. 조항별 파싱 =====
clauses = []
for i in range(1, len(parts), 2):
    header = parts[i].strip()
    body = parts[i + 1].strip() if i + 1 < len(parts) else ""
    name, num, title = normalize_article_key(header)
    if not name:
        continue
    items_texts = split_items(body)

    # 조항 이름이 "제x조"로만 되어 있고 괄호나 제목이 없는 경우, 이전 clause에 병합
    if not title:
        if clauses:
            # 이전 clause의 items에 병합
            # 병합: items_texts를 각 항목별로 세부항목 분리 후 이전 clause의 items에 이어붙이기
            for it in items_texts:
                main_text, subitems = extract_subitems(it)
                clauses[-1]["clause"]["items"].append({
                    "text": main_text,
                    "subitems": subitems
                })
        # clauses가 비어 있으면 건너뜀
        continue

    if not items_texts:
        continue  # items가 없는 조항은 제외

    # 각 항목 내부에서 세부항목 분리
    structured_items = []
    for it in items_texts:
        main_text, subitems = extract_subitems(it)
        structured_items.append({
            "text": main_text,
            "subitems": subitems
        })

    clause_entry = {
        "clause": {
            "name": name,
            "title": title,
            "text": "",
            "items": structured_items
        }
    }
    clauses.append(clause_entry)

# ===== 5. 저장 =====
with open("/Users/jaehwayang/DSL/Projects/Corp/workspace/Data/proc/parsed_contract.json", "w", encoding="utf-8") as f:
    json.dump(clauses, f, ensure_ascii=False, indent=2)

print(f"✅ 변환 완료. 총 {len(words)}개의 단어를 병합했습니다.")