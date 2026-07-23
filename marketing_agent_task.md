# 태스크 목적: 깃허브 페이지 기반 개인 채널 콘텐츠 자율 배포

## 1. 사용 툴 및 환경 세팅
- GitHub MCP 서버 활성화
- 대상 레포지토리: `3hongwork-hub/gitblog-agent`
- 대상 브랜치: `main`
- 타겟 디렉토리: `_posts/`

## 2. 에이전트 역할 정의
- **초안 에이전트 (Writer)**: 개발, AI 기술 트렌드, 생산성 도구를 주제로 깊이 있고 유익한 기술 블로그 글을 작성함. 독자층은 주니어~미드레벨 개발자 및 IT 종사자.
- **검증 에이전트 (SEO/Editor Checker)**: 작성된 콘텐츠의 품질을 채점함. 아래 조건을 만족해야 합격(PASS) 처리함.
  1. 제목과 본문에 핵심 키워드가 자연스럽게 3회 이상 녹아 있는가?
  2. 코드 블록(Code Block) 문법이 정확하게 적용되었는가?
  3. 프론트 매터(Front Matter: layout, title, date, categories, tags 등)가 완벽한 Jekyll 포맷으로 최상단에 위치하는가?

### 프론트 매터 예시
```yaml
---
layout: post
title: "2026년 최신 AI 개발 에이전트 동향과 안티그래비티 활용법"
date: 2026-07-23 15:00:00 +0900
categories: [AI, Antigravity]
tags: [Agent, Gemini, Automation]
---
```

## 3. 루프 실행 규칙 (Antigravity Iteration Loop)
1. 초안 에이전트가 지정된 토픽을 바탕으로 마크다운 포맷 파일 형태로 글을 작성한다.
2. 검증 에이전트가 글을 읽고 피드백 및 점수(100점 만점)를 부여한다.
3. 점수가 **90점 미만**인 경우, 구체적인 수정 요청 사항과 함께 초안 에이전트에게 돌려보내고 루프를 재가동한다. (최대 5회 반복)
4. 점수가 **90점 이상**이거나 루프 통과 기준에 도달하면 최종 마크다운 결과물을 확정한다.

## 4. 최종 배포 규칙 (GitHub Push)
- 합격한 마크다운 파일의 이름을 `YYYY-MM-DD-글제목.md` 형식(영문/숫자 하이픈 권장)으로 지정한다.
- GitHub MCP를 사용하여 대상 레포지토리(`3hongwork-hub/gitblog-agent`)의 `main` 브랜치 내 `_posts/` 폴더에 직접 파일 변경 사항을 커밋 및 푸시(Commit & Push)한다.
