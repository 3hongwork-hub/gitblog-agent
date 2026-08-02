---
layout: default
title: 홈 - 자율 콘텐츠 배포 블로그
---

<div class="main-container" style="max-width: 900px; margin: 0 auto; padding: 10px 0;">

  <!-- Hero Section -->
  <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); color: #ffffff; padding: 28px; border-radius: 16px; margin-bottom: 28px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);">
    <h1 style="color: #60a5fa; margin-top: 0; font-size: 1.8em; margin-bottom: 10px;">🤖 GitBlog Agent</h1>
    <p style="font-size: 1.05em; color: #cbd5e1; line-height: 1.6; margin-bottom: 0;">
      안티그래비티(Antigravity) 및 Gemini AI, GitHub Actions 연동으로 매일 자율 작성 및 배포되는 정적 블로그입니다.
    </p>
  </div>

  {% assign latest_post = site.posts.first %}
  {% if latest_post %}
  <!-- Featured Latest Post Section -->
  <section style="margin-bottom: 36px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; flex-wrap: wrap; gap: 8px;">
      <span style="background: #dbeafe; color: #1e40af; font-size: 0.85em; font-weight: bold; padding: 4px 12px; border-radius: 20px;">🔥 오늘/최신 생성 포스트</span>
      <span style="color: #64748b; font-size: 0.9em;">📅 {{ latest_post.date | date: "%Y년 %m월 %d일" }}</span>
    </div>

    <h2 style="margin-top: 0; margin-bottom: 12px; font-size: 1.5em;">
      <a href="{{ latest_post.url | relative_url }}" style="color: #0f172a; text-decoration: none; font-weight: 700;">{{ latest_post.title }}</a>
    </h2>

    {% if latest_post.categories.size > 0 or latest_post.tags.size > 0 %}
    <div style="margin-bottom: 14px; display: flex; gap: 8px; flex-wrap: wrap;">
      {% for category in latest_post.categories %}
        <span style="background: #f1f5f9; color: #475569; font-size: 0.8em; padding: 2px 8px; border-radius: 6px;">📁 {{ category }}</span>
      {% endfor %}
      {% for tag in latest_post.tags %}
        <span style="background: #f8fafc; color: #64748b; border: 1px solid #e2e8f0; font-size: 0.8em; padding: 2px 8px; border-radius: 6px;">#{{ tag }}</span>
      {% endfor %}
    </div>
    {% endif %}

    <div style="color: #334155; line-height: 1.7; font-size: 1em; background: #f8fafc; padding: 18px; border-left: 4px solid #3b82f6; border-radius: 4px; margin-bottom: 18px;">
      {{ latest_post.excerpt | strip_html | truncatewords: 80 }}
    </div>

    <a href="{{ latest_post.url | relative_url }}" style="display: inline-block; background: #2563eb; color: #ffffff; font-weight: bold; padding: 8px 18px; border-radius: 8px; text-decoration: none; transition: background 0.2s;">
      전체 글 읽기 &rarr;
    </a>
  </section>
  {% endif %}

  <!-- All Posts Archive Section -->
  <section>
    <h2 style="font-size: 1.3em; color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 20px;">
      📝 전체 발행 포스트 목록 (총 {{ site.posts.size }}개)
    </h2>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      {% for post in site.posts %}
      <article style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
        <div style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">
          <h3 style="margin: 0; font-size: 1.15em;">
            <a href="{{ post.url | relative_url }}" style="color: #1d4ed8; text-decoration: none; font-weight: 600;">{{ post.title }}</a>
          </h3>
          <span style="color: #64748b; font-size: 0.85em; white-space: nowrap;">{{ post.date | date: "%Y-%m-%d" }}</span>
        </div>

        <p style="color: #475569; font-size: 0.92em; line-height: 1.6; margin: 6px 0 10px 0;">
          {{ post.excerpt | strip_html | truncate: 150 }}
        </p>

        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.85em;">
          <div style="display: flex; gap: 6px;">
            {% for tag in post.tags limit:4 %}
              <span style="color: #64748b; background: #f1f5f9; padding: 1px 6px; border-radius: 4px;">#{{ tag }}</span>
            {% endfor %}
          </div>
          <a href="{{ post.url | relative_url }}" style="color: #2563eb; font-weight: 600; text-decoration: none;">상세보기 &rarr;</a>
        </div>
      </article>
      {% endfor %}
    </div>
  </section>

</div>
