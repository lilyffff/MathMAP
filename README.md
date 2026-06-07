# MathMAP
[EBSi](https://www.ebsi.co.kr/ebs/xip/xipa/retrieveSCVMainInfo.ebs?irecord=202603241&targetCd=D100&cookieGradeVal=high1#none;)
고등학교 수학 모의고사 풀이용 반응형 웹앱입니다.

## 실행

업로드 기능까지 사용하려면 서버 모드로 실행합니다.

```powershell
python mathmap_server.py
```

브라우저에서 엽니다.

```text
http://127.0.0.1:8600/
```

정적 파일만 확인할 때는 아래처럼 실행할 수도 있습니다.

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

관리자 PDF 업로드는 파일 저장과 PDF 전처리가 필요하므로 GitHub Pages가 아니라 `mathmap_server.py` 서버 모드에서 동작합니다.
