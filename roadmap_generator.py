from typing import Dict, List, Optional, Any
import json
from dataclasses import dataclass
from jinja2 import Template
import logging
from react_roadmap_parser import QdrantRoadmapStore
from datetime import datetime
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('roadmap_generator.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class RoadmapGenerationRequest:
    """로드맵 생성 요청 데이터"""
    subject: str  # 주제 (예: "React", "Python", "Machine Learning")
    level: str    # 난이도 ("beginner", "intermediate", "advanced", "all")
    focus_areas: List[str]  # 중점 분야 (예: ["hooks", "typescript", "testing"])
    output_format: str = "html"  # 출력 형식 ("html", "json", "markdown")
    save_to_file: bool = True  # 파일로 저장할지 여부
    output_dir: str = "."  # 출력 디렉토리

class RoadmapGenerator:
    """로드맵 생성기"""
    
    def __init__(self, qdrant_store: QdrantRoadmapStore):
        self.store = qdrant_store
        self.html_template = self._load_html_template()
    
    def generate_roadmap(self, request: RoadmapGenerationRequest) -> Dict[str, Any]:
        """로드맵 생성 (트리 구조로 반환)"""
        logger.info(f"Generating roadmap for {request.subject} - {request.level}")
        print(f"🔍 로드맵 생성 시작: {request.subject} - {request.level}")
        
        # 카테고리별로 노드들을 수집하여 계층 구조 구성
        categories = ['beginner', 'intermediate', 'advanced', 'community']
        hierarchy = []
        
        for category in categories:
            # 레벨 필터링
            if request.level != "all" and request.level != category:
                continue
                
            logger.info(f"Collecting nodes for category: {category}")
            print(f"📂 카테고리 '{category}'에서 노드 수집 중...")
            nodes = self.store.get_nodes_by_category(category)
            print(f"   발견된 노드 수: {len(nodes)}")
            
            if nodes:
                # 해당 카테고리의 루트 노드들 찾기 (depth=1인 노드들)
                root_nodes = [n for n in nodes if n.get('depth', 0) == 1]
                print(f"   루트 노드 수 (depth=1): {len(root_nodes)}")
                
                if root_nodes:
                    # 첫 번째 루트 노드를 대표로 사용
                    root_node = root_nodes[0]
                    print(f"   루트 노드 제목: {root_node.get('title', 'N/A')}")
                    subtree = self.store.get_subtree(root_node['id'])
                    
                    if subtree:
                        # 카테고리 정보를 명시적으로 설정
                        subtree['node']['category'] = category
                        hierarchy.append(subtree)
                        logger.info(f"Added {category} subtree: {subtree['node']['title']}")
                        print(f"   ✅ {category} 서브트리 추가: {subtree['node']['title']}")
                    else:
                        print(f"   ❌ 서브트리를 가져올 수 없음")
                else:
                    print(f"   ❌ 루트 노드가 없음")
            else:
                print(f"   ❌ 노드가 없음")
        
        # 결과가 없으면 전체 노드로 계층 구조 구성
        if not hierarchy:
            logger.info("No category-based hierarchy found, building from all nodes")
            print("🔄 카테고리 기반 계층 구조를 찾을 수 없음, 전체 노드로 구성")
            all_nodes = self._collect_relevant_nodes(request)
            print(f"   수집된 관련 노드 수: {len(all_nodes)}")
            if all_nodes:
                structured_data = self._build_hierarchy(all_nodes)
                hierarchy = structured_data.get('hierarchy', [])
                logger.info(f"Built hierarchy with {len(hierarchy)} root nodes")
                print(f"   구성된 계층 구조 루트 노드 수: {len(hierarchy)}")
            else:
                print("   ❌ 관련 노드가 없음")
        
        logger.info(f"Final hierarchy count: {len(hierarchy)}")
        print(f"📊 최종 계층 구조 수: {len(hierarchy)}")
        
        if not hierarchy:
            print("❌ 계층 구조가 비어있음 - 빈 결과 반환")
            return {
                'format': request.output_format,
                'content': f"'{request.subject}'에 대한 로드맵을 찾을 수 없습니다.",
                'metadata': {
                    'subject': request.subject,
                    'level': request.level,
                    'focus_areas': request.focus_areas,
                    'node_count': 0
                }
            }
        
        # 출력 형식에 따른 렌더링
        structured_data = {'hierarchy': hierarchy}
        if request.output_format == "html":
            result = self._render_html(structured_data, request)
            if request.save_to_file:
                result = self._save_html_to_file(result, request)
            return result
        elif request.output_format == "json":
            result = self._render_json(structured_data)
            if request.save_to_file:
                result = self._save_json_to_file(result, request)
            return result
        elif request.output_format == "markdown":
            result = self._render_markdown(structured_data)
            if request.save_to_file:
                result = self._save_markdown_to_file(result, request)
            return result
        else:
            raise ValueError(f"Unsupported output format: {request.output_format}")
    
    def _collect_relevant_nodes(self, request: RoadmapGenerationRequest) -> List[Dict[str, Any]]:
        """관련 노드들 수집"""
        nodes = []
        
        print(f"   🔍 주제 '{request.subject}' 기반 검색 중...")
        # 주제 기반 검색
        subject_results = self.store.search_nodes(request.subject, limit=50)
        print(f"      주제 검색 결과: {len(subject_results)}개")
        nodes.extend([r['node'] for r in subject_results])
        
        # 중점 분야 기반 검색
        for focus_area in request.focus_areas:
            print(f"   🔍 중점 분야 '{focus_area}' 기반 검색 중...")
            focus_results = self.store.search_nodes(focus_area, limit=20)
            print(f"      중점 분야 검색 결과: {len(focus_results)}개")
            nodes.extend([r['node'] for r in focus_results])
        
        print(f"   📊 검색된 총 노드 수: {len(nodes)}")
        
        # 레벨 필터링
        if request.level != "all":
            before_filter = len(nodes)
            nodes = [n for n in nodes if n['category'] == request.level]
            after_filter = len(nodes)
            print(f"   🎯 레벨 필터링: {before_filter} → {after_filter}개")
        
        # 중복 제거
        before_dedup = len(nodes)
        unique_nodes = {}
        for node in nodes:
            unique_nodes[node['id']] = node
        after_dedup = len(unique_nodes)
        print(f"   🧹 중복 제거: {before_dedup} → {after_dedup}개")
        
        return list(unique_nodes.values())
    
    def _build_hierarchy(self, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """계층 구조 구성"""
        # 노드를 ID로 매핑
        node_map = {node['id']: node for node in nodes}
        
        # 루트 노드 찾기
        root_nodes = [n for n in nodes if n['parent_id'] is None]
        
        # 계층 구조 구성
        def build_tree(node_id: str) -> Dict[str, Any]:
            node = node_map[node_id]
            children = [n for n in nodes if n['parent_id'] == node_id]
            children.sort(key=lambda x: x['order'])
            
            return {
                'node': node,
                'children': [build_tree(child['id']) for child in children if child['id'] in node_map]
            }
        
        hierarchy = []
        for root in root_nodes:
            hierarchy.append(build_tree(root['id']))
        
        return {'hierarchy': hierarchy}
    
    def _render_html(self, data: Dict[str, Any], request: RoadmapGenerationRequest) -> Dict[str, Any]:
        """HTML 렌더링"""
        html_content = self.html_template.render(
            title=f"{request.subject} 학습 로드맵",
            hierarchy=data['hierarchy'],
            level=request.level,
            focus_areas=request.focus_areas
        )
        
        return {
            'format': 'html',
            'content': html_content,
            'metadata': {
                'subject': request.subject,
                'level': request.level,
                'focus_areas': request.focus_areas,
                'node_count': self._count_nodes(data['hierarchy'])
            }
        }
    
    def _render_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """JSON 렌더링"""
        return {
            'format': 'json',
            'content': json.dumps(data, ensure_ascii=False, indent=2),
            'data': data
        }
    
    def _render_markdown(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Markdown 렌더링"""
        def render_node(node_data: Dict[str, Any], depth: int = 0) -> str:
            node = node_data['node']
            indent = "  " * depth
            
            # 헤더 레벨 결정
            header_level = "#" * min(depth + 1, 6)
            
            lines = [f"{header_level} {node['title']}\n"]
            
            if node['content']:
                lines.append(f"{node['content']}\n")
            
            # 링크 추가
            if node['links']:
                lines.append("**참고 자료:**\n")
                for link in node['links']:
                    lines.append(f"- [{link['title']}]({link['url']}) ({link['type']})\n")
            
            # 태그 추가
            if node['tags']:
                lines.append(f"**태그:** {', '.join(node['tags'])}\n")
            
            lines.append("\n")
            
            # 자식 노드들 렌더링
            for child in node_data['children']:
                lines.append(render_node(child, depth + 1))
            
            return "".join(lines)
        
        markdown_content = ""
        for root in data['hierarchy']:
            markdown_content += render_node(root)
        
        return {
            'format': 'markdown',
            'content': markdown_content
        }
    
    def _count_nodes(self, hierarchy: List[Dict[str, Any]]) -> int:
        """노드 수 계산"""
        count = 0
        for item in hierarchy:
            count += 1
            count += self._count_nodes(item['children'])
        return count
    
    def _load_html_template(self) -> Template:
        """HTML 템플릿 로드"""
        template_str = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - 인터랙티브 마인드맵</title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            overflow-x: auto;
        }

        .mindmap-container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            min-width: 1200px;
        }

        .mindmap-title {
            text-align: center;
            font-size: 2.5em;
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 30px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.1);
        }

        .mindmap {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 30px;
        }

        .root-node {
            background: linear-gradient(135deg, #FF6B6B, #FF8E53);
            color: white;
            padding: 20px 40px;
            border-radius: 25px;
            font-size: 1.8em;
            font-weight: bold;
            box-shadow: 0 10px 25px rgba(255, 107, 107, 0.3);
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .root-node:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(255, 107, 107, 0.4);
        }

        .main-branches {
            display: flex;
            justify-content: space-around;
            width: 100%;
            gap: 30px;
            flex-wrap: wrap;
        }

        .branch {
            flex: 1;
            min-width: 350px;
            max-width: 400px;
        }

        .level-node {
            padding: 15px 25px;
            border-radius: 20px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-bottom: 15px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }

        .beginner {
            background: linear-gradient(135deg, #4ECDC4, #44A08D);
            color: white;
        }

        .intermediate {
            background: linear-gradient(135deg, #FDBB2D, #22C1C3);
            color: white;
        }

        .advanced {
            background: linear-gradient(135deg, #FA8072, #FF6347);
            color: white;
        }

        .community {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }

        .level-node:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.2);
        }

        .sub-branches {
            margin-left: 20px;
            margin-top: 15px;
            display: none;
        }

        .sub-branches.expanded {
            display: block;
            animation: slideDown 0.3s ease-out;
        }

        @keyframes slideDown {
            from {
                opacity: 0;
                max-height: 0;
            }
            to {
                opacity: 1;
                max-height: 1000px;
            }
        }

        .sub-node {
            background: rgba(255, 255, 255, 0.9);
            border-left: 4px solid #3498db;
            padding: 12px 20px;
            margin: 8px 0;
            border-radius: 8px;
            font-size: 0.95em;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .sub-node:hover {
            background: rgba(52, 152, 219, 0.1);
            transform: translateX(5px);
        }

        .detail-node {
            background: rgba(255, 255, 255, 0.7);
            border-left: 3px solid #95a5a6;
            padding: 8px 15px;
            margin: 5px 0 5px 20px;
            border-radius: 5px;
            font-size: 0.85em;
            color: #2c3e50;
        }

        .resource-node {
            background: rgba(255, 255, 255, 0.7);
            border-left: 3px solid #2ecc71;
            padding: 8px 15px;
            margin: 5px 0 5px 20px;
            border-radius: 5px;
            font-size: 0.85em;
            color: #27ae60;
        }

        .book-node {
            background: rgba(255, 255, 255, 0.7);
            border-left: 3px solid #9b59b6;
            padding: 8px 15px;
            margin: 5px 0 5px 20px;
            border-radius: 5px;
            font-size: 0.85em;
            color: #8e44ad;
        }

        .resource-node a {
            color: #2980b9;
            text-decoration: underline;
            font-weight: 500;
            transition: all 0.2s ease;
            padding: 2px 4px;
            border-radius: 3px;
            background: rgba(41, 128, 185, 0.1);
        }

        .resource-node a:hover {
            color: #ffffff;
            background: #3498db;
            text-decoration: none;
            transform: translateX(3px);
            box-shadow: 0 2px 8px rgba(52, 152, 219, 0.3);
        }

        .expand-icon {
            float: right;
            transition: transform 0.3s ease;
        }

        .expand-icon.rotated {
            transform: rotate(90deg);
        }

        .controls {
            text-align: center;
            margin-bottom: 20px;
        }

        .btn {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 25px;
            cursor: pointer;
            margin: 0 10px;
            font-size: 0.9em;
            transition: all 0.3s ease;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
    </style>
</head>
<body>
    <div class="mindmap-container">
        <h1 class="mindmap-title">{{ title }}</h1>

        <div class="controls">
            <button class="btn" onclick="expandAll()">전체 펼치기</button>
            <button class="btn" onclick="collapseAll()">전체 접기</button>
        </div>

        <div class="mindmap">
            <div class="root-node" onclick="toggleAllBranches()">
                {{ title }}
            </div>

            <div class="main-branches" id="mainBranches" style="display: none;">
                {% for item in hierarchy %}
                    <div class="branch">
                        <div class="level-node {{ item.node.category }}" onclick="toggleBranch('{{ item.node.id }}')">
                            {% if item.node.category == 'beginner' %}초급 (Beginner)
                            {% elif item.node.category == 'intermediate' %}중급 (Intermediate)
                            {% elif item.node.category == 'advanced' %}고급 (Advanced)
                            {% elif item.node.category == 'community' %}추천 커뮤니티
                            {% else %}{{ item.node.title }}
                            {% endif %} <span class="expand-icon">▶</span>
                        </div>
                        <div class="sub-branches" id="{{ item.node.id }}">
                            {% for child in item.children %}
                                <div class="sub-node" onclick="toggleSubBranch('{{ child.node.id }}')">
                                    {{ child.node.title }} <span class="expand-icon">▶</span>
                                </div>
                                <div class="sub-branches" id="{{ child.node.id }}">
                                    {% for detail in child.children %}
                                        {% if detail.node.node_type == 'detail' %}
                                            <div class="detail-node">{{ detail.node.content }}</div>
                                        {% elif detail.node.node_type == 'resource' %}
                                            <div class="resource-node">
                                                {% for link in detail.node.links %}
                                                    {% if link.type == 'video' %}🎥
                                                    {% elif link.type == 'documentation' %}📖
                                                    {% elif link.type == 'book' %}📚
                                                    {% else %}🔗
                                                    {% endif %}
                                                    <a href="{{ link.url }}" target="_blank">{{ link.title }}</a>
                                                {% endfor %}
                                                {% if not detail.node.links %}
                                                    {{ detail.node.content }}
                                                {% endif %}
                                            </div>
                                        {% elif detail.node.node_type == 'book' %}
                                            <div class="book-node">
                                                {% for link in detail.node.links %}
                                                    📚 <a href="{{ link.url }}" target="_blank">{{ link.title }}</a>
                                                {% endfor %}
                                                {% if not detail.node.links %}
                                                    📚 {{ detail.node.content }}
                                                {% endif %}
                                            </div>
                                        {% endif %}
                                    {% endfor %}
                                </div>
                            {% endfor %}
                        </div>
                    </div>
                {% endfor %}
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
        return Template(template_str)

    def _save_html_to_file(self, result: Dict[str, Any], request: RoadmapGenerationRequest) -> Dict[str, Any]:
        """HTML 결과를 파일로 저장"""
        try:
            # 파일명 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            level_suffix = f"_{request.level}" if request.level != "all" else ""
            focus_suffix = f"_{'_'.join(request.focus_areas)}" if request.focus_areas else ""
            
            filename = f"roadmap_{request.subject.lower()}{level_suffix}{focus_suffix}_{timestamp}.html"
            filepath = os.path.join(request.output_dir, filename)
            
            # 파일 저장
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(result['content'])
            
            logger.info(f"HTML 로드맵을 {filepath}에 저장했습니다.")
            
            # 결과에 파일 경로 추가
            result['file_path'] = filepath
            result['filename'] = filename
            
            return result
            
        except Exception as e:
            logger.error(f"HTML 파일 저장 중 오류: {e}")
            return result
    
    def _save_json_to_file(self, result: Dict[str, Any], request: RoadmapGenerationRequest) -> Dict[str, Any]:
        """JSON 결과를 파일로 저장"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            level_suffix = f"_{request.level}" if request.level != "all" else ""
            focus_suffix = f"_{'_'.join(request.focus_areas)}" if request.focus_areas else ""
            
            filename = f"roadmap_{request.subject.lower()}{level_suffix}{focus_suffix}_{timestamp}.json"
            filepath = os.path.join(request.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(result['content'])
            
            logger.info(f"JSON 로드맵을 {filepath}에 저장했습니다.")
            
            result['file_path'] = filepath
            result['filename'] = filename
            
            return result
            
        except Exception as e:
            logger.error(f"JSON 파일 저장 중 오류: {e}")
            return result
    
    def _save_markdown_to_file(self, result: Dict[str, Any], request: RoadmapGenerationRequest) -> Dict[str, Any]:
        """Markdown 결과를 파일로 저장"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            level_suffix = f"_{request.level}" if request.level != "all" else ""
            focus_suffix = f"_{'_'.join(request.focus_areas)}" if request.focus_areas else ""
            
            filename = f"roadmap_{request.subject.lower()}{level_suffix}{focus_suffix}_{timestamp}.md"
            filepath = os.path.join(request.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(result['content'])
            
            logger.info(f"Markdown 로드맵을 {filepath}에 저장했습니다.")
            
            result['file_path'] = filepath
            result['filename'] = filename
            
            return result
            
        except Exception as e:
            logger.error(f"Markdown 파일 저장 중 오류: {e}")
            return result
