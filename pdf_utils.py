import re


def clean_pdf_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\x01", " ")

    noise_patterns = [
        r"행·복·금·융·투·자·길·라·잡·이",
        r"TEL\.\s*02\)\d{4}-\d{4}",
        r"FAX\.\s*02\)\d{3,4}-\d{4}",
        r"www\.\s*kofia\.or\.kr",
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, " ", text)

    cleaned_lines = []
    blank_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            blank_count = min(blank_count + 1, 2)
            continue
        if re.fullmatch(r"(금융투자상품 관련 분쟁사례|분쟁조정사례·판례집)\s*\d+", line):
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue

        filtered_chars = []
        for ch in line:
            code = ord(ch)
            is_hangul = (
                0xAC00 <= code <= 0xD7A3
                or 0x3131 <= code <= 0x318E
                or 0x1100 <= code <= 0x11FF
            )
            is_ascii = ch.isascii() and (
                ch.isalnum() or ch in " \t.,:;!?()[]{}'\"%/-+&*#@_=~<>"
            )
            is_common_symbol = ch in "·•○△▲▽▼◆◇□■※―–~…“”‘’ㆍⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"

            if is_hangul or is_ascii or is_common_symbol:
                filtered_chars.append(ch)
            elif ch.isspace():
                filtered_chars.append(" ")
            else:
                filtered_chars.append(" ")

        cleaned = re.sub(r"[ \t]+", " ", "".join(filtered_chars)).strip()
        if cleaned:
            if blank_count:
                cleaned_lines.extend([""] * blank_count)
                blank_count = 0
            cleaned_lines.append(cleaned)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"(?:\bh\b\s*){4,}", " ", cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r" *\n *", "\n", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def clean_pdf_documents(docs):
    for doc in docs:
        doc.page_content = clean_pdf_text(doc.page_content)
    return docs
