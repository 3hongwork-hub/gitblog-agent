---
layout: post
title: "Next.js 15 Server Actions와 Vercel AI SDK 조합을 통한 스트리밍 제너레이티브 UI(Generative UI) 아키텍처 실전 구축"
date: 2026-11-01 09:00:00 +0900
categories: [AI, Fullstack]
tags: [Next.js, Vercel AI SDK, Generative UI, React Server Components, Server Actions]
---

### 서론: 정적 텍스트를 넘어 동적 컴포넌트로 향하는 AI 인터페이스의 진화

초기 생성형 AI 애플리케이션의 사용자 경험(UX)은 대개 챗봇 형태의 텍스트 스트리밍에 국한되어 있었습니다. 사용자가 질문을 던지면 언어 모델(LLM)이 마크다운이나 평문 형태로 답변을 내려주는 구조가 주를 이뤘죠. 하지만 엔터프라이즈 환경과 복잡한 웹 서비스가 고도화됨에 따라, 사용자는 단순히 텍스트로 요약된 정보뿐만 아니라 **시각화된 차트, 실시간 대화형 폼(Form), 동적 카드 컴포넌트** 등 문맥에 맞는 UI가 실시간으로 렌더링되기를 원하고 있습니다.

이것이 바로 **제너레이티브 UI(Generative UI)** 패러다임입니다. 백엔드에서 단순히 문자열을 스트리밍하는 것을 넘어, LLM이 도구 호출(Tool Calling)이나 구조화된 출력(Structured Outputs)을 통해 프론트엔드의 특정 React 컴포넌트를 직접 지정하고 데이터를 주입하여 스트리밍 방식으로 화면에 그려내는 아키텍처입니다. 

본 포스트에서는 2026년 현재 표준으로 자리 잡은 **Next.js 15(App Router)**의 최신 **Server Actions** 메커니즘과 **Vercel AI SDK v4+**의 핵심 기능을 결합하여, 서버 컴포넌트의 강력한 보안성과 타입 안전성을 유지하면서도 완벽하게 동작하는 스트리밍 제너레이티브 UI 파이프라인을 구축하는 실전 가이드를 공유합니다.

---

### 1. Next.js 15 App Router와 Vercel AI SDK 아키텍처 이해

전통적인 방식에서는 클라이언트가 AI 모델과 직접 통신하거나, 커스텀 API 라우트를 거쳐 텍스트를 파싱한 뒤 프론트엔드에서 수동으로 `switch-case` 문을 돌려 컴포넌트를 매핑하는 복잡하고 취약한 코드를 작성해야 했습니다. 이 과정은 타입 불일치를 야기하고, API 키 노출 위험 및 네트워크 오버헤드를 동반했습니다.

Next.js 15의 Server Actions와 Vercel AI SDK의 `createStreamableUI` / `useUIState` 패턴을 활용하면 이 아키텍처가 혁신적으로 단순화됩니다.

1. **클라이언트 (Client Component)**: 사용자의 입력을 받아 Server Action을 호출하고, 실시간으로 렌더링되는 UI 상태 스트림을 구독합니다.
2. **서버 액션 (Server Action / RSC)**: LLM과 통신을 수행합니다. LLM은 사용자의 의도를 파악하고 적절한 도구(Tool)를 호출하기로 결정합니다.
3. **도구 정의 (Tool Definition with Zod)**: 서버 측에서 Zod 스키마를 통해 AI가 생성해야 할 데이터의 타입을 강제합니다.
4. **스트리밍 UI 주입**: AI 도구 실행 결과에 따라 서버에서 직접 React 컴포넌트를 스트리밍 가능한 UI 객체로 변환하여 클라이언트로 푸시합니다.

이 구조는 클라이언트가 무거운 비즈니스 로직이나 컴포넌트 매핑 규칙을 알 필요 없이, 서버가 내려주는 안전한 컴포넌트 스트림을 그대로 렌더링(Server-Driven UI)할 수 있게 만듭니다.

---

### 2. Zod 스키마 기반 도구 정의 및 서버 액션 파이프라인 구현

제너레이티브 UI의 핵심은 LLM이 무작위 텍스트가 아니라 사전에 정의된 엄격한 스키마에 맞는 데이터를 반환하도록 강제하는 것입니다. 실무에서 자주 쓰이는 '주문 데이터 조회 및 시각화 대시보드' 컴포넌트를 동적으로 생성하는 백엔드 파이프라인을 작성해 보겠습니다.

