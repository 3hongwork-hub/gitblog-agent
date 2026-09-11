---
layout: post
title: "SWE-bench와 LLM-as-a-Judge를 결합한 자율 소프트웨어 엔지니어링 에이전트 평가 및 벤치마크 파이프라인 실전 구축"
date: 2026-09-11 09:00:00 +0900
categories: [AI, Engineering]
tags: [SWE-bench, LLM-as-a-Judge, AgentEvaluation, MLOps, Python]
---

현대 소프트웨어 엔지니어링 생태계에서 LLM 기반의 자율 코딩 에이전트는 단순한 코드 자동완성 수준을 넘어, 실제 복잡한 오픈소스 이슈를 해결하고 리팩토링을 수행하는 주체로 진화하고 있습니다. 하지만 에이전트의 성능이 향상될수록 엔지니어들이 직면하는 가장 큰 고민은 "이 에이전트가 정말 프로덕션 수준의 신뢰성을 가지는가?"라는 검증의 문제입니다. 기존의 단순 유닛 테스트 통과 여부만으로는 에이전트의 실질적인 문제 해결 능력, 논리적 사고 과정, 그리고 예기치 않은 부작용을 완벽히 측정하기 어렵습니다.

이번 포스트에서는 실제 GitHub 이슈를 기반으로 에이전트의 코딩 능력을 엄격하게 평가하는 **SWE-bench** 표준 프레임워크와, 정성적 및 다면적 코드 품질을 채점하기 위한 **LLM-as-a-Judge(LLM 심사위원)** 아키텍처를 결합하여 견고한 에이전트 평가 및 벤치마크 자동화 파이프라인을 구축하는 실전 방법을 다룹니다.

---

### 1. SWE-bench 기반 에이전트 평가 아키텍처의 이해

에이전트 벤치마크 파이프라인을 구축하기 위해서는 에이전트가 격리된 실행 환경(Sandbox) 내에서 복잡한 리포지토리를 클론하고, 자연어로 된 이슈 설명을 읽은 뒤, 실제 패치(Patch)를 생성하여 유닛 테스트를 통과하는 전 과정을 자동화해야 합니다.

SWE-bench는 실제 Python 오픈소스 리포지토리(예: Django, SymPy, Scikit-learn 등)의 실제 이슈와 머지된 풀 리퀘스트(PR)를 벤치마크 데이터셋으로 제공합니다. 에이전트 평가 파이프라인의 핵심 구조는 다음과 같이 설계됩니다.

1. **데이터셋 로더 (Dataset Loader):** 평가하고자 하는 SWE-bench 하위셋(예: Lite 버전)을 로드하여 이슈 ID, 리포지토리 정보, 기본 테스트 케이스를 파싱합니다.
2. **격리된 실행 환경 (Docker Sandbox):** 각 이슈별로 정확한 Python 버전 및 의존성 라이브러리가 설치된 Docker 컨테이너를 동적으로 프로비저닝합니다.
3. **에이전트 실행 및 패치 추출 (Agent Execution & Patch Generation):** 에이전트가 리포지토리 내부에서 코드를 수정하고, 최종적으로 `git diff`를 통해 생성한 패치 파일을 추출합니다.
4. **테스트 검증 (Test Evaluation):** 추출된 패치를 원본 리포지토리에 적용한 후, 해당 이슈와 연관된 회귀 테스트(Regression Tests)와 패치 테스트를 실행하여 성공 여부를 판정합니다.

---

### 2. LLM-as-a-Judge를 통한 정성적 코드 품질 평가 도입

기능적 테스트(Functional Test)가 통과하더라도, 에이전트가 작성한 코드가 안티 패턴을 포함하고 있거나, 가독성이 현저히 떨어지거나, 보안 취약점을 유발할 수 있습니다. 이를 보완하기 위해 **LLM-as-a-Judge** 패턴을 도입하여 다차원적인 평가를 수행합니다.

LLM 심사위원은 생성된 패치와 원래 이슈의 요구사항을 입력받아 다음과 같은 기준으로 점수를 부여합니다.
* **정확성 (Correctness):** 요구사항을 정확히 충족하고 있는지 여부
* **유지보수성 (Maintainability):** 기존 코드베이스의 컨벤션을 따르고 가독성이 높은지 여부
* **효율성 (Efficiency):** 불필요한 연산이나 리소스 낭비를 유발하지 않는지 여부

이러한 평가는 수치화된 메트릭과 함께 상세한 피드백 텍스트를 반환하므로, 에이전트의 프롬프트나 툴 체인을 개선하는 데 결정적인 인사이트를 제공합니다.

---

### 3. Python 기반 SWE-bench 및 LLM-as-a-Judge 통합 파이프라인 구현

아래 코드는 SWE-bench 데이터셋을 활용해 에이전트의 패치를 실행하고, 동시에 LLM-as-a-Judge를 통해 코드 품질을 평가하는 통합 벤치마크 파이프라인의 핵심 구현 예시입니다.

