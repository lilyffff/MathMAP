from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in partial installs
    load_dotenv = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - reported through the app status
    PdfReader = None

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - app falls back to keyword scoring
    BM25Okapi = None


ROOT = Path(__file__).resolve().parent
DEFAULT_LIBRARY_DIR = ROOT / "data" / "math_mock_exams"
INDEX_PATH = ROOT / ".math_mock_exam_index.json"

ANSWER_HINTS = ("정답", "해설", "답지", "풀이", "answer", "solution", "solutions")
QUESTION_DIR_HINTS = ("question", "questions", "문제", "모의고사")
ANSWER_DIR_HINTS = ("answer", "answers", "solution", "solutions", "정답", "해설", "답지")
TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
PROBLEM_RE = re.compile(r"(?m)(?:^|\n)\s*((?:[1-9]|[12][0-9]|30))\s*[\.)]\s+")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall((text or "").lower()):
        tokens.append(raw)
        if re.fullmatch(r"[가-힣]+", raw) and len(raw) >= 2:
            tokens.extend(raw[i : i + 2] for i in range(len(raw) - 1))
    return tokens


def safe_id(value: str) -> str:
    return sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def classify_pdf(path: Path, library_dir: Path) -> str:
    name = path.name.lower()
    parent_bits = [part.lower() for part in path.relative_to(library_dir).parts[:-1]]
    if any(hint in name for hint in ANSWER_HINTS):
        return "answer"
    if any(any(hint in bit for hint in ANSWER_DIR_HINTS) for bit in parent_bits):
        return "answer"
    if any(any(hint in bit for hint in QUESTION_DIR_HINTS) for bit in parent_bits):
        return "question"
    return "question"


