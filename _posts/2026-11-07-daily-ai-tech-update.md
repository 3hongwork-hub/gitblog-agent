---
layout: post
title: "OpenTelemetry GenAI Semantic Conventions와 Arize Phoenix 기반 프로덕션 LLM 분산 트레이싱 파이프라인 구축"
date: 2026-11-07 09:00:00 +0900
categories: [AI, MLOps]
tags: [OpenTelemetry, Observability, Arize Phoenix, LLMOps, Distributed Tracing]
---

대규모 언어 모델(LLM)을 활용한 애플리케이션이 단순한 질의응답을 넘어 복잡한 멀티-스텝 에이전트, RAG 파이프라인, 외부 API 오케스트레이션 구조로 진화하면서 기존의 전통적인 APM(Application Performance Monitoring) 방식으로는 시스템의 병목과 장애를 추적하기 어려워졌습니다. 토큰 사용량에 따른 비용 급증, 단계별 레이턴시 파편화, 문맥 오염으로 인한 환각(Hallucination) 현상은 기존의 HTTP 상태 코드나 단순 CPU/메모리 메트릭 모니터링으로는 원인을 규명할 수 없습니다.

벤더 종속적인 트레이싱 도구에 의존하지 않고 엔터프라이즈 환경에서 안정적인 관측성(Observability)을 확보하기 위해, 오픈 표준인 **OpenTelemetry(OTel)의 GenAI Semantic Conventions**와 경량 오픈소스 평가 관측 플랫폼인 **Arize Phoenix**를 결합한 분산 트레이싱 파이프라인 구축 기법을 심층적으로 살펴봅니다.

---

## 1. LLM 관측성의 핵심: OpenTelemetry GenAI Semantic Conventions 표준 이해

전통적인 분산 트레이싱이 `http.method`, `db.statement`와 같은 스팬(Span) 속성을 통해 네트워크 트래픽 흐름을 추적했다면, LLM 파이프라인에서는 프롬프트, 생성 토큰, 모델 파라미터, 임베딩 벡터 크기 등을 계측해야 합니다. 클라우드 네이티브 컴퓨팅 재단(CNCF)의 OpenTelemetry 프로젝트는 이를 위해 GenAI 표준 속성 규격을 정의했습니다.

주요 시맨틱 속성은 다음과 같습니다:
- `gen_ai.system`: 모델 제공자 (예: `openai`, `anthropic`, `local`)
- `gen_ai.request.model`: 요청된 기본 모델 명칭
- `gen_ai.response.model`: 실제 추론을 수행한 상세 모델 명칭 (스냅샷 식별)
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`: 입출력 토큰 소비량
- `gen_ai.prompt`, `gen_ai.completion`: 입출력 페이로드 데이터(보안 규정에 따른 마스킹 처리 지원)

자체 구축 서비스 전반에 이러한 표준 스펙을 준수하는 트레이서를 삽입하면, 서드파티 모니터링 벤더가 변경되더라도 계측 코드(Instrumentation Code)를 다시 작성할 필요가 없으며, 단일 분산 트레이스 컨텍스트 안에서 마이크로서비스 호출과 LLM 추론 단계를 매끄럽게 연결할 수 있습니다.

---

## 2. Arize Phoenix 아키텍처 및 OpenInference 자동 계측 연동

Arize Phoenix는 OTel 표준을 충실히 따르는 대표적인 오픈소스 관측 플랫폼입니다. 내부적으로 `OpenInference` 프로젝트를 통해 LlamaIndex, LangChain, DSPy, OpenAI/Anthropic SDK의 호출을 OTel 스팬으로 자동 변환해 수집기(Collector)로 전송합니다.

기존 상용 SaaS(LangSmith, Datadog LLM Observability 등)와 비교했을 때, Phoenix는 사내 온프레미스 쿠버네티스 클러스터나 사설망 내에 독립 컨테이너로 띄울 수 있어 내부 데이터의 외부 유출(PII/보안 감사 이슈)을 원천 차단할 수 있습니다. 수집된 스팬 데이터를 기반으로 토큰 비용 분석, 레이턴시 P95/P99 구간 분석은 물론, 실시간 Evals(평가) 파이프라인을 트리거하여 환각 여부와 컨텍스트 관련성을 즉각 측정할 수 있습니다.

---

## 3. 실전 구현: OTel 수집기 및 커스텀 체인 분산 트레이싱 구축

아래 코드는 OpenTelemetry 트레이서 프로바이더를 초기화하여 Phoenix OTLP gRPC 엔드포인트(`4317` 포트)로 트레이스 데이터를 직접 스트리밍하고, 검색-합성 멀티 스텝 체인을 수동 계측하는 실전 파이프라인입니다.

```python
# tracer_pipeline.py
import os
import time
from typing import List, Dict, Any
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from openinference.semconv.trace import SpanAttributes

# 1. OpenTelemetry 리소스 정의 및 트레이서 프로바이더 구성
resource = Resource(attributes={
    ResourceAttributes.SERVICE_NAME: "enterprise-agent-service",
    ResourceAttributes.SERVICE_VERSION: "1.4.0",
    ResourceAttributes.DEPLOYMENT_ENVIRONMENT: "production"
})

tracer_provider = TracerProvider(resource=resource)

# 2. Arize Phoenix OTLP gRPC 수집기 익스포터 등록
otlp_exporter = OTLPSpanExporter(
    endpoint=os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "localhost:4317"),
    insecure=True
)
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("rag.pipeline.tracer")

