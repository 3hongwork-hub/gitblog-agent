---
layout: post
title: "vLLM과 PagedAttention 최적화: 초고속 고효율 로컬 LLM 서빙 인프라 구축"
date: 2026-08-25 09:00:00 +0900
categories: [AI, Infrastructure]
tags: [vLLM, PagedAttention, GPU, Inference, MLOps, LLMServing]
---

2026년 기업 내 보안 규정과 비용 최적화를 위해 자체 인프라(On-Premise) 또는 프라이빗 클라우드에서 오픈소스 소형/대형 모델(Llama 3.3, DeepSeek, Qwen 2.5)을 직접 서빙하는 요구가 급증하고 있습니다.

이러한 로컬 LLM 서빙 환경에서 가장 큰 성능 병목은 **KV 캐시(Key-Value Cache) 메모리 낭비와 처리량(Throughput)** 문제입니다. 이번 글에서는 가상 메모리 페이징 기법을 도입해 처리량을 최대 24배까지 끌어올린 **vLLM과 PagedAttention의 아키텍처 및 실전 서빙 파이프라인**을 분석합니다.

---

## 1. PagedAttention의 핵심 원리와 메모리 절감

전통적인 트랜스포머 추론 엔진은 요청마다 최대 시퀀스 길이에 맞춰 연속된 GPU 메모리를 미리 할당(Pre-allocation)하므로, 심각한 메모리 단편화(Memory Fragmentation)와 낭비(60~80%)가 발생했습니다.

```
[기존 방식]: 요청마다 고정된 연속 메모리 예약 -> 내부 단편화로 동시 요청 수 급감
[PagedAttention]: OS의 가상 메모리 페이징처럼 KV 텐서를 작은 블록(Block) 단위로 쪼개어 동적 할당
```

* **메모리 낭비율 4% 미만으로 감소**: 남는 GPU VRAM을 거의 100% 활용하여 동시 처리 가능한 배치 크기(Batch Size)를 대폭 확장
* **Copy-on-Write 기반 프롬프트 공유**: 시스템 프롬프트나 Few-shot 예시가 동일한 경우 물리 메모리를 중복 할당하지 않고 공유

---

## 2. 실전 vLLM OpenAI 호환 서버 배포 스크립트

```bash
# 1. vLLM 기반 고성능 OpenAI 호환 API 서버 구동 예시
python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 32768 \
    --enable-prefix-caching \
    --port 8000
```

```python
# 2. Python OpenAI SDK를 통한 vLLM 서버 연동
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="token-local-vllm"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-Coder-32B-Instruct",
    messages=[
        {"role": "system", "content": "당신은 고성능 시스템 엔지니어입니다."},
        {"role": "user", "content": "비동기 I/O 이벤트 루프의 락-프리 큐 구조를 설명해주세요."}
    ],
    temperature=0.2
)

print(response.choices[0].message.content)
```

---

## 3. 프로덕션 운영 시 3대 핵심 튜닝 지표

1. **`--enable-prefix-caching` 활성화**: 시스템 프롬프트나 긴 컨텍스트 RAG 질의 시 첫 토큰 생성 시간(TTFT)을 80% 이상 단축할 수 있습니다.
2. **텐서 병렬화(`--tensor-parallel-size`)**: 모델 크기에 맞게 다중 GPU(A100/H100/L40S)에 가중치를 균등 분산하여 VRAM 부족(OOM)을 방지하세요.
3. **지속적 배치 처리(Continuous Batching)**: 들어오는 요청을 기다리지 않고 토큰 단위로 실시간 인터리빙 처리하여 GPU 가동률(SM Utilization)을 극대화하세요.

---

## 4. 결론

자체 모델 서빙 인프라의 가성비와 처리량을 극대화하기 위해서는 **vLLM의 PagedAttention 및 프리픽스 캐싱 최적화**를 표준 런타임으로 채택하여 GPU 비용을 획기적으로 절감할 수 있습니다.