먼저, Vercel AI SDK와 Next.js Server Actions를 활용한 서버측 코드를 구현합니다.

```typescript
// app/actions.ts
'use server';

import { createAI, createStreamableUI, getMutableAIState } from 'ai/rsc';
import { google } from '@ai-sdk/google';
import { z } from 'zod';
import React from 'react';
import OrderMetricsCard from '@/components/OrderMetricsCard';
import ProductTable from '@/components/ProductTable';

// 1. AI 상태 및 UI 상태 타입 정의
export type ServerMessage = {
  role: 'user' | 'assistant' | 'system';
  content: string;
};

export type ClientState = {
  id: string;
  display: React.ReactNode;
};

// 2. 주문화면 제너레이티브 UI를 생성하는 메인 액션 함수
async function submitUserMessage(userInput: string) {
  'use server';

  const aiState = getMutableAIState<typeof AI>();
  aiState.update([...aiState.get(), { role: 'user', content: userInput }]);

  // 스트리밍 UI 객체 생성 (초기에는 로딩 스피너 표시 등 처리 가능)
  const uiStream = createStreamableUI(
    <div className="animate-pulse p-4 text-sm text-gray-500">데이터를 분석하고 있습니다...</div>
  );

  (async () => {
    try {
      // Vercel AI SDK의 streamText 또는 generateText를 활용하여 LLM 호출
      const { toolCalls } = await google('gemini-2.5-pro').generateText({
        system: '당신은 숙련된 이커머스 데이터 분석 어시스턴트입니다. 사용자의 요청에 따라 적절한 UI 컴포넌트를 도구 호출을 통해 렌더링하세요.',
        messages: aiState.get(),
        tools: {
          // 주문 메트릭 카드 컴포넌트를 동적 생성하기 위한 도구
          renderOrderMetrics: {
            description: '특정 기간의 매출, 주문 건수, 취소율 등의 지표를 카드 형태로 시각화합니다.',
            parameters: z.object({
              startDate: z.string().describe('조회 시작일 (YYYY-MM-DD)'),
              endDate: z.string().describe('조회 종료일 (YYYY-MM-DD)'),
              totalRevenue: z.number().describe('총 매출액'),
              orderCount: z.number().describe('총 주문 건수'),
            }),
            execute: async ({ startDate, endDate, totalRevenue, orderCount }) => {
              // 컴포넌트를 완성하여 스트림에 업데이트
              uiStream.done(
                <OrderMetricsCard
                  startDate={startDate}
                  endDate={endDate}
                  totalRevenue={totalRevenue}
                  orderCount={orderCount}
                />
              );
              
              aiState.update([
                ...aiState.get(),
                {
                  role: 'assistant',
                  content: `[주문 메트릭 대시보드 렌더링 완료: ${startDate} ~ ${endDate}]`,
                },
              ]);
            },
          },
          // 상품 리스트 테이블 컴포넌트를 동적 생성하기 위한 도구
          renderProductTable: {
            description: '상위 판매 상품 목록을 테이블 형태로 시각화합니다.',
            parameters: z.object({
              category: z.string().describe('상품 카테고리'),
              limit: z.number().describe('표출할 상품 개수'),
            }),
            execute: async ({ category, limit }) => {
              // 실제 데이터베이스 페치 로직 시뮬레이션
              const mockProducts = [
                { id: '1', name: 'AI 기반 코드 어시스턴트 프로', price: 120000, sales: 430 },
                { id: '2', name: '클라우드 네이티브 쿠버네티스 마스터', price: 95000, sales: 310 },
              ].slice(0, limit);

              uiStream.done(
                <ProductTable category={category} products={mockProducts} />
              );

              aiState.update([
                ...aiState.get(),
                {
                  role: 'assistant',
                  content: `[${category} 카테고리 상위 ${limit}개 상품 테이블 렌더링 완료]`,
                },
              ]);
            },
          },
        },
      });
    } catch (error) {
      console.error('Generative UI Streaming Error:', error);
      uiStream.error(new Error('AI 응답을 생성하는 중 오류가 발생했습니다.'));
    }
  })();

  return {
    id: Date.now().toString(),
    display: uiStream.value,
  };
}

// 3. AI Context Provider 설정
export const AI = ai({
  actions: {
    submitUserMessage,
  },
  initialState: [] as ServerMessage[],
  initialUIState: [] as ClientState[],
});
```

