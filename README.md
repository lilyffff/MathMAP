# MathMAP

고등학교 수학 모의고사 풀이용 반응형 웹앱입니다.

## 실행

```powershell
python -m http.server 8600 --bind 127.0.0.1 -d generated_exam_page
```

브라우저에서 엽니다.

```text
http://127.0.0.1:8600/2026_06_g1_math_practice.html
```

## 로그인

- 학생: 학번 `10101`, 초기 패스워드 `1`
- 교사: 휴대폰 번호, 초기 패스워드 `123`
- 관리자: 앱 이름 `Math맵` 클릭, ID `lily.jeongwon@gmail.com`, 패스워드 `123`

## 배포

GitHub Pages는 루트 `index.html`에서 `generated_exam_page/2026_06_g1_math_practice.html`로 이동합니다.
