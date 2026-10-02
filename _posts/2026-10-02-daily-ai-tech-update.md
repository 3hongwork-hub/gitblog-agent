---
layout: post
title: "GraphRAG와 커뮤니티 요약 계층화: 대규모 비정형 지식 그래프 기반 지능형 검색 및 엔터프라이즈 RAG 아키텍처 실전 구축"
date: 2026-10-02 09:00:00 +0900
categories: [AI, Architecture]
tags: [GraphRAG, KnowledgeGraph, RAG, NetworkX, LLM, VectorSearch]
---

현대 엔터프라이즈 환경에서 지식 기반 시스템(RAG)은 단순한 문서 검색을 넘어, 조직 내 산재한 수많은 비정형 문서 간의 복잡한 맥락과 관계(Relationship)를 이해해야 하는 과제에 직면해 있습니다. 전통적인 청크 기반 벡터 검색(Vector Search)은 키워드나 의미론적 유사도(Semantic Similarity) 측면에서는 뛰어난 성능을 보이지만, "전체 문서 집합을 관통하는 거시적인 트렌드나 특정 엔티티 간의 다중 홉(Multi-hop) 관계"를 질의하는 전역적(Global) 질문에는 구조적인 한계를 드러냅니다.

오늘 포스트에서는 이러한 전통적 RAG의 한계를 극복하기 위해 등장한 **GraphRAG** 아키텍처의 핵심 개념을 파악하고, 텍스트 코퍼스에서 지식 그래프(Knowledge Graph)를 추출하여 커뮤니티 기반 계층적 요약(Community Summarization) 구조를 구축하는 프로덕션급 파이프라인을 실전 코드를 통해 상세히 살펴보겠습니다.

---

### 1. GraphRAG 아키텍처의 핵심 철학: 전역 검색(Global Search)과 커뮤니티 검출

기본적인 RAG 파이프라인은 질문과 가장 유사한 몇 개의 텍스트 청크를 검색하여 LLM에 주입하는 국소적(Local) 검색 방식을 취합니다. 하지만 사용자가 "올해 우리 회사의 주요 프로젝트 전반에 걸친 기술적 병목 현상의 공통 원인은 무엇인가?"와 같은 질문을 던진다면, 개별 청크 단위의 검색으로는 파편화된 정보만 모이게 되어 전체적인 맥락을 조망하기 어렵습니다.

GraphRAG는 이 문제를 해결하기 위해 문서들로부터 **엔티티(Entity, 개체)**와 **관계(Relationship)**를 추출하여 지식 그래프를 구성합니다. 그 후, 그래프 이론의 **커뮤니티 검출 알고리즘(예: Leiden Algorithm)**을 적용하여 서로 긴밀하게 연결된 엔티티 군집(Community)을 찾아냅니다. 

핵심 아이디어는 다음과 같습니다:
1. **계층적 커뮤니티 구조화**: 미세한 서브그래프부터 거시적인 클러스터까지 계층적으로 커뮤니티를 형성합니다.
2. **커뮤니티 요약(Community Summarization)**: LLM을 활용해 각 커뮤니티에 속한 엔티티와 관계 정보를 바탕으로 심층적인 요약 보고서를 미리 생성합니다.
3. **전역 맵-리듀스 검색(Global Map-Reduce Search)**: 사용자의 거시적 질문이 들어오면, 개별 청크가 아닌 각 커뮤니티 요약본들을 대상으로 맵-리듀스 방식으로 답변을 종합하여 환각(Hallucination)을 최소화하고 전체 맥락을 포착합니다.

---

### 2. Python과 NetworkX 기반 지식 그래프 추출 및 커뮤니티 계층화 파이프라인

이제 실제로 비정형 텍스트로부터 엔티티와 관계를 추출하고, 이를 바탕으로 네트워크 그래프를 구축한 뒤 커뮤니티를 요약하는 엔터프라이즈급 파이프라인 코드를 구현해 보겠습니다. 이 예제에서는 경량화를 위해 표준 Python 라이브러리와 NetworkX, 그리고 LLM 클라이언트 인터페이스를 활용합니다.

