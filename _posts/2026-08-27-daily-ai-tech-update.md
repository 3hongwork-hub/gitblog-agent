---
layout: post
title: "Next.js 15 Server Actions와 Vercel AI SDK로 구현하는 실시간 Generative UI 아키텍처"
date: 2026-08-27 09:00:00 +0900
categories: [Frontend, AI]
tags: [Next.js 15, Vercel AI SDK, Generative UI, Server Actions, React]
---

AI 애플리케이션의 사용자 경험(UX)은 단순한 텍스트 스트리밍을 넘어, 사용자의 의도와 데이터 구조에 맞추어 UI 컴포넌트 자체가 실시간으로 생성되고 진화하는 **Generative UI**의 시대로 접어들었습니다. 과거에는 LLM이 반환하는 JSON 데이터를 프론트엔드에서 일일이 파싱하여 조건문으로 분기 처리해야 했지만, 오늘날에는 모던 프레임워크와 AI SDK의 결합으로 서버 사이드에서 직접 컴포넌트를 스트리밍하고 클라이언트와 유기적으로 동기화할 수 있게 되었습니다.

이번 포스트에서는 최신 **Next.js 15**의 App Router와 **Server Actions**, 그리고 **Vercel AI SDK**를 유기적으로 결합하여, LLM의 응답에 따라 동적으로 UI를 렌더링하고 상태를 관리하는 실전 Generative UI 아키텍처 구축 방법을 깊이 있게 다룹니다.

---

### 1. Next.js 15 App Router와 AI SDK 통합 패러다임

Next.js 15는 비동기 요청 객체 처리 방식의 개선과 더불어 서버 컴포넌트(RSC)와 서버 액션(Server Actions)의 성능을 극대화했습니다. 특히 AI 애플리케이션 개발에 있어 클라이언트와 서버 간의 스트리밍 통신이 필수적이므로, Next.js의 스트리밍 아키텍처와 Vercel AI SDK의 `streamText` 및 `createAI` 유틸리티는 완벽한 궁합을 자랑합니다.

전통적인 방식은 클라이언트가 API 라우트를 호출하고, 서버가 텍스트를 스트리밍한 뒤 클라이언트가 이를 상태에 저장하는 구조였습니다. 반면, Next.js 15의 Server Actions를 활용하면 별도의 REST/GraphQL 엔드포인트 정의 없이 컴포넌트 내부에서 직접 서버 측 LLM 로직을 호출하고, 리액트의 `useActionState`나 AI SDK의 리액트 훅(`useChat`)을 통해 실시간 반응형 UI를 구성할 수 있습니다.

이 과정에서 가장 중요한 점은 LLM이 단순히 텍스트를 출력하는 것이 아니라, 구조화된 도구 호출(Tool Calling) 메커니즘을 통해 클라이언트에게 특정 리액트 컴포넌트를 렌더링하도록 지시(Payload 전달)하는 것입니다.

---

### 2. 도구 호출(Tool Calling) 기반 Generative UI 설계

Generative UI의 핵심은 **"LLM에게 컴포넌트 렌더링 권한을 위임하되, 엄격한 타입 안정성을 보장하는 것"**입니다. Vercel AI SDK는 `tool` 함수를 통해 AI가 호출할 수 있는 함수 정의를 지원하며, Zod를 이용해 스키마를 검증합니다.

아래는 사용자의 요청에 따라 날씨 정보 카드나 주가 차트 컴포넌트를 동적으로 생성하도록 설계된 서버 액션 및 도구 정의 코드의 실전 예시입니다.

```typescript
// app/actions.ts
'use server';

import { streamText, tool } from 'ai';
import { google } from '@ai-sdk/google';
import { z } from 'zod';

export async function submitUserMessage(messages: Array<any>) {
  // Gemini 모델을 활용한 스트리밍 텍스트 및 도구 호출 설정
  const result = await streamText({
    model: google('gemini-2.5-flash'),
    messages,
    system: '너는 친절한 AI 어시스턴트이며, 사용자 요청에 맞는 시각적 컴포넌트 도구를 적극 활용해.',
    tools: {
      // 1. 날씨 정보 UI 컴포넌트 생성 도구
      renderWeatherCard: tool({
        description: '특정 지역의 날씨 정보를 시각적 카드 UI로 렌더링합니다.',
        parameters: z.object({
          location: z.string().describe('도시 이름 (예: 서울, 뉴욕)'),
          temperature: z.number().describe('섭씨 온도'),
          condition: z.string().describe('날씨 상태 (맑음, 흐림, 비 등)'),
        }),
        // 도구가 실행될 때 반환할 데이터 (클라이언트 컴포넌트와 매핑됨)
        execute: async ({ location, temperature, condition }) => {
          return { location, temperature, condition };
        },
      }),
      // 2. 주식 차트 UI 컴포넌트 생성 도구
      renderStockChart: tool({
        description: '특정 기업의 주가 트렌드를 차트 UI로 렌더링합니다.',
        parameters: z.object({
          symbol: z.string().describe('주식 티커 심볼 (예: AAPL, TSLA)'),
          price: z.number().describe('현재 주가'),
          changePercent: z.number().describe('전일 대비 등락률 (%)'),
        }),
        execute: async ({ symbol, price, changePercent }) => {
          return { symbol, price, changePercent };
        },
      }),
    },
  });

  // 데이터 스트림을 클라이언트로 응답
  return result.toDataStreamResponse();
}
```

