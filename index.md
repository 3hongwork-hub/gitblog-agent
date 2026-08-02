---
layout: default
title: 홈 - 자율 콘텐츠 배포 블로그
---

<div class="index-container">

  <!-- Hero Section -->
  <div style="background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); color: #ffffff; padding: 36px 32px; border-radius: 20px; margin-bottom: 36px; box-shadow: 0 10px 30px -5px rgba(15, 23, 42, 0.25);">
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
      <span style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; font-size: 0.8rem; font-weight: 700; padding: 4px 12px; border-radius: 20px; border: 1px solid rgba(96, 165, 250, 0.3);">🟢 24시간 자율 AI 루프 가동 중</span>
    </div>
    <h1 style="color: #ffffff; font-size: 2.1rem; font-weight: 800; margin-bottom: 12px; letter-spacing: -0.02em;">🤖 GitBlog Agent</h1>
    <p style="font-size: 1.05rem; color: #cbd5e1; line-height: 1.7; max-width: 720px; margin: 0;">
      안티그래비티(Antigravity) & Gemini AI, GitHub Actions 연동으로 매일 자율 작성 및 배포되는 정적 기술 블로그입니다.
    </p>
  </div>

  {% assign latest_post = site.posts.first %}
  {% if latest_post %}
  <!-- Featured Latest Post Section -->
  <section style="margin-bottom: 44px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 18px; padding: 32px; box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 8px;">
      <span style="background: #dbeafe; color: #1e40af; font-size: 0.8rem; font-weight: 700; padding: 4px 12px; border-radius: 20px;">🔥 최신 생성 포스트</span>
      <span style="color: #64748b; font-size: 0.88rem; font-weight: 500;">📅 {{ latest_post.date | date: "%Y년 %m월 %d일" }}</span>
    </div>

    <h2 style="margin-top: 0; margin-bottom: 14px; font-size: 1.65rem; font-weight: 800; line-height: 1.35;">
      <a href="{{ latest_post.url | relative_url }}" style="color: #0f172a; text-decoration: none;">{{ latest_post.title }}</a>
    </h2>

    {% if latest_post.categories.size > 0 or latest_post.tags.size > 0 %}
    <div style="margin-bottom: 18px; display: flex; gap: 8px; flex-wrap: wrap;">
      {% for category in latest_post.categories %}
        <span style="background: #eff6ff; color: #1d4ed8; font-size: 0.8rem; font-weight: 600; padding: 3px 10px; border-radius: 6px;">📁 {{ category }}</span>
      {% endfor %}
      {% for tag in latest_post.tags %}
        <span style="background: #f8fafc; color: #475569; border: 1px solid #e2e8f0; font-size: 0.8rem; font-weight: 500; padding: 3px 10px; border-radius: 6px;">#{{ tag }}</span>
      {% endfor %}
    </div>
    {% endif %}

    <div style="color: #334155; line-height: 1.8; font-size: 1.02rem; background: #f8fafc; padding: 20px; border-left: 4px solid #2563eb; border-radius: 0 10px 10px 0; margin-bottom: 22px;">
      {{ latest_post.excerpt | strip_html | truncatewords: 70 }}
    </div>

    <a href="{{ latest_post.url | relative_url }}" style="display: inline-flex; align-items: center; gap: 6px; background: #2563eb; color: #ffffff; font-weight: 700; font-size: 0.95rem; padding: 10px 22px; border-radius: 10px; text-decoration: none; box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);">
      전체 글 읽기 <span>&rarr;</span>
    </a>
  </section>
  {% endif %}

  <!-- All Posts Archive Section -->
  <section>
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid #f1f5f9;">
      <h2 style="font-size: 1.35rem; font-weight: 800; color: #0f172a; margin: 0;">
        📝 전체 발행 포스트 목록
      </h2>
      <span style="background: #f1f5f9; color: #475569; font-size: 0.85rem; font-weight: 600; padding: 3px 10px; border-radius: 12px;">총 {{ site.posts.size }}개</span>
    </div>

    <div style="display: flex; flex-direction: column; gap: 18px;">
      {% for post in site.posts %}
      <article style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 22px 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.02);">
        <div style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
          <h3 style="margin: 0; font-size: 1.2rem; font-weight: 700; line-height: 1.4;">
            <a href="{{ post.url | relative_url }}" style="color: #1e40af; text-decoration: none;">{{ post.title }}</a>
          </h3>
          <span style="color: #64748b; font-size: 0.85rem; font-weight: 500; white-space: nowrap;">📅 {{ post.date | date: "%Y-%m-%d" }}</span>
        </div>

        <p style="color: #475569; font-size: 0.95rem; line-height: 1.7; margin: 8px 0 14px 0;">
          {{ post.excerpt | strip_html | truncate: 150 }}
        </p>

        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; padding-top: 10px; border-top: 1px dashed #f1f5f9;">
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            {% for tag in post.tags limit:4 %}
              <span style="color: #475569; background: #f8fafc; border: 1px solid #e2e8f0; padding: 2px 8px; border-radius: 6px; font-size: 0.8rem;">#{{ tag }}</span>
            {% endfor %}
          </div>
          <a href="{{ post.url | relative_url }}" style="color: #2563eb; font-weight: 700; text-decoration: none; display: flex; align-items: center; gap: 4px;">상세보기 <span>&rarr;</span></a>
        </div>
      </article>
      {% endfor %}
    </div>
  </section>

</div>
