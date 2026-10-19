---
layout: post
title: "Direct Preference Optimization(DPO)와 TRL 기반 정렬 학습: RLHF의 복잡성을 걷어낸 초경량 LLM 인간 피드백 최적화 파이프라인 구축"
date: 2026-10-19 09:00:00 +0900
categories: [AI, MachineLearning]
tags: [DPO, TRL, Alignment, LLM-FineTuning, HuggingFace]
---

대규모 언어 모델(LLM)을 개발할 때 베이스 모델의 사전 학습(Pre-training)과 지시 미세조정(Supervised Fine-Tuning, SFT)만으로는 사용자의 복잡한 의도, 안전성 기준, 스타일 선호도를 완벽히 반영하기 어렵습니다. 과거에는 이를 해결하기 위해 강화학습 기반의 RLHF(Reinforcement Learning from Human Feedback)가 표준으로 자리 잡았으나, 별도의 보상 모델(Reward Model) 학습, PPO(Proximal Policy Optimization)의 높은 최적화 불안정성, 그리고 액터-크리틱 네트워크 유지로 인한 막대한 GPU VRAM 소모는 프로덕션 레벨의 신속한 반복을 가로막는 치명적인 병목이었습니다.

2026년 현재, 엔터프라이즈 LLM 정렬 파이프라인의 사실상 표준(De-facto Standard)으로 자리 잡은 방법론은 바로 **DPO(Direct Preference Optimization)**입니다. DPO는 보상 모델 학습과 복잡한 강화학습 루프를 생략하고, 선호도 데이터셋에 대한 폐쇄형(Closed-form) 손실 함수를 도출하여 단순한 분류 손실(Classification Loss)처럼 언어 모델을 직접 최적화합니다.

본 포스트에서는 DPO의 수학적 원리를 간략히 짚어보고, Hugging Face의 `TRL(Transformer Reinforcement Learning)` 라이브러리와 `PEFT(LoRA)`를 결합하여 단일 또는 소규모 GPU 환경에서도 안정적으로 프로덕션급 정렬 학습을 완수할 수 있는 엔드투엔드 파이프라인을 구축해 보겠습니다.

---

### 1. PPO의 한계를 극복하는 DPO의 핵심 수학적 메커니즘

전통적인 RLHF 파이프라인은 세 단계로 구성됩니다: (1) SFT 모델 준비, (2) 인간 피드백 기반 보상 모델(Reward Model) 학습, (3) PPO 알고리즘을 사용한 정책 모델(Policy Model) 최적화. 이 과정에서 PPO는 참조 모델(Reference Model), 가치 모델(Value Model), 정책 모델(Policy Model), 보상 모델(Reward Model) 등 최소 4개의 독립적 모델 인스턴스를 GPU 메모리에 유지하거나 지속적으로 스왑해야 하는 오버헤드를 발생시킵니다.

DPO는 브래들리-테리(Bradley-Terry) 선호도 확률 모델을 재구성하여, 보상 함수 $r(x, y)$를 최적 정책 $\pi_\theta$와 참조 정책 $\pi_{ref}$ 간의 로그 확률 비율(Implicit Reward)로 수학적으로 치환합니다:

$$r(x, y) = \beta \log \frac{\pi_\theta(y \mid x)}{\pi_{ref}(y \mid x)}$$

이 변환을 통해 보상 모델을 직접 모델링하지 않고도, 선호된 응답($y_w$, Winner)과 거절된 응답($y_l$, Loser) 사이의 우위를 직접 정의하는 단일 목적 함수를 유도할 수 있습니다:

$$\mathcal{L}_{DPO}(\pi_\theta; \pi_{ref}) = -\mathbb{E}_{(x, y_w, y_l) \sim \mathcal{D}} \left[ \log \sigma \left( \beta \log \frac{\pi_\theta(y_w \mid x)}{\pi_{ref}(y_w \mid x)} - \beta \log \frac{\pi_\theta(y_l \mid x)}{\pi_{ref}(y_l \mid x)} \right) \right]$$

