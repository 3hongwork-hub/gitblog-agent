---
layout: post
title: "Next.js 15 Server Actions와 Vercel AI SDK를 활용한 제너레이티브 UI(Generative UI) 아키텍처: 스트리밍 컴포넌트 실전 구현"
date: 2026-10-08 09:00:00 +0900
categories: [Frontend, AI]
tags: [Next.js 15, Vercel AI SDK, Generative UI, Server Actions, React]
---

현대 웹 애플리케이션에서 인공지능(AI)과의 상호작용은 단순한 텍스트 채팅 창을 넘어, 사용자 인터페이스(UI) 그 자체를 동적으로 생성하는 **제너레이티브 UI(Generative UI)** 패러다임으로 진화하고 있습니다. 사용자가 자연어로 요청을 입력하면, 대규모 언어 모델(LLM)이 백엔드에서 실시간으로 적절한 리액트(React) 컴포넌트를 결정하고, 프론트엔드는 이를 스트리밍 방식으로 렌더링하여 사용자에게 시각적으로 풍부한 경험을 제공하는 방식입니다.

이번 포스트에서는 최신 **Next.js 15의 Server Actions**와 **Vercel AI SDK**의 핵심 기능을 결합하여, 프로덕션 환경에서 안정적으로 동작하는 제너레이티브 UI 아키텍처를 구축하는 방법을 실전 코드와 함께 상세히 다룹니다.

---

### 1. Next.js 15와 Vercel AI SDK 기반 스트리밍 아키텍처 설계

전통적인 AI 챗봇 구조는 LLM으로부터 순수 텍스트(Markdown 포함) 스트림을 받아 클라이언트에서 파싱하는 형태였습니다. 하지만 제너레이티브 UI는 LLM이 구조화된 데이터(Tool Call)를 반환하고, 이 메타데이터를 기반으로 클라이언트 또는 서버 컴포넌트를 동적으로 마운트해야 합니다.

이를 위해 Vercel AI SDK는 `streamUI` 함수와 React의 `createStreamableUI`를 제공합니다. 
1. **사용자 요청:** 클라이언트가 Next.js Server Action을 통해 입력을 전달합니다.
2. **LLM 툴 체이닝:** 서버 측에서 실행되는 LLM은 대화 맥락을 파악하고 등록된 도구(Tools) 중 어떤 UI 컴포넌트를 호출할지 결정합니다.
3. **컴포넌트 스트리밍:** 서버는 선택된 React 컴포넌트의 초기 상태 혹은 데이터를 생성하여 네트워크 스트림을 통해 클라이언트에 즉시 전송합니다.

이 아키텍처는 클라이언트 번들 사이즈를 최적화하고, 서버의 연산 능력을 활용하여 복잡한 비즈니스 로직(예: 실시간 주가 차트, 예약 위젯 등)을 안전하게 렌더링할 수 있게 해줍니다.

---

### 2. 백엔드: Server Actions와 동적 툴 정의 구현

먼저, Next.js 15 서버 환경에서 Vercel AI SDK를 활용해 LLM 호출과 UI 스트리밍을 처리하는 서버 액션을 구현합니다. 여기서는 사용자의 요청에 따라 날씨 정보 컴포넌트나 제품 목록 카드 컴포넌트를 동적으로 생성하는 시나리오를 가정합니다.

```typescript
// app/actions.tsx
'use server';

import { createStreamableUI } from 'ai/rsc';
import { openai } from '@ai-sdk/openai';
import { streamText } from 'ai';
import WeatherCard from '@/components/WeatherCard';
import ProductListCard from '@/components/ProductListCard';
import React from 'react';

export async function submitUserMessage(input: string) {
  'use server';

  // UI 스트림 객체 생성
  const uiStream = createStreamableUI(
    <div className="text-zinc-500 animate-pulse">AI가 응답을 준비 중입니다...</div>
  );

  (async () => {
    try {
      // LLM 스트리밍 호출 및 툴바인딩 설정
      const result = await streamText({
        model: openai('gpt-4o'),
        system: '당신은 유능한 AI 어시스턴트입니다. 사용자의 요청에 따라 적절한 UI 컴포넌트 도구를 호출하세요.',
        prompt: input,
        tools: {
          showWeather: {
            description: '특정 지역의 날씨 정보를 시각적 카드 UI로 표시합니다.',
            parameters: {
              type: 'object',
              properties: {
                location: { type: 'string', description: '도시 이름 (예: 서울, 도쿄)' },
                temperature: { type: 'number', description: '섭씨 온도' },
                condition: { type: 'string', description: '날씨 상태 (예: 맑음, 흐림)' },
              },
              required: ['location', 'temperature', 'condition'],
            },
            execute: async ({ location, temperature, condition }) => {
              // 컴포넌트를 스트림에 업데이트
              uiStream.update(
                <WeatherCard location={location} temperature={temperature} condition={condition} />
              );
              return { success: true, location };
            },
          },
          showProducts: {
            description: '추천 제품 목록을 카드 그리드 UI로 표시합니다.',
            parameters: {
              type: 'object',
              properties: {
                category: { type: 'string', description: '제품 카테고리' },
                limit: { type: 'number', description: '표시할 제품 수' },
              },
              required: ['category'],
            },
            execute: async ({ category, limit = 3 }) => {
              // 가상의 제품 데이터 조회 로직
              const mockProducts = [
                { id: 1, name: `${category} 프로 에디션`, price: '1,200,000원' },
                { id: 2, name: `${category} 라이트 모델`, price: '850,000원' },
              ];
              
              uiStream.update(
                <ProductListCard category={category} products={mockProducts} />
              );
              return { success: true, count: mockProducts.length };
            },
          },
        },
      });

      // 툴 호출이 완료된 후 최종 완료 상태로 전환
      uiStream.done();
    } catch (error) {
      console.error('Generative UI Streaming Error:', error);
      uiStream.error(new Error('UI 생성 중 오류가 발생했습니다.'));
    }
  })();

  return {
    id: Date.now(),
    display: uiStream.value,
  };
}
```

