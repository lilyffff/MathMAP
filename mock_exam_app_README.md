# 모의고사 수학 풀이 앱

## PDF 배치

기본 폴더는 `data/math_mock_exams`입니다.

권장 구조:

```text
data/math_mock_exams/
  questions/
    2026_03_고3_수학.pdf
    2026_04_고3_수학.pdf
  answers/
    2026_03_고3_수학_정답해설.pdf
    2026_04_고3_수학_정답해설.pdf
```

파일명이나 폴더명에 `정답`, `해설`, `답지`, `answer`, `solution`이 들어 있으면 정답 PDF로 분류합니다. 나머지는 문제 PDF로 분류합니다.

## 실행

```bash
pip install -r requirements.txt
python mock_exam_app.py --reindex
```

브라우저에서 `http://127.0.0.1:8501`을 엽니다.

다른 위치에 PDF가 있으면:

```bash
$env:MATH_MOCK_EXAM_DIR="C:\path\to\mock_exam_pdfs"
python mock_exam_app.py --reindex
```

## 동작

- 학생이 `수열` 같은 단원명을 입력하면 문제 PDF에서 관련 페이지 또는 문제 조각을 검색합니다.
- 문제 PDF 원본 페이지와 추출 텍스트를 함께 보여줍니다.
- 학생은 풀이 입력칸과 손풀이 캔버스에 풀이를 작성할 수 있습니다.
- `정답 보기`를 누르면 매칭되는 정답 PDF를 엽니다.
- `답 비교`를 누르면 `.env`의 `OPENAI_API_KEY`가 있을 때 학생 답과 정답 PDF 문맥을 비교해 오답 풀이 설명을 생성합니다.

PDF가 이미지 스캔본이면 `pypdf`가 텍스트를 추출하지 못해 검색 품질이 낮을 수 있습니다. 이 경우 OCR 처리된 PDF를 넣는 것이 좋습니다.
