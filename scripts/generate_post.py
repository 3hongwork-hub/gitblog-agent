# Gemini API를 활용해 daily 블로그 포스트 마크다운 파일 생성 및 README.md 목록을 자동 업데이트하는 스크립트
import datetime
import glob
import json
import os
import re
import urllib.request

def update_readme():
    posts = []
    post_files = glob.glob("_posts/*.md")
    post_files.sort(reverse=True)

    for filepath in post_files:
        filename = os.path.basename(filepath)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
        date_str = date_match.group(1) if date_match else ""
        
        title = filename
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            title_match = re.search(r'title:\s*["\']?(.*?)["\']?\s*\n', content)
            if title_match:
                title = title_match.group(1).strip()
        
        rel_link = f"_posts/{filename}"
        posts.append({"date": date_str, "title": title, "link": rel_link})

    table_rows = []
    for p in posts:
        table_rows.append(f"| {p['date']} | {p['title']} | [{p['title']}]({p['link']}) |")

    table_content = "\n".join(table_rows) if table_rows else "| - | 포스트가 없습니다. | - |"

    readme_text = f"""# 🤖 GitBlog Agent - 자율 콘텐츠 배포 블로그

안티그래비티(Antigravity) 및 Gemini 모델, GitHub Actions 연동으로 자율 작성 및 배포되는 정적 블로그 레포지토리입니다.

## 📝 발행된 포스트 목록 (최신순)

| 작성일 | 제목 | 링크 |
| :--- | :--- | :--- |
{table_content}

---
*이 레포지토리의 블로그 포스트 및 목록은 GitHub Actions에 의해 매일 자동으로 업데이트됩니다.*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_text.strip() + "\n")
    print("Successfully updated README.md")

def generate_blog_post():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Notice: GEMINI_API_KEY missing in local run. Updating README for existing posts.")
        update_readme()
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
오늘 날짜({today_str})를 기준으로 주니어~미드레벨 개발자를 위한 최신 AI 기술 트렌드, 생산성 도구, 또는 에이전틱 워크플로우를 주제로 한 흥미롭고 유익한 블로그 글을 한국어로 작성해줘.

다음 조건을 반드시 지켜줘:
1. 최상단에 Jekyll 프론트 매터(Front Matter)를 포함해줘.
   ---
   layout: post
   title: "오늘의 AI 개발 트렌드 및 생산성 인사이트"
   date: {today_str} 09:00:00 +0900
   categories: [AI, Automation]
   tags: [AI, Gemini, Developer]
   ---
2. 제목과 본문에 핵심 키워드가 자연스럽게 들어가도록 해줘.
3. 코드 예시가 필요하다면 마크다운 코드 블록(```)을 정확히 사용해줘.
4. 오직 마크다운 포맷 텍스트만 출력해줘.
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
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
            print(f"Successfully generated post: {filename}")

    except Exception as e:
        print(f"Failed to generate content: {e}")

    update_readme()

if __name__ == "__main__":
    generate_blog_post()
