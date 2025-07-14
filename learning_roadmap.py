import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import base64
import io
import time
import threading
import queue
from subprocess import Popen, PIPE, STDOUT
import re
import html
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup

# 데이터 구조 정의
@dataclass
class RoadmapChunk:
    id: str
    roadmap_id: str
    content: str
    html_fragment: str
    embedding: List[float]
    chunk_index: int
    metadata: Dict[str, Any]
    collection_tags: List[str]  # 수집을 위한 태그 (카테고리, 타입, 난이도 등)
    search_tags: List[str]      # 검색을 위한 태그 (키워드, 기술 스택 등)

@dataclass
class RoadmapDocument:
    id: str
    title: str
    original_html: str
    chunks: List[RoadmapChunk]
    metadata: Dict[str, Any]

# 페이지 설정
st.set_page_config(
    page_title="🗺️ 학습로드맵 시스템",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 스타일링
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
        color: white;
        padding: 2rem;
        border-radius: 0.5rem;
        margin-bottom: 2rem;
        text-align: center;
    }
    
    .metric-card {
        background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        padding: 1.5rem;
        border-radius: 0.5rem;
        border: 2px solid #cbd5e1;
        margin-bottom: 1rem;
    }
    
    .status-success {
        background: #dcfce7;
        color: #166534;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-weight: bold;
    }
    
    .status-pending {
        background: #fef3c7;
        color: #92400e;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-weight: bold;
    }
    
    .status-error {
        background: #fee2e2;
        color: #991b1b;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-weight: bold;
    }
    
    .upload-box {
        border: 2px dashed #f59e0b;
        border-radius: 0.5rem;
        padding: 2rem;
        text-align: center;
        background: #fef3c7;
        margin: 1rem 0;
    }
    
    .chunk-preview {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 0.375rem;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    
    .similarity-score {
        background: #e3f2fd;
        color: #1976d2;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-size: 0.875rem;
    }
</style>
""", unsafe_allow_html=True)

# 세션 상태 초기화
if 'roadmaps' not in st.session_state:
    st.session_state.roadmaps = []
if 'logs' not in st.session_state:
    st.session_state.logs = [
        {"날짜": "2024-01-15 14:30", "변경내용": "React 로드맵 보완", "상태": "완료"},
        {"날짜": "2024-01-15 13:45", "변경내용": "Python 링크 검증", "상태": "진행중"},
        {"날짜": "2024-01-15 12:20", "변경내용": "JavaScript 노드 추가", "상태": "실패"}
    ]
if 'validation_progress' not in st.session_state:
    st.session_state.validation_progress = 0
if 'uploaded_filenames' not in st.session_state:
    st.session_state.uploaded_filenames = []
if 'roadmap_documents' not in st.session_state:
    st.session_state.roadmap_documents = {}
if 'custom_tags' not in st.session_state:
    st.session_state.custom_tags = {}
if 'tag_suggestions' not in st.session_state:
    st.session_state.tag_suggestions = [
        "frontend", "backend", "database", "devops", "mobile", "ai", "ml", "data-science",
        "web-development", "mobile-development", "game-development", "security", "testing",
        "react", "vue", "angular", "nodejs", "python", "java", "javascript", "typescript",
        "html", "css", "sql", "mongodb", "postgresql", "docker", "kubernetes", "aws",
        "azure", "gcp", "git", "github", "ci-cd", "agile", "scrum", "ui-ux", "api",
        "microservices", "serverless", "blockchain", "iot", "cloud-computing"
    ]

# 유틸리티 함수들
def extract_keywords(content: str) -> List[str]:
    """컨텐츠에서 기술 키워드를 추출합니다."""
    tech_keywords = re.findall(r'\b(JavaScript|Python|React|Node\.js|HTML|CSS|API|Database|TypeScript|Vue|Angular|Django|Flask|Express|MongoDB|PostgreSQL|MySQL|Git|Docker|AWS|Azure|GCP)\b', content, re.IGNORECASE)
    return list(set([kw.lower() for kw in tech_keywords]))

def extract_roadmap_metadata(html_content: str) -> Dict[str, Any]:
    """HTML에서 로드맵 메타데이터를 추출합니다."""
    metadata = {
        "category": "programming",
        "difficulty": "intermediate",
        "tags": [],
        "created_at": datetime.now().isoformat()
    }
    
    # 제목 추출
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE)
    if title_match:
        metadata["title"] = title_match.group(1).strip()
    
    # 태그 추출
    tags = extract_keywords(html_content)
    metadata["tags"] = tags[:10]  # 상위 10개만
    
    # 난이도 추출
    if any(word in html_content.lower() for word in ["beginner", "기초", "입문"]):
        metadata["difficulty"] = "beginner"
    elif any(word in html_content.lower() for word in ["advanced", "고급", "심화"]):
        metadata["difficulty"] = "advanced"
    
    return metadata

def parse_html_sections(html_content: str, roadmap_id: str) -> List[RoadmapChunk]:
    """HTML을 의미있는 섹션으로 분할하여 청크를 생성합니다."""
    chunks = []
    
    try:
        # 계층 구조 파싱 (레벨 > 브랜치 > 서브브랜치)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 메인 브랜치들 찾기 (다양한 패턴 시도)
        main_branches = None
        
        # 패턴 1: main-branches 클래스
        main_branches = soup.find('div', class_='main-branches')
        
        # 패턴 2: branch, level, main이 포함된 클래스
        if not main_branches:
            main_branches = soup.find_all(['section', 'div'], class_=re.compile(r'branch|level|main'))
        
        # 패턴 3: 특정 구조 찾기
        if not main_branches:
            # h1, h2, h3 태그를 기준으로 구조 찾기
            headings = soup.find_all(['h1', 'h2', 'h3'])
            if headings:
                main_branches = []
                for heading in headings:
                    # 헤딩 다음의 div나 section을 찾기
                    next_sibling = heading.find_next_sibling(['div', 'section'])
                    if next_sibling:
                        main_branches.append(next_sibling)
        
        # 패턴 4: 모든 div를 브랜치로 간주
        if not main_branches:
            main_branches = soup.find_all('div', class_=True)
        
        if main_branches:
            # 구조화된 파싱
            chunks = _parse_structured_content(roadmap_id, main_branches, soup)
        else:
            # 기본 섹션별 분할
            chunks = _parse_basic_sections(roadmap_id, html_content)
        
        # 최소한 하나의 청크라도 생성되도록 보장
        if not chunks:
            chunks = _create_fallback_chunk(roadmap_id, html_content)
        
    except Exception as e:
        st.error(f"파싱 중 오류 발생: {str(e)}")
        # 오류 발생 시 기본 청크 생성
        chunks = _create_fallback_chunk(roadmap_id, html_content)
    
    return chunks

def _parse_structured_content(roadmap_id: str, main_branches, soup) -> List[RoadmapChunk]:
    """구조화된 콘텐츠 파싱"""
    chunks = []
    chunk_index = 0
    
    try:
        # 제목 추출
        title_elem = soup.find(['h1', 'title'])
        main_title = title_elem.get_text().strip() if title_elem else "학습 로드맵"
        
        # 레벨별 파싱
        for level_idx, level_branch in enumerate(main_branches):
            try:
                # 레벨 노드 찾기 (다양한 패턴 시도)
                level_node = None
                
                # 패턴 1: level, branch 클래스
                level_node = level_branch.find(['div', 'h2'], class_=re.compile(r'level|branch'))
                
                # 패턴 2: 첫 번째 div나 h2
                if not level_node:
                    level_node = level_branch.find(['div', 'h2'])
                
                # 패턴 3: level_branch 자체를 사용
                if not level_node:
                    level_node = level_branch
                
                if level_node:
                    level_title = level_node.get_text().strip()
                    if not level_title:
                        level_title = f"레벨 {level_idx + 1}"
                    
                    level_category = _extract_category_from_classes(level_node.get('class', []))
                    
                    # 레벨 청크 생성
                    level_chunk = RoadmapChunk(
                        id=f"{roadmap_id}_level_{level_idx}",
                        roadmap_id=roadmap_id,
                        content=f"{level_title} - {level_category} 단계",
                        html_fragment=str(level_branch),
                        embedding=[],
                        chunk_index=chunk_index,
                        metadata={
                            "section": level_title,
                            "level": level_idx + 1,
                            "category": level_category,
                            "type": "level",
                            "keywords": extract_keywords(level_title),
                            "tools": _extract_tools(level_branch),
                            "resources": _extract_resources(level_branch),
                            "learning_objectives": _extract_learning_objectives(level_branch)
                        },
                        collection_tags=[f"level-{level_category}"],
                        search_tags=[f"level-{level_category}"]
                    )
                    chunks.append(level_chunk)
                    chunk_index += 1
                    
                    # 브랜치 파싱 (다양한 패턴 시도)
                    branches = []
                    
                    # 패턴 1: branch, sub 클래스
                    branches = level_branch.find_all(['div'], class_=re.compile(r'branch|sub'))
                    
                    # 패턴 2: 모든 div
                    if not branches:
                        branches = level_branch.find_all('div')
                    
                    # 패턴 3: 모든 자식 요소
                    if not branches:
                        branches = level_branch.find_all(['div', 'section', 'p'])
                    
                    for branch_idx, branch in enumerate(branches):
                        try:
                            branch_title = branch.get_text().strip()
                            if not branch_title:
                                branch_title = f"브랜치 {branch_idx + 1}"
                            
                            # 너무 짧은 내용은 건너뛰기
                            if len(branch_title) < 3:
                                continue
                            
                            branch_chunk = RoadmapChunk(
                                id=f"{roadmap_id}_branch_{level_idx}_{branch_idx}",
                                roadmap_id=roadmap_id,
                                content=branch_title,
                                html_fragment=str(branch),
                                embedding=[],
                                chunk_index=chunk_index,
                                metadata={
                                    "section": branch_title,
                                    "level": level_idx + 1,
                                    "branch": branch_idx + 1,
                                    "category": level_category,
                                    "type": "branch",
                                    "keywords": extract_keywords(branch_title),
                                    "tools": _extract_tools(branch),
                                    "resources": _extract_resources(branch),
                                    "learning_objectives": _extract_learning_objectives(branch)
                                },
                                collection_tags=[f"branch-{branch_title}"],
                                search_tags=[f"branch-{branch_title}"]
                            )
                            chunks.append(branch_chunk)
                            chunk_index += 1
                            
                            # 서브브랜치 파싱 (선택적)
                            sub_branches = branch.find_all(['div'], class_=re.compile(r'sub|detail'))
                            if not sub_branches:
                                sub_branches = branch.find_all(['div', 'p'])
                            
                            for sub_idx, sub_branch in enumerate(sub_branches[:3]):  # 최대 3개만
                                try:
                                    sub_title = sub_branch.get_text().strip()
                                    if not sub_title or len(sub_title) < 3:
                                        continue
                                    
                                    sub_chunk = RoadmapChunk(
                                        id=f"{roadmap_id}_sub_{level_idx}_{branch_idx}_{sub_idx}",
                                        roadmap_id=roadmap_id,
                                        content=sub_title,
                                        html_fragment=str(sub_branch),
                                        embedding=[],
                                        chunk_index=chunk_index,
                                        metadata={
                                            "section": sub_title,
                                            "level": level_idx + 1,
                                            "branch": branch_idx + 1,
                                            "sub": sub_idx + 1,
                                            "category": level_category,
                                            "type": "sub_branch",
                                            "keywords": extract_keywords(sub_title),
                                            "tools": _extract_tools(sub_branch),
                                            "resources": _extract_resources(sub_branch),
                                            "learning_objectives": _extract_learning_objectives(sub_branch)
                                        },
                                        collection_tags=[f"sub-branch-{sub_title}"],
                                        search_tags=[f"sub-branch-{sub_title}"]
                                    )
                                    chunks.append(sub_chunk)
                                    chunk_index += 1
                                except Exception as e:
                                    st.warning(f"서브브랜치 파싱 오류: {str(e)}")
                                    continue
                                    
                        except Exception as e:
                            st.warning(f"브랜치 파싱 오류: {str(e)}")
                            continue
                            
            except Exception as e:
                st.warning(f"레벨 파싱 오류: {str(e)}")
                continue
        
        # 최소한 하나의 청크라도 생성되도록 보장
        if not chunks:
            # 전체 HTML을 하나의 청크로 생성
            fallback_chunk = RoadmapChunk(
                id=f"{roadmap_id}_fallback_structured",
                roadmap_id=roadmap_id,
                content=main_title,
                html_fragment=str(soup),
                embedding=[],
                chunk_index=0,
                metadata={
                    "section": main_title,
                    "level": 1,
                    "category": "unknown",
                    "type": "fallback_structured",
                    "keywords": extract_keywords(main_title),
                    "tools": [],
                    "resources": [],
                    "learning_objectives": []
                },
                collection_tags=["unknown"],
                search_tags=["unknown"]
            )
            chunks.append(fallback_chunk)
            
    except Exception as e:
        st.error(f"구조화된 파싱 중 오류: {str(e)}")
        # 오류 발생 시 기본 청크 생성
        fallback_chunk = RoadmapChunk(
            id=f"{roadmap_id}_error_fallback",
            roadmap_id=roadmap_id,
            content="파싱 오류로 인한 기본 청크",
            html_fragment="",
            embedding=[],
            chunk_index=0,
            metadata={
                "section": "오류",
                "level": 1,
                "category": "error",
                "type": "error",
                "keywords": [],
                "tools": [],
                "resources": [],
                "learning_objectives": []
            },
            collection_tags=["error"],
            search_tags=["error"]
        )
        chunks.append(fallback_chunk)
    
    return chunks

def _parse_basic_sections(roadmap_id: str, html_content: str) -> List[RoadmapChunk]:
    """기본 섹션별 분할"""
    chunks = []
    
    # 섹션별로 분할 (section, .step, .module, h2, h3 태그 기준)
    section_patterns = [
        r'<section[^>]*>(.*?)</section>',
        r'<div[^>]*class="[^"]*step[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*module[^"]*"[^>]*>(.*?)</div>',
        r'<h2[^>]*>(.*?)</h2>',
        r'<h3[^>]*>(.*?)</h3>',
        r'<div[^>]*class="[^"]*"[^>]*>(.*?)</div>',  # 모든 div
        r'<p[^>]*>(.*?)</p>'  # 모든 p 태그
    ]
    
    all_sections = []
    for pattern in section_patterns:
        sections = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
        all_sections.extend(sections)
    
    # 중복 제거 및 정리
    unique_sections = []
    for section in all_sections:
        cleaned = re.sub(r'<[^>]+>', '', section).strip()
        if cleaned and len(cleaned) > 5:  # 최소 길이 조건 완화
            unique_sections.append((section, cleaned))
    
    # 기본 청크 생성
    for i, (html_fragment, content) in enumerate(unique_sections):
        chunk = _create_basic_chunk(roadmap_id, i, html_fragment, content)
        chunks.append(chunk)
    
    return chunks

def _create_fallback_chunk(roadmap_id: str, html_content: str) -> List[RoadmapChunk]:
    """파싱 실패 시 기본 청크 생성"""
    # HTML에서 텍스트만 추출
    soup = BeautifulSoup(html_content, 'html.parser')
    text_content = soup.get_text().strip()
    
    if not text_content:
        text_content = "파싱할 수 있는 내용이 없습니다."
    
    # 제목 추출 시도
    title_elem = soup.find(['h1', 'title'])
    title = title_elem.get_text().strip() if title_elem else "학습 로드맵"
    
    chunk = RoadmapChunk(
        id=f"{roadmap_id}_fallback",
        roadmap_id=roadmap_id,
        content=text_content[:500] + "..." if len(text_content) > 500 else text_content,
        html_fragment=html_content[:1000] + "..." if len(html_content) > 1000 else html_content,
        embedding=[],
        chunk_index=0,
        metadata={
            "section": title,
            "step_number": 1,
            "type": "fallback",
            "level": 1,
            "category": "unknown",
            "keywords": extract_keywords(text_content),
            "tools": _extract_tools_from_text(text_content),
            "resources": _extract_resources_from_text(text_content),
            "learning_objectives": _extract_learning_objectives_from_text(text_content)
        },
        collection_tags=["unknown"],
        search_tags=["unknown"]
    )
    
    return [chunk]

def _create_basic_chunk(roadmap_id: str, index: int, html_fragment: str, content: str) -> RoadmapChunk:
    """기본 청크 생성"""
    # 섹션 제목 추출
    title_match = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', html_fragment, re.IGNORECASE)
    section_title = title_match.group(1).strip() if title_match else f"섹션 {index+1}"
    
    # 키워드 추출
    keywords = extract_keywords(content)
    
    return RoadmapChunk(
        id=f"{roadmap_id}_chunk_{index}",
        roadmap_id=roadmap_id,
        content=content,
        html_fragment=html_fragment,
        embedding=[],
        chunk_index=index,
        metadata={
            "section": section_title,
            "step_number": index + 1,
            "keywords": keywords,
            "tools": _extract_tools_from_text(content),
            "resources": _extract_resources_from_text(content),
            "learning_objectives": _extract_learning_objectives_from_text(content)
        },
        collection_tags=["unknown"],
        search_tags=["unknown"]
    )

def _extract_category_from_classes(classes: List[str]) -> str:
    """클래스에서 카테고리 추출"""
    class_str = ' '.join(classes).lower()
    if 'beginner' in class_str or '기초' in class_str:
        return 'beginner'
    elif 'advanced' in class_str or '고급' in class_str:
        return 'advanced'
    elif 'intermediate' in class_str or '중급' in class_str:
        return 'intermediate'
    else:
        return 'community'

def _extract_tools(element) -> List[str]:
    """요소에서 도구 추출"""
    tools = []
    text = element.get_text().lower()
    
    # 도구 키워드 패턴
    tool_patterns = [
        r'\b(vscode|visual studio|sublime|atom|webstorm|intellij)\b',
        r'\b(git|github|gitlab|bitbucket)\b',
        r'\b(docker|kubernetes|jenkins|travis)\b',
        r'\b(npm|yarn|webpack|vite|parcel)\b',
        r'\b(react|vue|angular|svelte)\b',
        r'\b(node\.js|express|django|flask|spring)\b'
    ]
    
    for pattern in tool_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        tools.extend(matches)
    
    return list(set(tools))

def _extract_resources(element) -> List[Dict[str, str]]:
    """요소에서 리소스 추출"""
    resources = []
    
    # 링크 찾기
    links = element.find_all('a', href=True)
    for link in links:
        url = link.get('href', '')
        title = link.get_text().strip()
        if url and title:
            resources.append({
                'url': url,
                'title': title,
                'type': _determine_resource_type(url)
            })
    
    return resources

def _extract_learning_objectives(element) -> List[str]:
    """요소에서 학습 목표 추출"""
    objectives = []
    text = element.get_text()
    
    # 학습 목표 패턴
    objective_patterns = [
        r'학습\s*목표[:\s]*([^.]*)',
        r'목표[:\s]*([^.]*)',
        r'이해\s*할\s*수\s*있[어야]*\s*한다?[:\s]*([^.]*)',
        r'할\s*수\s*있[어야]*\s*한다?[:\s]*([^.]*)'
    ]
    
    for pattern in objective_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        objectives.extend(matches)
    
    return objectives

def _extract_tools_from_text(text: str) -> List[str]:
    """텍스트에서 도구 추출"""
    return _extract_tools_from_text_helper(text)

def _extract_resources_from_text(text: str) -> List[Dict[str, str]]:
    """텍스트에서 리소스 추출"""
    resources = []
    
    # URL 패턴 찾기
    url_pattern = r'https?://[^\s<>"]+'
    urls = re.findall(url_pattern, text)
    
    for url in urls:
        resources.append({
            'url': url,
            'title': f"리소스 {len(resources) + 1}",
            'type': _determine_resource_type(url)
        })
    
    return resources

def _extract_learning_objectives_from_text(text: str) -> List[str]:
    """텍스트에서 학습 목표 추출"""
    return _extract_learning_objectives_from_text_helper(text)

def _extract_tools_from_text_helper(text: str) -> List[str]:
    """텍스트에서 도구 추출 헬퍼 함수"""
    tools = []
    text_lower = text.lower()
    
    tool_patterns = [
        r'\b(vscode|visual studio|sublime|atom|webstorm|intellij)\b',
        r'\b(git|github|gitlab|bitbucket)\b',
        r'\b(docker|kubernetes|jenkins|travis)\b',
        r'\b(npm|yarn|webpack|vite|parcel)\b',
        r'\b(react|vue|angular|svelte)\b',
        r'\b(node\.js|express|django|flask|spring)\b'
    ]
    
    for pattern in tool_patterns:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        tools.extend(matches)
    
    return list(set(tools))

def _extract_learning_objectives_from_text_helper(text: str) -> List[str]:
    """텍스트에서 학습 목표 추출 헬퍼 함수"""
    objectives = []
    
    objective_patterns = [
        r'학습\s*목표[:\s]*([^.]*)',
        r'목표[:\s]*([^.]*)',
        r'이해\s*할\s*수\s*있[어야]*\s*한다?[:\s]*([^.]*)',
        r'할\s*수\s*있[어야]*\s*한다?[:\s]*([^.]*)'
    ]
    
    for pattern in objective_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        objectives.extend(matches)
    
    return objectives

def _determine_resource_type(url: str) -> str:
    """URL에서 리소스 타입 결정"""
    url_lower = url.lower()
    if any(ext in url_lower for ext in ['.pdf', '.doc', '.docx']):
        return 'document'
    elif any(ext in url_lower for ext in ['.mp4', '.avi', '.mov', 'youtube.com', 'vimeo.com']):
        return 'video'
    elif any(ext in url_lower for ext in ['.jpg', '.png', '.gif']):
        return 'image'
    elif 'github.com' in url_lower:
        return 'code'
    elif any(domain in url_lower for domain in ['stackoverflow.com', 'docs.', 'tutorial']):
        return 'tutorial'
    else:
        return 'link'

def suggest_tags_for_chunk(chunk_content: str, chunk_metadata: Dict[str, Any]) -> Dict[str, List[str]]:
    """청크 내용과 메타데이터를 기반으로 수집 태그와 검색 태그 제안"""
    collection_tags = []
    search_tags = []
    
    # 기존 키워드에서 태그 추출
    keywords = chunk_metadata.get("keywords", [])
    for keyword in keywords:
        if keyword.lower() in st.session_state.tag_suggestions:
            search_tags.append(keyword.lower())
    
    # 도구에서 태그 추출
    tools = chunk_metadata.get("tools", [])
    for tool in tools:
        tool_lower = tool.lower()
        if tool_lower in st.session_state.tag_suggestions:
            search_tags.append(tool_lower)
    
    # 카테고리 기반 수집 태그
    category = chunk_metadata.get("category", "").lower()
    if category in ["beginner", "intermediate", "advanced"]:
        collection_tags.append(f"level-{category}")
        collection_tags.append(f"difficulty-{category}")
    
    # 타입 기반 수집 태그
    chunk_type = chunk_metadata.get("type", "").lower()
    if chunk_type in ["level", "branch", "sub_branch"]:
        collection_tags.append(f"type-{chunk_type}")
        collection_tags.append(f"structure-{chunk_type}")
    
    # 레벨 기반 수집 태그
    level = chunk_metadata.get("level", "")
    if level:
        collection_tags.append(f"hierarchy-level-{level}")
    
    # 내용 기반 검색 태그 추출
    content_lower = chunk_content.lower()
    
    # 기술 스택 검색 태그
    tech_patterns = {
        "frontend": ["react", "vue", "angular", "html", "css", "javascript", "typescript"],
        "backend": ["nodejs", "python", "java", "php", "ruby", "go"],
        "database": ["sql", "mongodb", "postgresql", "mysql", "redis"],
        "devops": ["docker", "kubernetes", "jenkins", "git", "aws", "azure"],
        "mobile": ["react-native", "flutter", "ios", "android", "swift", "kotlin"],
        "ai": ["machine-learning", "deep-learning", "tensorflow", "pytorch", "scikit-learn"],
        "security": ["authentication", "authorization", "encryption", "ssl", "oauth"],
        "testing": ["unit-test", "integration-test", "e2e-test", "jest", "cypress"]
    }
    
    for tag, patterns in tech_patterns.items():
        if any(pattern in content_lower for pattern in patterns):
            search_tags.append(tag)
    
    # 도메인별 수집 태그
    domain_patterns = {
        "web-development": ["web", "website", "frontend", "backend"],
        "mobile-development": ["mobile", "app", "ios", "android"],
        "data-science": ["data", "analysis", "statistics", "machine-learning"],
        "game-development": ["game", "unity", "unreal", "gaming"],
        "cybersecurity": ["security", "hacking", "penetration", "vulnerability"]
    }
    
    for domain, patterns in domain_patterns.items():
        if any(pattern in content_lower for pattern in patterns):
            collection_tags.append(domain)
    
    return {
        "collection_tags": list(set(collection_tags)),
        "search_tags": list(set(search_tags))
    }

def apply_tags_to_chunk(chunk: RoadmapChunk, custom_collection_tags: List[str] = None, custom_search_tags: List[str] = None) -> RoadmapChunk:
    """청크에 커스텀 태그를 적용"""
    # 기존 태그와 새 태그 결합
    updated_collection_tags = chunk.collection_tags.copy()
    updated_search_tags = chunk.search_tags.copy()
    
    if custom_collection_tags:
        updated_collection_tags.extend(custom_collection_tags)
        updated_collection_tags = list(set(updated_collection_tags))
    
    if custom_search_tags:
        updated_search_tags.extend(custom_search_tags)
        updated_search_tags = list(set(updated_search_tags))
    
    # 메타데이터 업데이트 (기존 키워드도 유지)
    updated_metadata = chunk.metadata.copy()
    if custom_search_tags:
        existing_keywords = updated_metadata.get("keywords", [])
        updated_metadata["keywords"] = list(set(existing_keywords + custom_search_tags))
    
    # 새로운 청크 객체 생성
    return RoadmapChunk(
        id=chunk.id,
        roadmap_id=chunk.roadmap_id,
        content=chunk.content,
        html_fragment=chunk.html_fragment,
        embedding=chunk.embedding,
        chunk_index=chunk.chunk_index,
        metadata=updated_metadata,
        collection_tags=updated_collection_tags,
        search_tags=updated_search_tags
    )

def search_chunks_by_tags(chunks: List[RoadmapChunk], search_tags: List[str], tag_type: str = "search") -> List[RoadmapChunk]:
    """태그 기반으로 청크 검색 (수집 태그 또는 검색 태그 선택 가능)"""
    if not search_tags:
        return chunks
    
    matched_chunks = []
    for chunk in chunks:
        if tag_type == "collection":
            chunk_tags = chunk.collection_tags
        else:  # search
            chunk_tags = chunk.search_tags
        
        # 하나라도 매칭되면 포함
        if any(tag.lower() in [ct.lower() for ct in chunk_tags] for tag in search_tags):
            matched_chunks.append(chunk)
    
    return matched_chunks

def get_tag_statistics(chunks: List[RoadmapChunk]) -> Dict[str, Dict[str, int]]:
    """청크들의 수집 태그와 검색 태그 통계 계산"""
    collection_tag_counts = {}
    search_tag_counts = {}
    
    for chunk in chunks:
        # 수집 태그 통계
        for tag in chunk.collection_tags:
            tag_lower = tag.lower()
            collection_tag_counts[tag_lower] = collection_tag_counts.get(tag_lower, 0) + 1
        
        # 검색 태그 통계
        for tag in chunk.search_tags:
            tag_lower = tag.lower()
            search_tag_counts[tag_lower] = search_tag_counts.get(tag_lower, 0) + 1
    
    return {
        "collection_tags": collection_tag_counts,
        "search_tags": search_tag_counts
    }

def calculate_similarity(query: str, chunk_content: str) -> float:
    """간단한 유사도 계산 (실제로는 벡터 임베딩 사용)"""
    query_words = set(query.lower().split())
    content_words = set(chunk_content.lower().split())
    
    if not query_words or not content_words:
        return 0.0
    
    intersection = query_words.intersection(content_words)
    union = query_words.union(content_words)
    
    return len(intersection) / len(union) if union else 0.0

def search_and_generate_html(query: str, roadmap_documents: Dict[str, RoadmapDocument], threshold: float = 0.1) -> str:
    """검색어 기반으로 관련 청크를 찾아 인터랙티브 마인드맵 HTML을 재생성합니다."""
    relevant_chunks = []
    
    # 파일명으로 검색하는 경우 특별 처리
    is_filename_search = query.startswith("filename:") or query.startswith("source:")
    
    # 모든 문서의 청크에서 검색
    for doc_id, document in roadmap_documents.items():
        for chunk in document.chunks:
            similarity = 0.0
            
            if is_filename_search:
                # 파일명 검색인 경우 태그 기반으로 검색
                if query in chunk.collection_tags or query in chunk.search_tags:
                    similarity = 1.0  # 완전 일치
                elif query.lower() in [tag.lower() for tag in chunk.collection_tags + chunk.search_tags]:
                    similarity = 0.8  # 대소문자 무시 일치
            else:
                # 일반 텍스트 검색
                similarity = calculate_similarity(query, chunk.content)
            
            if similarity >= threshold:
                relevant_chunks.append({
                    "chunk": chunk,
                    "similarity": similarity,
                    "document_title": document.title
                })
    
    # 유사도 순으로 정렬
    relevant_chunks.sort(key=lambda x: x["similarity"], reverse=True)
    top_chunks = relevant_chunks[:20]  # 상위 20개로 증가
    
    if not top_chunks:
        return "<h1>검색 결과가 없습니다</h1>"
    
    # 중복 제거 및 그룹화
    unique_chunks = {}
    for item in top_chunks:
        chunk = item["chunk"]
        # 청크 ID를 기준으로 중복 제거
        if chunk.id not in unique_chunks:
            unique_chunks[chunk.id] = item
        else:
            # 더 높은 유사도를 가진 것을 유지
            if item["similarity"] > unique_chunks[chunk.id]["similarity"]:
                unique_chunks[chunk.id] = item
    
    # 중복 제거된 청크들을 다시 정렬
    unique_chunks_list = list(unique_chunks.values())
    unique_chunks_list.sort(key=lambda x: x["similarity"], reverse=True)
    
    # 카테고리별로 그룹화
    categories = {
        "beginner": [],
        "intermediate": [],
        "advanced": [],
        "community": []
    }
    
    for item in unique_chunks_list:
        chunk = item["chunk"]
        category = chunk.metadata.get("category", "community").lower()
        if category in categories:
            categories[category].append(item)
        else:
            categories["community"].append(item)
    
    # HTML 템플릿 (인터랙티브 마인드맵)
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{query} - 검색 결과 기반 학습 로드맵</title>
        <style>
            body {{
                margin: 0;
                padding: 20px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                overflow-x: auto;
            }}

            .mindmap-container {{
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 30px;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
                min-width: 1200px;
            }}

            .mindmap-title {{
                text-align: center;
                font-size: 2.5em;
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 30px;
                text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.1);
            }}

            .search-info {{
                text-align: center;
                font-size: 1.2em;
                color: #34495e;
                margin-bottom: 20px;
                background: rgba(52, 152, 219, 0.1);
                padding: 15px;
                border-radius: 10px;
            }}

            .mindmap {{
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 30px;
            }}

            .root-node {{
                background: linear-gradient(135deg, #FF6B6B, #FF8E53);
                color: white;
                padding: 20px 40px;
                border-radius: 25px;
                font-size: 1.8em;
                font-weight: bold;
                box-shadow: 0 10px 25px rgba(255, 107, 107, 0.3);
                cursor: pointer;
                transition: all 0.3s ease;
            }}

            .root-node:hover {{
                transform: translateY(-5px);
                box-shadow: 0 15px 35px rgba(255, 107, 107, 0.4);
            }}

            .main-branches {{
                display: flex;
                justify-content: space-around;
                width: 100%;
                gap: 30px;
                flex-wrap: wrap;
            }}

            .branch {{
                flex: 1;
                min-width: 350px;
                max-width: 400px;
            }}

            .level-node {{
                padding: 15px 25px;
                border-radius: 20px;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-bottom: 15px;
                text-align: center;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
            }}

            .beginner {{
                background: linear-gradient(135deg, #4ECDC4, #44A08D);
                color: white;
            }}

            .intermediate {{
                background: linear-gradient(135deg, #FDBB2D, #22C1C3);
                color: white;
            }}

            .advanced {{
                background: linear-gradient(135deg, #FA8072, #FF6347);
                color: white;
            }}

            .community {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
            }}

            .level-node:hover {{
                transform: translateY(-3px);
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.2);
            }}

            .sub-branches {{
                margin-left: 20px;
                margin-top: 15px;
                display: none;
            }}

            .sub-branches.expanded {{
                display: block;
                animation: slideDown 0.3s ease-out;
            }}

            @keyframes slideDown {{
                from {{
                    opacity: 0;
                    max-height: 0;
                }}
                to {{
                    opacity: 1;
                    max-height: 1000px;
                }}
            }}

            .sub-node {{
                background: rgba(255, 255, 255, 0.9);
                border-left: 4px solid #3498db;
                padding: 12px 20px;
                margin: 8px 0;
                border-radius: 8px;
                font-size: 0.95em;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
                cursor: pointer;
                transition: all 0.2s ease;
            }}

            .sub-node:hover {{
                background: rgba(52, 152, 219, 0.1);
                transform: translateX(5px);
            }}

            .detail-node {{
                background: rgba(255, 255, 255, 0.7);
                border-left: 3px solid #95a5a6;
                padding: 8px 15px;
                margin: 5px 0 5px 20px;
                border-radius: 5px;
                font-size: 0.85em;
                color: #2c3e50;
            }}

            .resource-node {{
                background: rgba(46, 204, 113, 0.1);
                border-left: 3px solid #2ecc71;
                padding: 8px 15px;
                margin: 5px 0 5px 20px;
                border-radius: 5px;
                font-size: 0.85em;
                color: #27ae60;
            }}

            .similarity-score {{
                background: rgba(231, 76, 60, 0.1);
                border-left: 3px solid #e74c3c;
                padding: 8px 15px;
                margin: 5px 0 5px 20px;
                border-radius: 5px;
                font-size: 0.85em;
                color: #c0392b;
                font-weight: bold;
            }}

            .resource-node a {{
                color: #2980b9;
                text-decoration: underline;
                font-weight: 500;
                transition: all 0.2s ease;
                padding: 2px 4px;
                border-radius: 3px;
                background: rgba(41, 128, 185, 0.1);
            }}

            .resource-node a:hover {{
                color: #ffffff;
                background: #3498db;
                text-decoration: none;
                transform: translateX(3px);
                box-shadow: 0 2px 8px rgba(52, 152, 219, 0.3);
            }}

            .expand-icon {{
                float: right;
                transition: transform 0.3s ease;
            }}

            .expand-icon.rotated {{
                transform: rotate(90deg);
            }}

            .controls {{
                text-align: center;
                margin-bottom: 20px;
            }}

            .btn {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 25px;
                cursor: pointer;
                margin: 0 10px;
                font-size: 0.9em;
                transition: all 0.3s ease;
            }}

            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }}
        </style>
    </head>
    <body>
        <div class="mindmap-container">
            <h1 class="mindmap-title">{query} 학습 로드맵</h1>
            
            <div class="search-info">
                🔍 검색어: <strong>{query}</strong> | 📊 검색 결과: <strong>{len(unique_chunks_list)}개</strong> | 
                📚 소스 문서: <strong>{len(set(item['chunk'].roadmap_id for item in unique_chunks_list))}개</strong>
            </div>

            <div class="controls">
                <button class="btn" onclick="expandAll()">전체 펼치기</button>
                <button class="btn" onclick="collapseAll()">전체 접기</button>
            </div>

            <div class="mindmap">
                <div class="root-node" onclick="toggleAllBranches()">
                    {query} 학습 로드맵
                </div>

                <div class="main-branches" id="mainBranches" style="display: none;">
    """
    
    # 카테고리별로 브랜치 생성
    category_names = {
        "beginner": "초급 (Beginner)",
        "intermediate": "중급 (Intermediate)", 
        "advanced": "고급 (Advanced)",
        "community": "커뮤니티 (Community)"
    }
    
    for category, items in categories.items():
        if items:  # 해당 카테고리에 항목이 있는 경우만
            html_content += f"""
                    <div class="branch">
                        <div class="level-node {category}" onclick="toggleBranch('{category}')">
                            {category_names[category]} <span class="expand-icon">▶</span>
                        </div>
                        <div class="sub-branches" id="{category}">
                            <div class="sub-node" onclick="toggleSubBranch('{category}-details')">
                                검색 결과 <span class="expand-icon">▶</span>
                            </div>
                            <div class="sub-branches" id="{category}-details">
            """
            
            # 해당 카테고리의 청크들을 추가 (중복 제거된)
            for i, item in enumerate(items[:8]):  # 각 카테고리당 최대 8개로 제한
                chunk = item["chunk"]
                similarity = item["similarity"]
                section = chunk.metadata.get("section", "N/A")
                content = chunk.content[:150] + "..." if len(chunk.content) > 150 else chunk.content
                
                # HTML 이스케이프 처리
                section_escaped = html.escape(section)
                content_escaped = html.escape(content)
                
                html_content += f"""
                                <div class="detail-node">{section_escaped}</div>
                                <div class="detail-node">{content_escaped}</div>
                                <div class="similarity-score">유사도: {similarity:.2f}</div>
                """
                
                # 리소스가 있으면 추가 (링크 처리 개선)
                resources = chunk.metadata.get("resources", [])
                if resources:
                    for resource in resources[:3]:  # 최대 3개 리소스
                        if isinstance(resource, dict):
                            title = resource.get("title", "리소스")
                            url = resource.get("url", "#")
                            # URL 유효성 검사
                            if url and url != "#" and (url.startswith("http://") or url.startswith("https://")):
                                title_escaped = html.escape(title)
                                url_escaped = html.escape(url)
                                html_content += f'<div class="resource-node">🔗 <a href="{url_escaped}" target="_blank" rel="noopener noreferrer">{title_escaped}</a></div>'
                            else:
                                title_escaped = html.escape(title)
                                html_content += f'<div class="resource-node">📚 {title_escaped}</div>'
                        else:
                            # 문자열인 경우
                            resource_text = html.escape(str(resource))
                            html_content += f'<div class="resource-node">📚 {resource_text}</div>'
                
                # 도구 정보 추가
                tools = chunk.metadata.get("tools", [])
                if tools:
                    tools_text = ", ".join(tools[:3])  # 최대 3개 도구
                    tools_escaped = html.escape(tools_text)
                    html_content += f'<div class="detail-node">🔧 도구: {tools_escaped}</div>'
                
                # 학습 목표 추가
                learning_objectives = chunk.metadata.get("learning_objectives", [])
                if learning_objectives:
                    for objective in learning_objectives[:2]:  # 최대 2개 목표
                        objective_escaped = html.escape(objective)
                        html_content += f'<div class="detail-node">🎯 {objective_escaped}</div>'
            
            html_content += """
                            </div>
                        </div>
                    </div>
            """
    
    html_content += """
                </div>
            </div>
        </div>

        <script>
            let mainBranchesVisible = false;

            function toggleAllBranches() {
                const mainBranches = document.getElementById('mainBranches');
                mainBranchesVisible = !mainBranchesVisible;
                mainBranches.style.display = mainBranchesVisible ? 'flex' : 'none';
            }

            function toggleBranch(branchId) {
                const branch = document.getElementById(branchId);
                const icon = event.currentTarget.querySelector('.expand-icon');
                
                if (branch.style.display === 'none' || branch.style.display === '') {
                    branch.style.display = 'block';
                    branch.classList.add('expanded');
                    icon.classList.add('rotated');
                    icon.innerHTML = '▼';
                } else {
                    branch.style.display = 'none';
                    branch.classList.remove('expanded');
                    icon.classList.remove('rotated');
                    icon.innerHTML = '▶';
                }
            }

            function toggleSubBranch(subBranchId) {
                const subBranch = document.getElementById(subBranchId);
                const icon = event.currentTarget.querySelector('.expand-icon');
                
                if (subBranch.style.display === 'none' || subBranch.style.display === '') {
                    subBranch.style.display = 'block';
                    subBranch.classList.add('expanded');
                    icon.classList.add('rotated');
                    icon.innerHTML = '▼';
                } else {
                    subBranch.style.display = 'none';
                    subBranch.classList.remove('expanded');
                    icon.classList.remove('rotated');
                    icon.innerHTML = '▶';
                }
            }

            function expandAll() {
                const mainBranches = document.getElementById('mainBranches');
                mainBranches.style.display = 'flex';
                mainBranchesVisible = true;

                const allBranches = document.querySelectorAll('.sub-branches');
                const allIcons = document.querySelectorAll('.expand-icon');
                
                allBranches.forEach(branch => {
                    branch.style.display = 'block';
                    branch.classList.add('expanded');
                });
                
                allIcons.forEach(icon => {
                    icon.classList.add('rotated');
                    icon.innerHTML = '▼';
                });
            }

            function collapseAll() {
                const mainBranches = document.getElementById('mainBranches');
                mainBranches.style.display = 'none';
                mainBranchesVisible = false;

                const allBranches = document.querySelectorAll('.sub-branches');
                const allIcons = document.querySelectorAll('.expand-icon');
                
                allBranches.forEach(branch => {
                    branch.style.display = 'none';
                    branch.classList.remove('expanded');
                });
                
                allIcons.forEach(icon => {
                    icon.classList.remove('rotated');
                    icon.innerHTML = '▶';
                });
            }
        </script>
    </body>
    </html>
    """
    
    return html_content

def generate_mindmap_html(roadmap_data: Dict[str, Any]) -> str:
    """로드맵 데이터를 기반으로 인터랙티브 마인드맵 HTML을 생성합니다."""
    # 메인 토픽
    main_topic = html.escape(roadmap_data.get('main_topic', '학습 로드맵'))
    
    # 사전 요구사항
    prerequisites_html = ""
    if roadmap_data.get('prerequisites'):
        prerequisites_list = ""
        for req in roadmap_data['prerequisites']:
            prerequisites_list += f'<div class="detail-node">{html.escape(req)}</div>'
        prerequisites_html = f"""
        <div class="branch">
            <div class="level-node beginner" onclick="toggleBranch('prerequisites')">
                사전 요구사항 <span class="expand-icon">▶</span>
            </div>
            <div class="sub-branches" id="prerequisites">
                <div class="sub-node" onclick="toggleSubBranch('prerequisites-details')">
                    필수 선수 지식 <span class="expand-icon">▶</span>
                </div>
                <div class="sub-branches" id="prerequisites-details">
                    {prerequisites_list}
                </div>
            </div>
        </div>
        """
    
    # 단계별 내용
    phases_html = ""
    for i, phase in enumerate(roadmap_data.get('phases', [])):
        phase_title = html.escape(phase.get('title', f'단계 {i+1}'))
        duration = html.escape(phase.get('duration', ''))
        
        topics_html = ""
        for j, topic in enumerate(phase.get('topics', [])):
            topic_title = html.escape(topic.get('title', ''))
            topic_desc = html.escape(topic.get('description', ''))
            
            # 학습 링크 처리
            learning_links_html = ""
            if topic.get('learning_links'):
                for link in topic['learning_links']:
                    link_title = html.escape(link.get('title', '학습 링크'))
                    link_url = html.escape(link.get('url', '#'))
                    learning_links_html += f'<div class="resource-node">🔗 <a href="{link_url}" target="_blank">{link_title}</a></div>'
            
            topics_html += f"""
            <div class="detail-node">{topic_title}</div>
            <div class="detail-node">{topic_desc}</div>
            {learning_links_html}
            """
        
        # 단계별 클래스 결정
        phase_class = "beginner" if i == 0 else "intermediate" if i == 1 else "advanced"
        
        phases_html += f"""
        <div class="branch">
            <div class="level-node {phase_class}" onclick="toggleBranch('phase-{i}')">
                {phase_title} {f'({duration})' if duration else ''} <span class="expand-icon">▶</span>
            </div>
            <div class="sub-branches" id="phase-{i}">
                <div class="sub-node" onclick="toggleSubBranch('topics-{i}')">
                    학습 주제 <span class="expand-icon">▶</span>
                </div>
                <div class="sub-branches" id="topics-{i}">
                    {topics_html}
                </div>
            </div>
        </div>
        """
    
    # 추천 자료
    resources_html = ""
    if roadmap_data.get('resources'):
        resources_list = ""
        for res in roadmap_data['resources']:
            resources_list += f'<div class="resource-node">📚 {html.escape(res)}</div>'
        resources_html = f"""
        <div class="branch">
            <div class="level-node community" onclick="toggleBranch('resources')">
                추천 학습 자료 <span class="expand-icon">▶</span>
            </div>
            <div class="sub-branches" id="resources">
                {resources_list}
            </div>
        </div>
        """
    
    # HTML 템플릿 (인터랙티브 마인드맵)
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{main_topic} - 인터랙티브 마인드맵</title>
        <style>
            body {{
                margin: 0;
                padding: 20px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                overflow-x: auto;
            }}

            .mindmap-container {{
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 30px;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
                min-width: 1200px;
            }}

            .mindmap-title {{
                text-align: center;
                font-size: 2.5em;
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 30px;
                text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.1);
            }}

            .mindmap {{
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 30px;
            }}

            .root-node {{
                background: linear-gradient(135deg, #FF6B6B, #FF8E53);
                color: white;
                padding: 20px 40px;
                border-radius: 25px;
                font-size: 1.8em;
                font-weight: bold;
                box-shadow: 0 10px 25px rgba(255, 107, 107, 0.3);
                cursor: pointer;
                transition: all 0.3s ease;
            }}

            .root-node:hover {{
                transform: translateY(-5px);
                box-shadow: 0 15px 35px rgba(255, 107, 107, 0.4);
            }}

            .main-branches {{
                display: flex;
                justify-content: space-around;
                width: 100%;
                gap: 30px;
                flex-wrap: wrap;
            }}

            .branch {{
                flex: 1;
                min-width: 350px;
                max-width: 400px;
            }}

            .level-node {{
                padding: 15px 25px;
                border-radius: 20px;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-bottom: 15px;
                text-align: center;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
            }}

            .beginner {{
                background: linear-gradient(135deg, #4ECDC4, #44A08D);
                color: white;
            }}

            .intermediate {{
                background: linear-gradient(135deg, #FDBB2D, #22C1C3);
                color: white;
            }}

            .advanced {{
                background: linear-gradient(135deg, #FA8072, #FF6347);
                color: white;
            }}

            .community {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
            }}

            .level-node:hover {{
                transform: translateY(-3px);
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.2);
            }}

            .sub-branches {{
                margin-left: 20px;
                margin-top: 15px;
                display: none;
            }}

            .sub-branches.expanded {{
                display: block;
                animation: slideDown 0.3s ease-out;
            }}

            @keyframes slideDown {{
                from {{
                    opacity: 0;
                    max-height: 0;
                }}
                to {{
                    opacity: 1;
                    max-height: 1000px;
                }}
            }}

            .sub-node {{
                background: rgba(255, 255, 255, 0.9);
                border-left: 4px solid #3498db;
                padding: 12px 20px;
                margin: 8px 0;
                border-radius: 8px;
                font-size: 0.95em;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
                cursor: pointer;
                transition: all 0.2s ease;
            }}

            .sub-node:hover {{
                background: rgba(52, 152, 219, 0.1);
                transform: translateX(5px);
            }}

            .detail-node {{
                background: rgba(255, 255, 255, 0.7);
                border-left: 3px solid #95a5a6;
                padding: 8px 15px;
                margin: 5px 0 5px 20px;
                border-radius: 5px;
                font-size: 0.85em;
                color: #2c3e50;
            }}

            .resource-node {{
                background: rgba(46, 204, 113, 0.1);
                border-left: 3px solid #2ecc71;
                padding: 8px 15px;
                margin: 5px 0 5px 20px;
                border-radius: 5px;
                font-size: 0.85em;
                color: #27ae60;
            }}

            .resource-node a {{
                color: #2980b9;
                text-decoration: underline;
                font-weight: 500;
                transition: all 0.2s ease;
                padding: 2px 4px;
                border-radius: 3px;
                background: rgba(41, 128, 185, 0.1);
            }}

            .resource-node a:hover {{
                color: #ffffff;
                background: #3498db;
                text-decoration: none;
                transform: translateX(3px);
                box-shadow: 0 2px 8px rgba(52, 152, 219, 0.3);
            }}

            .expand-icon {{
                float: right;
                transition: transform 0.3s ease;
            }}

            .expand-icon.rotated {{
                transform: rotate(90deg);
            }}

            .controls {{
                text-align: center;
                margin-bottom: 20px;
            }}

            .btn {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 25px;
                cursor: pointer;
                margin: 0 10px;
                font-size: 0.9em;
                transition: all 0.3s ease;
            }}

            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }}
        </style>
    </head>
    <body>
        <div class="mindmap-container">
            <h1 class="mindmap-title">{main_topic}</h1>

            <div class="controls">
                <button class="btn" onclick="expandAll()">전체 펼치기</button>
                <button class="btn" onclick="collapseAll()">전체 접기</button>
            </div>

            <div class="mindmap">
                <div class="root-node" onclick="toggleAllBranches()">
                    {main_topic}
                </div>

                <div class="main-branches" id="mainBranches" style="display: none;">
                    {prerequisites_html}
                    {phases_html}
                    {resources_html}
                </div>
            </div>
        </div>

        <script>
            let mainBranchesVisible = false;

            function toggleAllBranches() {{
                const mainBranches = document.getElementById('mainBranches');
                mainBranchesVisible = !mainBranchesVisible;
                mainBranches.style.display = mainBranchesVisible ? 'flex' : 'none';
            }}

            function toggleBranch(branchId) {{
                const branch = document.getElementById(branchId);
                const icon = event.currentTarget.querySelector('.expand-icon');
                
                if (branch.style.display === 'none' || branch.style.display === '') {{
                    branch.style.display = 'block';
                    branch.classList.add('expanded');
                    icon.classList.add('rotated');
                    icon.innerHTML = '▼';
                }} else {{
                    branch.style.display = 'none';
                    branch.classList.remove('expanded');
                    icon.classList.remove('rotated');
                    icon.innerHTML = '▶';
                }}
            }}

            function toggleSubBranch(subBranchId) {{
                const subBranch = document.getElementById(subBranchId);
                const icon = event.currentTarget.querySelector('.expand-icon');
                
                if (subBranch.style.display === 'none' || subBranch.style.display === '') {{
                    subBranch.style.display = 'block';
                    subBranch.classList.add('expanded');
                    icon.classList.add('rotated');
                    icon.innerHTML = '▼';
                }} else {{
                    subBranch.style.display = 'none';
                    subBranch.classList.remove('expanded');
                    icon.classList.remove('rotated');
                    icon.innerHTML = '▶';
                }}
            }}

            function expandAll() {{
                const mainBranches = document.getElementById('mainBranches');
                mainBranches.style.display = 'flex';
                mainBranchesVisible = true;

                const allBranches = document.querySelectorAll('.sub-branches');
                const allIcons = document.querySelectorAll('.expand-icon');
                
                allBranches.forEach(branch => {{
                    branch.style.display = 'block';
                    branch.classList.add('expanded');
                }});
                
                allIcons.forEach(icon => {{
                    icon.classList.add('rotated');
                    icon.innerHTML = '▼';
                }});
            }}

            function collapseAll() {{
                const mainBranches = document.getElementById('mainBranches');
                mainBranches.style.display = 'none';
                mainBranchesVisible = false;

                const allBranches = document.querySelectorAll('.sub-branches');
                const allIcons = document.querySelectorAll('.expand-icon');
                
                allBranches.forEach(branch => {{
                    branch.style.display = 'none';
                    branch.classList.remove('expanded');
                }});
                
                allIcons.forEach(icon => {{
                    icon.classList.remove('rotated');
                    icon.innerHTML = '▶';
                }});
            }}
        </script>
    </body>
    </html>
    """
    
    return html_content

# 헤더
st.markdown("""
<div class="main-header">
    <h1>🗺️ 학습로드맵 시스템</h1>
    <p>AI 기반 개인화 학습 경로 생성 및 관리</p>