여기서 $\beta$는 참조 모델 $\pi_{ref}$로부터의 편차를 제어하는 하이퍼파라미터입니다. 값이 클수록 참조 모델의 생성 분포를 더 엄격하게 유지하며 언어 모델의 모드 붕괴(Mode Collapse) 및 환각을 방지합니다.

---

### 2. 고품질 선호도 데이터셋(Preference Dataset) 설계 및 전처리

성공적인 DPO 학습의 성패는 데이터셋 품질에 90% 이상 의존합니다. 프롬프트($prompt$), 채택된 응답($chosen$), 거절된 응답($rejected$)으로 구성된 트리플렛(Triplet) 데이터 구조에서 두 응답 간의 의미론적 차이가 명확해야 합니다.

단순 문법 오류나 길이 차이에 의한 편향(Length Bias)을 최소화하기 위해 다음 규칙을 준수해야 합니다:
1. **길이 정규화**: 채택된 답변이 단순히 더 길다는 이유로 선호되지 않도록 토큰 길이를 상호 유사하게 제어합니다.
2. **거절 응답의 구체성**: 거절된 응답이 단순한 무의미 텍스트(Gibberish)가 아니라, 논리적 결함, 안전 가이드라인 위반, 또는 부정확한 정보가 포함된 그럴듯한(Plausible) 오답이어야 경계선 최적화가 유효해집니다.

다음은 TRL의 `DPOTrainer`가 요구하는 표준 데이터셋 스키마 예시입니다:

```json
[
  {
    "prompt": "시스템 아키텍처에서 마이크로서비스 간 비동기 메시징의 장단점을 설명해 줘.",
    "chosen": "비동기 메시징은 시스템 간 결합도(Coupling)를 낮추고 트래픽 버퍼링을 통해 탄력성을 확보할 수 있습니다. 단, 최종 일관성(Eventual Consistency) 관리와 분산 추적(Distributed Tracing)의 복잡도가 증가합니다.",
    "rejected": "비동기 메시징은 무조건 빠른 속도를 보장하며 데이터 동기화가 실시간으로 즉시 해결되므로 대규모 시스템에서 단점이 전혀 없습니다."
  }
]
```

---

### 3. TRL과 LoRA 기반 DPO 파이프라인 구현

최신 TRL 라이브러리는 LoRA 어댑터를 학습 모델에만 장착하고, 어댑터가 비활성화된 기본 베이스 가중치를 내부적으로 $\pi_{ref}$로 취급하여 메모리 점유율을 획기적으로 낮춥니다. 이를 통해 A100(80GB) 한 장 혹은 L4(24GB) GPU 환경에서도 8B~14B 파라미터 모델의 정렬 학습이 가능합니다.

다음은 프로덕션 레벨에서 동작 가능한 DPO 파인튜닝 스크립트 전문입니다.

```python
import torch
from datasets import load_dataset
from peft import LoraConfig, TaskType
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from trl import DPOTrainer, DPOConfig

def run_dpo_pipeline():
    model_id = "meta-llama/Llama-3.1-8B-Instruct"

    # 1. 토크나이저 초기화 및 패딩 토큰 설정
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 2. bfloat16 기반 베이스 모델 로드 (Reference 모델 역할 겸용)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="flash_attention_2"
    )
    model.config.use_cache = False

    # 3. LoRA 어댑터 설정 (학습 대상 파라미터 격리)
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )

    # 4. 정렬용 선호도 데이터셋 로드
    # 실제 환경에서는 조직 내부의 클렌징된 데이터셋 경로를 지정합니다.
    dataset = load_dataset("json", data_files={"train": "preference_data_train.json", "test": "preference_data_eval.json"})

    # 5. DPO 학습 하이퍼파라미터 정의
    training_args = DPOConfig(
        output_dir="./results_llama3_dpo",
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=8,
        learning_rate=5e-6,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        num_train_epochs=3,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        bf16=True,
        max_prompt_length=512,
        max_length=1024,
        beta=0.1,  # KL 페널티 계수 (통상 0.05 ~ 0.2 권장)
        loss_type="sigmoid",
        gradient_checkpointing=True,
        optim="adamw_torch_fused",
        report_to="none"
    )

    # 6. DPOTrainer 인스턴스화
    # ref_model=None으로 지정할 경우, peft_config 기반 어댑터 비활성화 상태를 자동으로 참조 모델로 인식합니다.
    dpo_trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["test"],
        tokenizer=tokenizer,
        peft_config=peft_config
    )

    print(">>> DPO 정렬 학습을 시작합니다.")
    dpo_trainer.train()

    # 7. 최종 LoRA 어댑터 가중치 저장
    print(">>> 학습 완료. 가중치 저장 중...")
    dpo_trainer.save_model("./results_llama3_dpo/final_checkpoint")
    tokenizer.save_pretrained("./results_llama3_dpo/final_checkpoint")

if __name__ == "__main__":
    run_dpo_pipeline()
```

