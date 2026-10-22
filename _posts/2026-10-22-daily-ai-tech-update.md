---
layout: post
title: "SWE-bench 기반 에이전트 평가 자동화 파이프라인: LLM-as-a-Judge와 샌드박스 격리 환경을 활용한 프로덕션급 벤치마크 구축 실전 가이드"
date: 2026-10-22 09:00:00 +0900
categories: [AI, Engineering]
tags: [SWE-bench, AgentEvaluation, LLM-as-a-Judge, DockerSandbox, CI/CD]
---

현대 소프트웨어 엔지니어링 생태계에서 LLM 기반 코딩 에이전트는 단순한 코드 자동완성 도구를 넘어 실제 복잡한 코드베이스의 버그를 수정하고 기능 개발을 수행하는 자율 시스템으로 진화하고 있습니다. 그러나 챗봇 형태의 정성적인 평가만으로는 에이전트가 실제 프로덕션 환경의 복잡한 소프트웨어 공학 문제를 해결할 수 있는지 객관적으로 검증하기 어렵습니다. 

실제 GitHub 이슈를 해결하는 능력을 정량적으로 평가하기 위해 등장한 **SWE-bench** 표준은 에이전트 엔지니어링의 핵심 벤치마크로 자리 잡았습니다. 이번 포스트에서는 컨테이너 기반 샌드박스 격리 환경과 LLM-as-a-Judge 평가 메커니즘을 결합하여, 우리 팀만의 커스텀 코딩 에이전트 성능을 자동으로 측정하고 CI/CD 파이프라인에 통합할 수 있는 프로덕션급 에이전트 평가 자동화 파이프라인의 구축 실전 가이드를 공유합니다.

---

### 1. SWE-bench 아키텍처와 에이전트 평가 파이프라인 개요

전통적인 소프트웨어 테스트와 달리, 자율 코딩 에이전트 평가는 대상 모델이 직접 Git 레포지토리를 클론하고, 문제 정의(Issue Description)를 분석한 뒤, 코드를 수정하고 단위 테스트(Unit Test)를 통과시켜야 하는 전 과정을 포함합니다. 이 과정에서 악성 코드 실행이나 시스템 손상을 방지하기 위해 완전한 격리 환경이 필수적입니다.

우리가 구축할 평가 파이프라인은 다음과 같은 4단계 아키텍처로 구성됩니다.
1. **문제 로더(Issue Loader):** SWE-bench 데이터셋 또는 사내 커스텀 벤치마크셋에서 타겟 레포지토리와 이슈, 그리고 패치 전후의 테스트 케이스를 로드합니다.
2. **격리된 샌드박스 실행기(Sandbox Executor):** Docker 컨테이너를 동적으로 생성하여 레포지토리의 특정 커밋 상태를 복원하고, 대상 에이전트(예: LangGraph 기반 코딩 에이전트)에 이슈를 주입합니다.
3. **패치 추출 및 적용(Patch Application):** 에이전트가 수행한 파일 변경 사항을 Git Diff 형식으로 추출하고, 테스트 베드 환경에 적용합니다.
4. **검증 및 LLM-as-a-Judge 분석(Evaluation Engine):** 유닛 테스트 실행 결과(Pass/Fail)와 더불어, LLM-as-a-Judge를 통해 코드의 가독성, 아키텍처 일관성, 잠재적 부작용을 다차원적으로 채점합니다.

---

### 2. 안전한 격리 환경을 위한 Docker 샌드박스 실행기 구현

에이전트가 코드를 직접 빌드하고 실행하는 과정에서 시스템 자원 고갈이나 무한 루프 등의 위험이 존재합니다. Python의 `docker` SDK를 활용하여 네트워크가 차단되거나 자원이 엄격히 제한된 안전한 격리 컨테이너 실행기를 구현해 보겠습니다.

아래는 에이전트의 작업 공간을 컨테이너 내부에 구축하고 코드를 실행하는 핵심 파이썬 스크립트입니다.

```python
import docker
import os
from typing import Dict, Any

class SandboxExecutor:
    def __init__(self, base_image: str = "python:3.11-slim"):
        self.client = docker.from_env()
        self.base_image = base_image

    def run_agent_task(self, repo_path: str, issue_prompt: str) -> Dict[str, Any]:
        """
        격리된 Docker 컨테이너 안에서 에이전트 작업을 수행하고 결과를 반환합니다.
        """
        container = None
        try:
            # 컨테이너 생성: 자원 제한 및 네트워크 격리 적용
            container = self.client.containers.create(
                image=self.base_image,
                command="tail -f /dev/null",  # 대기 상태 유지
                working_dir="/workspace",
                volumes={
                    os.path.abspath(repo_path): {
                        'bind': '/workspace',
                        'mode': 'rw'
                    }
                },
                mem_limit="2g",
                nano_cpus=2000000000,  # 2 CPU cores
                network_disabled=True  # 보안을 위한 외부 네트워크 차단
            )
            container.start()

            # 의존성 설치 및 에이전트 구동 명령어 실행 시뮬레이션
            setup_exec = container.exec_run("pip install -e .")
            if setup_exec.exit_code != 0:
                return {"status": "error", "message": f"Setup failed: {setup_exec.output.decode()}"}

            # 에이전트 이슈 해결 프로세스 구동 (예시 명령어)
            agent_exec = container.exec_run(f"python -m agent.runner --prompt \"{issue_prompt}\"")
            
            # Git diff 추출
            diff_exec = container.exec_run("git diff")
            patch_content = diff_exec.output.decode('utf-8')

            # 테스트 케이스 실행 검증
            test_exec = container.exec_run("pytest")
            test_passed = (test_exec.exit_code == 0)

            return {
                "status": "success",
                "patch": patch_content,
                "test_passed": test_passed,
                "test_output": test_exec.output.decode('utf-8')
            }

        except Exception as e:
            return {"status": "exception", "message": str(e)}
        
        finally:
            if container:
                container.stop()
                container.remove()

# 사용 예시
if __name__ == "__main__":
    executor = SandboxExecutor()
    result = executor.run_agent_task(
        repo_path="./sample_target_repo",
        issue_prompt="Fix the null pointer exception in data parser module when input is empty."
    )
    print(f"Test Passed: {result.get('test_passed')}")
```

