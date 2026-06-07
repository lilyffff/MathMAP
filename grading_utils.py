import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI


evaluation_items = [
    {
        "question": "금융투자회사 직원에게 계좌관리를 일임할 때 투자일임계약서에 세부적으로 명기해야 한다고 한 두 가지는 무엇인가요?",
        "answer": "1. 직원에게 일임을 하는 사항; 2. 직원이 해서는 안되는 사항",
        "source_page": 38,
    },
    {
        "question": "당사자 간의 분쟁해결이 가장 손쉽고 합리적일 수 있다고 설명하면서도, 자본시장법 제55조와 관련해 유의하라고 한 금지 행위는 무엇인가요?",
        "answer": "1. 손실보전행위",
        "source_page": 41,
    },
    {
        "question": "발간사에서 최근 주요 이슈를 반영해 기존의 무엇을 보강한 증보판을 발간했다고 소개하나요?",
        "answer": "1. 분쟁조정사례·판례 핸드북",
        "source_page": 4,
    },
    {
        "question": "발간사에서 새롭게 추가했다고 소개한 중요 정보 두 가지는 무엇인가요?",
        "answer": "1. 금융사기에 대한 예방·대처법; 2. 모바일 폰을 활용한 투자 시 유의사항",
        "source_page": 4,
    },
    {
        "question": "공시정보 체크요령에서 증권회사 안내가 없어도 스스로 확인해야 한다고 든 CB 투자 관련 사항 두 가지는 무엇인가요?",
        "answer": "1. 전환권 행사시점; 2. 매수청구권에 관한 사항",
        "source_page": 27,
    },
    {
        "question": "투자자유형 분류기준의 자세한 내용은 한국금융투자협회 홈페이지의 어떤 경로에서 확인할 수 있나요?",
        "answer": "1. 한국금융투자협회 홈페이지; 2. 법규정보 시스템; 3. 모범규준",
        "source_page": 30,
    },
    {
        "question": "펀드 가입 절차 설명에서 '표준투자권유준칙'에 따라 투자자를 5등급 이상으로 분류할 때 제시한 다섯 유형은 무엇인가요?",
        "answer": "1. 안정형; 2. 안정추구형; 3. 위험·수익중립형; 4. 적극투자형; 5. 공격투자형",
        "source_page": 30,
    },
    {
        "question": "'투자자별 펀드잔고 통보' 서비스는 어떤 두 가지 정보를 어떤 방식으로 제공하며, 언제 제공받지 않을 수 있나요?",
        "answer": "1. 펀드잔고; 2. 개별 수익률 정보; 3. 전자우편 등; 4. 제공을 원하지 않을 경우 별도 신청",
        "source_page": 31,
    },
    {
        "question": "자산보관·관리보고서에는 어떤 네 가지 정보가 제공된다고 설명하나요?",
        "answer": "1. 펀드매니저 변동사항; 2. 약관 변경 사항; 3. 수익자 총회 의결 내용; 4. 운용상 위반사항·시정사항",
        "source_page": 32,
    },
    {
        "question": "'모바일폰 금융거래 10계명' 중 6번과 9번의 핵심 내용은 무엇인가요?",
        "answer": "1. 휴대폰 문자서비스(SMS), 일회용비밀번호(OTP) 이용하기; 2. 잠금기능을 설정하고 잠금비밀번호는 수시로 변경하기",
        "source_page": 26,
    },
    {
        "question": "임의매매에 따른 처벌 조항 설명에서 제시한 형사처벌 수준과 조문 번호는 무엇인가요?",
        "answer": "1. 5년 이하의 징역 또는 2억원 이하의 벌금; 2. 444",
        "source_page": 52,
    },
    {
        "question": "임의매매 설명에서 거래내역 확인과 계좌정보 관리에 관해 과실상계 예시로 든 고객 과실 두 가지는 무엇인가요?",
        "answer": "1. 장기간 거래내역 확인 소홀; 2. 계좌번호·비밀번호 관리 소홀",
        "source_page": 52,
    },
    {
        "question": "선물환 계약 불완전판매 사례 15에서 법원이 금융회사의 손해배상 비율을 전체 손해액의 몇 퍼센트로 본다고 판단했나요?",
        "answer": "1. 40%",
        "source_page": 102,
    },
    {
        "question": "금융투자상품 불완전판매 사례 17에서 투자자 A와 D의 투자금액은 각각 얼마인가요?",
        "answer": "1. 2억 4,300만원; 2. 1억 5,100여만원",
        "source_page": 104,
    },
    {
        "question": "당해 미수발생 증권 이후 반대매매 대상종목 선정 기준으로 제시한 세 가지 예시는 무엇인가요?",
        "answer": "1. 최근 매수 종목; 2. 종목코드 번호 선(후)순위; 3. 종목명 가나다순",
        "source_page": 115,
    },
    {
        "question": "반대매매 예시에서 195주가 7,000원에 체결된 것으로 가정할 경우 임의처분 금액은 약 얼마이며, 담보부족금액의 몇 배 수준인가요?",
        "answer": "1. 약 137만원; 2. 4.6배",
        "source_page": 115,
    },
    {
        "question": "피싱사기로 주민등록번호 등 개인정보를 알려줬을 경우 가까운 은행에 등록 요청하라고 한 시스템 이름은 무엇인가요?",
        "answer": "1. 개인정보 노출자 사고예방 시스템",
        "source_page": 141,
    },
    {
        "question": "보이스피싱 피해금 환급절차에서 금감원의 공고 기간과 피해금 환급 소요 기간은 각각 얼마인가요?",
        "answer": "1. 2개월; 2. 3개월 정도",
        "source_page": 141,
    },
    {
        "question": "대포폰 개설여부 조회는 어느 사이트에서 할 수 있으며, 함께 제공되는 서비스는 무엇인가요?",
        "answer": "1. www.msafer.or.kr; 2. 명의도용 사전차단 서비스",
        "source_page": 143,
    },
    {
        "question": "유사투자자문업 관련 판례 사례에서 B 증권투자 전문가가 배분 받은 비율과 유료회원의 월 가입료는 각각 얼마인가요?",
        "answer": "1. 50%; 2. 월 80만원",
        "source_page": 145,
    },
]

