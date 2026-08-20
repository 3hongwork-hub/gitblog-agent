# Gemini API를 활용해 daily 블로그 포스트 마크다운 파일 생성 및 README.md 목록과 최신 내용 요약을 자동 업데이트하는 스크립트
import datetime
import glob
import json
import os
import re
import time
import urllib.error
import urllib.request

def parse_post(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    filename = os.path.basename(filepath)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    date_str = date_match.group(1) if date_match else ""
    
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    title = filename
    categories = ""
    tags = ""
    body = content
    
    if fm_match:
        front_matter = fm_match.group(1)
        body = fm_match.group(2).strip()
        
        t_match = re.search(r'title:\s*["\']?(.*?)["\']?\s*\n', front_matter)
        if t_match:
            title = t_match.group(1).strip()
            
        c_match = re.search(r'categories:\s*\[?(.*?)\]?\s*\n', front_matter)
        if c_match:
            categories = c_match.group(1).strip()
            
        tg_match = re.search(r'tags:\s*\[?(.*?)\]?\s*\n', front_matter)
        if tg_match:
            tags = tg_match.group(1).strip()
    
    # Extract clean excerpt from body
    lines = body.split("\n")
    excerpt_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("---") or stripped.startswith("===") or stripped.startswith("```"):
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
        clean_text = re.sub(r'[*_`]', '', stripped)
        excerpt_lines.append(clean_text)
        if len(" ".join(excerpt_lines)) >= 150:
            break
            
    excerpt = " ".join(excerpt_lines)
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + "..."
    if not excerpt:
        excerpt = title

    rel_link = f"_posts/{filename}"
    
    return {
        "filename": filename,
        "date": date_str,
        "title": title,
        "categories": categories,
        "tags": tags,
        "excerpt": excerpt,
        "body": body,
        "link": rel_link
    }

def update_readme():
    post_files = glob.glob("_posts/*.md")
    post_files.sort(reverse=True)
    
    posts = [parse_post(fp) for fp in post_files]

    if not posts:
        latest_section = "*아직 등록된 포스트가 없습니다.*"
        table_content = "| - | 포스트가 없습니다. | - |"
    else:
        latest = posts[0]
        latest_body_preview = latest["body"]
        if len(latest_body_preview) > 2000:
            latest_body_preview = latest_body_preview[:2000] + f"\n\n*(이하 생략 ... [전체 포스트 읽기]({latest['link']}))*"
            
        latest_section = f"""### 📌 [{latest['title']}]({latest['link']})
- **작성일**: `{latest['date']}`
- **카테고리**: `{latest['categories'] or 'AI'}` | **태그**: `{latest['tags'] or 'Antigravity'}`

> **핵심 요약**: {latest['excerpt']}

<details>
<summary><b>📖 최신 포스트 본문 미리보기 (클릭하여 열기/접기)</b></summary>

{latest_body_preview}

</details>"""

        table_rows = []
        for p in posts:
            safe_title = p['title'].replace("|", "ㅣ")
            safe_excerpt = p['excerpt'].replace("|", "ㅣ").replace("\n", " ")
            table_rows.append(f"| {p['date']} | [{safe_title}]({p['link']}) | {safe_excerpt} |")
            
        table_content = "\n".join(table_rows)

    readme_text = f"""# 🤖 GitBlog Agent - 자율 콘텐츠 배포 블로그

> 🌐 **[실시간 웹 블로그 바로가기 (https://3hongwork-hub.github.io/gitblog-agent/)](https://3hongwork-hub.github.io/gitblog-agent/)**

안티그래비티(Antigravity) 및 Gemini AI, GitHub Actions 연동으로 자율 작성 및 배포되는 정적 블로그 레포지토리입니다.
매일 새롭게 생성된 AI/개발 트렌드 블로그 포스트의 최신 내용과 요약 목록이 `README.md`와 [실시간 웹 블로그](https://3hongwork-hub.github.io/gitblog-agent/)에 자동으로 업데이트됩니다.

---

## 🔥 최신 생성 포스트 (Latest Content)

{latest_section}

---

## 📝 전체 발행 포스트 목록 (총 {len(posts)}개)

| 작성일 | 제목 | 주요 내용 요약 |
| :--- | :--- | :--- |
{table_content}

---
*이 레포지토리의 블로그 포스트 및 README.md는 GitHub Actions에 의해 매일 자동으로 업데이트됩니다.*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_text.strip() + "\n")
    print(f"Successfully updated README.md with {len(posts)} post contents and summaries.")

def discover_active_endpoints(api_key):
    """Dynamically query Google API v1beta and v1 to list active model generateContent endpoints."""
    discovered = []
    for api_ver in ["v1beta", "v1"]:
        url = f"https://generativelanguage.googleapis.com/{api_ver}/models?key={api_key}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                for m in res_data.get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        full_name = m.get("name", "")
                        if full_name:
                            ep = f"https://generativelanguage.googleapis.com/{api_ver}/{full_name}:generateContent"
                            if ep not in discovered:
                                discovered.append(ep)
        except Exception as e:
            print(f"Notice: Failed to query {api_ver} models list: {e}")

    if discovered:
        print(f"Discovered {len(discovered)} active generateContent endpoints from Google API.")
    return discovered

def is_valid_korean_article(text):
    """Verify that generated text is a complete, full Korean article without thinking/outline artifacts."""
    if not text or len(text.strip()) < 500:
        return False
    
    # Must have front matter
    if not text.startswith("---"):
        return False
    
    # Check for unwanted thinking / outline keywords
    forbidden_tokens = [
        "*Introduction:*", "*Body 1:*", "*Body 2:*", "*Check:*",
        "Role: Chief Agent Writer", "Drafting Body", "Proceed to generate output",
        "*Topic Selection:*", "*Tone:*", "*Content Detail:*"
    ]
    for token in forbidden_tokens:
        if token.lower() in text.lower():
            return False
            
    # Check Korean character existence (must have substantial Korean text)
    korean_chars = re.findall(r'[가-힣]', text)
    if len(korean_chars) < 200:
        return False
        
    return True

def generate_blog_post():
    raw_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    
    if not raw_api_key:
        if is_github_actions:
            raise RuntimeError(
                "❌ GEMINI_API_KEY is missing in GitHub Repository Secrets!\n"
                "Please add GEMINI_API_KEY to Repository Settings -> Secrets and variables -> Actions."
            )
        else:
            print("Notice: GEMINI_API_KEY missing in local run. Updating README for existing posts.")
            update_readme()
            return

    # Clean whitespace or surrounding quotes from secret value
    api_key = raw_api_key.strip().strip('"').strip("'")

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    system_instruction_text = (
        "당신은 기술 전문 블로그 'GitBlog Agent'의 수석 한국어 테크 블로거입니다.\n"
        "지침:\n"
        "1. 생각 과정(Thinking), 개요(Outline), 기획 메모, 영문 체크리스트 등은 일절 출력하지 마십시오.\n"
        "2. 반드시 첫 줄부터 Jekyll Front Matter('---')로 시작하여, 서론 - 본론(소제목 3개 이상) - 실전 코드 예시(코드 주석 한국어) - 결론까지 1500자 이상의 완성된 포스트 본문 전문을 100% 매끄럽고 친절한 한국어로만 작성하여 출력하십시오."
    )

    prompt = f"""
오늘 날짜({today_str})를 기준으로 개발자 및 AI 연구자들을 위해 다음 주제 중 하나를 선택하여 완성도 높은 기술 블로그 포스트를 100% 자연스럽고 완벽한 한국어로 작성해줘:
- 최신 AI 개발 에이전트 동향 및 자율 배포 워크플로우
- 안티그래비티(Antigravity) 및 Gemini 활용법
- 루프 엔지니어링(Loop Engineering) 및 에이전틱 워크플로우(Agentic Workflow)
- 자가 치유(Self-Healing) 개발 생산성 자동화 팁

작성 형식:
---
layout: post
title: "매력적인 한국어 제목"
date: {today_str} 09:00:00 +0900
categories: [AI, Automation]
tags: [Antigravity, Gemini, AIAgent, Automation, LoopEngineering]
---

(이어서 서론, 소제목 본문 3개, 코드 블록, 결론까지 완성된 한국어 본문을 바로 작성)
"""

    discovered_endpoints = discover_active_endpoints(api_key)
    
    fallback_endpoints = [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-002:generateContent",
        "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash-002:generateContent"
    ]
    
    endpoints_to_try = []
    for ep in discovered_endpoints + fallback_endpoints:
        if ep not in endpoints_to_try:
            endpoints_to_try.append(ep)

    generated_text = None
    last_error = None

    for base_url in endpoints_to_try:
        url = f"{base_url}?key={api_key}"
        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction_text}]
            },
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        for attempt in range(2):
            try:
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    # Clean markdown wrappers
                    cleaned = raw_text.strip()
                    if cleaned.startswith("```markdown"):
                        cleaned = cleaned[11:]
                    if cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()

                    fm_pos = cleaned.find("---")
                    if fm_pos != -1:
                        cleaned = cleaned[fm_pos:]

                    if is_valid_korean_article(cleaned):
                        generated_text = cleaned
                        print(f"Successfully generated full Korean article using endpoint: {base_url}")
                        break
                    else:
                        print(f"Output from {base_url} contained outline/invalid text. Trying next model...")
                        break
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8")
                except Exception:
                    pass

                print(f"Endpoint {base_url} (attempt {attempt+1}) failed with HTTP {e.code}: {err_body or e}")
                last_error = f"HTTP {e.code}: {err_body or e}"

                if e.code == 429:
                    if "limit: 0" in err_body or "limit: 0" in str(e):
                        print(f"⚠️ Endpoint {base_url} returned limit 0. Trying next endpoint...")
                        break
                    if attempt == 0:
                        print("⚠️ Rate Limit hit (429 Resource Exhausted). Waiting 22 seconds before retrying...")
                        time.sleep(22)
                        continue
                elif e.code == 404:
                    break
                break
            except Exception as e:
                print(f"Endpoint {base_url} failed: {e}")
                last_error = e
                break

        if generated_text:
            break

    if generated_text:
        os.makedirs("_posts", exist_ok=True)
        filename = f"_posts/{today_str}-daily-ai-tech-update.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(generated_text)
        print(f"Successfully generated post file: {filename}")
    else:
        raise RuntimeError(f"❌ Failed to generate content with all Gemini models. Detailed Error:\n{last_error}")

    update_readme()

if __name__ == "__main__":
    generate_blog_post()