```python
import os
import subprocess
import json
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from openai import OpenAI

# OpenAI 클라이언트 초기화 (LLM-as-a-Judge 용도)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "mock-key"))

class EvaluationResult(BaseModel):
    issue_id: str = Field(description="평가 대상 이슈 식별자")
    functional_passed: bool = Field(description="유닛 테스트 통과 여부")
    judge_score: int = Field(description="LLM 심사위원의 코드 품질 점수 (1-10)")
    judge_feedback: str = Field(description="심사위원의 상세 피드백 및 개선 제안")

def run_docker_sandbox_test(repo_name: str, base_commit: str, patch_content: str) -> bool:
    """
    Docker 컨테이너를 동적으로 실행하여 에이전트가 생성한 패치를 적용하고
    SWE-bench 테스트 스위트를 실행하는 시뮬레이션 함수
    """
    print(f"[*] 샌드박스 환경 구축 중: Repository={repo_name}, Commit={base_commit}")
    
    # 실제 프로덕션 환경에서는 Docker SDK를 사용하여 컨테이너 내부에서 pytest 등을 실행
    # 여기서는 예시를 위해 가상 실행 로직을 구현합니다.
    try:
        # 가상의 패치 적용 및 테스트 명령어 실행 시뮬레이션
        # subprocess.run(["docker", "exec", container_id, "pytest", ...], check=True)
        
        # 패치 내용이 비어있지 않고 기본 구문 검증을 통과했다고 가정
        if patch_content and "def " in patch_content:
            return True
        return False
    except subprocess.CalledProcessError:
        return False

def evaluate_with_llm_judge(issue_description: str, agent_patch: str) -> Dict[str, Any]:
    """
    LLM-as-a-Judge를 활용하여 에이전트가 작성한 패치의 정성적 품질을 평가
    """
    prompt = f"""
    당신은 수석 소프트웨어 아키텍트입니다. 다음 GitHub 이슈와 AI 에이전트가 작성한 코드 패치를 면밀히 검토하고 평가해주세요.
    
    [이슈 설명]:
    {issue_description}
    
    [에이전트 패치]:
    {agent_patch}
    
    다음 JSON 형식으로만 응답해주세요:
    {{
      "score": (1부터 10 사이의 정수),
      "feedback": "코드의 품질, 컨벤션 준수 여부, 잠재적 부작용에 대한 상세 분석"
    }}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    result = json.loads(response.choices[0].message.content)
    return result

def run_benchmark_pipeline(benchmark_dataset: List[Dict[str, Any]]) -> List[EvaluationResult]:
    """
    전체 벤치마크 데이터셋에 대해 기능 테스트와 LLM 심사위원 평가를 수행하는 파이프라인
    """
    results = []
    
    for item in benchmark_dataset:
        issue_id = item["issue_id"]
        repo = item["repo"]
        base_commit = item["base_commit"]
        issue_desc = item["text"]
        agent_patch = item["agent_generated_patch"] # 에이전트가 생성한 git diff 패치
        
        # 1. 기능적 유닛 테스트 검증
        passed = run_docker_sandbox_test(repo, base_commit, agent_patch)
        
        # 2. LLM-as-a-Judge 정성적 평가
        judge_res = evaluate_with_llm_judge(issue_desc, agent_patch)
        
        eval_result = EvaluationResult(
            issue_id=issue_id,
            functional_passed=passed,
            judge_score=judge_res["score"],
            judge_feedback=judge_res["feedback"]
        )
        results.append(eval_result)
        
    return results

# --- 실행 예시 ---
if __name__ == "__main__":
    sample_dataset = [
        {
            "issue_id": "django__django-12345",
            "repo": "django/django",
            "base_commit": "abc1234",
            "text": "QuerySet.get()에서 특정 조건 하에 예외 처리가 누락되는 버그 수정",
            "agent_generated_patch": "diff --git a/django/db/models/query.py b/django/db/models/query.py\n--- a/django/db/models/query.py\n+++ b/django/db/models/query.py\n@@ -100,6 +100,8 @@\n     def get(self, *args, **kwargs):\n         clone = self._chain()\n+        if not kwargs and not args:\n+            raise EmptyResultSet(\"QuerySet.get() requires args or kwargs\")\n         return super().get(*args, **kwargs)"
        }
    ]
    
    evaluation_reports = run_benchmark_pipeline(sample_dataset)
    for report in evaluation_reports:
        print(f"\n[이슈 ID: {report.issue_id}]")
        print(f" - 기능 테스트 통과: {report.functional_passed}")
        print(f" - LLM 심사위원 점수: {report.judge_score}/10")
        print(f" - 심사 피드백: {report.judge_feedback}")
```

---

### 결론

자율 소프트웨어 엔지니어링 에이전트의 발전 속도는 눈부시지만, 이를 안전하게 프로덕션에 도입하고 지속적으로 개선하기 위해서는 객관적이고 다차원적인 평가 체계가 필수적입니다. 본 포스트에서 살펴본 바와 같이, **SWE-bench**를 통한 엄격한 샌드박스 기반 기능 검증과 **LLM-as-a-Judge**를 통한 정성적 코드 품질 평가를 결합하면 에이전트의 실제 역량을 입체적으로 측정할 수 있습니다. 

향후 MLOps 파이프라인에 이러한 벤치마크 체계를 자동화하여 통합한다면, 새로운 프롬프트 전략이나 모델 가중치를 적용했을 때의 성능 변화를 실시간으로 트래킹하고 더욱 신뢰할 수 있는 코딩 에이전트를 구축할 수 있을 것입니다.