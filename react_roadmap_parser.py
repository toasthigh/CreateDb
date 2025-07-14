import json
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
import uuid
import logging
import webbrowser
from datetime import datetime

# AI 검증 로깅 시스템 import
from db_validation_logger import (
    DatabaseValidationLogger, ValidationLog, ChangeLog,
    ValidationStatus, ChangeType
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('react_roadmap_parser.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class RoadmapNode:
    """로드맵 노드 데이터 클래스"""
    id: str
    title: str
    content: str
    depth: int
    parent_id: Optional[str]
    node_type: str  # 'root', 'branch', 'sub_branch', 'detail', 'resource', 'book'
    category: str   # 'beginner', 'intermediate', 'advanced', 'community'
    links: List[Dict[str, str]]  # [{'url': '', 'title': '', 'type': 'video|doc|book'}]
    order: int      # 같은 depth에서의 순서
    tags: List[str] # 검색을 위한 태그들

class ReactRoadmapParser:
    """React 로드맵 HTML 파서"""
    
    def __init__(self, html_content: str, validation_logger: Optional[DatabaseValidationLogger] = None):
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.nodes: List[RoadmapNode] = []
        self.current_order = 0
        self.validation_logger = validation_logger
        
    def parse(self) -> List[RoadmapNode]:
        """HTML을 파싱하여 로드맵 노드 리스트 반환"""
        start_time = datetime.now()
        
        # 루트 노드 생성
        root_node = self._create_root_node()
        self.nodes.append(root_node)
        
        # 메인 브랜치들 파싱
        main_branches = self.soup.find('div', class_='main-branches')
        if main_branches:
            branches = main_branches.find_all('div', class_='branch')
            for branch in branches:
                self._parse_branch(branch, root_node.id)
        
        # 파싱 완료 후 로그 저장
        if self.validation_logger:
            self._log_initial_parsing(len(self.nodes), start_time)
        
        return self.nodes
    
    def _log_initial_parsing(self, total_nodes: int, start_time: datetime):
        """초기 파싱 로그 저장"""
        processing_time = (datetime.now() - start_time).total_seconds()
        
        validation_log = ValidationLog(
            id=None,
            timestamp=datetime.now(),
            operation_type="initial_parsing",
            status=ValidationStatus.SUCCESS,
            total_nodes=total_nodes,
            validated_nodes=total_nodes,
            failed_nodes=0,
            error_messages=[],
            metadata={
                'source': 'react_roadmap.html',
                'parser_version': '1.0',
                'node_types': self._get_node_type_distribution()
            },
            ai_model="manual_parsing",
            processing_time=processing_time
        )
        
        self.validation_logger.log_validation(validation_log)
        logger.info(f"Initial parsing completed: {total_nodes} nodes parsed in {processing_time:.2f}s")
    
    def _get_node_type_distribution(self) -> Dict[str, int]:
        """노드 타입별 분포 계산"""
        distribution = {}
        for node in self.nodes:
            node_type = node.node_type
            distribution[node_type] = distribution.get(node_type, 0) + 1
        return distribution
    
    def _create_root_node(self) -> RoadmapNode:
        """루트 노드 생성"""
        title = self.soup.find('h1', class_='mindmap-title')
        return RoadmapNode(
            id=str(uuid.uuid4()),
            title=title.get_text().strip() if title else "React 학습 로드맵",
            content="React 학습을 위한 체계적인 로드맵",
            depth=0,
            parent_id=None,
            node_type='root',
            category='general',
            links=[],
            order=0,
            tags=['react', 'roadmap', 'learning', 'frontend']
        )
    
    def _parse_branch(self, branch_elem, parent_id: str) -> None:
        """브랜치 요소 파싱"""
        level_node = branch_elem.find('div', class_='level-node')
        if not level_node:
            return
        
        # 카테고리 결정
        category = self._get_category_from_classes(level_node.get('class', []))
        
        # 브랜치 제목 추출
        title_text = level_node.get_text().strip()
        title = re.sub(r'\s*▶\s*$', '', title_text)  # 화살표 제거
        
        self.current_order += 1
        branch_node = RoadmapNode(
            id=str(uuid.uuid4()),
            title=title,
            content=f"{category} 단계의 React 학습 내용",
            depth=1,
            parent_id=parent_id,
            node_type='branch',
            category=category,
            links=[],
            order=self.current_order,
            tags=[category, 'react', 'learning']
        )
        self.nodes.append(branch_node)
        
        # 서브 브랜치들 파싱
        sub_branches = branch_elem.find('div', class_='sub-branches')
        if sub_branches:
            self._parse_sub_branches(sub_branches, branch_node.id, category)
    
    def _parse_sub_branches(self, sub_branches_elem, parent_id: str, category: str) -> None:
        """서브 브랜치들 파싱"""
        sub_nodes = sub_branches_elem.find_all('div', class_='sub-node', recursive=False)
        
        for sub_node in sub_nodes:
            title_text = sub_node.get_text().strip()
            title = re.sub(r'\s*▶\s*$', '', title_text)
            
            self.current_order += 1
            sub_branch_node = RoadmapNode(
                id=str(uuid.uuid4()),
                title=title,
                content=f"{category} 단계의 {title} 관련 내용",
                depth=2,
                parent_id=parent_id,
                node_type='sub_branch',
                category=category,
                links=[],
                order=self.current_order,
                tags=[category, 'react'] + self._extract_tags_from_title(title)
            )
            self.nodes.append(sub_branch_node)
            
            # 상세 내용 파싱
            next_sibling = sub_node.find_next_sibling('div', class_='sub-branches')
            if next_sibling:
                self._parse_details(next_sibling, sub_branch_node.id, category)
    
    def _parse_details(self, details_elem, parent_id: str, category: str) -> None:
        """상세 내용 파싱"""
        detail_nodes = details_elem.find_all(['div'])
        
        for detail_node in detail_nodes:
            classes = detail_node.get('class', [])
            
            if 'detail-node' in classes:
                self._parse_detail_node(detail_node, parent_id, category)
            elif 'resource-node' in classes:
                self._parse_resource_node(detail_node, parent_id, category)
            elif 'book-node' in classes:
                self._parse_book_node(detail_node, parent_id, category)
    
    def _parse_detail_node(self, detail_node, parent_id: str, category: str) -> None:
        """상세 노드 파싱"""
        content = detail_node.get_text().strip()
        if not content:
            return
        
        # 제목 추출 (첫 번째 ':' 또는 첫 번째 문장)
        title_match = re.match(r'^([^:]+):', content)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = content[:50] + "..." if len(content) > 50 else content
        
        self.current_order += 1
        detail_node_obj = RoadmapNode(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            depth=3,
            parent_id=parent_id,
            node_type='detail',
            category=category,
            links=[],
            order=self.current_order,
            tags=[category, 'react'] + self._extract_tags_from_content(content)
        )
        self.nodes.append(detail_node_obj)
    
    def _parse_resource_node(self, resource_node, parent_id: str, category: str) -> None:
        """리소스 노드 파싱"""
        links = self._extract_links_from_node(resource_node)
        content = resource_node.get_text().strip()
        
        # 리소스 타입 결정
        resource_type = self._determine_resource_type(content)
        
        title = self._extract_title_from_resource(content)
        
        self.current_order += 1
        resource_node_obj = RoadmapNode(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            depth=3,
            parent_id=parent_id,
            node_type='resource',
            category=category,
            links=links,
            order=self.current_order,
            tags=[category, 'react', 'resource', resource_type]
        )
        self.nodes.append(resource_node_obj)
    
    def _parse_book_node(self, book_node, parent_id: str, category: str) -> None:
        """책 노드 파싱"""
        links = self._extract_links_from_node(book_node)
        content = book_node.get_text().strip()
        
        title = self._extract_title_from_book(content)
        
        self.current_order += 1
        book_node_obj = RoadmapNode(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            depth=3,
            parent_id=parent_id,
            node_type='book',
            category=category,
            links=links,
            order=self.current_order,
            tags=[category, 'react', 'book', 'reference']
        )
        self.nodes.append(book_node_obj)
    
    def _extract_links_from_node(self, node) -> List[Dict[str, str]]:
        """노드에서 링크 추출"""
        links = []
        for link in node.find_all('a', href=True):
            link_type = self._determine_link_type(link['href'])
            links.append({
                'url': link['href'],
                'title': link.get_text().strip(),
                'type': link_type
            })
        return links
    
    def _determine_link_type(self, url: str) -> str:
        """URL에서 링크 타입 결정"""
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'video'
        elif 'github.com' in url:
            return 'github'
        elif any(domain in url for domain in ['docs.', 'developer.mozilla.org', '.org/']):
            return 'documentation'
        elif 'book' in url or 'pdf' in url:
            return 'book'
        else:
            return 'website'
    
    def _determine_resource_type(self, content: str) -> str:
        """리소스 타입 결정"""
        if content.startswith('🎥'):
            return 'video'
        elif content.startswith('📖') or content.startswith('📄'):
            return 'documentation'
        elif content.startswith('🔗'):
            return 'link'
        else:
            return 'general'
    
    def _extract_title_from_resource(self, content: str) -> str:
        """리소스에서 제목 추출"""
        # 이모지 제거하고 첫 번째 ':' 앞까지 또는 링크 텍스트 추출
        cleaned = re.sub(r'^[🎥📖📄🔗]\s*', '', content)
        if ':' in cleaned:
            return cleaned.split(':')[0].strip()
        return cleaned[:50] + "..." if len(cleaned) > 50 else cleaned
    
    def _extract_title_from_book(self, content: str) -> str:
        """책에서 제목 추출"""
        # "추천 책:" 이후 부분 추출
        match = re.search(r'추천 책:\s*(.+)', content)
        if match:
            return match.group(1).strip()
        return content[:50] + "..." if len(content) > 50 else content
    
    def _get_category_from_classes(self, classes: List[str]) -> str:
        """CSS 클래스에서 카테고리 추출"""
        for cls in classes:
            if cls in ['beginner', 'intermediate', 'advanced', 'community']:
                return cls
        return 'general'
    
    def _extract_tags_from_title(self, title: str) -> List[str]:
        """제목에서 태그 추출"""
        tags = []
        keywords = ['hooks', 'router', 'redux', 'typescript', 'testing', 'nextjs', 'jsx', 'props', 'state']
        title_lower = title.lower()
        
        for keyword in keywords:
            if keyword in title_lower:
                tags.append(keyword)
        
        return tags
    
    def _extract_tags_from_content(self, content: str) -> List[str]:
        """내용에서 태그 추출"""
        tags = []
        keywords = ['hooks', 'router', 'redux', 'typescript', 'testing', 'nextjs', 'jsx', 'props', 'state', 'useeffect', 'usestate', 'component']
        content_lower = content.lower()
        
        for keyword in keywords:
            if keyword in content_lower:
                tags.append(keyword)
        
        return tags

class QdrantRoadmapStore:
    """Qdrant를 사용한 로드맵 데이터 저장소"""
    
    def __init__(self, host: str = "localhost", port: int = 6333, collection_name: str = "reactmap_nodes", 
                 validation_logger: Optional[DatabaseValidationLogger] = None,
                 url: str = "https://716df701-f4b5-4b66-ac26-c54a0b880e19.eu-central-1-0.aws.cloud.qdrant.io:6333", 
                 api_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.oX318Jngsvd3u-bL5f-L5T8wQWnBhehPqBDS-ToR7wE"):
        if url and api_key:
            self.client = QdrantClient(url=url, api_key=api_key)
        else:
            self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        
        # SentenceTransformer 로딩 시도
        try:
            self.encoder = SentenceTransformer('all-MiniLM-L6-v2')  # 경량화된 모델
            self.encoder_available = True
        except Exception as e:
            logger.warning(f"SentenceTransformer 로딩 실패: {e}")
            self.encoder = None
            self.encoder_available = False
            
        self.validation_logger = validation_logger
        
    def initialize_collection(self, force_recreate: bool = False):
        """컬렉션 초기화"""
        if force_recreate:
            try:
                self.client.delete_collection(self.collection_name)
                logger.info(f"Deleted existing collection: {self.collection_name}")
            except Exception as e:
                logger.info(f"Collection {self.collection_name} doesn't exist or couldn't be deleted: {e}")
        
        # 컬렉션 존재 확인
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE)  # all-MiniLM-L6-v2의 벡터 사이즈
            )
            logger.info(f"Created collection: {self.collection_name}")
            
            # 검색에 필요한 인덱스 생성
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="category",
                    field_schema="keyword"
                )
                logger.info("Created index for 'category' field")
            except Exception as e:
                logger.warning(f"Failed to create index for 'category': {e}")
                
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="parent_id",
                    field_schema="keyword"
                )
                logger.info("Created index for 'parent_id' field")
            except Exception as e:
                logger.warning(f"Failed to create index for 'parent_id': {e}")
                
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="node_type",
                    field_schema="keyword"
                )
                logger.info("Created index for 'node_type' field")
            except Exception as e:
                logger.warning(f"Failed to create index for 'node_type': {e}")
        else:
            logger.info(f"Collection {self.collection_name} already exists")
    
    def get_collection_info(self) -> Optional[Dict[str, Any]]:
        """Collection 정보 조회"""
        try:
            collections = self.client.get_collections()
            collection_exists = any(col.name == self.collection_name for col in collections.collections)
            
            if not collection_exists:
                return None
            
            # Collection 정보 조회
            collection_info = self.client.get_collection(self.collection_name)
            
            return {
                'name': self.collection_name,
                'points_count': collection_info.points_count,
                'vectors_count': collection_info.vectors_count,
                'status': collection_info.status,
                'config': {
                    'vector_size': collection_info.config.params.vectors.size,
                    'distance': collection_info.config.params.vectors.distance
                }
            }
            
        except Exception as e:
            logger.error(f"Collection 정보 조회 중 오류: {str(e)}")
            return None
    
    def store_nodes(self, nodes: List[RoadmapNode]):
        """노드들을 Qdrant에 저장"""
        if not self.encoder_available:
            logger.warning("SentenceTransformer가 사용 불가능하여 벡터 저장을 건너뜁니다.")
            return
            
        start_time = datetime.now()
        points = []
        
        for node in nodes:
            # 임베딩을 위한 텍스트 생성
            embedding_text = self._create_embedding_text(node)
            
            # 벡터 생성
            vector = self.encoder.encode(embedding_text).tolist()
            
            # 페이로드 생성
            payload = {
                'id': node.id,
                'title': node.title,
                'content': node.content,
                'depth': node.depth,
                'parent_id': node.parent_id,
                'node_type': node.node_type,
                'category': node.category,
                'links': node.links,
                'order': node.order,
                'tags': node.tags,
                'embedding_text': embedding_text
            }
            
            points.append(PointStruct(
                id=node.id,
                vector=vector,
                payload=payload
            ))
        
        # 배치로 저장
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"Stored {len(points)} nodes in Qdrant in {processing_time:.2f}s")
        
        # 저장 로그 기록
        if self.validation_logger:
            self._log_node_storage(len(points), processing_time)
    
    def _log_node_storage(self, total_nodes: int, processing_time: float):
        """노드 저장 로그 기록"""
        validation_log = ValidationLog(
            id=None,
            timestamp=datetime.now(),
            operation_type="node_storage",
            status=ValidationStatus.SUCCESS,
            total_nodes=total_nodes,
            validated_nodes=total_nodes,
            failed_nodes=0,
            error_messages=[],
            metadata={
                'collection_name': self.collection_name,
                'vector_size': 384,
                'embedding_model': 'all-MiniLM-L6-v2'
            },
            ai_model="sentence_transformer",
            processing_time=processing_time
        )
        
        self.validation_logger.log_validation(validation_log)
    
    def _create_embedding_text(self, node: RoadmapNode) -> str:
        """노드를 임베딩을 위한 텍스트로 변환"""
        parts = [
            f"Title: {node.title}",
            f"Content: {node.content}",
            f"Category: {node.category}",
            f"Type: {node.node_type}",
            f"Tags: {', '.join(node.tags)}"
        ]
        
        # 링크 정보 추가
        if node.links:
            link_titles = [link['title'] for link in node.links]
            parts.append(f"Resources: {', '.join(link_titles)}")
        
        return " | ".join(parts)
    
    def search_nodes(self, query: str, limit: int = 10, category: str = None) -> List[Dict[str, Any]]:
        """노드 검색"""
        if not self.encoder_available:
            logger.warning("SentenceTransformer가 사용 불가능하여 검색을 건너뜁니다.")
            return []
            
        query_vector = self.encoder.encode(query).tolist()
        
        # 필터 조건 설정
        query_filter = None
        if category:
            query_filter = {
                "must": [
                    {"key": "category", "match": {"value": category}}
                ]
            }
        
        search_results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter
        )
        
        return [
            {
                'score': result.score,
                'node': result.payload
            }
            for result in search_results
        ]
    
    def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """ID로 노드 조회"""
        try:
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[node_id]
            )
            return result[0].payload if result else None
        except Exception as e:
            logger.error(f"Error retrieving node {node_id}: {e}")
            return None
    
    def get_nodes_by_category(self, category: str) -> List[Dict[str, Any]]:
        """카테고리별 노드 조회"""
        try:
            scroll_result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter={
                    "must": [
                        {"key": "category", "match": {"value": category}}
                    ]
                },
                limit=100
            )
            
            return [point.payload for point in scroll_result[0]]
        except Exception as e:
            logger.error(f"Error retrieving nodes by category {category}: {e}")
            return []
    
    def get_children_nodes(self, parent_id: str) -> List[Dict[str, Any]]:
        """부모 ID로 자식 노드들 조회"""
        try:
            scroll_result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter={
                    "must": [
                        {"key": "parent_id", "match": {"value": parent_id}}
                    ]
                },
                limit=100
            )
            
            # 순서대로 정렬
            nodes = [point.payload for point in scroll_result[0]]
            return sorted(nodes, key=lambda x: x['order'])
        except Exception as e:
            logger.error(f"Error retrieving children of {parent_id}: {e}")
            return []
    
    def get_subtree(self, node_id: str) -> dict:
        """특정 노드 id를 루트로 하는 계층 트리(dict) 반환"""
        node = self.get_node_by_id(node_id)
        if not node:
            return None
        children = self.get_children_nodes(node_id)
        return {
            'node': node,
            'children': [self.get_subtree(child['id']) for child in children]
        }
    
    def update_node(self, node_id: str, updated_data: Dict[str, Any]):
        """노드 업데이트"""
        try:
            # 기존 노드 조회
            existing_node = self.get_node_by_id(node_id)
            if not existing_node:
                logger.error(f"Node {node_id} not found")
                return False
            
            # 변경 로그 기록
            if self.validation_logger:
                self._log_node_update(node_id, existing_node, updated_data)
            
            # 노드 업데이트
            updated_node = existing_node.copy()
            updated_node.update(updated_data)
            
            # 벡터 재생성
            embedding_text = self._create_embedding_text_from_dict(updated_node)
            vector = self.encoder.encode(embedding_text).tolist()
            
            # 업데이트 시간 추가
            updated_node['last_updated'] = datetime.now().isoformat()
            
            # Qdrant에 업데이트
            point = PointStruct(
                id=node_id,
                vector=vector,
                payload=updated_node
            )
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            
            logger.info(f"Updated node {node_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating node {node_id}: {e}")
            return False
    
    def _create_embedding_text_from_dict(self, node_dict: Dict[str, Any]) -> str:
        """딕셔너리 형태의 노드를 임베딩 텍스트로 변환"""
        parts = [
            f"Title: {node_dict.get('title', '')}",
            f"Content: {node_dict.get('content', '')}",
            f"Category: {node_dict.get('category', '')}",
            f"Type: {node_dict.get('node_type', '')}",
            f"Tags: {', '.join(node_dict.get('tags', []))}"
        ]
        
        # 링크 정보 추가
        links = node_dict.get('links', [])
        if links:
            link_titles = [link.get('title', '') for link in links]
            parts.append(f"Resources: {', '.join(link_titles)}")
        
        return " | ".join(parts)
    
    def _log_node_update(self, node_id: str, old_data: Dict[str, Any], new_data: Dict[str, Any]):
        """노드 업데이트 로그 기록"""
        change_log = ChangeLog(
            id=None,
            timestamp=datetime.now(),
            node_id=node_id,
            change_type=ChangeType.UPDATE,
            old_data=old_data,
            new_data=new_data,
            validation_status=ValidationStatus.SUCCESS,
            error_message=None,
            ai_suggestion="노드 업데이트",
            metadata={
                'updated_fields': list(new_data.keys()),
                'source': 'qdrant_store'
            }
        )
        
        self.validation_logger.log_change(change_log)