# 3. 비즈니스 로직 계측 데코레이터 및 실행 체인
class ProductionRAGWorkflow:
    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name

    def retrieve_documents(self, query: str) -> List[Dict[str, Any]]:
        # Vector DB 검색 단계를 명시적 스팬으로 추적
        with tracer.start_as_current_span("vector_retrieval") as span:
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, "RETRIEVER")
            span.set_attribute("retrieval.query", query)
            span.set_attribute("retrieval.top_k", 3)
            
            # 가상 검색 지연 및 결과 페이로드 모사
            time.sleep(0.08)
            mock_docs = [
                {"id": "doc_101", "score": 0.89, "content": "K8s Ray 클러스터 아키텍처 스펙 문서"},
                {"id": "doc_102", "score": 0.76, "content": "분산 인메모리 캐싱 최적화 가이드"}
            ]
            
            span.set_attribute("retrieval.num_results", len(mock_docs))
            return mock_docs

    def execute_rag(self, user_prompt: str) -> str:
        # 전체 워크플로우 루트 체인 스팬 생성
        with tracer.start_as_current_span("rag_workflow_root") as root_span:
            root_span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, "CHAIN")
            root_span.set_attribute(SpanAttributes.INPUT_VALUE, user_prompt)

            # [1단계] 문서 검색
            retrieved_docs = self.retrieve_documents(user_prompt)
            context_str = "\n".join([d["content"] for d in retrieved_docs])

            # [2단계] LLM 호출 스팬 계측 (GenAI 시맨틱 컨벤션 준수)
            with tracer.start_as_current_span("llm_inference") as llm_span:
                llm_span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, "LLM")
                llm_span.set_attribute("gen_ai.system", "openai")
                llm_span.set_attribute("gen_ai.request.model", self.model_name)
                llm_span.set_attribute("gen_ai.request.temperature", 0.2)

                system_prompt = f"컨텍스트를 바탕으로 답변하십시오:\n{context_str}"
                full_prompt = f"{system_prompt}\n질문: {user_prompt}"
                
                # 프롬프트 입력 기록
                llm_span.set_attribute("gen_ai.prompt", full_prompt)

                # 실제 API 호출 모사 (비용 계산을 위한 토큰 메트릭 주입)
                time.sleep(0.35)  # 추론 지연 시간
                generated_output = "Ray 클러스터의 워커 노드는 KEDA에 의해 분산 스케일링됩니다."
                
                prompt_tokens = len(full_prompt.split()) * 2
                completion_tokens = len(generated_output.split()) * 2

                # 표준 토큰 메트릭 주입
                llm_span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
                llm_span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
                llm_span.set_attribute("gen_ai.usage.total_tokens", prompt_tokens + completion_tokens)
                llm_span.set_attribute("gen_ai.completion", generated_output)

            root_span.set_attribute(SpanAttributes.OUTPUT_VALUE, generated_output)
            return generated_output

if __name__ == "__main__":
    workflow = ProductionRAGWorkflow()
    response = workflow.execute_rag("Ray Cluster의 분산 스케일링 정책은 무엇인가요?")
    print(f"Workflow Response: {response}")
    # 배치 버퍼 강제 플러시
    tracer_provider.shutdown()
```

위 파이프라인이 실행되면 다음과 같은 메트릭 계층 구조가 Phoenix UI상에 형성됩니다:
1. `rag_workflow_root` (체인 전체 실행 시간, 입출력 확인)
2. `vector_retrieval` (검색 문서 수, 벡터 DB 응답 지연 시간, 매칭 스코어)
3. `llm_inference` (모델별 인풋/아웃풋 토큰 소비량, 온도 파라미터, 프롬프트 페이로드)

---

## 4. 실시간 평가(Evals) 파이프라인 연계 및 데이터 드리프트 모니터링

단순히 트레이스를 쌓는 것에 그치지 않고, 수집된 스팬 데이터를 기반으로 백그라운드 평가 워커(Evaluation Worker)를 구성할 수 있습니다. 

Phoenix는 OTel 스팬을 주기적으로 폴링하거나 웹훅으로 수신하여 가벼운 평가 모델(SLM 또는 규칙 기반 분석기)을 통해 아래 지표를 비동기 산출합니다:
- **Context Relevance(컨텍스트 관련성)**: 질의 내용과 검색된 청크 간의 코사인 유사도 및 정보 포함 비율.
- **Faithfulness(충실성/환각 탐지)**: 모델의 최종 응답이 컨텍스트 내의 사실에 기반했는지 여부.
- **Latency Anomalies(지연 시간 이상치 감지)**: 특정 토큰 길이 대비 비정상적으로 긴 Time to First Token(TTFT) 분석.

이를 통해 LLM 공급자의 모델 업데이트(Silent Update)로 인한 성능 저하나 검색 품질 저하를 운영팀이 사용자 불만 접수 전에 감지하고 즉시 롤백 또는 프롬프트 보정을 수행할 수 있습니다.

---

## 결론: 관측 불가능한 AI는 프로덕션이 될 수 없다

LLM 시스템을 프로덕션 엔터프라이즈 환경에서 운영한다는 것은 비결정론적인(Non-deterministic) 모델의 출력을 제어 가능하고 감사 가능한 엔지니어링 영역으로 끌어올리는 작업을 의미합니다.

특정 모니터링 벤더에 종속되지 않은 **OpenTelemetry GenAI Semantic Conventions** 표준을 채택하고, **Arize Phoenix**와 같은 인프라 친화적인 오픈소스 관측 플랫폼을 파이프라인에 조기 도입함으로써, 엔지니어는 비용 누수, 지연 시간 병목, 모델의 환각 문제를 정확한 데이터에 근거하여 디버깅할 수 있습니다. 진정한 엔지니어링 신뢰성은 모든 프롬프트와 토큰 하나하나를 투명하게 추적할 수 있는 관측성 인프라에서 시작됩니다.