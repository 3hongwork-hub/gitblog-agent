---
layout: post
title: "Direct Preference Optimization(DPO)과 실전 선호도 학습: 보상 모델 없는 사후 학습 파이프라인 구축"
date: 2026-09-09 09:00:00 +0900
categories: [AI, MachineLearning]
tags: [DPO, RLHF, FineTuning, LLM, PyTorch]
---

대규모 언어 모델(LLM)을 파인튜닝하는 전통적인 방식인 인간 피드백 기반 강화학습(RLHF, Reinforcement Learning from Human Feedback)은 강력하지만, 그 과정이 극도로 복잡하고 불안정하기로 악명이 높습니다. 프록시 보상 모델(Reward Model)을 먼저 학습시킨 뒤, PPO(Proximal Policy Optimization) 알고리즘을 사용해 액터(Actor) 모델을 최적화하는 과정은 막대한 메모리와 연산 자원을 요구하며 하이퍼파라미터 튜닝 역시 까다롭습니다. 

이러한 RLHF의 구조적 복잡성과 불안정성을 혁신적으로 해결하기 위해 등장한 기법이 바로 **DPO(Direct Preference Optimization)**입니다. DPO는 별도의 보상 모델 학습이나 강화학습 루프 없이, 선호도 데이터셋만으로 언어 모델을 직접 최적화할 수 있는 수렴성 높은 사후 학습(Post-training) 방법론입니다. 이번 포스트에서는 DPO의 이론적 배경을 짚어보고, 실제 프로덕션 환경에서 PyTorch와 허깅페이스(Hugging Face) 생태계를 활용해 보상 모델 없는 사후 학습 파이프라인을 구축하는 실전 아키텍처를 살펴보겠습니다.

---

### 1. 왜 DPO인가?: RLHF의 한계와 보상 함수 재정의

전통적인 RLHF 파이프라인은 세 단계로 나뉩니다. 첫째, SFT(Supervised Fine-Tuning) 모델 학습. 둘째, 인간의 선호(어떤 응답이 더 좋은가)를 점수로 매기는 보상 모델 학습. 셋째, 보상 모델의 점수를 극대화하기 위한 PPO 강화학습. 이 과정에서 보상 모델과 정책(Policy) 모델, 참조(Reference) 모델, 크리틱(Critic) 모델까지 동시에 메모리에 올려야 하므로 GPU VRAM 소모가 폭발적으로 증가합니다.

DPO는 수학적 트릭을 통해 이 복잡성을 제거합니다. 강화학습의 목적 함수를 언어 모델의 정책 자체에 대한 직접적인 손실 함수(Loss Function)로 재정의한 것입니다. 보상 함수 $r(x, y)$를 최적화 정책 $\pi_\theta(y|x)$와 참조 정책 $\pi_{ref}(y|x)$ 간의 로그 확률 비율로 표현할 수 있다는 점에 착안했습니다.

$$ \mathcal{L}_{DPO}(\theta; \pi_{ref}) = -\mathbb{E}_{(x, y_w, y_l)} \left[ \log \sigma \left( \beta \log \frac{\pi_\theta(y_w|x)}{\pi_{ref}(y_w|x)} - \beta \log \frac{\pi_\theta(y_l|x)}{\pi_{ref}(y_l|x)} \right) \right] $$

여기서 $y_w$는 선호되는 응답(Winner), $y_l$은 거부되는 응답(Loser)이며, $\beta$는 참조 정책으로부터의 이탈을 제어하는 파라미터입니다. 이 방식의 가장 큰 장점은 **강화학습 루프 없이 표준적인 교차 엔트로피(Cross-Entropy) 손실 함수를 계산하듯 모델을 가볍고 안정적으로 학습**시킬 수 있다는 점입니다.

---

### 2. DPO 파이프라인 실전 아키텍처 및 데이터셋 준비

성공적인 DPO 학습을 위해서는 프롬프트($x$), 선호 응답($y_w$), 비선호 응답($y_l$)으로 구성된 고품질의 페어(Pair) 데이터셋이 필수적입니다. 허깅페이스의 `trl`(Transformer Reinforcement Learning) 라이브러리는 이러한 DPO 학습을 표준화된 인터페이스로 지원합니다.

전체적인 파이프라인 아키텍처는 다음과 같이 설계합니다.
1. **기반 모델 및 참조 모델 로드**: 메모리 효율성을 위해 QLoRA(Quantized LoRA)를 결합하여 베이스 모델을 4비트로 로드합니다.
2. **데이터셋 토크나이징**: 프롬프트와 응답을 모델의 입력 포맷에 맞게 결합하고 정렬합니다.
3. **DPOTrainer 설정**: $\beta$ 값과 학습률, 배치 크기를 정의하고 트레이너를 초기화합니다.