```python
import os
import json
from typing import List, Dict, Any
import networkx as nx
from openai import OpenAI

# OpenAI 클라이언트 초기화 (실제 프로덕션에서는 환경 변수 설정 필수)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"))

class GraphRAGBuilder:
    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        self.graph = nx.Graph()

    def extract_entities_and_relations(self, text_chunk: str) -> Dict[str, Any]:
        """
        텍스트 청크에서 주요 엔티티와 그들 간의 관계를 구조화된 JSON으로 추출합니다.
        """
        prompt = f"""
        다음 텍스트를 분석하여 핵심 엔티티(인물, 기술, 조직, 개념 등)와 
        엔티티 간의 관계를 추출하십시오. 
        반드시 아래의 JSON 형식으로만 응답하세요.
        {{
            "entities": [
                {{"name": "엔티티이름", "type": "유형(예: Technology, Organization)"}}
            ],
            "relations": [
                {{"source": "엔티티A", "target": "엔티티B", "description": "관계 설명"}}
            ]
        }}
        
        텍스트:
        {text_chunk}
        """
        
        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"추출 중 오류 발생: {e}")
            return {"entities": [], "relations": []}

    def build_knowledge_graph(self, chunks: List[str]):
        """
        여러 텍스트 청크를 순회하며 NetworkX 지식 그래프를 구축합니다.
        """
        for idx, chunk in enumerate(chunks):
            print(f"[{idx+1}/{len(chunks)}] 청크 처리 및 지식 그래프 통합 중...")
            extracted_data = self.extract_entities_and_relations(chunk)
            
            # 엔티티 노드 추가
            for entity in extracted_data.get("entities", []):
                self.graph.add_node(
                    entity["name"], 
                    entity_type=entity["type"], 
                    source_chunk=idx
                )
            
            # 관계 엣지 추가
            for rel in extracted_data.get("relations", []):
                source = rel.get("source")
                target = rel.get("target")
                desc = rel.get("description")
                if source and target:
                    if self.graph.has_edge(source, target):
                        # 기존 관계가 있다면 설명 보강
                        self.graph[source][target]["description"] += f"; {desc}"
                    else:
                        self.graph.add_edge(source, target, description=desc)

        print(f"지식 그래프 구축 완료: 노드 {self.graph.number_of_nodes}개, 엣지 {self.graph.number_of_edges}개")

    def detect_communities_and_summarize(self) -> List[Dict[str, Any]]:
        """
        네트워크 커뮤니티를 감지하고 각 커뮤니티별 요약 보고서를 생성합니다.
        """
        # Louvain 알고리즘을 통한 커뮤니티 검출 (networkx.algorithms.community 활용)
        from networkx.algorithms.community import louvain_communities
        
        communities = louvain_communities(self.graph, seed=42)
        community_summaries = []

        for comm_id, comm_nodes in enumerate(communities):
            subgraph = self.graph.subgraph(comm_nodes)
            
            # 커뮤니티 내 노드 및 엣지 정보 수집
            nodes_info = [
                f"- {node} ({data.get('entity_type', 'Unknown')})" 
                for node, data in subgraph.nodes(data=True)
            ]
            edges_info = [
                f"- {u} -> {v}: {data.get('description', '')}" 
                for u, v, data in subgraph.edges(data=True)
            ]
            
            community_text = "Entities:\n" + "\n".join(nodes_info) + "\n\nRelations:\n" + "\n".join(edges_info)
            
            # LLM을 통한 커뮤니티 심층 요약 생성
            summary_prompt = f"""
            다음은 지식 그래프 내의 특정 커뮤니티에 속한 엔티티와 관계 클러스터입니다.
            이 커뮤니티가 다루고 있는 핵심 주제, 주요 인사이트, 그리고 전체 시스템에서의 역할을 
            종합적으로 요약해 주세요.
            
            {community_text}
            """
            
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": summary_prompt}]
            )
            summary_text = response.choices[0].message.content
            
            community_summaries.append({
                "community_id": comm_id,
                "nodes": list(comm_nodes),
                "summary": summary_text
            })
            
        return community_summaries
```

---

### 3. 전역 맵-리듀스(Global Map-Reduce) 검색 엔진 구현

지식 그래프와 커뮤니티 요약 계층이 완성되었다면, 이제 사용자의 거시적인 질문에 대응하는 전역 검색 엔진을 구현할 차례입니다. 맵 단계에서는 각 커뮤니티 요약본이 사용자 질문에 대해 어떤 관련이 있는지 점수와 부분 답변을 도출하고, 리듀스 단계에서 이를 최종 답변으로 통합합니다.