def generate_roadmap_html(nodes: List[RoadmapNode], template_path: str = 'react_roadmap.html') -> str:
    """원본 템플릿 스타일을 재사용하여 파싱된 노드 트리를 트리구조로 렌더링"""
    # 템플릿에서 head, script, 스타일 추출
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()
    head = re.search(r'(<head>[\s\S]*?</head>)', html)
    script = re.search(r'(<script>[\s\S]*?</script>)', html)
    
    head_html = head.group(1) if head else ''
    script_html = script.group(1) if script else ''

    # 노드 트리를 계층적으로 렌더링
    def render_nodes(parent_id, depth):
        children = [n for n in nodes if n.parent_id == parent_id]
        if not children:
            return ''
        html = []
        if depth == 1:
            html.append('<div class="main-branches" id="mainBranches" style="display: flex;">')
        for node in children:
            if node.node_type == 'branch':
                html.append(f'<div class="branch">')
                html.append(f'<div class="level-node {node.category}" onclick="toggleBranch(\'{node.id}\')">{node.title} <span class="expand-icon">▶</span></div>')
                html.append(f'<div class="sub-branches" id="{node.id}">{render_nodes(node.id, depth+1)}</div>')
                html.append('</div>')
            elif node.node_type == 'sub_branch':
                html.append(f'<div class="sub-node" onclick="toggleSubBranch(\'{node.id}\')">{node.title} <span class="expand-icon">▶</span></div>')
                html.append(f'<div class="sub-branches" id="{node.id}">{render_nodes(node.id, depth+1)}</div>')
            elif node.node_type == 'detail':
                html.append(f'<div class="detail-node">{node.content}</div>')
            elif node.node_type == 'resource':
                # 링크가 있으면 a 태그로
                if node.links:
                    for link in node.links:
                        html.append(f'<div class="resource-node">{link.get("type", "🔗")} <a href="{link["url"]}" target="_blank">{link["title"]}</a></div>')
                else:
                    html.append(f'<div class="resource-node">{node.content}</div>')
            elif node.node_type == 'book':
                if node.links:
                    for link in node.links:
                        html.append(f'<div class="book-node">📚 <a href="{link["url"]}" target="_blank">{link["title"]}</a></div>')
                else:
                    html.append(f'<div class="book-node">📚 {node.content}</div>')
        if depth == 1:
            html.append('</div>')
        return '\n'.join(html)

    # 루트 노드 찾기
    root = next((n for n in nodes if n.node_type == 'root'), None)
    if not root:
        root_title = 'React 학습 로드맵'
    else:
        root_title = root.title

    body = f'''
    <body>
    <div class="mindmap-container">
        <h1 class="mindmap-title">{root_title}</h1>
        <div class="controls">
            <button class="btn" onclick="expandAll()">전체 펼치기</button>
            <button class="btn" onclick="collapseAll()">전체 접기</button>
        </div>
        <div class="mindmap">
            <div class="root-node" onclick="toggleAllBranches()">{root_title}</div>
            {render_nodes(root.id if root else None, 1)}
        </div>
    </div>
    {script_html}
    </body>
    '''
    return f'<!DOCTYPE html>\n<html lang="ko">\n{head_html}\n{body}\n</html>'