def split_problem_blocks(text: str) -> list[tuple[str | None, str]]:
    cleaned = text.replace("\x00", " ")
    matches = list(PROBLEM_RE.finditer(cleaned))
    if len(matches) < 2:
        return []

    blocks: list[tuple[str | None, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        block = norm_space(cleaned[start:end])
        if len(block) >= 40:
            blocks.append((match.group(1), block))
    return blocks


def extract_pdf_docs(path: Path, file_id: str, kind: str) -> tuple[list[dict[str, Any]], int, str | None]:
    if PdfReader is None:
        return [], 0, "pypdf가 설치되어 있지 않습니다. `pip install -r requirements.txt`를 먼저 실행하세요."

    docs: list[dict[str, Any]] = []
    try:
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
        for page_index, page in enumerate(reader.pages):
            page_no = page_index + 1
            text = page.extract_text() or ""
            blocks = split_problem_blocks(text)
            if not blocks:
                blocks = [(None, norm_space(text))]

            for block_index, (problem_no, block_text) in enumerate(blocks):
                if not block_text:
                    continue
                doc_id = safe_id(f"{path}|{page_no}|{problem_no}|{block_index}|{block_text[:80]}")
                title = f"{path.name} - {page_no}쪽"
                if problem_no:
                    title += f" - {problem_no}번"
                docs.append(
                    {
                        "id": doc_id,
                        "file_id": file_id,
                        "kind": kind,
                        "file_name": path.name,
                        "page": page_no,
                        "problem_no": problem_no,
                        "title": title,
                        "text": block_text,
                    }
                )
        return docs, total_pages, None
    except Exception as exc:
        return [], 0, f"{path.name} 읽기 실패: {exc}"


def build_index(library_dir: Path) -> dict[str, Any]:
    library_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(library_dir.rglob("*.pdf"))
    files: dict[str, dict[str, Any]] = {}
    docs: list[dict[str, Any]] = []
    errors: list[str] = []

    for pdf in pdfs:
        kind = classify_pdf(pdf, library_dir)
        file_id = safe_id(str(pdf.resolve()))
        file_docs, total_pages, error = extract_pdf_docs(pdf, file_id, kind)
        if error:
            errors.append(error)
        files[file_id] = {
            "id": file_id,
            "name": pdf.name,
            "path": str(pdf.resolve()),
            "relative_path": str(pdf.relative_to(library_dir)),
            "kind": kind,
            "total_pages": total_pages,
        }
        docs.extend(file_docs)

    index = {
        "version": 1,
        "built_at": now_iso(),
        "library_dir": str(library_dir.resolve()),
        "files": files,
        "docs": docs,
        "errors": errors,
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def load_index(force: bool = False) -> dict[str, Any]:
    if load_dotenv is not None:
        load_dotenv(override=True)

    library_dir = Path(os.getenv("MATH_MOCK_EXAM_DIR", str(DEFAULT_LIBRARY_DIR))).resolve()
    if force or not INDEX_PATH.exists():
        return build_index(library_dir)

    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return build_index(library_dir)

    if Path(index.get("library_dir", "")).resolve() != library_dir:
        return build_index(library_dir)
    return index


def bm25_rank(query: str, docs: list[dict[str, Any]], top_k: int = 10) -> list[tuple[float, dict[str, Any]]]:
    if not docs:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    lower_query = query.lower().strip()
    scored: list[tuple[float, dict[str, Any]]] = []
    if BM25Okapi is not None:
        corpus = [tokenize(doc.get("text", "")) for doc in docs]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query_tokens)
        for score, doc in zip(scores, docs):
            text = doc.get("text", "").lower()
            bonus = 4.0 if lower_query and lower_query in text else 0.0
            if doc.get("problem_no") and doc["problem_no"] in query_tokens:
                bonus += 2.0
            final_score = float(score) + bonus
            if final_score > 0:
                scored.append((final_score, doc))
    else:
        query_set = set(query_tokens)
        for doc in docs:
            doc_tokens = tokenize(doc.get("text", ""))
            overlap = sum(1 for token in doc_tokens if token in query_set)
            bonus = 4 if lower_query and lower_query in doc.get("text", "").lower() else 0
            final_score = float(overlap + bonus)
            if final_score > 0:
                scored.append((final_score, doc))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:top_k]


def file_digit_tokens(name: str) -> set[str]:
    return set(re.findall(r"\d{1,6}", name))


def find_answer_file(index: dict[str, Any], problem_doc: dict[str, Any]) -> dict[str, Any] | None:
    files = list(index.get("files", {}).values())
    answers = [file for file in files if file.get("kind") == "answer"]
    if not answers:
        return None
    if len(answers) == 1:
        return answers[0]

    question_file = index["files"].get(problem_doc.get("file_id"), {})
    q_digits = file_digit_tokens(question_file.get("name", ""))
    q_stem = re.sub(r"[^가-힣a-z0-9]+", "", Path(question_file.get("name", "")).stem.lower())

    best_score = -1
    best_answer = answers[0]
    for answer in answers:
        a_digits = file_digit_tokens(answer.get("name", ""))
        a_stem = re.sub(r"[^가-힣a-z0-9]+", "", Path(answer.get("name", "")).stem.lower())
        score = len(q_digits & a_digits) * 5
        for hint in ANSWER_HINTS:
            a_stem = a_stem.replace(hint, "")
        if q_stem and (q_stem in a_stem or a_stem in q_stem):
            score += 4
        if score > best_score:
            best_score = score
            best_answer = answer
    return best_answer


def answer_context(index: dict[str, Any], problem_doc: dict[str, Any]) -> dict[str, Any]:
    answer_file = find_answer_file(index, problem_doc)
    if not answer_file:
        return {"answer_file": None, "answer_docs": [], "answer_page": None}

    candidates = [
        doc
        for doc in index.get("docs", [])
        if doc.get("kind") == "answer" and doc.get("file_id") == answer_file.get("id")
    ]
    query = " ".join(
        part
        for part in [
            problem_doc.get("problem_no") or "",
            problem_doc.get("title") or "",
            problem_doc.get("text", "")[:700],
            "정답 해설 풀이",
        ]
        if part
    )
    ranked = bm25_rank(query, candidates, top_k=3)
    docs = [doc for _, doc in ranked] or candidates[:3]
    return {
        "answer_file": answer_file,
        "answer_docs": docs,
        "answer_page": docs[0]["page"] if docs else 1,
    }


def make_pdf_url(file_id: str, page: int | None = None) -> str:
    suffix = f"#page={page}&view=FitH" if page else "#view=FitH"
    return f"/pdf/{quote(file_id)}{suffix}"


def explain_with_llm(problem_doc: dict[str, Any], answer_docs: list[dict[str, Any]], student_answer: str) -> str:
    if load_dotenv is not None:
        load_dotenv(override=True)
    if not os.getenv("OPENAI_API_KEY"):
        context = "\n\n".join(doc.get("text", "")[:900] for doc in answer_docs)
        return (
            "OPENAI_API_KEY가 설정되어 있지 않아 자동 채점과 풀이 설명은 실행하지 않았습니다.\n\n"
            "아래 정답 PDF 문맥을 보고 학생 답과 비교하세요.\n\n"
            f"{context or '정답 PDF에서 추출된 텍스트가 없습니다. 화면의 정답 PDF를 직접 확인하세요.'}"
        )

    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        return f"langchain-openai를 불러오지 못해 AI 피드백을 생성하지 못했습니다: {exc}"

    answer_context_text = "\n\n".join(
        f"[정답 PDF {doc.get('page')}쪽]\n{doc.get('text', '')[:1400]}" for doc in answer_docs
    )
    prompt = f"""
너는 고등학교 수학 모의고사 풀이를 도와주는 친절한 선생님이다.
학생의 답과 풀이를 정답 PDF 문맥과 비교하라.

규칙:
- 정답 여부를 먼저 한 줄로 말한다. 예: "판정: 정답" 또는 "판정: 오답"
- 학생 답이 틀렸으면, 틀린 지점을 짚고 올바른 풀이 과정을 단계별로 설명한다.
- 정답 PDF 문맥에 없는 내용을 확정적으로 지어내지 말고, 부족하면 "정답 PDF 문맥만으로는 확인이 어렵다"고 말한다.
- 한국어로, 고등학생이 이해할 수 있게 간결하게 설명한다.

[문제]
출처: {problem_doc.get('title')}
{problem_doc.get('text', '')[:2200]}

[학생 답과 풀이]
{student_answer}

[정답 PDF 문맥]
{answer_context_text}
"""
    try:
        llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-5-nano"), temperature=0)
        result = llm.invoke(prompt)
        return getattr(result, "content", str(result)).strip()
    except Exception as exc:
        return f"AI 피드백 생성 중 오류가 발생했습니다: {exc}"


@dataclass
class JsonResponse:
    payload: dict[str, Any]
    status: HTTPStatus = HTTPStatus.OK


class MockExamHandler(BaseHTTPRequestHandler):
    server_version = "MockExamMathApp/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{now_iso()}] {self.address_string()} {fmt % args}")

    def send_json(self, response: JsonResponse) -> None:
        body = json.dumps(response.payload, ensure_ascii=False).encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_text(APP_HTML)
                return
            if parsed.path == "/api/status":
                self.send_json(JsonResponse(status_payload(load_index())))
                return
            if parsed.path == "/api/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                self.send_json(JsonResponse(search_payload(query)))
                return
            if parsed.path.startswith("/api/problem/"):
                problem_id = unquote(parsed.path.rsplit("/", 1)[-1])
                self.send_json(JsonResponse(problem_payload(problem_id)))
                return
            if parsed.path.startswith("/api/answer/"):
                problem_id = unquote(parsed.path.rsplit("/", 1)[-1])
                self.send_json(JsonResponse(answer_payload(problem_id)))
                return
            if parsed.path.startswith("/pdf/"):
                self.serve_pdf(unquote(parsed.path.rsplit("/", 1)[-1]))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception:
            traceback.print_exc()
            self.send_json(JsonResponse({"error": "서버 오류가 발생했습니다."}, HTTPStatus.INTERNAL_SERVER_ERROR))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/reindex":
                index = load_index(force=True)
                self.send_json(JsonResponse(status_payload(index)))
                return
            if parsed.path == "/api/check":
                body = self.read_json_body()
                self.send_json(JsonResponse(check_payload(body)))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception:
            traceback.print_exc()
            self.send_json(JsonResponse({"error": "서버 오류가 발생했습니다."}, HTTPStatus.INTERNAL_SERVER_ERROR))

    def serve_pdf(self, file_id: str) -> None:
        index = load_index()
        file_info = index.get("files", {}).get(file_id)
        if not file_info:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = Path(file_info["path"]).resolve()
        library_dir = Path(index["library_dir"]).resolve()
        if library_dir not in path.parents and path != library_dir:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        ctype = mimetypes.guess_type(path.name)[0] or "application/pdf"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{quote(path.name)}"')
        self.end_headers()
        self.wfile.write(data)