```python
class GlobalSearchEngine:
    def __init__(self, community_summaries: List[Dict[str, Any]], model_name: str = "gpt-4o"):
        self.summaries = community_summaries
        self.model_name = model_name

    def global_search(self, query: str) -> str:
        """
        Map-Reduce 방식을 활용한 전역 검색 수행
        """
        print(f"'{query}'에 대한 전역 검색(Map-Reduce) 실행 중...")
        map_results = []

        # Map 단계: 개별 커뮤니티 요약별로 질문에 대한 관련 답변 및 점수 추출
        for comm in self.summaries:
            map_prompt = f"""
            사용자 질문: "{query}"
            
            다음은 지식 그래프의 커뮤니티 #{comm['community_id']} 요약입니다:
            {comm['summary']}
            
            위 커뮤니티 요약이 사용자 질문에 답변하는 데 기여하는 바를 분석하고, 
            관련된 정보와 중요도 점수(0~100)를 포함하여 간결하게 리포트해 주세요.
            만약 전혀 관련이 없다면 점수를 0점으로 매기세요.
            """
            
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": map_prompt}],
                temperature=0.0
            )
            map_results.append(response.choices[0].message.content)

        # Reduce 단계: 모든 커뮤니티별 분석 결과를 종합하여 최종 답변 생성
        combined_context = "\n\n---\n\n".join(map_results)
        
        reduce_prompt = f"""
        사용자 질문: "{query}"
        
        다음은 각 지식 그래프 커뮤니티별 분석 리포트 모음입니다:
        {combined_context}
        
        위의 리포트들을 종합하여, 사용자 질문에 명확하고 통찰력 있는 최종 종합 답변을 작성해 주십시오.
        출처나 개별 커뮤니티 번호는 자연스럽게 녹여내고, 구조화된 형태로 답변을 구성하세요.
        """
        
        final_response = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": reduce_prompt}]
        )
        
        return final_response.choices[0].message.content

# --- 실행 예시 시뮬레이션 ---
if __name__ == "__main__":
    # 테스트용 샘플 비정형 텍스트 코퍼스
    sample_corpus = [
        "Project Alpha는 내부 클라우드 인프라를 Kubernetes 기반으로 마이그레이션하는 프로젝트입니다. 팀 리더인 킴(Kim)이 주도하고 있습니다.",
        "Project Beta는 AI 기반 고객 응대 챗봇 개발 프로젝트입니다. 박(Park) 엔지니어가 참여하고 있으며, LLM 추론 가속화를 위해 vLLM을 도입했습니다.",
        "Kubernetes 인프라와 LLM 추론 서버 간의 네트워크 레이턴시 병목 현상이 Project Alpha와 Project Beta 모두에서 공통으로 발견되었습니다."
    ]
    
    # 1. 그래프 구축기 초기화 및 실행
    rag_builder = GraphRAGBuilder()
    rag_builder.build_knowledge_graph(sample_corpus)
    
    # 2. 커뮤니티 검출 및 요약
    summaries = rag_builder.detect_communities_and_summarize()
    
    # 3. 전역 검색 엔진 가동
    search_engine = GlobalSearchEngine(summaries)
    answer = search_engine.global_search("우리 회사의 주요 프로젝트들에서 공통적으로 나타나는 기술적 과제는 무엇인가요?")
    
    print("\n[최종 GraphRAG 응답 결과]")
    print(answer)
```

---

### 4. 프로덕션 환경 도입 시 고려해야 할 아키텍처 베스트 프 연습

GraphRAG 시스템을 실제 엔터프라이즈 프로덕션 환경에 배포할 때 반드시 검토해야 할 실무 최적화 포인트는 다음과 같습니다.

1. **그래프 DB 및 벡터 DB의 하이브리드 인덱싱**:
   대규모 코퍼스의 경우, 메인 지식 그래프는 Neo4j나 Amazon Neptune 같은 그래프 데이터베이스에 영구 저장하고, 청크 및 커뮤니티 요약은 Pinecone이나 Milvus 같은 벡터 DB와 연동하여 하이브리드 검색(Hybrid Vector + Graph Traversal)을 구성하는 것이 확장성 측면에서 유리합니다.
2. **증분 업데이트(Incremental Update) 파이프라인**:
   새로운 문서가 추가될 때마다 전체 그래프를 처음부터 다시 빌드하는 것은 비용과 시간 낭비입니다. 새로운 청크에서 추출된 엔티티가 기존 그래프에 존재하는지 퍼지 매칭(Fuzzy Matching)을 통해 병합하고, 영향받는 커뮤니티만 재요약하는 증분 업데이트 로직을 반드시 설계해야 합니다.
3. **LLM API 비용 및 토큰 최적화**:
   초기 지식 그래프 추출 및 커뮤니티 요약 단계는 많은 토큰을 소모합니다. 따라서 초기 빌드 시에는 비용 효율적인 고성능 소형 모델(예: GPT-4o-mini 또는 Claude 3.5 Haiku)을 활용하고, 최종 전역 합성 단계에서만 최상위 플래그십 모델을 사용하는 티어드(Tiered) LLM 전략을 적용하는 것이 경제적입니다.

---

### 결론

오늘 포스트에서는 전통적 RAG의 전역적 정보 탐색 한계를 극복하는 **GraphRAG** 아키텍처의 이론적 배경과 이를 파이썬 코드로 구현하는 실전 파이프라인을 다루어 보았습니다. 텍스트 청크를 넘어 엔티티와 관계를 연결하고, 커뮤니티 계층 요약을 통해 거시적 맥락까지 포착하는 지식 그래프 기반 RAG 시스템은 복잡한 엔터프라이즈 지식 관리 시스템의 필수적인 표준으로 자리 잡고 있습니다. 

이번에 구축한 파이프라인을 바탕으로 사내 문서 코퍼스에 적용해 보며, 여러분만의 지능형 엔터프라이즈 AI 검색 인프라를 한 단계 업그레이드해 보시길 바랍니다.