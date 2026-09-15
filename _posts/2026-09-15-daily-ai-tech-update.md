---
layout: post
title: "Next.js 15 Server Actions와 Vercel AI SDK를 활용한 제너레이티브 UI 및 스트리밍 아키텍처 실전 구축"
date: 2026-09-15 09:00:00 +0900
categories: [Frontend, Architecture]
tags: [Next.js, VercelAISDK, GenerativeUI, React, TypeScript]
---

최근 웹 애플리케이션 개발 패러다임은 단순한 텍스트 기반의 챗봇 인터페이스를 넘어, 사용자의 의도에 따라 컴포넌트 자체가 동적으로 렌더링되는 **제너레이티브 UI(Generative UI)** 중심으로 진화하고 있습니다. 고정된 레이아웃 안에서 텍스트 응답만 보여주던 방식은 사용자의 복잡한 요구사항(예: 실시간 차트 생성, 동적 결제 모듈, 인터랙티브 폼)을 충족하기에 한계가 명확합니다.

본 포스트에서는 최신 **Next.js 15**의 강력한 아키텍처인 **Server Actions**와 **Vercel AI SDK**를 결합하여, 서버 측에서 안전하게 LLM과 통신하고 실시간으로 리액트 컴포넌트 스트리밍을 구현하는 프로덕션급 제너레이티브 UI 아키텍처의 설계 및 실전 구현 방법을 상세히 다룹니다.

---

### 1. Next.js 15와 Vercel AI SDK 연동 아키텍처 이해

전통적인 클라이언트 중심 AI 애플리케이션은 API 키 노출 위험, 대규모 페이로드 처리의 어려움, 그리고 컴포넌트 상태 동기화의 복잡성이라는 문제를 안고 있었습니다. Next.js 15의 **Server Actions**와 **React Server Components(RSC)** 생태계는 이러한 문제를 해결하는 이상적인 기반을 제공합니다.

Vercel AI SDK v4 이상에서는 서버와 클라이언트 간의 데이터 흐름을 완벽하게 추상화한 `streamText` 및 `createStreamableUI` 등의 유틸리티를 제공합니다. 이를 통해 LLM의 토큰 스트리밍과 동시에 구조화된 리액트 컴포넌트(`JSX.Element`)를 클라이언트로 안전하게 푸시할 수 있습니다. 

전체적인 데이터 흐름은 다음과 같습니다:
1. **사용자 입력**: 클라이언트 컴포넌트에서 Next.js Server Action 호출.
2. **서버 처리**: 서버 측에서 시스템 프롬프트와 도구(Tools) 정의를 바탕으로 LLM(`gpt-4o` 또는 `claude-3-5-sonnet`)에 요청 전송.
3. **컴포넌트 스트리밍**: LLM이 특정 툴 호출(Tool Call)을 트리거하면, 서버는 해당 툴에 매핑된 리액트 컴포넌트를 즉시 렌더링하여 스트림 형태로 클라이언트에 전송.
4. **실시간 UI 갱신**: 클라이언트는 수신된 컴포넌트를 지연 없이 화면에 마운트하여 제너레이티브 UI 완성.

---

### 2. 도구 정의 및 제너레이티브 UI 컴포넌트 설계

사용자의 입력에 따라 동적으로 렌더링될 컴포넌트와 이를 제어할 AI 툴 스키마를 정의해야 합니다. 여기서는 사용자가 재무 데이터 분석을 요청했을 때 인터랙티브 차트 컴포넌트를 동적으로 생성하는 시나리오를 구현합니다.

먼저, 클라이언트와 서버에서 공통으로 사용할 수 있는 동적 차트 컴포넌트와 이를 처리할 서버 액션 파일을 작성합니다.

```typescript
// app/actions.tsx
'use server';

import { streamUI } from 'ai/rsc';
import { openai } from '@ai-sdk/openai';
import { z } from 'zod';
import { StockChartComponent } from '@/components/StockChartComponent';
import { LoadingCard } from '@/components/LoadingCard';

export async function submitUserMessage(userInput: string) {
  // 스트리밍 UI 객체 생성
  const result = await streamUI({
    model: openai('gpt-4o'),
    system: '당신은 전문 금융 어시스턴트입니다. 사용자의 요청에 따라 적절한 UI 컴포넌트를 동적으로 생성하여 응답하세요.',
    prompt: userInput,
    // AI가 호출할 수 있는 도구(Tools) 정의
    tools: {
      showStockChart: {
        description: '주식 종목의 가격 변동 추이 차트를 화면에 표시합니다.',
        parameters: z.object({
          symbol: z.string().describe('주식 티커 심볼 (예: AAPL, TSLA)'),
          timeframe: z.enum(['1D', '1W', '1M', '1Y']).describe('조회 기간'),
        }),
        // 도구 실행 시 렌더링할 리액트 컴포넌트 반환
        generate: async function* ({ symbol, timeframe }) {
          // 1단계: 데이터 로딩 중 상태 표시 컴포넌트 전송
          yield <LoadingCard message={`${symbol} 데이터를 불러오는 중입니다...`} />;

          // 외부 금융 API 호출 시뮬레이션
          await new Promise((resolve) => setTimeout(resolve, 1500));
          const mockData = [
            { date: '2026-09-10', price: 150 },
            { date: '2026-09-11', price: 155 },
            { date: '2026-09-12', price: 152 },
            { date: '2026-09-15', price: 160 },
          ];

          // 2단계: 최종 완성된 인터랙티브 차트 컴포넌트 스트리밍
          return <StockChartComponent symbol={symbol} timeframe={timeframe} data={mockData} />;
        },
      },
    },
  });

  return {
    id: Date.now(),
    display: result.value,
  };
}
```