def main():
    """메인 실행 함수"""
    # 검증 로거 초기화
    validation_logger = DatabaseValidationLogger("validation_logs.db")
    
    # HTML 파일 읽기
    with open('react_roadmap.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 파싱 (로거 전달)
    parser = ReactRoadmapParser(html_content, validation_logger)
    nodes = parser.parse()
    
    logger.info(f"Parsed {len(nodes)} nodes from HTML")
    
    # Qdrant 저장소 초기화 시도 (로거 전달)
    try:
        store = QdrantRoadmapStore(validation_logger=validation_logger)
        store.initialize_collection(force_recreate=True)
        
        # 노드들 저장
        store.store_nodes(nodes)
        
        # 테스트 검색
        logger.info("Testing search functionality...")
        
        # 카테고리별 검색
        for category in ['beginner', 'intermediate', 'advanced', 'community']:
            results = store.search_nodes(f"{category} react", limit=3, category=category)
            logger.info(f"\n{category.upper()} category search results:")
            for result in results:
                logger.info(f"  - {result['node']['title']} (score: {result['score']:.3f})")
        
        # 키워드 검색
        search_queries = ['hooks', 'typescript', 'testing', 'router']
        for query in search_queries:
            results = store.search_nodes(query, limit=3)
            logger.info(f"\nSearch results for '{query}':")
            for result in results:
                logger.info(f"  - {result['node']['title']} (score: {result['score']:.3f})")
                
    except Exception as e:
        logger.warning(f"Qdrant 연결 실패: {e}")
        logger.info("Qdrant 없이 HTML 파싱과 생성만 진행합니다.")
    
    # --- HTML로 저장 및 웹 브라우저로 열기 ---
    html_result = generate_roadmap_html(nodes, template_path='react_roadmap.html')
    output_path = 'parsed_roadmap.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_result)
    logger.info(f"파싱 결과를 {output_path}로 저장했습니다.")
    webbrowser.open(output_path)

if __name__ == "__main__":
    main()
