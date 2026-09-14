---
layout: post
title: "DSPy와 자동 Teleprompter 최적화: 선언적 프롬프트 프로그래밍을 통한 프로덕션급 LLM 파이프라인 구축"
date: 2026-09-14 09:00:00 +0900
categories: [AI, Architecture]
tags: [DSPy, PromptEngineering, Teleprompter, LLMOptimization, Python]
---

대규모 언어 모델(LLM)을 활용한 소프트웨어를 개발할 때 가장 번거롭고 반복적인 작업 중 하나는 바로 **프롬프트 엔지니어링**입니다. 시스템 프롬프트를 미세 조정하고, Few-shot 예시를 수동으로 골라 넣으며, 모델의 버전이 바뀔 때마다 프롬프트를 처음부터 다시 테스트하는 과정은 엔지니어링 관점에서 매우 비효율적이고 확장성이 떨어집니다. 

이러한 문제를 해결하기 위해 등장한 개념이 바로 스탠포드 대학교 NLP 연구팀이 제안한 **DSPy(Declarative Language Model Programming)**입니다. DSPy는 프롬프트를 수동으로 텍스트 조작하는 방식에서 벗어나, 파이썬 코드를 통해 LLM 파이프라인을 **선언적(Declarative)**으로 정의하고, 컴파일러를 통해 최적의 프롬프트와 가중치를 자동으로 찾아내는 패러다임을 제공합니다. 이번 포스트에서는 DSPy의 핵심 개념과 Teleprompter를 활용한 자동 Few-shot 최적화 파이프라인을 프로덕션 환경에 적용하는 방법을 실전 코드를 통해 상세히 알아보겠습니다.

---

### 1. 프롬프트 엔지니어링의 한계와 DSPy의 선언적 프로그래밍 패러다임

전통적인 LLM 애플리케이션 개발은 프롬프트 문자열을 직접 조합하는 방식으로 이루어졌습니다. 예를 들어, 사용자 입력과 모델 응답 사이에 자연어로 된 지시사항을 넣고, 몇 가지 예시(Few-shot examples)를 하드코딩하여 프롬프트를 구성합니다. 이 방식은 다음과 같은 치명적인 한계를 가집니다.

* **모델 종속성:** GPT-4에서 완벽하게 동작하던 프롬프트가 Claude 3.5 Sonnet이나 오픈소스 모델인 Llama 3로 변경되는 순간 성능이 급격히 떨어져 처음부터 다시 튜닝해야 합니다.
* **유지보수성 결여:** 프롬프트 내부의 지시사항과 예시가 복잡해질수록 코드와 프롬프트의 결합도가 높아져 리팩토링이 불가능에 가까워집니다.
* **최적화의 부재:** 시스템의 전체 성능(Accuracy)을 높이기 위해 어떤 Few-shot 예시를 어떤 순서로 배치해야 가장 최적인지 수학적이거나 체계적으로 검증하기 어렵습니다.

DSPy는 이러한 문제를 해결하기 위해 LLM 프로그램 구조를 **모듈(Modules)**과 **시그니처(Signatures)**로 분리합니다. 시그니처는 LLM이 수행해야 할 입력과 출력의 계약(Interface)을 정의하며, 모듈은 이를 수행하는 논리적 단위입니다. 개발자는 "어떤 프롬프트를 쓸 것인가"가 아니라 "어떤 태스크를 수행할 것인가"를 선언하고, 컴파일러(Teleprompter)에게 데이터셋을 넘겨주어 최적의 프롬프트 조합을 알아서 찾아내도록 위임합니다.

---

### 2. DSPy 시그니처와 모듈을 활용한 복잡한 추론 파이프라인 설계

DSPy를 활용해 복잡한 질의응답 및 근거 추론(Chain of Thought) 파이프라인을 구축해 보겠습니다. DSPy의 `dspy.Signature`를 사용하면 LLM이 이해해야 할 입출력 명세를 명확하게 타입 기반으로 정의할 수 있습니다.

아래 코드는 사용자 질문에 대해 관련 문서를 검색하고, 이를 바탕으로 정확한 답변과 근거(Rationale)를 생성하는 파이프라인을 DSPy 모듈로 구현한 예시입니다.

```python
import dspy

# 1. LLM 및 검색기(Retriever) 설정 (예: OpenAI 모델 및 로컬 벡터 서치 연동 가정)
llm = dspy.LM('openai/gpt-4o-mini', temperature=0.0)
dspy.configure(lm=llm)

# 2. 입출력 계약을 정의하는 시그니처(Signature) 작성
class GenerateAnswerWithCitation(dspy.Signature):
    """주어진 컨텍스트(Context)를 바탕으로 질문(Question)에 대한 정확하고 상세한 답변을 생성하고, 인용 근거를 제시합니다."""
    
    context: str = dspy.InputField(desc="답변 도출에 필요한 신뢰할 수 있는 외부 문서 컨텍스트")
    question: str = dspy.InputField(desc="사용자의 자연어 질문")
    
    rationale: str = dspy.OutputField(desc="답변을 도출하기까지의 단계별 추론 과정 (Chain of Thought)")
    answer: str = dspy.OutputField(desc="최종 사용자 답변")

# 3. 사용자 정의 DSPy 모듈 구현
class AdvancedRAGPipeline(dspy.Module):
    def __init__(self, retriever_func):
        super().__init__()
        # 내부적으로 Chain of Thought 모듈에 시그니처를 바인딩
        self.generate_answer = dspy.ChainOfThought(GenerateAnswerWithCitation)
        self.retriever = retriever_func

    def forward(self, question: str):
        # 1단계: 외부 리트리버를 통해 관련 컨텍스트 검색
        retrieved_docs = self.retriever(question)
        context_str = "\n".join(retrieved_docs)
        
        # 2단계: 선언된 시그니처 모듈을 통해 추론 및 답변 생성 수행
        prediction = self.generate_answer(context=context_str, question=question)
        
        return dspy.Prediction(
            context=context_str,
            rationale=prediction.rationale,
            answer=prediction.answer
        )
```