---

### 3. LLM-as-a-Judge 기반 다차원 코드 품질 평가 파이프라인

단순히 단위 테스트 통과 여부(Pass/Fail)만으로는 정교한 에이전트의 성능을 변별하기 어렵습니다. 예를 들어, 테스트를 통과했더라도 불필요하게 복잡한 코드를 작성했거나 보안 취약점을 유발했을 수 있습니다. 이를 보완하기 위해 최신 LLM을 심판(Judge)으로 활용하는 평가 로직을 도입합니다.

```python
import json
from openai import OpenAI

class LLMCodeJudge:
    def __init__(self, model_name: str = "gpt-4o"):
        self.client = OpenAI()
        self.model_name = model_name

    def evaluate_patch(self, issue_description: str, original_code: str, generated_patch: str) -> dict:
        """
        생성된 패치에 대해 LLM이 다차원 평가를 수행하고 JSON 형태로 점수를 반환합니다.
        """
        system_prompt = """
        당신은 수석 소프트웨어 아키텍트이자 코드 리뷰어입니다. 
        주어진 이슈 설명과 원본 코드, 그리고 에이전트가 생성한 Git 패치를 분석하여 다음 3가지 지표를 1부터 5까지 평가해주세요:
        1. correctness (정확성): 이슈를 정확하게 해결했는가?
        2. code_quality (코드 품질): 가독성, 모듈화, 언어 관용구를 잘 준수했는가?
        3. safety_efficiency (안전성과 효율성): 잠재적 버그, 보안 취약점, 성능 저하 요인이 없는가?
        
        응답은 반드시 아래의 JSON 형식으로만 출력하세요:
        {
            "correctness": 점수(정수),
            "code_quality": 점수(정수),
            "safety_efficiency": 점수(정수),
            "reasoning": "평가 상세 근거 요약"
        }
        """

        user_content = f"""
        [이슈 설명]
        {issue_description}

        [원본 코드 스니펫]
        {original_code}

        [생성된 패치 (Git Diff)]
        {generated_patch}
        """

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content)

# 사용 예시
if __name__ == "__main__":
    judge = LLMCodeJudge()
    evaluation = judge.evaluate_patch(
        issue_description="Fix null pointer in parser",
        original_code="def parse(data): return data['key']",
        generated_patch="+ def parse(data):\n+     if not data: return None\n+     return data.get('key')"
    )
    print("Judge Evaluation Result:", json.dumps(evaluation, indent=2, ensure_ascii=False))
```

---

### 4. CI/CD 파이프라인 통합 및 대시보드 리포팅

구축한 에이전트 평가 자동화 파이프라인은 GitHub Actions 등의 CI/CD 도구와 결합하여, 에이전트 코드베이스가 업데이트될 때마다 자동으로 회귀 테스트(Regression Test)를 수행해야 합니다. 매 주말마다 SWE-bench Lite 데이터셋의 300개 대표 이슈를 대상으로 에이전트를 구동하고, 통과율(Resolve Rate)과 LLM-as-a-Judge 평균 점수를 사내 대시보드(예: Datadog 또는 Grafana)에 자동으로 메트릭으로 전송하도록 구성합니다.

이를 통해 개발팀은 프롬프트 엔지니어링 변경이나 RAG 검색 알고리즘 개선이 실제 코딩 에이전트의 문제 해결 능력에 미치는 영향을 객관적인 수치로 즉시 확인할 수 있습니다.

---

### 결론

오늘날 AI 엔지니어링의 핵심 경쟁력은 '감에 의존한 프롬프트 수정'이 아니라, '엄격하고 과학적인 평가 체계(Evaluation Framework)'를 갖추는 데 있습니다. 오늘 살펴본 SWE-bench 기반의 샌드박스 격리 에이전트 평가 파이프라인과 LLM-as-a-Judge 체인을 도입함으로써, 개발팀은 자율 코딩 에이전트의 성능 저하를 방지하고 프로덕션 수준의 안정성을 확보할 수 있습니다. 지금 바로 사내 에이전트 개발 파이프라인에 이 벤치마크 시스템을 적용해 보시기 바랍니다.