def status_payload(index: dict[str, Any]) -> dict[str, Any]:
    files = list(index.get("files", {}).values())
    question_count = sum(1 for file in files if file.get("kind") == "question")
    answer_count = sum(1 for file in files if file.get("kind") == "answer")
    return {
        "library_dir": index.get("library_dir"),
        "built_at": index.get("built_at"),
        "question_files": question_count,
        "answer_files": answer_count,
        "chunks": len(index.get("docs", [])),
        "errors": index.get("errors", []),
    }


def public_problem(doc: dict[str, Any], score: float | None = None) -> dict[str, Any]:
    preview = norm_space(doc.get("text", ""))[:260]
    payload = {
        "id": doc["id"],
        "title": doc.get("title"),
        "file_id": doc.get("file_id"),
        "file_name": doc.get("file_name"),
        "page": doc.get("page"),
        "problem_no": doc.get("problem_no"),
        "text": doc.get("text", ""),
        "preview": preview,
        "pdf_url": make_pdf_url(doc["file_id"], doc.get("page")),
    }
    if score is not None:
        payload["score"] = round(score, 3)
    return payload


def search_payload(query: str) -> dict[str, Any]:
    index = load_index()
    docs = [doc for doc in index.get("docs", []) if doc.get("kind") == "question"]
    ranked = bm25_rank(query, docs, top_k=20)
    return {
        "query": query,
        "results": [public_problem(doc, score) for score, doc in ranked],
        "status": status_payload(index),
    }


