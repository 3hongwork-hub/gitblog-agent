# Gemini API를 활용해 daily 블로그 포스트 마크다운 파일 생성 및 README.md 목록과 최신 내용 요약을 자동 업데이트하는 스크립트
import datetime
import glob
import json
import os
import re
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

def generate_blog_post():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Notice: GEMINI_API_KEY missing in local run. Updating README for existing posts.")
        update_readme()
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
너는 안티그래비티(Antigravity) AI 에이전트와 Gemini 기반 자율 개발 블로그 'GitBlog Agent'의 수석 에이전트 작가야.
오늘 날짜({today_str})를 기준으로 개발자 및 AI 연구자들을 위해 최신 AI 개발 에이전트 동향, 안티그래비티(Antigravity) 및 Gemini 2.0 활용법, 루프 엔지니어링(Loop Engineering), 에이전틱 워크플로우(Agentic Workflow), 또는 개발 생산성 자동화 팁 중 하나를 주제로 흥미롭고 유익한 블로그 포스트를 한국어로 작성해줘.

다음 지침을 반드시 준수해줘:
1. 최상단에는 아래 형식의 Jekyll 프론트 매터(Front Matter)를 포함해야 해 (제목은 작성 내용에 맞게 매일 다채롭고 매력적으로 지어줘):
   ---
   layout: post
   title: "주제에 어울리는 매력적인 제목"
   date: {today_str} 09:00:00 +0900
   categories: [AI, Automation]
   tags: [Antigravity, Gemini, AIAgent, Automation]
   ---
2. 서론-본론(2~3개 세부 항목)-결론 구조로 완성도 높게 작성해줘.
3. 실전 예시 코드나 지시서 예시가 필요하다면 마크다운 코드 블록(```)을 사용해줘.
4. 오직 마크다운 포맷 텍스트만 출력해줘.
"""

    models_to_try = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]
    generated_text = None
    last_error = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                generated_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"Successfully generated content using model: {model}")
                break
        except Exception as e:
            print(f"Model {model} failed: {e}")
            last_error = e

    if generated_text:
        if generated_text.startswith("```markdown"):
            generated_text = generated_text[11:]
        if generated_text.startswith("```"):
            generated_text = generated_text[3:]
        if generated_text.endswith("```"):
            generated_text = generated_text[:-3]
        generated_text = generated_text.strip()

        os.makedirs("_posts", exist_ok=True)
        filename = f"_posts/{today_str}-daily-ai-tech-update.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(generated_text)
        print(f"Successfully generated post file: {filename}")
    else:
        print(f"Failed to generate content with all models. Last error: {last_error}")

    update_readme()

if __name__ == "__main__":
    generate_blog_post()