</div>
""", unsafe_allow_html=True)

# 사이드바 네비게이션
with st.sidebar:
    st.title("🧭 네비게이션")
    page = st.selectbox(
        "페이지 선택",
        ["메인 대시보드", "로드맵 생성/조회", "HTML 업로드/파싱", "DB → HTML 재생성", "AI 배치 검증/보완", "변경 로그/이력"]
    )
    st.markdown("---")
    chatgpt_model = st.selectbox("ChatGPT 모델명", ["gpt-3.5-turbo", "gpt-4", "gpt-4o"], index=0)
    openai_api_key = st.text_input("OpenAI API Key", type="password")
    st.session_state["chatgpt_model"] = chatgpt_model
    st.session_state["openai_api_key"] = openai_api_key

# 메인 대시보드
if page == "메인 대시보드":
    st.header("📊 메인 대시보드")
    
    # 주요 지표
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("생성된 로드맵", "24", "↗️ 3")
    with col2:
        st.metric("학습 요소", "156", "↗️ 12")
    with col3:
        st.metric("검증 완료", "89", "↗️ 8")
    
    # 빠른 실행
    st.subheader("🚀 빠른 실행")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("+ 새 로드맵 생성", type="primary"):
            st.success("로드맵 생성 페이지로 이동합니다")
    with col2:
        if st.button("🔄 배치 검증 실행"):
            st.session_state.validation_progress = 67
            st.success("배치 검증이 시작되었습니다")
    with col3:
        if st.button("🔧 AI 보완 실행"):
            st.success("AI 보완 작업이 시작되었습니다")
    
    # 최근 생성 로드맵
    st.subheader("📋 최근 생성 로드맵")
    recent_roadmaps = pd.DataFrame({
        "주제": ["React 기초학습", "Python 데이터분석", "JavaScript ES6+"],
        "생성시간": ["2시간 전", "1일 전", "3일 전"],
        "상태": ["완료", "완료", "완료"]
    })
    st.dataframe(recent_roadmaps, use_container_width=True)
    
    # 통계 차트
    st.subheader("📈 학습 통계")
    col1, col2 = st.columns(2)
    
    with col1:
        # 월별 로드맵 생성 추이
        chart_data = pd.DataFrame({
            "월": ["1월", "2월", "3월", "4월", "5월"],
            "생성 수": [5, 8, 12, 15, 24]
        })
        fig = px.line(chart_data, x="월", y="생성 수", title="월별 로드맵 생성 추이")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # 주제별 분포
        subject_data = pd.DataFrame({
            "주제": ["React", "Python", "JavaScript", "Java", "기타"],
            "개수": [8, 6, 4, 3, 3]
        })
        fig = px.pie(subject_data, values="개수", names="주제", title="주제별 로드맵 분포")
        st.plotly_chart(fig, use_container_width=True)

# 로드맵 생성/조회
elif page == "로드맵 생성/조회":
    st.header("🤖 로드맵 생성/조회")
    
    # 탭 생성
    tab1, tab2 = st.tabs(["📝 AI 로드맵 생성", "📚 생성된 로드맵 조회"])
    
    with tab1:
        st.subheader("📝 AI 로드맵 생성")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("🎯 학습 주제 입력")
            
            topic = st.text_input(
                "학습 주제를 입력하세요",
                placeholder="예: Python 프로그래밍, 머신러닝, 웹 개발, 데이터 분석 등",
                help="구체적인 주제를 입력하면 더 정확한 로드맵을 생성할 수 있습니다"
            )
            
            # 설정 상태 확인
            api_key = st.session_state.get("openai_api_key", "")
            selected_model = st.session_state.get("chatgpt_model", "gpt-3.5-turbo")
            
            if not api_key:
                st.warning("⚠️ 사이드바에서 OpenAI API 키를 먼저 입력해주세요")
            
            st.info(f"📋 선택된 모델: {selected_model}")
            
            st.markdown("---")
            st.markdown("### 💡 사용 방법")
            st.markdown("""
            1. 사이드바에서 OpenAI API 키를 입력하세요
            2. 사이드바에서 ChatGPT 모델을 선택하세요
            3. 학습하고 싶은 주제를 입력하세요
            4. '로드맵 생성' 버튼을 클릭하세요
            """)
        
        with col2:
            st.subheader("🚀 로드맵 생성")
            
            # 설정 상태 확인
            if not st.session_state.get("openai_api_key"):
                st.warning("⚠️ 사이드바에서 OpenAI API 키를 먼저 입력해주세요")
            
            st.markdown("<br>", unsafe_allow_html=True)
            generate_button = st.button("🚀 로드맵 생성", type="primary", disabled=not st.session_state.get("openai_api_key"))
        
        # 로드맵 생성
        if generate_button:
            if not api_key:
                st.error("❌ 사이드바에서 OpenAI API 키를 입력해주세요.")
            elif not topic:
                st.error("학습 주제를 입력해주세요.")
            else:
                with st.spinner("로드맵을 생성하고 있습니다... (최대 2분 소요될 수 있습니다)"):
                    try:
                        # learning_roadmap_generator.py의 함수들 import
                        import openai
                        import json
                        import html
                        from typing import Dict, List, Any
                        
                        def call_chatgpt_api(api_key: str, model: str, topic: str) -> Dict[str, Any]:
                            """ChatGPT API를 호출하여 학습 로드맵을 생성합니다."""
                            try:
                                # 진행 상황 표시
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                
                                status_text.text("API 연결 중...")
                                progress_bar.progress(25)
                                # httpx 클라이언트를 직접 설정하여 프록시 문제 해결
                                import httpx
                                
                                # 프록시 설정 없이 httpx 클라이언트 생성 (timeout 증가)
                                http_client = httpx.Client(
                                    timeout=httpx.Timeout(120.0),  # 2분으로 증가
                                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
                                )
                                
                                # OpenAI 클라이언트 생성
                                client = openai.OpenAI(
                                    api_key=api_key,
                                    http_client=http_client
                                )
                                
                                status_text.text("ChatGPT API 호출 중...")
                                progress_bar.progress(50)
                                
                                prompt = f"""
                                주제 "{topic}"에 대한 체계적인 학습 로드맵을 생성해주세요.
                                
                                다음 JSON 형식으로 응답해주세요:
                                {{
                                    "main_topic": "주제명",
                                    "prerequisites": ["사전 요구사항1", "사전 요구사항2"],
                                    "phases": [
                                        {{
                                            "title": "단계명",
                                            "duration": "예상 소요시간",
                                            "topics": [
                                                {{
                                                    "title": "세부 주제명",
                                                    "description": "세부 주제 설명",
                                                    "learning_links": [
                                                        {{
                                                            "title": "관련 학습 링크 제목",
                                                            "url": "https://example.com/learning-resource"
                                                        }}
                                                    ]
                                                }}
                                            ]
                                        }}
                                    ],
                                    "resources": ["추천 자료1", "추천 자료2"]
                                }}
                                
                                각 단계는 논리적 순서로 배치하고, 초보자부터 고급자까지 단계적으로 학습할 수 있도록 구성해주세요.
                                각 주제마다 관련된 유용한 학습 링크(온라인 강의, 문서, 튜토리얼 등)를 포함해주세요.
                                """
                                
                                response = client.chat.completions.create(
                                    model=model,
                                    messages=[
                                        {"role": "system", "content": "당신은 교육 전문가입니다. 주어진 주제에 대해 체계적이고 효과적인 학습 로드맵을 제공합니다."},
                                        {"role": "user", "content": prompt}
                                    ],
                                    max_tokens=3000,  # 토큰 수 증가
                                    temperature=0.7,
                                    timeout=120  # API 호출 timeout 설정
                                )
                                
                                status_text.text("응답 처리 중...")
                                progress_bar.progress(75)
                                
                                content = response.choices[0].message.content
                                
                                # JSON 파싱 시도
                                try:
                                    # 마크다운 코드 블록 제거
                                    if "```json" in content:
                                        content = content.split("```json")[1].split("```")[0]
                                    elif "```" in content:
                                        content = content.split("```")[1].split("```")[0]
                                    
                                    roadmap_data = json.loads(content.strip())
                                    
                                    status_text.text("로드맵 생성 완료!")
                                    progress_bar.progress(100)
                                    
                                    return roadmap_data
                                    
                                except json.JSONDecodeError:
                                    # JSON 파싱 실패 시 기본 구조 생성
                                    status_text.text("JSON 파싱 실패, 기본 구조 생성 중...")
                                    progress_bar.progress(90)
                                    
                                    return {
                                        "main_topic": topic,
                                        "prerequisites": ["기본적인 학습 의지", "꾸준한 학습 시간 확보"],
                                        "phases": [
                                            {
                                                "title": "기초 단계",
                                                "duration": "2-4주",
                                                "topics": [
                                                    {"title": "기본 개념 이해", "description": content[:200] + "..."}
                                                ]
                                            }
                                        ],
                                        "resources": ["온라인 강의", "관련 서적", "실습 자료"]
                                    }
                                    
                            except Exception as e:
                                # 진행 상황 초기화
                                progress_bar.progress(0)
                                status_text.text("오류 발생")
                                
                                st.error(f"API 호출 중 오류가 발생했습니다: {str(e)}")
                                # 오류 상세 정보 표시
                                st.error(f"오류 타입: {type(e).__name__}")
                                st.error(f"오류 메시지: {str(e)}")
                                
                                # timeout 관련 안내
                                if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                                    st.warning("⚠️ 시간 초과가 발생했습니다. 다음을 시도해보세요:")
                                    st.markdown("""
                                    - 네트워크 연결 상태를 확인하세요
                                    - 더 간단한 주제로 다시 시도해보세요
                                    - 잠시 후 다시 시도해보세요
                                    - 다른 ChatGPT 모델을 선택해보세요
                                    """)
                                
                                # 대안: 기본 로드맵 생성
                                st.warning("기본 로드맵을 생성합니다.")
                                return {
                                    "main_topic": topic,
                                    "prerequisites": ["기본적인 학습 의지", "꾸준한 학습 시간 확보"],
                                    "phases": [
                                        {
                                            "title": "기초 단계",
                                            "duration": "2-4주",
                                            "topics": [
                                                {"title": "기본 개념 이해", "description": f"{topic}의 기본 개념을 학습합니다."},
                                                {"title": "핵심 원리 파악", "description": f"{topic}의 핵심 원리를 이해합니다."}
                                            ]
                                        },
                                        {
                                            "title": "중급 단계",
                                            "duration": "4-8주",
                                            "topics": [
                                                {"title": "실습 및 적용", "description": f"{topic}을 실제로 적용해봅니다."},
                                                {"title": "문제 해결", "description": f"{topic} 관련 문제를 해결하는 방법을 학습합니다."}
                                            ]
                                        },
                                        {
                                            "title": "고급 단계",
                                            "duration": "8-12주",
                                            "topics": [
                                                {"title": "심화 학습", "description": f"{topic}의 고급 개념을 학습합니다."},
                                                {"title": "프로젝트 수행", "description": f"{topic}을 활용한 실제 프로젝트를 수행합니다."}
                                            ]
                                        }
                                    ],
                                    "resources": ["온라인 강의", "관련 서적", "실습 자료", "커뮤니티 참여"]
                                }
                            finally:
                                # httpx 클라이언트 정리
                                if 'http_client' in locals():
                                    http_client.close()
                                
                                # 진행 상황 정리
                                if 'progress_bar' in locals():
                                    progress_bar.empty()
                                if 'status_text' in locals():
                                    status_text.empty()
                        

                        
                        # 로드맵 생성
                        roadmap_data = call_chatgpt_api(api_key, selected_model, topic)
                        
                        if roadmap_data:
                            st.success("로드맵이 성공적으로 생성되었습니다!")
                            
                            # 마인드맵 HTML 생성
                            mindmap_html = generate_mindmap_html(roadmap_data)
                            
                            # HTML 표시
                            st.components.v1.html(mindmap_html, height=800, scrolling=True)
                            
                            # 다운로드 버튼
                            st.download_button(
                                label="📥 HTML 파일 다운로드",
                                data=mindmap_html,
                                file_name=f"{topic}_roadmap.html",
                                mime="text/html",
                                key=f"download_ai_generated_{topic}"
                            )
                            
                            # 원본 데이터 표시 (선택사항)
                            with st.expander("📄 원본 데이터 보기"):
                                st.json(roadmap_data)
                            
                            # 세션에 저장
                            new_roadmap = {
                                "주제": topic,
                                "난이도": "AI 생성",
                                "중점분야": "AI 기반",
                                "생성시간": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "데이터": roadmap_data
                            }
                            st.session_state.roadmaps.append(new_roadmap)
                            
                    except Exception as e:
                        st.error(f"로드맵 생성 중 오류가 발생했습니다: {str(e)}")
    
    with tab2:
        st.subheader("📚 생성된 로드맵 조회")
        
        if st.session_state.roadmaps:
            # 로드맵 목록 표시
            roadmaps_df = pd.DataFrame([
                {
                    "주제": roadmap["주제"],
                    "난이도": roadmap["난이도"],
                    "중점분야": roadmap["중점분야"],
                    "생성시간": roadmap["생성시간"]
                }
                for roadmap in st.session_state.roadmaps
            ])
            st.dataframe(roadmaps_df, use_container_width=True)
            
            # 상세 조회
            if st.session_state.roadmaps:
                st.subheader("🔍 상세 조회")
                selected_roadmap_idx = st.selectbox(
                    "조회할 로드맵 선택:",
                    options=range(len(st.session_state.roadmaps)),
                    format_func=lambda x: f"{st.session_state.roadmaps[x]['주제']} ({st.session_state.roadmaps[x]['생성시간']})"
                )
                
                if selected_roadmap_idx is not None:
                    selected_roadmap = st.session_state.roadmaps[selected_roadmap_idx]
                    
                    col_info1, col_info2, col_info3 = st.columns(3)
                    with col_info1:
                        st.metric("주제", selected_roadmap["주제"])
                    with col_info2:
                        st.metric("난이도", selected_roadmap["난이도"])
                    with col_info3:
                        st.metric("생성시간", selected_roadmap["생성시간"])
                    
                    # 로드맵 데이터가 있으면 재생성
                    if "데이터" in selected_roadmap:
                        st.subheader("🗺️ 로드맵 미리보기")
                        roadmap_data = selected_roadmap["데이터"]
                        
                        # 마인드맵 HTML 재생성
                        mindmap_html = generate_mindmap_html(roadmap_data)
                        st.components.v1.html(mindmap_html, height=600, scrolling=True)
                        
                        # 다운로드 버튼
                        st.download_button(
                            label="📥 HTML 파일 다운로드",
                            data=mindmap_html,
                            file_name=f"{selected_roadmap['주제']}_roadmap.html",
                            mime="text/html",
                            key=f"download_viewed_{selected_roadmap['주제']}"
                        )
        else:
            st.info("생성된 로드맵이 없습니다. AI 로드맵 생성 탭에서 로드맵을 생성해보세요.")

# HTML 업로드/파싱
elif page == "HTML 업로드/파싱":
    st.header("📤 HTML 업로드/파싱")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📁 파일 업로드")
        
        # Qdrant DB 초기화 버튼
        col_init1, col_init2 = st.columns(2)
        with col_init1:
            if st.button("🗄️ Qdrant Collection 초기화", type="secondary"):
                try:
                    from react_roadmap_parser import QdrantRoadmapStore
                    from db_validation_logger import DatabaseValidationLogger
                    
                    validation_logger = DatabaseValidationLogger("validation_logs.db")
                    store = QdrantRoadmapStore(validation_logger=validation_logger)
                    store.initialize_collection(force_recreate=True)
                    st.success("Qdrant Collection이 성공적으로 초기화되었습니다!")
                except ImportError:
                    st.error("Qdrant 모듈을 찾을 수 없습니다.")
                except Exception as e:
                    st.error(f"초기화 중 오류 발생: {str(e)}")
        
        with col_init2:
            if st.button("📊 Collection 상태 확인", type="secondary"):
                try:
                    from react_roadmap_parser import QdrantRoadmapStore
                    from db_validation_logger import DatabaseValidationLogger
                    
                    validation_logger = DatabaseValidationLogger("validation_logs.db")
                    store = QdrantRoadmapStore(validation_logger=validation_logger)
                    
                    # Collection 정보 확인
                    collection_info = store.get_collection_info()
                    if collection_info:
                        st.success(f"✅ Collection 상태: 활성화")
                        col_info1, col_info2, col_info3 = st.columns(3)
                        with col_info1:
                            st.metric("포인트 수", collection_info.get('points_count', 'N/A'))
                        with col_info2:
                            st.metric("벡터 수", collection_info.get('vectors_count', 'N/A'))
                        with col_info3:
                            st.metric("벡터 크기", collection_info.get('config', {}).get('vector_size', 'N/A'))
                    else:
                        st.warning("⚠️ Collection이 초기화되지 않았습니다.")
                except ImportError:
                    st.error("Qdrant 모듈을 찾을 수 없습니다.")
                except Exception as e:
                    st.error(f"상태 확인 중 오류 발생: {str(e)}")
        
        uploaded_file = st.file_uploader(
            "HTML 파일을 업로드하세요",
            type=['html', 'htm'],
            help="HTML 마인드맵 파일을 업로드하여 파싱합니다"
        )
        
        # 추가 태그 입력란
        custom_tags_input = st.text_input(
            "추가 태그 입력 (콤마로 구분)",
            value="",
            help="예: project:myproj, version:1.0, customtag"
        )
        
        parsing_status = st.empty()
        nodes = None
        error_msg = None
        if uploaded_file is not None:
            # 파일 내용 읽기
            html_content = uploaded_file.read().decode('utf-8')
            filename = uploaded_file.name
            st.success(f"파일 '{filename}'이 업로드되었습니다!")
            
            # 파일 정보 표시
            st.info(f"파일 크기: {len(html_content)} bytes")
            
            # 파일명 리스트에 추가(중복 방지)
            if filename not in st.session_state.uploaded_filenames:
                st.session_state.uploaded_filenames.append(filename)

            # 파싱 및 Qdrant 적재 버튼
            if st.button("🔍 파싱 및 Qdrant 적재"):
                with st.spinner("파싱 및 Qdrant 적재 중..."):
                    try:
                        # 새로운 파싱 로직 사용
                        roadmap_id = f"roadmap_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        
                        # 메타데이터 추출
                        metadata = extract_roadmap_metadata(html_content)
                        title = metadata.get("title", filename)
                        
                        # 섹션별 청크 생성
                        st.info("🔍 HTML 파싱 시작...")
                        
                        # HTML 기본 정보 표시
                        st.write(f"**HTML 크기:** {len(html_content)} bytes")
                        
                        # HTML 구조 미리보기
                        soup = BeautifulSoup(html_content, 'html.parser')
                        title_elem = soup.find(['h1', 'title'])
                        if title_elem:
                            st.write(f"**제목:** {title_elem.get_text().strip()}")
                        
                        chunks = parse_html_sections(html_content, roadmap_id)
                        
                        st.write(f"**파싱 결과:** {len(chunks)}개 청크 생성됨")
                        
                        if not chunks:
                            st.warning("⚠️ 파싱된 청크가 없습니다. HTML 구조를 확인해주세요.")
                            st.write("**HTML 구조 분석:**")
                            
                            # HTML 구조 디버깅
                            soup = BeautifulSoup(html_content, 'html.parser')
                            
                            # 주요 태그 찾기
                            st.write("**발견된 주요 태그:**")
                            main_tags = soup.find_all(['div', 'section', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            tag_info = []
                            for tag in main_tags[:10]:  # 상위 10개만
                                classes = ' '.join(tag.get('class', []))
                                tag_info.append({
                                    "태그": tag.name,
                                    "클래스": classes,
                                    "텍스트": tag.get_text().strip()[:50] + "..." if len(tag.get_text().strip()) > 50 else tag.get_text().strip()
                                })
                            st.dataframe(pd.DataFrame(tag_info), use_container_width=True)
                            
                            # 클래스별 분포
                            all_classes = []
                            for tag in soup.find_all():
                                all_classes.extend(tag.get('class', []))
                            
                            class_counts = {}
                            for cls in all_classes:
                                class_counts[cls] = class_counts.get(cls, 0) + 1
                            
                            if class_counts:
                                st.write("**클래스별 분포 (상위 10개):**")
                                sorted_classes = sorted(class_counts.items(), key=lambda x: x[1], reverse=True)[:10]
                                for cls, count in sorted_classes:
                                    st.write(f"• {cls}: {count}회")
                        else:
                            # 파일명 태그를 모든 청크에 추가
                            for chunk in chunks:
                                chunk.collection_tags.append(f"filename:{filename}")
                                chunk.collection_tags.append(f"source:{filename}")
                                chunk.search_tags.append(f"filename:{filename}")
                                chunk.search_tags.append(f"source:{filename}")
                                # 커스텀 태그도 추가
                                if custom_tags_input.strip():
                                    custom_tags = [t.strip() for t in custom_tags_input.split(",") if t.strip()]
                                    chunk.collection_tags.extend(custom_tags)
                                    chunk.search_tags.extend(custom_tags)
                            
                            # RoadmapDocument 생성
                            document = RoadmapDocument(
                                id=roadmap_id,
                                title=title,
                                original_html=html_content,
                                chunks=chunks,
                                metadata=metadata
                            )
                            
                            # 세션에 저장
                            st.session_state.roadmap_documents[roadmap_id] = document
                            
                            parsing_status.success(f"✅ 파싱 결과: 성공! (청크 수: {len(chunks)})")
                            
                            # 파싱 통계
                            st.write("**📊 파싱 통계:**")
                            type_counts = {}
                            category_counts = {}
                            for chunk in chunks:
                                chunk_type = chunk.metadata.get("type", "unknown")
                                type_counts[chunk_type] = type_counts.get(chunk_type, 0) + 1
                                
                                category = chunk.metadata.get("category", "unknown")
                                category_counts[category] = category_counts.get(category, 0) + 1
                            
                            col_stat1, col_stat2 = st.columns(2)
                            with col_stat1:
                                st.write("**타입별 분포:**")
                                for chunk_type, count in type_counts.items():
                                    st.write(f"• {chunk_type}: {count}개")
                            
                            with col_stat2:
                                st.write("**카테고리별 분포:**")
                                for category, count in category_counts.items():
                                    st.write(f"• {category}: {count}개")
                            
                            # 미리보기
                            st.write("**파싱된 청크 일부 미리보기:**")
                            preview_data = []
                            for chunk in chunks[:5]:  # 상위 5개만 표시
                                preview_data.append({
                                    "ID": chunk.id,
                                    "섹션": chunk.metadata.get("section", "N/A"),
                                    "타입": chunk.metadata.get("type", "N/A"),
                                    "레벨": chunk.metadata.get("level", "N/A"),
                                    "카테고리": chunk.metadata.get("category", "N/A"),
                                    "키워드": ", ".join(chunk.metadata.get("keywords", [])[:3]),
                                    "도구": ", ".join(chunk.metadata.get("tools", [])[:2]),
                                    "수집 태그": ", ".join(chunk.collection_tags[:3]),
                                    "검색 태그": ", ".join(chunk.search_tags[:3]),
                                    "내용 길이": len(chunk.content),
                                    "내용 미리보기": chunk.content[:100] + "..." if len(chunk.content) > 100 else chunk.content
                                })
                            st.dataframe(pd.DataFrame(preview_data), use_container_width=True)
                            
                            # 상세 미리보기 (첫 번째 청크)
                            if chunks:
                                st.write("**첫 번째 청크 상세 내용:**")
                                first_chunk = chunks[0]
                                st.json({
                                    "id": first_chunk.id,
                                    "roadmap_id": first_chunk.roadmap_id,
                                    "metadata": {
                                        "section": first_chunk.metadata.get("section", "N/A"),
                                        "type": first_chunk.metadata.get("type", "N/A"),
                                        "level": first_chunk.metadata.get("level", "N/A"),
                                        "category": first_chunk.metadata.get("category", "N/A"),
                                        "keywords": first_chunk.metadata.get("keywords", []),
                                        "tools": first_chunk.metadata.get("tools", []),
                                        "resources": first_chunk.metadata.get("resources", []),
                                        "learning_objectives": first_chunk.metadata.get("learning_objectives", [])
                                    },
                                    "collection_tags": first_chunk.collection_tags,
                                    "search_tags": first_chunk.search_tags,
                                    "content_preview": first_chunk.content[:200] + "..." if len(first_chunk.content) > 200 else first_chunk.content
                                })
                            
                            # 태그 관리 섹션
                            st.write("---")
                            st.subheader("🏷️ 태그 관리")
                            
                            # 태그 통계
                            tag_stats = get_tag_statistics(chunks)
                            if tag_stats:
                                st.write("**📊 현재 태그 통계:**")
                                col_tag1, col_tag2 = st.columns(2)
                                
                                with col_tag1:
                                    st.write("**📦 수집 태그 (상위 10개):**")
                                    collection_sorted = sorted(tag_stats["collection_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
                                    for tag, count in collection_sorted:
                                        st.write(f"• {tag}: {count}회")
                                
                                with col_tag2:
                                    st.write("**🔍 검색 태그 (상위 10개):**")
                                    search_sorted = sorted(tag_stats["search_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
                                    for tag, count in search_sorted:
                                        st.write(f"• {tag}: {count}회")
                            
                            # 개별 청크 태그 편집
                            st.write("**✏️ 청크별 태그 편집:**")
                            
                            # 청크 선택
                            chunk_options = {f"{i+1}. {chunk.metadata.get('section', 'N/A')}": i for i, chunk in enumerate(chunks[:10])}
                            selected_chunk_key = st.selectbox("편집할 청크 선택:", list(chunk_options.keys()))
                            
                            if selected_chunk_key:
                                selected_chunk_idx = chunk_options[selected_chunk_key]
                                selected_chunk = chunks[selected_chunk_idx]
                                
                                # 현재 태그 표시
                                col_current1, col_current2 = st.columns(2)
                                with col_current1:
                                    st.write(f"**📦 수집 태그:** {', '.join(selected_chunk.collection_tags) if selected_chunk.collection_tags else '없음'}")
                                with col_current2:
                                    st.write(f"**🔍 검색 태그:** {', '.join(selected_chunk.search_tags) if selected_chunk.search_tags else '없음'}")
                                
                                # 태그 제안
                                suggested_tags = suggest_tags_for_chunk(selected_chunk.content, selected_chunk.metadata)
                                if suggested_tags["collection_tags"] or suggested_tags["search_tags"]:
                                    col_suggest1, col_suggest2 = st.columns(2)
                                    with col_suggest1:
                                        if suggested_tags["collection_tags"]:
                                            st.write(f"**📦 제안 수집 태그:** {', '.join(suggested_tags['collection_tags'])}")
                                    with col_suggest2:
                                        if suggested_tags["search_tags"]:
                                            st.write(f"**🔍 제안 검색 태그:** {', '.join(suggested_tags['search_tags'])}")
                                
                                # 커스텀 태그 입력
                                col_input1, col_input2 = st.columns(2)
                                with col_input1:
                                    collection_tags_input = st.text_input(
                                        "추가할 수집 태그 (콤마로 구분):",
                                        value="",
                                        help="예: web-development, beginner, type-level"
                                    )
                                with col_input2:
                                    search_tags_input = st.text_input(
                                        "추가할 검색 태그 (콤마로 구분):",
                                        value="",
                                        help="예: react, javascript, frontend"
                                    )
                                
                                # 태그 적용 버튼
                                if st.button("🏷️ 태그 적용", key="apply_tags"):
                                    new_collection_tags = []
                                    new_search_tags = []
                                    
                                    if collection_tags_input.strip():
                                        new_collection_tags = [tag.strip().lower() for tag in collection_tags_input.split(",") if tag.strip()]
                                    
                                    if search_tags_input.strip():
                                        new_search_tags = [tag.strip().lower() for tag in search_tags_input.split(",") if tag.strip()]
                                    
                                    if new_collection_tags or new_search_tags:
                                        # 청크 업데이트
                                        updated_chunk = apply_tags_to_chunk(selected_chunk, new_collection_tags, new_search_tags)
                                        chunks[selected_chunk_idx] = updated_chunk
                                        
                                        # 문서 업데이트
                                        document.chunks = chunks
                                        st.session_state.roadmap_documents[roadmap_id] = document
                                        
                                        st.success(f"✅ 태그가 적용되었습니다! (수집: {len(new_collection_tags)}개, 검색: {len(new_search_tags)}개)")
                                        
                                        # 업데이트된 태그 표시
                                        col_updated1, col_updated2 = st.columns(2)
                                        with col_updated1:
                                            st.write(f"**📦 업데이트된 수집 태그:** {', '.join(updated_chunk.collection_tags)}")
                                        with col_updated2:
                                            st.write(f"**🔍 업데이트된 검색 태그:** {', '.join(updated_chunk.search_tags)}")
                            
                            # 일괄 태그 적용
                            st.write("**📦 일괄 태그 적용:**")
                            col_bulk1, col_bulk2 = st.columns(2)
                            with col_bulk1:
                                bulk_collection_tags = st.text_input(
                                    "모든 청크에 적용할 수집 태그 (콤마로 구분):",
                                    value="",
                                    help="예: roadmap, learning"
                                )
                            with col_bulk2:
                                bulk_search_tags = st.text_input(
                                    "모든 청크에 적용할 검색 태그 (콤마로 구분):",
                                    value="",
                                    help="예: tutorial, guide"
                                )
                            
                            if st.button("📦 일괄 태그 적용", key="apply_bulk_tags"):
                                new_collection_tags = []
                                new_search_tags = []
                                
                                if bulk_collection_tags.strip():
                                    new_collection_tags = [tag.strip().lower() for tag in bulk_collection_tags.split(",") if tag.strip()]
                                
                                if bulk_search_tags.strip():
                                    new_search_tags = [tag.strip().lower() for tag in bulk_search_tags.split(",") if tag.strip()]
                                
                                if new_collection_tags or new_search_tags:
                                    # 모든 청크에 태그 적용
                                    updated_chunks = []
                                    for chunk in chunks:
                                        updated_chunk = apply_tags_to_chunk(chunk, new_collection_tags, new_search_tags)
                                        updated_chunks.append(updated_chunk)
                                    
                                    # 문서 업데이트
                                    document.chunks = updated_chunks
                                    st.session_state.roadmap_documents[roadmap_id] = document
                                    
                                    st.success(f"✅ 일괄 태그가 적용되었습니다! ({len(chunks)}개 청크)")
                            
                            # 태그 기반 검색
                            st.write("**🔍 태그 기반 검색:**")
                            col_search1, col_search2 = st.columns(2)
                            with col_search1:
                                search_collection_tags = st.text_input(
                                    "검색할 수집 태그 (콤마로 구분):",
                                    value="",
                                    help="예: beginner, web-development"
                                )
                            with col_search2:
                                search_search_tags = st.text_input(
                                    "검색할 검색 태그 (콤마로 구분):",
                                    value="",
                                    help="예: react, javascript"
                                )
                            
                            if st.button("🔍 태그 검색", key="search_by_tags"):
                                matched_chunks = chunks
                                
                                # 수집 태그 검색
                                if search_collection_tags.strip():
                                    collection_search_tags = [tag.strip().lower() for tag in search_collection_tags.split(",") if tag.strip()]
                                    matched_chunks = search_chunks_by_tags(matched_chunks, collection_search_tags, "collection")
                                
                                # 검색 태그 검색
                                if search_search_tags.strip():
                                    search_search_tag_list = [tag.strip().lower() for tag in search_search_tags.split(",") if tag.strip()]
                                    matched_chunks = search_chunks_by_tags(matched_chunks, search_search_tag_list, "search")
                                
                                st.write(f"**검색 결과:** {len(matched_chunks)}개 청크 발견")
                                
                                if matched_chunks:
                                    search_results = []
                                    for i, chunk in enumerate(matched_chunks[:5]):
                                        search_results.append({
                                            "순서": i + 1,
                                            "섹션": chunk.metadata.get("section", "N/A"),
                                            "타입": chunk.metadata.get("type", "N/A"),
                                            "수집 태그": ", ".join(chunk.collection_tags[:3]),
                                            "검색 태그": ", ".join(chunk.search_tags[:3]),
                                            "내용 미리보기": chunk.content[:100] + "..." if len(chunk.content) > 100 else chunk.content
                                        })
                                    st.dataframe(pd.DataFrame(search_results), use_container_width=True)
                                else:
                                    st.info("검색 조건에 맞는 청크가 없습니다.")
                        
                                                # 기존 파싱 로직도 유지 (호환성)
                        try:
                            from react_roadmap_parser import ReactRoadmapParser, QdrantRoadmapStore
                            from db_validation_logger import DatabaseValidationLogger
                            validation_logger = DatabaseValidationLogger("validation_logs.db")
                            parser = ReactRoadmapParser(html_content, validation_logger)
                            nodes = parser.parse()
                            
                            # 파일명 태깅
                            for n in nodes:
                                if hasattr(n, 'tags') and isinstance(n.tags, list):
                                    n.tags.append(f"source:{filename}")
                                    n.tags.append(f"filename:{filename}")
                                if hasattr(n, 'links') and isinstance(n.links, list):
                                    for link in n.links:
                                        if isinstance(link, dict):
                                            link['source'] = filename
                            
                            # Qdrant 적재
                            store = QdrantRoadmapStore(validation_logger=validation_logger)
                            store.initialize_collection(force_recreate=False)
                            store.store_nodes(nodes)
                            st.success("Qdrant DB에 적재 완료!")
                            
                            # 디비 적재된 데이터 미리보기
                            st.write("**📊 Qdrant DB 적재된 데이터 미리보기:**")
                            
                            # Collection 정보 확인
                            collection_info = store.get_collection_info()
                            if collection_info:
                                col_db1, col_db2, col_db3 = st.columns(3)
                                with col_db1:
                                    st.metric("저장된 포인트", collection_info.get('points_count', 0))
                                with col_db2:
                                    st.metric("벡터 수", collection_info.get('vectors_count', 0))
                                with col_db3:
                                    st.metric("Collection 상태", "활성화")
                            
                            # 저장된 노드 샘플 조회
                            try:
                                # 카테고리별 노드 수 조회
                                categories = ['beginner', 'intermediate', 'advanced', 'community']
                                category_counts = {}
                                for category in categories:
                                    category_nodes = store.get_nodes_by_category(category)
                                    category_counts[category] = len(category_nodes)
                                
                                st.write("**📈 카테고리별 노드 분포:**")
                                category_df = pd.DataFrame([
                                    {"카테고리": cat, "노드 수": count}
                                    for cat, count in category_counts.items()
                                ])
                                st.dataframe(category_df, use_container_width=True)
                                
                                # 최근 저장된 노드 샘플 조회
                                st.write("**🔍 저장된 노드 샘플:**")
                                sample_nodes = []
                                for category in categories:
                                    nodes = store.get_nodes_by_category(category)
                                    if nodes:
                                        sample_nodes.extend(nodes[:2])  # 카테고리당 2개씩
                                        if len(sample_nodes) >= 6:  # 최대 6개
                                            break
                                
                                if sample_nodes:
                                    node_preview_data = []
                                    for i, node_data in enumerate(sample_nodes[:6]):
                                        node_preview_data.append({
                                            "순서": i + 1,
                                            "제목": node_data.get('title', 'N/A')[:30] + "..." if len(node_data.get('title', '')) > 30 else node_data.get('title', 'N/A'),
                                            "카테고리": node_data.get('category', 'N/A'),
                                            "타입": node_data.get('node_type', 'N/A'),
                                            "태그 수": len(node_data.get('tags', [])),
                                            "링크 수": len(node_data.get('links', []))
                                        })
                                    st.dataframe(pd.DataFrame(node_preview_data), use_container_width=True)
                                    
                                    # 첫 번째 노드 상세 정보
                                    if sample_nodes:
                                        st.write("**📋 첫 번째 노드 상세 정보:**")
                                        first_node = sample_nodes[0]
                                        st.json({
                                            "id": first_node.get('id', 'N/A'),
                                            "title": first_node.get('title', 'N/A'),
                                            "category": first_node.get('category', 'N/A'),
                                            "node_type": first_node.get('node_type', 'N/A'),
                                            "depth": first_node.get('depth', 'N/A'),
                                            "tags": first_node.get('tags', []),
                                            "links": first_node.get('links', [])
                                        })
                                else:
                                    st.info("저장된 노드가 없습니다.")
                                    
                            except Exception as e:
                                st.warning(f"데이터 미리보기 중 오류: {str(e)}")
                                
                        except ImportError:
                            st.warning("기존 파싱 모듈을 찾을 수 없어 새로운 파싱 방식만 사용합니다.")
                        
                    except Exception as e:
                        error_msg = str(e)
                        parsing_status.error(f"파싱 결과: 실패 - {error_msg}")
        else:
            parsing_status.info("HTML 파일을 업로드하고 파싱해주세요")
    
    with col2:
        st.subheader("🔍 파싱 결과")
        
        if parsing_status.empty():
            st.info("HTML 파일을 업로드하고 파싱해주세요")
        elif parsing_status.success:
            # 파싱 통계
            if st.session_state.roadmap_documents:
                latest_doc = list(st.session_state.roadmap_documents.values())[-1]
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.metric("청크 수", len(latest_doc.chunks))
                with col_b:
                    st.metric("키워드 수", len(latest_doc.metadata.get("tags", [])))
                with col_c:
                    st.metric("문서 제목", latest_doc.title[:20] + "..." if len(latest_doc.title) > 20 else latest_doc.title)
                
                # 발견된 키워드들
                st.write("**발견된 키워드:**")
                tags = latest_doc.metadata.get("tags", [])
                if tags:
                    tag_cols = st.columns(3)
                    for i, tag in enumerate(tags[:9]):  # 상위 9개만
                        col_idx = i % 3
                        tag_cols[col_idx].write(f"• {tag}")
                
                # 구조 정보
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.write(f"**난이도:** {latest_doc.metadata.get('difficulty', 'unknown')}")
                with col_info2:
                    st.write(f"**카테고리:** {latest_doc.metadata.get('category', 'programming')}")
                
                # 청크별 상세 정보
                st.write("**청크별 상세 정보:**")
                chunk_details = []
                for i, chunk in enumerate(latest_doc.chunks[:10]):  # 상위 10개만
                    chunk_details.append({
                        "순서": i + 1,
                        "ID": chunk.id,
                        "섹션": chunk.metadata.get("section", "N/A"),
                        "타입": chunk.metadata.get("type", "N/A"),
                        "레벨": chunk.metadata.get("level", "N/A"),
                        "카테고리": chunk.metadata.get("category", "N/A"),
                        "키워드 수": len(chunk.metadata.get("keywords", [])),
                        "도구 수": len(chunk.metadata.get("tools", [])),
                        "리소스 수": len(chunk.metadata.get("resources", [])),
                        "학습목표 수": len(chunk.metadata.get("learning_objectives", [])),
                        "수집 태그": ", ".join(chunk.collection_tags[:3]),
                        "검색 태그": ", ".join(chunk.search_tags[:3]),
                        "내용 길이": len(chunk.content),
                        "HTML 길이": len(chunk.html_fragment)
                    })
                st.dataframe(pd.DataFrame(chunk_details), use_container_width=True)
                
                # 태그 통계
                tag_stats = get_tag_statistics(latest_doc.chunks)
                if tag_stats:
                    st.write("**🏷️ 태그 통계:**")
                    col_tag_stat1, col_tag_stat2 = st.columns(2)
                    
                    with col_tag_stat1:
                        st.write("**📦 수집 태그 (상위 10개):**")
                        collection_sorted = sorted(tag_stats["collection_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
                        for tag, count in collection_sorted:
                            st.write(f"• {tag}: {count}회")
                    
                    with col_tag_stat2:
                        st.write("**🔍 검색 태그 (상위 10개):**")
                        search_sorted = sorted(tag_stats["search_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
                        for tag, count in search_sorted:
                            st.write(f"• {tag}: {count}회")
                
                # 구조화된 정보 요약
                st.write("**🏗️ 구조화된 정보 요약:**")
                col_sum1, col_sum2 = st.columns(2)
                
                with col_sum1:
                    # 타입별 분포
                    type_counts = {}
                    for chunk in latest_doc.chunks:
                        chunk_type = chunk.metadata.get("type", "unknown")
                        type_counts[chunk_type] = type_counts.get(chunk_type, 0) + 1
                    
                    st.write("**타입별 분포:**")
                    for chunk_type, count in type_counts.items():
                        st.write(f"• {chunk_type}: {count}개")
                    
                    # 도구별 분포
                    all_tools = []
                    for chunk in latest_doc.chunks:
                        all_tools.extend(chunk.metadata.get("tools", []))
                    
                    tool_counts = {}
                    for tool in all_tools:
                        tool_counts[tool] = tool_counts.get(tool, 0) + 1
                    
                    if tool_counts:
                        st.write("**🔧 발견된 도구:**")
                        for tool, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                            st.write(f"• {tool}: {count}회")
                
                with col_sum2:
                    # 리소스별 분포
                    all_resources = []
                    for chunk in latest_doc.chunks:
                        all_resources.extend(chunk.metadata.get("resources", []))
                    
                    resource_types = {}
                    for resource in all_resources:
                        resource_type = resource.get("type", "unknown")
                        resource_types[resource_type] = resource_types.get(resource_type, 0) + 1
                    
                    if resource_types:
                        st.write("**📚 리소스 타입별 분포:**")
                        for res_type, count in sorted(resource_types.items(), key=lambda x: x[1], reverse=True):
                            st.write(f"• {res_type}: {count}개")
                    
                    # 학습 목표 요약
                    all_objectives = []
                    for chunk in latest_doc.chunks:
                        all_objectives.extend(chunk.metadata.get("learning_objectives", []))
                    
                    if all_objectives:
                        st.write("**🎯 학습 목표 (일부):**")
                        for obj in all_objectives[:3]:
                            st.write(f"• {obj[:50]}{'...' if len(obj) > 50 else ''}")
                
                # 저장 버튼
                if st.button("💾 Qdrant 저장", key="save_parsed"):
                    st.success("파싱된 데이터가 벡터 데이터베이스에 저장되었습니다!")
            elif parsing_status.data:
                # 기존 방식 호환성
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("노드 수", parsing_status.data["nodes"])
                with col_b:
                    st.metric("링크 수", parsing_status.data["links"])
                
                # 발견된 주제들
                st.write("**발견된 주제:**")
                for topic in parsing_status.data["topics"]:
                    st.write(f"• {topic}")
                
                # 구조 정보
                st.write(f"**구조 유형:** {parsing_status.data['structure']}")
                
                # 저장 버튼
                if st.button("💾 Qdrant 저장", key="save_parsed_old"):
                    st.success("파싱된 데이터가 벡터 데이터베이스에 저장되었습니다!")
        elif parsing_status.error:
            st.error(f"파싱 결과: 실패 - {parsing_status.data}")

# DB → HTML 재생성
elif page == "DB → HTML 재생성":
    st.header("🔄 DB → HTML 재생성")
    
    # 업로드된 파일명 리스트 표시
    if st.session_state.get('uploaded_filenames'):
        st.info("업로드된 파일명: " + ", ".join(st.session_state.uploaded_filenames))
    
    # 저장된 문서 목록 표시
    if st.session_state.roadmap_documents:
        st.subheader("📚 저장된 문서 목록")
        doc_list = []
        for doc_id, doc in st.session_state.roadmap_documents.items():
            doc_list.append({
                "ID": doc_id,
                "제목": doc.title,
                "청크 수": len(doc.chunks),
                "태그": ", ".join(doc.metadata.get("tags", [])[:3]),
                "난이도": doc.metadata.get("difficulty", "unknown")
            })
        st.dataframe(pd.DataFrame(doc_list))
    
    # 검색 및 재생성 폼
    with st.form("search_form"):
        col1, col2 = st.columns(2)
        with col1:
            # 파일명 선택 드롭다운 추가
            if st.session_state.get('uploaded_filenames'):
                st.write("**📁 업로드된 파일명으로 검색:**")
                selected_filename = st.selectbox(
                    "파일명 선택:",
                    options=["직접 입력"] + st.session_state.uploaded_filenames,
                    help="파일명을 선택하면 자동으로 검색어가 입력됩니다"
                )
                
                if selected_filename != "직접 입력":
                    # 선택된 파일명으로 검색어 자동 설정
                    search_query = f"filename:{selected_filename}"
                    subject = st.text_input("주제 검색", value=search_query, placeholder="검색할 주제를 입력하세요")
                else:
                    subject = st.text_input("주제 검색", placeholder="검색할 주제를 입력하세요 (예: filename:react_roadmap.html)")
            else:
                subject = st.text_input("주제 검색", placeholder="검색할 주제를 입력하세요 (예: filename:react_roadmap.html)")
            
            level = st.selectbox("난이도 필터", ["all", "beginner", "intermediate", "advanced", "community"])
        with col2:
            focus_areas = st.text_input("중점분야 (콤마로 구분)", value="")
            output_format = st.selectbox("출력 형식", ["html", "json", "markdown"], index=0)
        
        similarity_threshold = st.slider("유사도 임계값", 0.0, 1.0, 0.1, 0.1)
        
        # 파일명 검색 도움말
        st.info("💡 **파일명으로 검색하려면:** `filename:파일명.html` 또는 `source:파일명.html` 형식으로 입력하세요")
        
        regenerate = st.form_submit_button("🔄 HTML 재생성", type="primary")
    
    # 폼 밖에서 결과 처리 및 다운로드 버튼 표시
    if regenerate:
        with st.spinner("로드맵 생성 중..."):
            if st.session_state.roadmap_documents:
                # 새로운 검색 기반 재생성
                query = subject or "React"
                # 기존: generated_html = search_and_generate_html(query, st.session_state.roadmap_documents, similarity_threshold)
                # 1. 청크 검색
                matched_chunks = []
                for doc in st.session_state.roadmap_documents.values():
                    for chunk in doc.chunks:
                        # 파일명/태그/텍스트 검색
                        if query.lower() in chunk.content.lower() or any(query.lower() in tag.lower() for tag in chunk.collection_tags + chunk.search_tags):
                            matched_chunks.append(chunk)
                if not matched_chunks:
                    st.warning("검색 결과가 없습니다.")
                    
                # 2. 계층적 구조로 변환
                roadmap_data = convert_chunks_to_roadmap_data(matched_chunks, main_topic=query)
                # 3. 마인드맵 HTML 생성
                generated_html = generate_mindmap_html(roadmap_data)
                # 결과를 세션 상태에 저장
                st.session_state.generated_result = {
                    "query": query,
                    "html_content": generated_html,
                    "output_format": output_format,
                    "generated_at": datetime.now().isoformat()
                }
                st.success(f"로드맵 생성 완료! 검색어: '{query}'")
                if output_format == "html":
                    st.components.v1.html(generated_html, height=600, scrolling=True)
                elif output_format == "json":
                    st.json(roadmap_data)
                elif output_format == "markdown":
                    markdown_content = f"# {query} 학습 로드맵\n\n" + str(roadmap_data)
                    st.code(markdown_content, language="markdown")
            else:
                # 기존 방식 호환성
                try:
                    from roadmap_generator import RoadmapGenerator, RoadmapGenerationRequest
                    from react_roadmap_parser import QdrantRoadmapStore
                    
                    store = QdrantRoadmapStore()
                    generator = RoadmapGenerator(store)
                    request = RoadmapGenerationRequest(
                        subject=subject or "React",
                        level=level,
                        focus_areas=[x.strip() for x in focus_areas.split(",") if x.strip()],
                        output_format=output_format,
                        save_to_file=False
                    )
                    result = generator.generate_roadmap(request)
                    st.success(f"로드맵 생성 완료! 노드 수: {result['metadata'].get('node_count', 0)}")
                    
                    if output_format == "html":
                        st.components.v1.html(result["content"], height=600, scrolling=True)
                    elif output_format == "json":
                        st.json(result["content"])
                    elif output_format == "markdown":
                        st.code(result["content"], language="markdown")
                except ImportError:
                    st.error("로드맵 생성 모듈을 찾을 수 없습니다.")
    
    # 다운로드 버튼들 (폼 밖에서 표시)
    if hasattr(st.session_state, 'generated_result'):
        result = st.session_state.generated_result
        query = result["query"]
        html_content = result["html_content"]
        output_format = result["output_format"]
        
        st.subheader("📥 다운로드")
        
        if output_format == "html":
            st.download_button(
                "⬇️ HTML 다운로드", 
                data=html_content, 
                file_name=f"{query}_roadmap.html", 
                key=f"download_search_html_{query}"
            )
        elif output_format == "json":
            result_data = {
                "query": query,
                "generated_at": result["generated_at"],
                "html_content": html_content,
                "source_documents": list(st.session_state.roadmap_documents.keys()) if st.session_state.roadmap_documents else []
            }
            st.download_button(
                "⬇️ JSON 다운로드", 
                data=json.dumps(result_data, indent=2), 
                file_name=f"{query}_roadmap.json", 
                key=f"download_search_json_{query}"
            )
        elif output_format == "markdown":
            markdown_content = f"# {query} 학습 로드맵\n\n"
            markdown_content += f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            markdown_content += "## 검색 결과 기반 학습 경로\n\n"
            markdown_content += "이 로드맵은 검색어 기반으로 관련 콘텐츠를 재구성한 것입니다.\n\n"
            
            st.download_button(
                "⬇️ Markdown 다운로드", 
                data=markdown_content, 
                file_name=f"{query}_roadmap.md", 
                key=f"download_search_md_{query}"
            )

# AI 배치 검증/보완
elif page == "AI 배치 검증/보완":
    st.header("⚡ AI 배치 검증/보완")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("🔍 배치 실행")
        chatgpt_model = st.session_state.get("chatgpt_model", "gpt-3.5-turbo")
        openai_api_key = st.session_state.get("openai_api_key", "")
        if st.button("🔍 검증/보완 배치 실행", type="primary"):
            if not openai_api_key:
                st.error("❌ 사이드바에서 OpenAI API Key를 입력하세요.")
            else:
                st.info("실행 로그가 아래에 실시간으로 표시됩니다.")
                log_placeholder = st.empty()
                progress_placeholder = st.empty()
                log_lines = []
                q = queue.Queue()
                def run_and_stream():
                    process = Popen([
                        'python', 'run_batch.py', '--once',
                        '--model', chatgpt_model,
                        '--api_key', openai_api_key
                    ], stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)
                    for line in process.stdout:
                        q.put(line)
                    process.stdout.close()
                    process.wait()
                    q.put(None)
                t = threading.Thread(target=run_and_stream)
                t.start()
                while True:
                    try:
                        line = q.get(timeout=0.1)
                    except queue.Empty:
                        time.sleep(0.1)
                        continue
                    if line is None:
                        break
                    log_lines.append(line)
                    log_placeholder.code(''.join(log_lines), language='bash')
                    progress_placeholder.progress(min(100, len(log_lines) % 100))
                progress_placeholder.empty()
                st.success("실행 완료!")
                st.text_area("전체 STDOUT 로그", ''.join(log_lines), height=200)
    with col2:
        st.subheader("📊 검증/보완 결과")
        st.info("배치 작업을 실행하면 결과가 여기에 표시됩니다")

# 변경 로그/이력
elif page == "변경 로그/이력":
    st.header("📋 변경 로그/이력")
    
    # 필터링 옵션
    col1, col2, col3 = st.columns(3)
    with col1:
        search_term = st.text_input("🔍 검색어", placeholder="로그 검색")
    with col2:
        date_filter = st.date_input("📅 날짜 필터")
    with col3:
        status_filter = st.selectbox("상태 필터", ["전체", "완료", "진행중", "실패"])
    
    # 로그 테이블
    st.subheader("📊 변경 이력")
    
    logs_df = pd.DataFrame(st.session_state.logs)
    
    # 필터링 적용
    if search_term:
        logs_df = logs_df[logs_df['변경내용'].str.contains(search_term, case=False, na=False)]
    
    if status_filter != "전체":
        logs_df = logs_df[logs_df['상태'] == status_filter]
    
    # 상태별 색상 적용
    def style_status(val):
        if val == "완료":
            return "background-color: #dcfce7; color: #166534"
        elif val == "진행중":
            return "background-color: #fef3c7; color: #92400e"
        elif val == "실패":
            return "background-color: #fee2e2; color: #991b1b"
        return ""
    
    styled_df = logs_df.style.applymap(style_status, subset=['상태'])
    st.dataframe(styled_df, use_container_width=True)
    
    # 통계 정보
    st.subheader("📈 로그 통계")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_logs = len(logs_df)
        st.metric("전체 로그", total_logs)
    
    with col2:
        completed = len(logs_df[logs_df['상태'] == '완료'])
        st.metric("완료", completed)
    
    with col3:
        failed = len(logs_df[logs_df['상태'] == '실패'])
        st.metric("실패", failed)
    
    # 로그 다운로드
    if st.button("⬇️ 로그 다운로드"):
        csv = logs_df.to_csv(index=False)
        st.download_button(
            label="CSV 다운로드",
            data=csv,
            file_name=f"change_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="download_change_logs_csv"
        )
    
    # 시간별 변경 추이
    st.subheader("📊 시간별 변경 추이")
    
    # 시간별 데이터 생성 (시뮬레이션)
    time_data = pd.DataFrame({
        "시간": pd.date_range(start='2024-01-01', periods=30, freq='D'),
        "변경수": [2, 3, 1, 4, 2, 3, 5, 2, 1, 3, 4, 2, 6, 3, 2, 1, 4, 3, 2, 5, 3, 2, 1, 4, 3, 2, 5, 3, 2, 1]
    })
    
    fig = px.line(time_data, x="시간", y="변경수", title="일별 변경 로그 추이")
    st.plotly_chart(fig, use_container_width=True)

# 푸터
st.markdown("---")
st.markdown("*🗺️ 학습로드맵 시스템 v1.0 - AI 기반 개인화 학습 경로 생성*")

def convert_chunks_to_roadmap_data(chunks: List[RoadmapChunk], main_topic: str = "로드맵") -> Dict[str, Any]:
    """
    DB에서 읽은 청크 리스트를 generate_mindmap_html에서 요구하는 계층적 dict 구조로 변환합니다.
    """
    prerequisites = []
    phases = []
    resources = []
    phase_dict = {}
    for chunk in chunks:
        if chunk.metadata.get("type") in ["prerequisite", "requirement"] or "사전" in chunk.metadata.get("section", ""):
            prerequisites.append(chunk.content)
        if chunk.metadata.get("resources"):
            for res in chunk.metadata["resources"]:
                if isinstance(res, dict):
                    resources.append(res.get("title") or res.get("url") or str(res))
                else:
                    resources.append(str(res))
        level = chunk.metadata.get("level", 1)
        phase_key = f"{level}"
        if phase_key not in phase_dict:
            phase_dict[phase_key] = {
                "title": chunk.metadata.get("section", f"단계 {level}"),
                "duration": "",
                "topics": []
            }
        topic = {
            "title": chunk.metadata.get("section", ""),
            "description": chunk.content,
            "learning_links": []
        }
        if chunk.metadata.get("resources"):
            for res in chunk.metadata["resources"]:
                if isinstance(res, dict) and res.get("url"):
                    topic["learning_links"].append({
                        "title": res.get("title", res.get("url")),
                        "url": res.get("url")
                    })
        phase_dict[phase_key]["topics"].append(topic)
    phases = [phase_dict[k] for k in sorted(phase_dict.keys(), key=lambda x: int(x) if x.isdigit() else x)]
    return {
        "main_topic": main_topic,
        "prerequisites": prerequisites,
        "phases": phases,
        "resources": resources
    }