---

### 3. 프론트엔드: React 클라이언트 컴포넌트 및 상태 연동

서버에서 스트리밍되어 내려오는 UI 엘리먼트를 실시간으로 렌더링하고, 사용자와의 대화 인터페이스를 제공하는 클라이언트 컴포넌트를 작성합니다. Next.js 15의 `useOptimistic` 및 리액트의 `startTransition`을 결합하면 사용자 경험을 극대화할 수 있습니다.

```tsx
// app/page.tsx
'use client';

import { useState, useTransition } from 'react';
import { submitUserMessage } from './actions';
import { readStreamableValue } from 'ai/rsc';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  display: React.ReactNode;
}

export default function GenerativeUIChat() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isPending, startTransition] = useTransition();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isPending) return;

    const userInput = input;
    setInput('');

    // 사용자 메시지 낙관적 추가
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), role: 'user', display: <div className="text-blue-600 font-medium">사용자: {userInput}</div> },
    ]);

    startTransition(async () => {
      try {
        const response = await submitUserMessage(userInput);
        setMessages((prev) => [
          ...prev,
          { id: response.id, role: 'assistant', display: response.display },
        ]);
      } catch (err) {
        console.error('메시지 전송 실패:', err);
      }
    });
  };

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto p-4 justify-between bg-zinc-50">
      {/* 대화 및 제너레이티브 UI 렌더링 영역 */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 p-4 bg-white rounded-xl shadow-sm border border-zinc-200">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className="p-3 rounded-lg max-w-xl">
              {msg.display}
            </div>
          </div>
        ))}
      </div>

      {/* 입력 폼 영역 */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 서울 날씨 알려줘 또는 개발자 노트북 추천해줘"
          className="flex-1 px-4 py-3 border border-zinc-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-black bg-white"
          disabled={isPending}
        />
        <button
          type="submit"
          disabled={isPending}
          className="px-6 py-3 bg-black text-white font-semibold rounded-xl hover:bg-zinc-800 disabled:opacity-50 transition-colors"
        >
          {isPending ? '생성 중...' : '전송'}
        </button>
      </form>
    </div>
  );
}
```

---

### 4. 결론 및 프로덕션 운영 팁

Next.js 15 Server Actions와 Vercel AI SDK를 활용한 제너레이티브 UI 패턴은 개발자가 정적이고 지루한 챗봇 인터페이스에서 벗어나, 문맥에 맞는 맞춤형 대시보드와 위젯을 실시간으로 제공하는 강력한 수단입니다. 

프로덕션 환경에서 이 아키텍처를 안정적으로 운영하기 위한 몇 가지 권장 사항은 다음과 같습니다.
1. **타입 안전성 확보:** LLM의 툴 파라미터 정의와 리액트 컴포넌트의 `Props` 인터페이스를 엄격하게 일치시켜 런타임 타입 에러를 예방하세요.
2. **에러 핸들링 및 폴백(Fallback):** 네트워크 지연이나 LLM 환각(Hallucination)으로 인해 잘못된 툴 파라미터가 전달될 경우를 대비해, 컴포넌트 내부에 견고한 에러 경계(Error Boundary)를 구성해야 합니다.
3. **캐싱 및 최적화:** 동적으로 렌더링되는 컴포넌트 내부에서 무거운 데이터베이스 쿼리가 발생하지 않도록, 서버 액션 단계에서 적절한 캐싱 전략(`React cache` 또는 Redis)을 병행하는 것이 좋습니다.

제너레이티브 UI는 프론트엔드 엔지니어링과 생성형 AI의 경계를 허물며 사용자 경험의 지평을 넓히고 있습니다. 오늘 살펴본 패턴을 바탕으로 여러분의 프로덕션 애플리케이션에 차세대 AI 인터페이스를 도입해 보시기 바랍니다.