---

### 4. DPO 학습 모니터링 메트릭 분석 및 실전 트러블슈팅

DPO 파이프라인 실행 중에는 일반적인 크로스 엔트로피 손실 외에 정렬 성능을 가늠하는 핵심 메트릭들을 반드시 관찰해야 합니다.

* **`rewards/accuracies`**: 채택된 응답($y_w$)의 암묵적 보상이 거절된 응답($y_l$)의 보상보다 높은 샘플의 비율입니다. 학습이 정상적이라면 이 값은 $0.5$에서 시작하여 점진적으로 $0.75 \sim 0.90$ 수준으로 수렴해야 합니다. 만약 급격히 $1.0$에 도달한다면 모델이 과적합(Overfitting)되어 출력 다양성을 상실하고 있을 가능성이 큽니다.
* **`rewards/margins`**: 채택된 응답과 거절된 응답 간 보상 값의 평균 차이($\Delta r$)입니다. 마진이 양수 범위에서 점진적으로 증가해야 이상적입니다. 음수로 떨어질 경우 정렬 방향이 반대로 수렴하고 있음을 의미합니다.
* **$\beta$ 하이퍼파라미터 튜닝 전략**: 
  - 응답이 장황해지거나 이전 지시사항 준수 능력을 상실하는 '정렬 세금(Alignment Tax)' 현상이 나타나면 $\beta$를 $0.1 \rightarrow 0.2$로 상향하여 참조 모델과의 괴리를 줄여야 합니다.
  - 반대로 모델이 여전히 거절해야 할 패턴(비윤리적 요청, 오류 코드 생성)을 계속 생성한다면 선호도 신호 반영 강도를 높이기 위해 $\beta$를 $0.05$ 수준으로 낮추는 것이 적절합니다.

---

### 마치며: 정렬(Alignment) 공학의 다음 단계

DPO는 복잡한 강화학습 인프라를 구축할 여력이 부족했던 엔지니어링 팀에게 강력한 정렬 도구를 제공했습니다. 별도의 보상 함수 네트워크 훈련과 PPO의 수렴 불안정성 문제를 완전히 제거함으로써, 지속적인 데이터 피드백 루프를 CI/CD 파이프라인에 통합할 수 있는 길을 열었습니다.

최근에는 DPO의 한계를 보완하기 위해 참조 모델 자체를 완전히 배제하는 SimPO(Simple Preference Optimization)나 온라인 선호도 피드백을 실시간으로 수렴하는 On-policy DPO 기법들이 지속적으로 등장하고 있습니다. 그러나 상용 프로덕션 환경에서 검증된 안정성과 툴체인의 성숙도 측면에서 볼 때, LoRA와 결합된 TRL DPO 파이프라인은 여전히 가장 신뢰할 수 있는 선택지입니다. 고도화된 선호도 데이터 수집 파이프라인과 DPO를 통해 모델의 최종 응답 퀄리티를 한 단계 끌어올려 보시기 바랍니다.