이 구조의 강력한 점은 `GenerateAnswerWithCitation`이라는 시그니처 내부의 프롬프트 텍스트를 개발자가 직접 작성할 필요가 없다는 점입니다. DSPy 프레임워크가 모델의 특성에 맞게 가장 효과적인 프롬프트 구조로 변환하여 요청을 보냅니다.

---

### 3. Teleprompter와 MiproV2를 활용한 자동 Few-shot 최적화 실전

DSPy의 진정한 가치는 **Teleprompter(컴파일러)**에 있습니다. Teleprompter는 제공된 검증 데이터셋(Validation Dataset)과 평가 지표(Metric)를 기반으로, 시스템 내부의 프롬프트와 Few-shot 예시를 자동으로 최적화합니다. 

최신 DSPy 버전에서 제공하는 `MiproV2` (Multi-prompt Instruction Proposal Optimizer)는 명령어(Instructions)와 Few-shot 예시를 동시에 최적화하는 가장 강력한 옵티마이저 중 하나입니다. 이를 활용해 프로덕션 파이프라인을 최적화하는 코드를 살펴봅니다.

```python
from dspy.teleprompt import MIPROv2

# 1. 평가용 학습/검증 데이터셋 준비 (dspy.Example 객체 리스트)
trainset = [
    dspy.Example(
        context="DSPy는 스탠포드에서 개발한 LLM 프로그래밍 프레임워크입니다.",
        question="DSPy는 누가 개발했나요?",
        answer="스탠포드 대학교에서 개발했습니다."
    ).with_inputs('context', 'question'),
    # 추가 학습 데이터 생략...
]

# 2. 모델의 출력을 평가할 커스텀 메트릭(Metric) 함수 정의
def validation_metric(gold, pred, trace=None):
    """정답(gold.answer)과 예측값(pred.answer)의 의미적 유사성 및 키워드 포함 여부 평가"""
    gold_answer = gold.answer.strip().lower()
    pred_answer = pred.answer.strip().lower()
    
    # 단순 문자열 일치 또는 임베딩 기반 유사도 검증 로직 구현 가능
    return gold_answer in pred_answer

# 3. 더미 리트리버 함수 정의
def mock_retriever(query):
    return ["DSPy는 스탠포드에서 개발한 LLM 프로그래밍 프레임워크입니다.", "프롬프트를 코드로 관리하는 선언적 패러다임을 제공합니다."]

# 4. 파이프라인 인스턴스화
unoptimized_rag = AdvancedRAGPipeline(retriever_func=mock_retriever)

# 5. MIPROv2 Teleprompter 설정 및 컴파일 실행
teleprompter = MIPROv2(
    metric=validation_metric,
    auto="light", # 최적화 강도 설정 ('light', 'medium', 'heavy')
    num_threads=4
)

# 컴파일을 수행하면 최적의 instruction과 Few-shot 예시가 주입된 최적화된 모듈이 반환됨
optimized_rag = teleprompter.compile(
    student=unoptimized_rag,
    trainset=trainset,
    num_trials=10
)

# 6. 최적화된 파이프라인 실행 테스트
result = optimized_rag(question="DSPy를 만든 곳은 어디인가요?")
print(f"추론 과정 (Rationale): {result.rationale}")
print(f"최종 답변 (Answer): {result.answer}")
```

위 과정을 거치면, 개발자가 수동으로 프롬프트를 수정할 필요 없이 데이터 기반으로 검증된 가장 성능이 높은 프롬프트와 Few-shot 조합이 자동으로 생성됩니다. 모델이 업그레이드되거나 비즈니스 요구사항이 변경되어 데이터셋이 추가될 때마다 `compile` 함수만 다시 실행하면 지속적인 프롬프트 파이프라인 고도화(Continuous Prompt Optimization)가 가능해집니다.

---

### 결론

오늘날 AI 엔지니어링은 단순히 프롬프트 엔지니어링의 감에 의존하는 단계를 지나, 엄격한 코드 구조와 데이터 기반 최적화가 동반되는 시스템 엔지니어링으로 진화하고 있습니다. DSPy는 LLM 애플리케이션 개발에 선언적 프로그래밍 개념을 도입함으로써, 프롬프트를 하드코딩하는 지저분한 관행에서 벗어나 체계적이고 유지보수가 용이한 아키텍처를 구축할 수 있게 해줍니다. 

특히 대규모 프로덕션 환경에서 모델 성능을 극대화하고, 모델 교체에 유연하게 대응해야 하는 백엔드/AI 엔지니어라면 DSPy와 Teleprompter 기반의 자동 최적화 파이프라인 도입을 적극 검토해 보시기 바랍니다. 견고하고 확장 가능한 LLM 아키텍처 설계의 새로운 기준을 경험하게 될 것입니다.