위 코드에서 `streamUI` 함수는 AI의 응답 내용뿐만 아니라, 특정 조건(`tools.showStockChart`)이 충족되었을 때 리액트 컴포넌트를 제너레이티브하게 생성하여 클라이언트로 흘려보내는 핵심적인 역할을 수행합니다.

---

### 3. 클라이언트 인터페이스 및 대화형 상태 관리 구현

서버에서 스트리밍되어 오는 제너레이티브 UI와 텍스트 응답을 원활하게 렌더링하기 위해 클라이언트 측 컴포넌트를 구현합니다. Next.js 15의 클라이언트 컴포넌트 환경에서 `useActionState` 또는 Vercel AI SDK가 제공하는 상태 관리 패턴을 활용합니다.

```tsx
// app/page.tsx
'use client';

import { useState } from 'react';
import { submitUserMessage } from './actions';
import { useUIState, useActions } from 'ai/rsc';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  display: React.ReactNode;
}

export default function GenerativeUIPage() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userInput = input;
    setInput('');
    setIsLoading(true);

    // 사용자 메시지 낙관적 업데이트
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), role: 'user', display: <p>{userInput}</p> },
    ]);

    try {
      // Server Action 호출
      const response = await submitUserMessage(userInput);

      // AI 어시스턴트의 제너레이티브 UI 응답 추가
      setMessages((prev) => [
        ...prev,
        { id: response.id, role: 'assistant', display: response.display },
      ]);
    } catch (error) {
      console.error('Generative UI 스트리밍 오류:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="flex flex-col h-screen max-w-4xl mx-auto p-4 justify-between bg-gray-50 dark:bg-zinc-950">
      {/* 대화 및 제너레이티브 UI 렌더링 영역 */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-2">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`p-4 rounded-2xl max-w-[85%] shadow-sm ${
                m.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-900 dark:text-zinc-100'
              }`}
            >
              {m.display}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-sm animate-pulse">
              AI가 응답을 생성하고 컴포넌트를 조립하고 있습니다...
            </div>
          </div>
        )}
      </div>

      {/* 입력 폼 영역 */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 애플(AAPL) 1개월 주가 차트 보여줘"
          className="flex-1 px-4 py-3 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={isLoading}
          className="px-6 py-3 rounded-xl bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          전송
        </button>
      </form>
    </main>
  );
}
```

---

### 4. 프로덕션 운영 시 고려사항 및 최적화 팁

Next.js 15와 Vercel AI SDK 기반의 제너레이티브 UI 파이프라인을 프로덕션 환경에 배포할 때 반드시 검토해야 할 핵심 엔지니어링 포인트는 다음과 같습니다.

* **스트리밍 에러 핸들링 (ErrorBoundary)**: 서버 액션 내부의 LLM 호출이나 외부 API 연동 중 예외가 발생할 경우, 클라이언트 전체가 깨지지 않도록 React `ErrorBoundary`를 적극 활용하여 대체 UI(Fallback UI)를 제공해야 합니다.
* **타입 안정성 보장**: Zod 스키마 정의 시 엄격한 유효성 검사를 수행하여, LLM이 환각(Hallucination) 현상으로 잘못된 파라미터를 전달하더라도 타입 오류로 인한 서버 크래시를 방지합니다.
* **엣지 런타임 최적화**: Vercel Edge Runtime 또는 Cloudflare Workers 등 분산 엣지 환경에서 Server Actions를 실행하면 전 세계 사용자에게 초저지연 AI 응답 및 컴포넌트 스트리밍을 제공할 수 있습니다.

---

### 결론

지금까지 Next.js 15의 Server Actions와 Vercel AI SDK를 결합하여 실시간 제너레이티브 UI 아키텍처를 구축하는 방법을 살펴보았습니다. 정적인 텍스트 응답을 넘어, 사용자의 맥락에 맞는 인터랙티브 컴포넌트를 실시간으로 조립하고 스트리밍하는 이 기술은 웹 애플리케이션의 사용자 경험을 완전히 새로운 차원으로 도약시킵니다. 앞으로 복잡한 엔터프라이즈 AI 서비스 개발에 본 아키텍처를 도입하여 확장성과 유지보수성을 모두 확보해 보시길 바랍니다.