def find_problem(index: dict[str, Any], problem_id: str) -> dict[str, Any] | None:
    for doc in index.get("docs", []):
        if doc.get("id") == problem_id and doc.get("kind") == "question":
            return doc
    return None


def problem_payload(problem_id: str) -> dict[str, Any]:
    index = load_index()
    problem = find_problem(index, problem_id)
    if not problem:
        return {"error": "문제를 찾지 못했습니다."}
    return {"problem": public_problem(problem)}


def answer_payload(problem_id: str) -> dict[str, Any]:
    index = load_index()
    problem = find_problem(index, problem_id)
    if not problem:
        return {"error": "문제를 찾지 못했습니다."}
    ctx = answer_context(index, problem)
    answer_file = ctx["answer_file"]
    if not answer_file:
        return {"answer_file": None, "message": "연결된 정답 PDF를 찾지 못했습니다."}
    return {
        "answer_file": answer_file,
        "answer_page": ctx["answer_page"],
        "answer_pdf_url": make_pdf_url(answer_file["id"], ctx["answer_page"]),
        "answer_context": [public_problem(doc) for doc in ctx["answer_docs"]],
    }


def check_payload(body: dict[str, Any]) -> dict[str, Any]:
    index = load_index()
    problem_id = body.get("problem_id", "")
    student_answer = body.get("student_answer", "").strip()
    problem = find_problem(index, problem_id)
    if not problem:
        return {"error": "문제를 찾지 못했습니다."}
    if not student_answer:
        return {"error": "학생 답과 풀이를 먼저 입력하세요."}
    ctx = answer_context(index, problem)
    feedback = explain_with_llm(problem, ctx["answer_docs"], student_answer)
    return {
        "feedback": feedback,
        "answer": answer_payload(problem_id),
    }


