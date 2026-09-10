---
layout: post
title: "GraphRAG와 커스텀 엔티티 추출 파이프라인: 비정형 대규모 문서에서 지식 그래프 실시간 구축하기"
date: 2026-09-10 09:00:00 +0900
categories: [AI, Architecture]
tags: [GraphRAG, KnowledgeGraph, Neo4j, LLM, VectorSearch, Python]
---

대규모 언어 모델(LLM)을 활용한 전통적인 RAG(Retrieval-Augmented Generation) 시스템은 개별 문서 조각(Chunk)의 벡터 유사도 검색에 의존합니다. 이 방식은 키워드 매칭이나 국소적인 의미 포착에는 뛰어납니다. 하지만 "사내 전체 프로젝트 간의 복잡한 의존성 관계"나 "글로벌 공급망 전반에 걸친 리스크 전파"와 같이 방대한 데이터에 산재한 복합적인 관계를 추론해야 하는 전역적(Global) 질의에는 한계가 명확합니다.

단순 청크 단위의 검색을 넘어, 문서 내의 개체(Entity)와 관계(Relationship)를 추출하여 유기적인 네트워크로 연결하는 **GraphRAG(Graph-based Retrieval-Augmented Generation)** 아키텍처가 차세대 엔터프라이즈 AI의 핵심으로 자리 잡고 있습니다. 이번 포스트에서는 LLM과 벡터 데이터베이스, 그리고 그래프 DB(Neo4j)를 결합하여 비정형 문서로부터 지식 그래프(Knowledge Graph)를 자동으로 구축하고, 이를 기반으로 고도화된 하이브리드 검색 파이프라인을 구현하는 실전 엔지니어링 방법을 심층적으로 살펴보겠습니다.

---

### 1. GraphRAG 아키텍처의 핵심 설계 철학

전통적 RAG가 '숲을 보지 못하고 나무만 보는' 구조였다면, GraphRAG는 숲의 전체 생태계와 나무 간의 상관관계를 동시에 조망할 수 있게 해줍니다. 

GraphRAG의 전체 파이프라인은 크게 두 가지 축으로 구성됩니다. 첫째는 **인덱싱(Indexing) 단계**로, 비정형 텍스트를 입력받아 LLM을 통해 개체(사람, 조직, 기술, 이벤트 등)와 이들 간의 관계를 추출한 뒤 그래프 스토어에 적재합니다. 둘째는 **검색 및 생성(Retrieval & Generation) 단계**로, 사용자의 질의 유형에 따라 벡터 유사도 검색과 그래프 순회(Graph Traversal)를 결합하여 문맥을 극대화합니다.

특히 전역적 질문(예: "우리 회사의 지난 3년간 기술 스택 전환이 비즈니스에 미친 종합적인 영향은?")에 대응하기 위해, 그래프 전체의 커뮤니티 구조를 요약하는 *Hierarchical Community Summarization* 기법이 필수적입니다. 데이터가 방대해질수록 토큰 효율성과 응답 정확도를 동시에 잡기 위한 비동기 파이프라인 설계가 요구됩니다.

```
[비정형 문서] 
     │
     ▼
[LLM 기반 개체/관계 추출 파이프라인] 
     │
     ├───────────────┬───────────────┐
     ▼               ▼               ▼
[Neo4j (그래프)]  [Chroma (벡터)]  [커뮤니티 요약 계층]
     └───────────────┼───────────────┘
                     ▼
          [하이브리드 리트리버]
                     │
                     ▼
            [최종 LLM 응답 생성]
```

---

### 2. LLM 기반 엔티티 및 관계 추출 엔진 구현

지식 그래프 구축의 품질은 원본 텍스트에서 얼마나 정확하고 일관성 있게 개체와 관계를 추출해 내느냐에 달려 있습니다. 프롬프트의 모호성을 줄이고 구조화된 출력(Structured Outputs)을 보장하기 위해, Pydantic과 LLM의 JSON 모드(또는 함수 호출)를 결합한 추출 엔진을 구현합니다.

아래는 파이썬 환경에서 비정형 텍스트로부터 노드와 엣지를 정의하고 추출하는 핵심 파이프라인 코드입니다.

