from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import fitz
from flask import Flask, jsonify, request, send_from_directory

import build_exam_practice_page as builder


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "generated_exam_page"
UPLOAD_DIR = ROOT / "uploads"
EXAM_DIR = WEB_DIR / "exams"
REGISTRY_PATH = EXAM_DIR / "registry.json"
QUESTION_PAGE_WIDTH = 1088

app = Flask(__name__, static_folder=None)


def safe_pdf_name(filename: str, fallback: str) -> str:
    name = Path(filename or fallback).name.replace(" ", "")
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def exam_id_from_name(filename: str) -> str:
    stem = Path(filename).stem
    ascii_id = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return ascii_id or f"exam_{datetime.now():%Y%m%d_%H%M%S}"


def load_embedded_exams() -> list[dict]:
    html_path = WEB_DIR / "2026_06_g1_math_practice.html"
    if not html_path.exists():
        return []
    html = html_path.read_text(encoding="utf-8")
    match = re.search(r"const embeddedExamFiles = (.*?);\n", html, re.S)
    if not match:
        match = re.search(r"const examFiles = (.*?);\n", html, re.S)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return []


def load_uploaded_exams() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data.get("exams", [])


def save_uploaded_exams(exams: list[dict]) -> None:
    EXAM_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps({"version": 1, "exams": exams}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def all_exams() -> list[dict]:
    exams = load_embedded_exams()
    uploaded = load_uploaded_exams()
    existing_ids = {exam.get("id") for exam in exams}
    exams.extend(exam for exam in uploaded if exam.get("id") not in existing_ids)
    return exams


def render_question_pages(question_pdf: Path, asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(question_pdf))
    for page_index, page in enumerate(doc):
        width_scale = QUESTION_PAGE_WIDTH / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(width_scale, width_scale), alpha=False)
        pix.save(str(asset_dir / f"page_{page_index + 1:02d}_problems.png"))


def render_uploaded_problem_images(
    asset_dir: Path,
    image_prefix: str,
    short_answers: dict[int, list[str]],
    answer_key: dict[int, str],
    scores: dict[int, int],
    explanations: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    problems: list[dict[str, object]] = []
    for number in range(1, builder.TOTAL_PROBLEMS + 1):
        page_no, x0, y0, x1, y1 = builder.PAGE_IMAGE_RECTS[number]
        page_image = asset_dir / f"page_{page_no:02d}_problems.png"
        if not page_image.exists():
            raise FileNotFoundError(f"문제지 PDF에서 {page_no}페이지를 찾을 수 없습니다.")

        doc = fitz.open(str(page_image))
        page = doc[0]
        clip = fitz.Rect(x0, max(0, y0 - builder.TOP_MARGIN_PX), x1, y1) & page.rect
        pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), clip=clip, alpha=False)
        image_name = f"problem_{number:02d}.png"
        pix.save(str(asset_dir / image_name))

        labels = short_answers.get(number, [])
        if number <= 21 and answer_key.get(number) in {"1", "2", "3", "4", "5"}:
            labels = []
        if number >= 22:
            labels = builder.DEFAULT_SHORT_ANSWER_LABELS.get(number, labels or ["정답"])

        explanation = explanations.get(number, {})
        problems.append(
            {
                "number": number,
                "page": page_no,
                "image": f"{image_prefix}/assets/{image_name}",
                "width": pix.width,
                "height": pix.height,
                "kind": "short" if labels else "choice",
                "labels": labels,
                "correct": answer_key.get(number, ""),
                "score": scores.get(number, 0),
                "explanation": explanation,
            }
        )
    return problems


def render_uploaded_explanations(answer_pdf: Path, asset_dir: Path, image_prefix: str) -> dict[int, dict[str, object]]:
    original_asset_dir = builder.ASSET_DIR
    try:
        builder.ASSET_DIR = asset_dir
        raw = builder.render_explanation_images(answer_pdf)
    finally:
        builder.ASSET_DIR = original_asset_dir

    converted: dict[int, dict[str, object]] = {}
    for number, info in raw.items():
        image_name = Path(str(info.get("image", ""))).name
        converted[number] = {
            "image": f"{image_prefix}/assets/{image_name}",
            "width": info.get("width", 0),
            "height": info.get("height", 0),
        }
    return converted


def process_uploaded_exam(question_pdf: Path, answer_pdf: Path) -> dict:
    exam_id = exam_id_from_name(question_pdf.name)
    exam_root = EXAM_DIR / exam_id
    asset_dir = exam_root / "assets"
    image_prefix = f"exams/{exam_id}"

    if exam_root.exists():
        shutil.rmtree(exam_root)
    asset_dir.mkdir(parents=True, exist_ok=True)

    render_question_pages(question_pdf, asset_dir)
    shutil.copyfile(answer_pdf, exam_root / "answer_explanation.pdf")

    answer_key = builder.extract_answer_key(answer_pdf)
    scores = builder.extract_problem_scores(question_pdf)
    explanations = render_uploaded_explanations(answer_pdf, asset_dir, image_prefix)
    short_answers = builder.detect_short_answer_numbers(question_pdf)
    problems = render_uploaded_problem_images(
        asset_dir,
        image_prefix,
        short_answers,
        answer_key,
        scores,
        explanations,
    )

    return {
        "id": exam_id,
        "name": question_pdf.name,
        "explanationPdf": f"{image_prefix}/answer_explanation.pdf",
        "uploadedAt": datetime.now().isoformat(timespec="seconds"),
        "problems": problems,
    }


@app.get("/api/exams")
def api_exams():
    return jsonify({"exams": all_exams()})


@app.post("/api/upload-exam")
def api_upload_exam():
    question = request.files.get("questionPdf")
    answer = request.files.get("answerPdf")
    if not question or not answer:
        return jsonify({"error": "문제지 PDF와 해설지 PDF를 모두 업로드하세요."}), 400

    question_name = safe_pdf_name(question.filename, "문제지.pdf")
    answer_name = safe_pdf_name(answer.filename, "해설지.pdf")
    if not question_name.lower().endswith(".pdf") or not answer_name.lower().endswith(".pdf"):
        return jsonify({"error": "PDF 파일만 업로드할 수 있습니다."}), 400

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    question_path = UPLOAD_DIR / question_name
    answer_path = UPLOAD_DIR / answer_name
    question.save(question_path)
    answer.save(answer_path)

    try:
        exam = process_uploaded_exam(question_path, answer_path)
    except Exception as exc:
        return jsonify({"error": f"PDF 전처리에 실패했습니다: {exc}"}), 500

    exams = [item for item in load_uploaded_exams() if item.get("id") != exam["id"]]
    exams.append(exam)
    save_uploaded_exams(exams)
    return jsonify({"exam": exam, "exams": all_exams()})


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "2026_06_g1_math_practice.html")


@app.get("/<path:path>")
def static_files(path: str):
    return send_from_directory(WEB_DIR, path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8600, debug=False)