아래는 프로덕션 환경에서 사용할 수 있는 DPO 파이프라인 구현의 핵심 코드입니다.

```python
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from trl import DPOTrainer
from peft import LoraConfig, get_peft_model

# 1. 모델 및 토크나이저 로드 (메모리 효율을 위한 4비트 양자화 적용)
model_id = "meta-llama/Llama-3-8B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto",
)

# 참조 모델(Reference Model)은 학습되지 않도록 별도로 두거나 
# DPO 트레이너 내부에서 LoRA를 활용해 가중치 고정 상태로 암묵적 참조를 수행합니다.
ref_model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto",
)

# 2. LoRA 설정 (Parameter-Efficient Fine-Tuning)
peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)

# 3. 선호도 데이터셋 로드 (예: UltraFeedback 또는 Anthropic HH-RLHFSubset)
dataset = load_dataset("json", data_files="preference_dataset.json", split="train")

# 데이터셋 구조 확인: 각 샘플은 'prompt', 'chosen', 'rejected' 필드를 포함해야 함
print(f"학습 데이터 샘플 수: {len(dataset)}")

# 4. DPO 트레이닝 아규먼트 설정
training_args = TrainingArguments(
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    gradient_checkpointing=True,
    learning_rate=5e-7,
    logging_steps=10,
    output_dir="./dpo_llama3_output",
    optim="paged_adamw_8bit",
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    bf16=True,
    report_to="tensorboard",
)

# 5. DPOTrainer 초기화 및 학습 실행
dpo_trainer = DPOTrainer(
    model=model,
    ref_model=ref_model,
    args=training_args,
    beta=0.1,  # 참조 모델과의 발산을 제어하는 하이퍼파라미터
    train_dataset=dataset,
    tokenizer=tokenizer,
    peft_config=peft_config,
    max_length=1024,
    max_prompt_length=512,
)

print("DPO 사후 학습 파이프라인 구동 시작...")
dpo_trainer.train()

# 학습된 어댑터 가중치 저장
dpo_trainer.model.save_pretrained("./dpo_final_adapter")
tokenizer.save_pretrained("./dpo_final_adapter")
print("DPO 학습 완료 및 모델 가중치 저장 성공!")
```

---

### 3. 프로덕션 환경에서의 DPO 최적화 및 평가 전략

DPO를 성공적으로 도입하기 위해서는 코드 구현뿐만 아니라 운영 측면의 노하우가 필요합니다. 첫째, **데이터 품질 관리**입니다. $y_w$와 $y_l$ 간의 명확한 격차가 존재하지 않거나, 환각(Hallucination)이 양쪽 모두에 포함된 데이터로 학습을 진행하면 모델의 일반화 성능이 급격히 저하됩니다. LLM-as-a-Judge 기법을 활용해 데이터셋을 사전에 필터링하는 단계를 파이프라인에 포함하는 것이 좋습니다.

둘째, **$\beta$ 파라미터 튜닝**입니다. $\beta$는 보통 $0.1$에서 $0.5$ 사이의 값을 사용합니다. $\beta$가 너무 작으면 모델이 참조 모델의 원래 분포로부터 너무 멀어져 텍스트 생성 능력이 망가지거나(Degeneration) 반복 문구가 발생하기 쉽습니다. 반대로 너무 크면 선호도 데이터의 반영 비율이 낮아져 학습 효과가 미미해집니다.

셋째, **평가(Evaluation)** 체계입니다. 학습 중간체크포인트마다 AlpacaEval이나 MT-Bench와 같은 표준 벤치마크를 수행하거나, 별도의 테스트 프롬프트 세트에 대해 기존 베이스 모델과 승률(Win-rate)을 비교하는 자동화된 평가 스크립트를 연동해야 합니다.

---

### 결론

오늘날 AI 엔지니어링 환경에서 모델의 성능을 결정짓는 핵심은 단순히 거대한 베이스 모델을 가져오는 것을 넘어, 특정 도메인과 사용자 경험에 맞게 얼마나 안정적이고 효율적으로 사후 학습을 수행하느냐에 달려 있습니다. 

DPO는 복잡한 보상 모델과 불안정한 PPO 강화학습 루프를 제거함으로써, 엔지니어들이 훨씬 적은 VRAM과 간단한 코드 구조로도 고품질의 선호도 학습을 수행할 수 있도록 길을 열어주었습니다. 위에서 살펴본 QLoRA 및 TRL 기반의 DPO 파이프라인을 여러분의 MLOps 인프라에 도입하여, 더욱 안전하고 사용자 의도에 정확히 부합하는 차세대 LLM 애플리케이션을 구축해 보시기 바랍니다.