```python
import os
from typing import List, Optional
from pydantic import BaseModel, Field
from openai import OpenAI

# OpenAI 클라이언트 초기화 (2026년 기준 최신 표준 준수)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class Entity(BaseModel):
    name: str = Field(description="추출된 개체의 고유 이름")
    category: str = Field(description="개체의 유형 (예: 기술, 조직, 인물, 프로젝트)")
    description: str = Field(description="해당 문맥에서 개체의 역할 및 설명")

class Relationship(BaseModel):
    source: str = Field(description="출발 개체 이름")
    target: str = Field(description="도착 개체 이름")
    relation: str = Field(description="두 개체 간의 관계를 나타내는 동사구 (예: '사용한다', '소속이다', '의존한다')")
    strength: float = Field(default=1.0, description="관계의 강도 또는 신뢰도 점수 (0.0 ~ 1.0)")

class KnowledgeGraphExtraction(BaseModel):
    entities: List[Entity] = Field(description="추출된 모든 개체 리스트")
    relationships: List[Relationship] = Field(description="추출된 모든 관계 리스트")

def extract_knowledge_from_chunk(text_chunk: str) -> Optional[KnowledgeGraphExtraction]:
    """
    단일 텍스트 청크로부터 구조화된 지식 그래프 요소를 추출합니다.
    """
    prompt = f"""
    당신은 전문 지식 그래프 엔지니어입니다. 다음 텍스트를 분석하여 
    핵심 개체(Entity)와 개체 간의 관계(Relationship)를 추출하십시오.
    
    분석할 텍스트:
    {text_chunk}
    """
    
    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 정확한 지식 그래프 구조화를 수행하는 전문 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            response_format=KnowledgeGraphExtraction,
        )
        return completion.choices.message.parsed
    except Exception as e:
        print(f"추출 중 오류 발생: {e}")
        return None

# 테스트 실행 예시
sample_text = "Alice는 TechCorp의 AI 엔지니어로 근무하며, 내부 프로젝트인 Project-X에서 PyTorch와 Neo4j를 활용해 GraphRAG 시스템을 구축하고 있습니다."
result = extract_knowledge_from_chunk(sample_text)
if result:
    print(f"추출된 개체 수: {len(result.entities)}")
    print(f"추출된 관계 수: {len(result.relationships)}")
```

---

### 3. Neo4j 그래프 데이터베이스 연동 및 하이브리드 검색 아키텍처

추출된 개체와 관계는 관계형 데이터베이스보다는 그래프 데이터베이스인 Neo4j에 적재하는 것이 효율적입니다. 노드(Node)는 개체를 의미하고, 엣지(Edge)는 관계를 의미합니다. 여기에 각 노드 및 텍스트 청크의 벡터 임베딩을 결합하면, Cypher 쿼리와 벡터 유사도 검색을 동시에 수행하는 하이브리드 리트리버를 완성할 수 있습니다.

다음은 Neo4j 드라이버를 사용하여 추출된 지식 요소를 그래프로 적재하고, 하이브리드 검색을 수행하는 구조입니다.

```python
from neo4j import GraphDatabase

class Neo4jGraphManager:
    def __init__(self, uri: str, auth: tuple):
        self.driver = GraphDatabase.driver(uri, auth=auth)

    def close(self):
        self.driver.close()

    def save_knowledge_graph(self, kg_data: KnowledgeGraphExtraction):
        """
        추출된 개체와 관계를 Neo4j 그래프 DB에 Upsert 방식으로 저장합니다.
        """
        with self.driver.session() as session:
            for entity in kg_data.entities:
                session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    ON CREATE SET e.category = $category, e.description = $description
                    ON MATCH SET e.description = $description
                    """,
                    name=entity.name, category=entity.category, description=entity.description
                )
            
            for rel in kg_data.relationships:
                session.run(
                    """
                    MATCH (s:Entity {name: $source})
                    MATCH (t:Entity {name: $target})
                    MERge (s)-[r:RELATED_TO {type: $relation}]->(t)
                    SET r.strength = $strength
                    """,
                    source=rel.source, target=rel.target, relation=rel.relation, strength=rel.strength
                )

    def hybrid_graph_vector_search(self, query_entity: str, max_depth: int = 2) -> list:
        """
        특정 개체를 중심으로 한 그래프 순회(Graph Traversal)와 연관 노드 검색을 수행합니다.
        """
        query = f"""
        MATCH (start:Entity {{name: $query_entity}})
        CALL apoc.path.subgraphNodes(start, {{maxLevel: $max_depth}})
        YIELD node
        RETURN node.name AS name, node.category AS category, node.description AS description
        """
        with self.driver.session() as session:
            # APOC 플러그인이 없는 환경을 위한 기본 경로 탐색 Cypher 폴백
            fallback_query = """
            MATCH path = (start:Entity {name: $query_entity})-[r*1..2]-(connected:Entity)
            RETURN DISTINCT connected.name AS name, connected.category AS category, connected.description AS description
            LIMIT 20
            """
            result = session.run(fallback_query, query_entity=query_entity)
            return [record.data() for record in result]

# 사용 예시 (환경 변수 또는 직접 연결 정보 입력)
# db_manager = Neo4jGraphManager("bolt://localhost:7687", ("neo4j", "password"))
# db_manager.save_knowledge_graph(result)
```

이와 같은 구조를 통해 시스템은 단순 유사 문장 매칭을 넘어, "A 기술을 사용하는 팀이 연계된 다른 프로젝트는 무엇인가?"와 같은 다단계 관계 추론(Multi-hop Reasoning) 질의에 정확하게 대응할 수 있습니다.

---

### 결론

전통적 RAG의 구조적 한계를 뛰어넘는 **GraphRAG**는 복잡한 맥락과 거대한 문서 집합을 다루는 엔터프라이즈 AI 시스템의 필수 불가결한 아키텍처로 진화하고 있습니다. LLM의 뛰어난 구조화 추출 능력과 Neo4j 같은 그래프 데이터베이스의 강력한 관계형 순회 성능을 결합함으로써, 기업은 자사 내부에 산재한 지식을 완벽하게 구조화하고 활용할 수 있습니다.

오늘 살펴본 개체 추출 파이프라인과 하이브리드 검색 아키텍처를 바탕으로, 여러분의 AI 서비스에 깊이 있는 추론 능력을 더해 보시길 바랍니다.