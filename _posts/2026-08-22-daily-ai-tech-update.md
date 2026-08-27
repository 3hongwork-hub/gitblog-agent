---
layout: post
title: "GraphRAG와 하이브리드 검색: 복잡한 코드베이스를 위한 차세대 RAG 아키텍처"
date: 2026-08-22 09:00:00 +0900
categories: [AI, Architecture]
tags: [RAG, GraphRAG, KnowledgeGraph, VectorSearch, Embedding]
---

2026년 대규모 소프트웨어 프로젝트와 엔터프라이즈 환경에서 기존의 단순 벡터 검색 기반 RAG(Retrieval-Augmented Generation)는 명확한 한계에 부딪혔습니다. 단순 코사인 유사도(Cosine Similarity) 기반 청킹 검색은 여러 파일과 모듈 간의 **의존성 그래프, 상속 관계, 데이터 흐름**과 같은 전역적 구조를 포착하지 못하기 때문입니다.

이러한 문제를 해결하기 위해 등장한 것이 바로 **GraphRAG(지식 그래프 + RAG)**와 **하이브리드 검색(Hybrid Search)** 기법입니다. 이번 글에서는 지식 그래프를 활용해 코드베이스와 문서의 문맥을 완벽하게 파싱하는 차세대 RAG 파이프라인을 다룹니다.

---

## 1. 전통적 벡터 RAG vs GraphRAG 비교

```
[전통적 RAG]:  문서/코드 -> 텍스트 청킹(Chunking) -> 벡터 임베딩 -> 유사도 Top-K 추출 (구조적 연결 상실)
[GraphRAG]:    문서/코드 -> AST/개체 추출 -> 지식 그래프(Nodes & Edges) 구축 -> 커뮤니티 요약 + 하이브리드 검색
```

* **전역 질의(Global Query) 대응**: "이 프로젝트의 전반적인 인증 아키텍처는 어떻게 구성되어 있는가?"와 같이 프로젝트 전체를 아우르는 질문에 대해 기존 벡터 검색은 개별 파일 조각만 가져오지만, GraphRAG는 커뮤니티 계층 요약을 통해 프로젝트 전체 구조를 종합적으로 설명합니다.
* **명시적 관계 추적**: 클래스 간 상속, 함수 호출 체인, API 엔드포인트와 DB 테이블 간의 관계를 그래프 엣지(Edge)로 명확히 인덱싱합니다.

---

## 2. GraphRAG & 하이브리드 검색 아키텍처 파이프라인

```
+-------------------------------------------------------------+
|                 GraphRAG Processing Flow                    |
|                                                             |
|   [Source Code/Docs] ──> [Entity & Relation Extraction]     |
|                                 │                           |
|                                 ▼                           |
|   [Vector Index (BM25 + Dense)] + [Knowledge Graph (Neo4j)] |
|                                 │                           |
|                                 ▼                           |
|   [Hybrid Retriever] ──> [Re-ranking] ──> [LLM Generation]  |
+-------------------------------------------------------------+
```

---

## 3. 실전 Python 예시: NetworkX & LlamaIndex 기반 GraphRAG 구축

```python
import networkx as nx
from typing import List, Dict

class CodeGraphRAG:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.vector_store = {}

    def add_code_entity(self, entity_name: str, entity_type: str, docstring: str):
        # 1. 그래프 노드 추가
        self.graph.add_node(entity_name, type=entity_type, summary=docstring)

    def add_dependency(self, source: str, target: str, relation: str):
        # 2. 의존성 엣지 추가 (예: 'calls', 'inherits', 'imports')
        self.graph.add_edge(source, target, relation=relation)

    def query_context(self, start_entity: str, depth: int = 2) -> Dict:
        """특정 모듈을 중심으로 연결된 모든 의존성 서브그래프 탐색"""
        subgraph_nodes = nx.single_source_shortest_path_length(self.graph, start_entity, cutoff=depth)
        
        context = []
        for node in subgraph_nodes:
            node_data = self.graph.nodes[node]
            neighbors = list(self.graph.neighbors(node))
            context.append({
                "entity": node,
                "type": node_data.get("type"),
                "summary": node_data.get("summary"),
                "dependencies": neighbors
            })
        return {"root": start_entity, "connected_context": context}

if __name__ == "__main__":
    rag = CodeGraphRAG()
    rag.add_code_entity("AuthService", "Class", "JWT 발급 및 세션 검증 서비스")
    rag.add_code_entity("TokenValidator", "Helper", "RS256 서명 검증 유틸리티")
    rag.add_dependency("AuthService", "TokenValidator", "uses")
    
    result = rag.query_context("AuthService")
    print(f"GraphRAG 추출 컨텍스트: {result}")
```

---

## 4. 결론

복잡한 대규모 레포지토리나 기술 문서를 다루는 AI 시스템을 구축할 때는 단순 벡터 검색을 넘어 **지식 그래프와 BM25 키워드 검색을 융합한 GraphRAG 아키텍처**를 채택함으로써 환각을 제거하고 신뢰도 높은 컨텍스트를 제공해야 합니다.