위 코드는 LLM이 사용자의 입력("서울 날씨 어때?" 또는 "테슬라 주가 알려줘")을 분석하여 적절한 도구를 선택하고, 해당 도구의 파라미터를 채워 스트림으로 전송하는 기반을 마련합니다.

---

### 3. 클라이언트 측 동적 컴포넌트 렌더링 및 상태 관리

서버로부터 전달된 스트림을 받아 화면에 실시간으로 UI를 그려내는 것은 클라이언트 컴포넌트의 몫입니다. Vercel AI SDK의 `useChat` 훅은 서버 액션과 연동되어 메시지 목록과 도구 호출 상태를 자동으로 관리해 줍니다.

클라이언트에서는 AI가 반환한 도구 이름(`toolName`)에 따라 미리 정의된 리액트 컴포넌트(WeatherCard, StockChart 등)를 동적으로 매핑하여 렌더링합니다.

```tsx
// app/page.tsx
'use client';

import { useChat } from '@ai-sdk/react';
import { WeatherCard } from '@/components/WeatherCard';
import { StockChart } from '@/components/StockChart';

export default function ChatDashboard() {
  const { messages, input, handleInputChange, handleSubmit } = useChat({
    // Next.js 15 서버 액션을 API 엔드포인트 대신 활용
    api: '/api/chat', // 또는 서버 액션을 감싼 라우트 핸들러
  });

  return (
    <main className="flex flex-col h-screen max-w-3xl mx-auto p-4 justify-between">
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.map((m) => (
          <div key={m.id} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div className="p-3 rounded-lg bg-gray-100 dark:bg-gray-800 text-sm max-w-[80%]">
              {m.content}
            </div>

            {/* 도구 호출 결과(Tool Invocations) 순회 및 Generative UI 렌더링 */}
            {m.toolInvocations?.map((toolInvocation) => {
              const { toolCallId, toolName, state } = toolInvocation;

              if (state === 'result') {
                if (toolName === 'renderWeatherCard') {
                  const { location, temperature, condition } = toolInvocation.result;
                  return <WeatherCard key={toolCallId} location={location} temperature={temperature} condition={condition} />;
                }
                if (toolName === 'renderStockChart') {
                  const { symbol, price, changePercent } = toolInvocation.result;
                  return <StockChart key={toolCallId} symbol={symbol} price={price} changePercent={changePercent} />;
                }
              }

              return (
                <div key={toolCallId} className="text-xs text-gray-400 italic mt-2">
                  🔄 실시간 데이터 및 컴포넌트 생성 중... ({toolName})
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="날씨나 주가 정보를 물어보세요 (예: 서울 날씨 어때?)"
          className="flex-1 border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-blue-700">
          전송
        </button>
      </form>
    </main>
  );
}
```

이 구조를 통해 사용자는 텍스트 답변뿐만 아니라, 시스템이 즉시 생성해 낸 인터랙티브한 위젯 형태의 UI를 실시간으로 경험할 수 있습니다. 

---

### 결론

Next.js 15의 고성능 서버 아키텍처와 Vercel AI SDK, 그리고 정교한 도구 호출(Tool Calling) 메커니즘의 결합은 Generative UI 구현을 더 이상 복잡하고 거대한 엔터프라이즈 프로젝트만의 전유물이 아닌, 표준적인 웹 개발 패턴으로 탈바꿈시키고 있습니다. 개발자는 복잡한 파싱 로직이나 상태 관리 지옥에 빠지지 않고, Zod 기반의 타입 안전성과 리액트 컴포넌트 조합만으로 강력하고 유연한 AI 애플리케이션을 구축할 수 있습니다. 

앞으로의 AI 엔지니어링은 단지 언어 모델의 응답 속도를 높이는 것을 넘어, 그 응답이 사용자의 화면 위에서 얼마나 직관적이고 인터랙티브한 UI로 살아 움직이게 하느냐에 의해 판가름 날 것입니다. 오늘 다룬 아키텍처를 바탕으로 여러분의 프로덕션 환경에도 생동감 넘치는 Generative UI를 도입해 보시기 바랍니다.