APP_HTML = r"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>모의고사 수학 풀이 앱</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #687382;
      --line: #d9dee7;
      --blue: #2563eb;
      --green: #0f766e;
      --red: #b42318;
      --soft: #eef4ff;
      --shadow: 0 10px 24px rgba(18, 28, 45, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Malgun Gothic", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    button, input, textarea { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      border-radius: 8px;
      min-height: 38px;
      padding: 0 12px;
      cursor: pointer;
    }
    button.primary { background: var(--blue); color: white; border-color: var(--blue); }
    button.good { background: var(--green); color: white; border-color: var(--green); }
    button:disabled { cursor: not-allowed; opacity: .55; }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    header {
      display: flex;
      gap: 16px;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.92);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    h1 {
      margin: 0;
      font-size: 19px;
      letter-spacing: 0;
      white-space: nowrap;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .main {
      display: grid;
      grid-template-columns: 330px minmax(0, 1fr) 390px;
      gap: 14px;
      padding: 14px;
      min-height: 0;
    }
    aside, section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-height: 0;
    }
    .search-panel {
      display: grid;
      grid-template-rows: auto auto 1fr;
      padding: 12px;
      gap: 10px;
    }
    .search-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 40px;
      padding: 0 12px;
    }
    .hint { color: var(--muted); font-size: 13px; line-height: 1.45; }
    .results {
      overflow: auto;
      display: grid;
      align-content: start;
      gap: 8px;
      padding-right: 2px;
    }
    .result {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 10px;
      text-align: left;
      min-height: 86px;
    }
    .result.active { border-color: var(--blue); background: var(--soft); }
    .result strong { display: block; font-size: 14px; margin-bottom: 5px; }
    .result span { display: block; color: var(--muted); font-size: 12px; line-height: 1.35; }
    .problem-panel {
      display: grid;
      grid-template-rows: auto minmax(280px, 1fr) auto;
      overflow: hidden;
    }
    .panel-head {
      padding: 12px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .title-block { min-width: 0; }
    .title-block h2 {
      margin: 0 0 4px;
      font-size: 16px;
      letter-spacing: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: #edf2f7;
      color: #405064;
      font-size: 12px;
    }
    .viewer {
      display: grid;
      grid-template-rows: minmax(220px, 1fr) minmax(120px, auto);
      min-height: 0;
    }
    iframe {
      width: 100%;
      height: 100%;
      border: 0;
      background: #f1f3f6;
    }
    .text-box {
      border-top: 1px solid var(--line);
      padding: 12px;
      overflow: auto;
      max-height: 220px;
      color: #283443;
      line-height: 1.55;
      font-size: 14px;
      white-space: pre-wrap;
    }
    .answer-panel {
      display: grid;
      grid-template-rows: auto minmax(220px, 1fr) auto;
      overflow: hidden;
    }
    .work {
      padding: 12px;
      display: grid;
      grid-template-rows: auto 150px auto minmax(190px, 1fr);
      gap: 10px;
      min-height: 0;
    }
    textarea {
      width: 100%;
      min-height: 130px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      resize: vertical;
      line-height: 1.45;
    }
    canvas {
      width: 100%;
      height: 150px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      touch-action: none;
    }
    .tools { display: flex; gap: 8px; flex-wrap: wrap; }
    .feedback {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      overflow: auto;
      white-space: pre-wrap;
      line-height: 1.5;
      background: #fbfcfe;
      color: #263342;
    }
    .empty {
      height: 100%;
      display: grid;
      place-items: center;
      color: var(--muted);
      text-align: center;
      padding: 18px;
      line-height: 1.5;
    }
    @media (max-width: 1180px) {
      .main { grid-template-columns: 300px minmax(0, 1fr); }
      .answer-panel { grid-column: 1 / -1; min-height: 540px; }
    }
    @media (max-width: 760px) {
      header { align-items: flex-start; flex-direction: column; }
      h1 { white-space: normal; }
      .main { grid-template-columns: 1fr; padding: 10px; }
      .search-panel, .problem-panel, .answer-panel { min-height: 460px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div>
        <h1>모의고사 수학 풀이 앱</h1>
        <div id="status" class="status">색인 상태를 확인하는 중...</div>
      </div>
      <button id="reindexBtn" title="PDF 폴더를 다시 읽어 검색 색인을 만듭니다.">↻ 색인 갱신</button>
    </header>

    <main class="main">
      <aside class="search-panel">
        <div class="search-row">
          <input id="query" value="수열" placeholder="단원명 또는 키워드" />
          <button id="searchBtn" class="primary" title="검색">검색</button>
        </div>
        <div class="hint" id="libraryHint"></div>
        <div id="results" class="results"></div>
      </aside>

      <section class="problem-panel">
        <div class="panel-head">
          <div class="title-block">
            <h2 id="problemTitle">문제를 선택하세요</h2>
            <div class="chips" id="problemMeta"></div>
          </div>
          <button id="answerBtn" class="good" disabled title="정답 PDF를 엽니다.">정답 보기</button>
        </div>
        <div id="problemViewer" class="viewer">
          <div class="empty">왼쪽에서 “수열”처럼 단원명을 검색하면 관련 문제가 한 개씩 표시됩니다.</div>
        </div>
        <div class="panel-head">
          <div class="tools">
            <button id="prevBtn" disabled title="이전 문제">←</button>
            <button id="nextBtn" disabled title="다음 문제">→</button>
          </div>
          <span class="hint" id="position"></span>
        </div>
      </section>

      <section class="answer-panel">
        <div class="panel-head">
          <div class="title-block">
            <h2>풀이 공간</h2>
            <div class="hint">최종 답과 풀이 과정을 적은 뒤 비교하세요.</div>
          </div>
        </div>
        <div class="work">
          <textarea id="studentAnswer" placeholder="예: 정답 ③. 등차수열의 합 공식을 이용하면 ..."></textarea>
          <canvas id="scratch" width="720" height="300"></canvas>
          <div class="tools">
            <button id="clearCanvas" title="풀이판 지우기">지우기</button>
            <button id="checkBtn" class="primary" disabled title="학생 답과 정답 PDF 문맥을 비교합니다.">답 비교</button>
          </div>
          <div id="feedback" class="feedback">정답 보기 또는 답 비교 결과가 여기에 표시됩니다.</div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const state = { results: [], current: -1, problem: null };
    const $ = (id) => document.getElementById(id);

    async function api(url, options = {}) {
      const res = await fetch(url, options);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return await res.json();
    }

    function setStatus(status) {
      $("status").textContent = `문제 PDF ${status.question_files}개 · 정답 PDF ${status.answer_files}개 · 검색 조각 ${status.chunks}개 · ${status.built_at || "-"}`;
      $("libraryHint").textContent = `PDF 위치: ${status.library_dir}`;
      if (status.errors && status.errors.length) {
        $("libraryHint").textContent += ` · 오류 ${status.errors.length}건`;
      }
    }

    function chip(text) {
      const el = document.createElement("span");
      el.className = "chip";
      el.textContent = text;
      return el;
    }

    function renderResults() {
      const box = $("results");
      box.innerHTML = "";
      if (!state.results.length) {
        box.innerHTML = '<div class="empty">검색 결과가 없습니다. PDF에 텍스트가 들어 있는지 확인하거나 색인을 갱신하세요.</div>';
        return;
      }
      state.results.forEach((item, index) => {
        const btn = document.createElement("button");
        btn.className = `result ${index === state.current ? "active" : ""}`;
        btn.innerHTML = `<strong>${item.title}</strong><span>${item.preview || "미리보기 텍스트 없음"}</span>`;
        btn.onclick = () => selectProblem(index);
        box.appendChild(btn);
      });
    }

    function renderProblem(problem) {
      $("problemTitle").textContent = problem.title;
      $("problemMeta").innerHTML = "";
      $("problemMeta").append(
        chip(problem.file_name),
        chip(`${problem.page}쪽`),
        chip(problem.problem_no ? `${problem.problem_no}번` : "페이지 단위")
      );
      $("problemViewer").innerHTML = `
        <iframe title="문제 PDF" src="${problem.pdf_url}"></iframe>
        <div class="text-box">${escapeHtml(problem.text || "PDF에서 추출된 텍스트가 없습니다. 위 PDF 화면을 확인하세요.")}</div>
      `;
      $("answerBtn").disabled = false;
      $("checkBtn").disabled = false;
      $("prevBtn").disabled = state.current <= 0;
      $("nextBtn").disabled = state.current >= state.results.length - 1;
      $("position").textContent = `${state.current + 1} / ${state.results.length}`;
    }

    function escapeHtml(text) {
      return text.replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    }

    async function selectProblem(index) {
      state.current = index;
      renderResults();
      const data = await api(`/api/problem/${encodeURIComponent(state.results[index].id)}`);
      state.problem = data.problem;
      renderProblem(data.problem);
      $("feedback").textContent = "풀이를 작성한 뒤 정답 보기 또는 답 비교를 누르세요.";
    }

    async function search() {
      $("results").innerHTML = '<div class="empty">검색 중...</div>';
      const q = $("query").value.trim();
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
      setStatus(data.status);
      state.results = data.results;
      state.current = -1;
      state.problem = null;
      renderResults();
      if (state.results.length) await selectProblem(0);
    }

    async function showAnswer() {
      if (!state.problem) return;
      $("feedback").textContent = "정답 PDF를 찾는 중...";
      const data = await api(`/api/answer/${encodeURIComponent(state.problem.id)}`);
      if (!data.answer_file) {
        $("feedback").textContent = data.message || "정답 PDF를 찾지 못했습니다.";
        return;
      }
      $("feedback").innerHTML = `<iframe title="정답 PDF" src="${data.answer_pdf_url}" style="height:320px;border:1px solid var(--line);border-radius:8px;"></iframe>`;
    }

    async function checkAnswer() {
      if (!state.problem) return;
      $("feedback").textContent = "AI가 학생 답과 정답 PDF를 비교하는 중...";
      const data = await api("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          problem_id: state.problem.id,
          student_answer: $("studentAnswer").value
        })
      });
      $("feedback").textContent = data.error || data.feedback || "결과가 없습니다.";
    }

    async function reindex() {
      $("reindexBtn").disabled = true;
      $("status").textContent = "PDF 색인을 다시 만드는 중...";
      try {
        const data = await api("/api/reindex", { method: "POST" });
        setStatus(data);
        await search();
      } finally {
        $("reindexBtn").disabled = false;
      }
    }

    function setupCanvas() {
      const canvas = $("scratch");
      const ctx = canvas.getContext("2d");
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.strokeStyle = "#1f2937";
      let drawing = false;
      const pos = (event) => {
        const rect = canvas.getBoundingClientRect();
        const point = event.touches ? event.touches[0] : event;
        return {
          x: (point.clientX - rect.left) * canvas.width / rect.width,
          y: (point.clientY - rect.top) * canvas.height / rect.height
        };
      };
      const start = (event) => { drawing = true; const p = pos(event); ctx.beginPath(); ctx.moveTo(p.x, p.y); event.preventDefault(); };
      const move = (event) => { if (!drawing) return; const p = pos(event); ctx.lineTo(p.x, p.y); ctx.stroke(); event.preventDefault(); };
      const end = () => { drawing = false; };
      canvas.addEventListener("mousedown", start);
      canvas.addEventListener("mousemove", move);
      window.addEventListener("mouseup", end);
      canvas.addEventListener("touchstart", start, { passive: false });
      canvas.addEventListener("touchmove", move, { passive: false });
      canvas.addEventListener("touchend", end);
      $("clearCanvas").onclick = () => ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    $("searchBtn").onclick = search;
    $("query").addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });
    $("answerBtn").onclick = showAnswer;
    $("checkBtn").onclick = checkAnswer;
    $("reindexBtn").onclick = reindex;
    $("prevBtn").onclick = () => state.current > 0 && selectProblem(state.current - 1);
    $("nextBtn").onclick = () => state.current < state.results.length - 1 && selectProblem(state.current + 1);

    setupCanvas();
    api("/api/status").then(setStatus).then(search).catch(err => {
      $("status").textContent = `앱 초기화 오류: ${err.message}`;
    });
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="고등학교 모의고사 수학 PDF 검색/풀이 앱")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--reindex", action="store_true", help="시작할 때 PDF 색인을 다시 만듭니다.")
    args = parser.parse_args()

    if args.reindex:
        load_index(force=True)
    else:
        load_index(force=False)

    server = ThreadingHTTPServer((args.host, args.port), MockExamHandler)
    print(f"모의고사 수학 풀이 앱: http://{args.host}:{args.port}")
    print(f"PDF 폴더: {os.getenv('MATH_MOCK_EXAM_DIR', str(DEFAULT_LIBRARY_DIR))}")
    server.serve_forever()


if __name__ == "__main__":
    main()