---

### 3. 클라이언트 컴포넌트 연동 및 실시간 UI 렌더링 파이프라인

서버에서 생성된 UI 스트림을 클라이언트 컴포넌트에서 안전하게 받아 화면에 마운트하는 방식은 Next.js 15 환경에서 매우 직관적입니다. `useUIState`와 `useActions` 훅을 활용하여 사용자 인터페이스를 구성합니다.

```tsx
// app/page.tsx
'use client';

import React, { useState } from 'react';
import { useAIState, useUIState, useActions } from 'ai/rsc';
import type { AI } from './actions';

export default function GenerativeDashboardPage() {
  const [input, setInput] = useState('');
  const [conversation, setConversation] = useUIState<typeof AI>();
  const [aiState] = useAIState<typeof AI>();
  const { submitUserMessage } = useActions<typeof AI>();
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    setIsLoading(true);
    setInput('');

    // 낙관적 업데이트(Optimistic Update) 적용
    setConversation((current: any[]) => [
      ...current,
      {
        id: Date.now().toString(),
        display: <div className="p-3 bg-blue-50 rounded-lg text-blue-900 self-end">사용자: {input}</div>,
      },
    ]);

    try {
      // 서버 액션 호출 및 스트리밍 UI 결과 수신
      const message = await submitUserMessage(input);
      setConversation((current: any[]) => [...current, message]);
    } catch (err) {
      console.error('Failed to submit message:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="flex flex-col h-screen max-w-4xl mx-auto p-4 justify-between bg-gray-50">
      {/* 헤더 영역 */}
      <header className="py-4 border-b border-gray-200">
        <h1 className="text-xl font-bold text-gray-800">엔터프라이즈 AI 제너레이티브 대시보드</h1>
        <p className="text-xs text-gray-500">Next.js 15 Server Actions & Vercel AI SDK</p>
      </header>

      {/* 대화 및 동적 컴포넌트 렌더링 영역 */}
      <div className="flex-1 overflow-y-auto py-6 space-y-6">
        {conversation.map((message) => (
          <div key={message.id} className="flex flex-col space-y-2">
            {message.display}
          </div>
        ))}
      </div>

      {/* 입력 폼 영역 */}
      <form onSubmit={handleSubmit} className="flex gap-2 py-4 border-t border-gray-200">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 지난달 매출 데이터 보여줘, 혹은 개발 관련 상품 리스트 띄워줘..."
          className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm shadow-sm"
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={isLoading}
          className="px-6 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition disabled:opacity-50 text-sm shadow-sm"
        >
          {isLoading ? '생성 중...' : '전송'}
        </button>
      </form>
    </main>
  );
}
```

이 구현체에서 클라이언트는 비즈니스 로직이나 데이터 가공 처리 방식을 전혀 알 필요가 없습니다. 서버의 Server Action이 LLM을 제어하고, LLM의 도구 선택 결과에 따라 완성된 React 컴포넌트 스트림(`uiStream.value`)을 클라이언트로 밀어주기 때문에 프론트엔드 번들 크기를 경량화할 수 있으며 보안 취약점도 원천 차단됩니다.

---

### 결론: 제너레이티브 UI를 통한 차세대 AI 애플리케이션 개발의 완성

오늘 살펴본 **Next.js 15 Server Actions와 Vercel AI SDK 조합의 스트리티브 제너레이티브 UI 아키텍처**는 단순한 텍스트 챗봇의 한계를 뛰어넘어, 사용자의 의도에 즉각 반응하는 동적 웹 애플리케이션을 구축하는 가장 현대적이고 강력한 방법입니다.

서버 컴포넌트와 Zod 스키마 검증을 결합함으로써 타입 안전성과 보안성을 동시에 확보하였으며, 클라이언트와 서버 간의 스트리밍 통신을 통해 유연하고 끊김 없는(Seamless) 사용자 경험을 제공할 수 있게 되었습니다. 앞으로 엔터프라이즈 환경에서 AI 에이전트의 출력이 단순 텍스트를 넘어 복잡한 대시보드, 인터랙티브 폼, 실시간 시각화 컴포넌트로 확장되는 트렌드 속에서 본 아키텍처 패턴은 핵심 표준으로 자리 잡을 것입니다. 

지금 바로 여러분의 Next.js 프로젝트에 도입하여 차세대 AI 사용자 경험을 직접 구현해 보시기 바랍니다.