answer_key = [item["answer"] for item in evaluation_items]


def grade_predictions(questions, predicted_answers, model_name="gpt-5-mini"):
    def normalize_for_match(text: str) -> str:
        text = (text or "").replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(
            r"(^|;\s*)(\d+)\s*[.)]\s*",
            lambda match: f"{match.group(1)}{match.group(2)}. ",
            text,
        )
        text = re.sub(r"(^|;\s*)(\d+\.\s*)답\s+", r"\1\2", text)
        text = re.sub(r"\s*;\s*", "; ", text)
        text = re.sub(r"\s*,\s*", ", ", text)
        text = re.sub(r"\s*/\s*", " / ", text)
        text = re.sub(r"\s*→\s*", " → ", text)
        text = re.sub(r"§\s*", "", text)
        text = re.sub(r"\s*%\s*", "%", text)
        text = text.replace("‘", "").replace("’", "").replace("“", "").replace("”", "")
        text = re.sub(r"www\.\s*kofia\.or\.kr", "한국금융투자협회 홈페이지", text, flags=re.IGNORECASE)
        text = re.sub(r"투자자의\s+", "", text)
        text = re.sub(r"모바일폰\s+(?=잠금기능)", "", text)
        text = re.sub(r"(\d+개월)간\b", r"\1", text)
        text = re.sub(r"\s*상당\b", "", text)
        text = re.sub(r"에 관한 사항\b", "", text)
        text = re.sub(r"(?<=수익률)\s*정보\b", "", text)
        text = re.sub(r"등을?\s*(통해|통하여)?\s*제공(?:함|됨|됩니다)?", "등", text)
        text = re.sub(r"별도 신청\s*시\s*제공받지 않을 수 있음\.?", "별도 신청", text)
        return text.strip()

    def has_standard_answer_format(text: str) -> bool:
        normalized = normalize_for_match(text)
        if is_exact_no_info(normalized):
            return True

        parts = normalized.split("; ")
        if not parts:
            return False

        for expected_number, part in enumerate(parts, start=1):
            marker = f"{expected_number}. "
            if not part.startswith(marker) or not part[len(marker) :].strip():
                return False
        return True

    def answer_item_count(text: str) -> int:
        normalized = normalize_for_match(text)
        if is_exact_no_info(normalized):
            return 0
        return len(normalized.split("; "))

    def is_exact_no_info(text: str) -> bool:
        stripped = normalize_for_match(text).strip(" .,:;!?\"'`()[]{}")
        return stripped == "없는 정보"

    def has_format_violation(predicted: str, answer: str):
        raw = (predicted or "").strip()
        pred = normalize_for_match(predicted)
        ans = normalize_for_match(answer)

        if not raw:
            return True, "빈 답변"
        if pred == ans:
            return False, ""
        if "\n" in raw or "\r" in raw:
            return True, "줄바꿈이나 여러 줄 형식"
        if re.search(r"(?m)^\s*[-*•]", raw) or re.search(r"(?m)^\s*\d+[.)]", raw):
            if not has_standard_answer_format(predicted):
                return True, "표준 답안 번호 형식 아님"
        if re.match(r"^(정답|답변|답)\s*[:：]", raw):
            return True, "접두어"
        return False, ""

    grading_prompt = ChatPromptTemplate.from_template(
        """
너는 RAG 대회 자동 채점 시스템이다.
아래에는 질문, 모델 예측 답변, 정답이 주어진다.

채점 기준:
- 정답 표준 형식은 단일 답도 "1. 답", 여러 답은 "1. 답; 2. 답; 3. 답"처럼 한 줄 번호 목록이다
- 다만 채점은 형식보다 핵심 정보 일치를 우선한다
- 핵심 정보가 모두 맞고 순서를 이해할 수 있으면 조사, 접미어, 따옴표, "답" 같은 군더더기, "에 관한 사항", "정보", "상당", "간", "제공" 같은 가벼운 표현 차이는 감점하지 않고 1점이다
- 홈페이지 이름과 URL처럼 같은 위치를 가리키는 표현, "2개월"과 "2개월간", "월 80만원"과 "월 80만원 상당"처럼 의미가 같은 값 표현은 1점으로 본다
- 항목 수나 세미콜론 구분이 정답과 다르더라도 필요한 핵심 정보가 모두 명확히 들어 있고 불필요한 정보가 답을 흐리지 않으면 1점이다
- 문서에 정보가 없을 때만 "없는 정보"를 번호 없이 쓴다
- 숫자, 날짜, 코드, URL, "없는 정보" 같은 답은 의미가 바뀌지 않아야 한다
- 예측 답변이 정확히 "없는 정보"인데 정답이 존재하면 반드시 0점이다
- 답에 여러 요소가 필요한 문항은 주요 요소를 모두 맞히면 1점이다
- 상위 개념이나 행위명을 물었는데 하위 유형만 나열한 경우처럼 답의 방향은 맞지만 질문이 요구한 추상도와 다르면 0.5점이다
- 일부 요소가 빠졌거나, 정답 요소 중 일부만 맞았거나, 관련은 있지만 범위 밖 정보가 섞이면 0.5점이다
- 틀리거나 문서에 없는 내용을 지어내면 0점

반드시 아래 형식만 사용한다.
1번: 1점 (설명)
2번: 0.5점 (설명)
3번: 0점 (설명)

질문-답변 리스트에 적힌 문항번호를 그대로 사용한다.
문항번호를 1번부터 다시 매기지 않는다.

질문-답변 리스트:
{qa_pairs}
"""
    )

    forced_results = {}
    qa_rows = []
    pending_numbers = set()

    for idx in range(len(questions)):
        predicted = predicted_answers[idx]
        answer = answer_key[idx]
        number = idx + 1
        normalized_predicted = normalize_for_match(predicted)
        normalized_answer = normalize_for_match(answer)

        if normalized_predicted == normalized_answer:
            forced_results[number] = (
                f"{number}번: 1점 (설명: 출력 형식과 내용이 정답과 정확히 일치합니다)"
            )
            continue

        if is_exact_no_info(predicted) and not is_exact_no_info(answer):
            forced_results[number] = (
                f"{number}번: 0점 (설명: 예측이 '없는 정보'인데 정답은 문서에 존재함)"
            )
            continue

        format_violation, reason = has_format_violation(predicted, answer)
        if format_violation:
            forced_results[number] = (
                f"{number}번: 0점 (설명: 형식 위반 사유: {reason})"
            )
            continue

        qa_rows.append(
            f"문항번호: {number}번\n질문: {questions[idx]}\n예측: {predicted}\n정답: {answer}"
        )
        pending_numbers.add(number)

    llm_result = ""
    if qa_rows:
        llm = ChatOpenAI(model=model_name)
        parser = StrOutputParser()
        grading_chain = grading_prompt | llm | parser
        llm_result = grading_chain.invoke({"qa_pairs": "\n".join(qa_rows)})

    score_line_pattern = re.compile(
        r"(\d+)번\s*[:：]\s*(1(?:\.0)?|0(?:\.5|\.0)?)\s*점\s*(.*)"
    )
    for line in llm_result.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = score_line_pattern.search(stripped.replace("*", ""))
        if match:
            number = int(match.group(1))
            if number not in pending_numbers:
                continue
            score = f"{float(match.group(2)):g}"
            explanation = match.group(3).strip()
            if explanation and not explanation.startswith("("):
                explanation = f"(설명: {explanation})"
            if not explanation:
                explanation = "(설명: 자동 채점)"
            forced_results[number] = f"{number}번: {score}점 {explanation}"

    for number in range(1, len(questions) + 1):
        if number not in forced_results:
            forced_results[number] = (
                f"{number}번: 0점 (설명: 자동 채점 결과를 확인하지 못해 0점 처리)"
            )

    return "\n".join(forced_results[idx] for idx in range(1, len(questions) + 1))
