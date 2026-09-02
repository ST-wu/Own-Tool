import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from tools.code_nebula.analyzer import ASTCodeAnalyzer
from tools.code_nebula.graph import nebula_engine
from tools.code_nebula.models import SymbolNode, SymbolType, RelationType


def test_ast_analyzer_parses_project():
    """驗證 AST 分析器能精準提取專案模組、類別、函數與調用關係"""
    analyzer = ASTCodeAnalyzer()
    symbols, edges = analyzer.analyze_directory()

    assert len(symbols) > 10, "應解析出至少 10 個以上符號"
    assert len(edges) > 5, "應解析出至少 5 條以上關聯邊"

    # 驗證關鍵類別存在
    class_symbols = [s for s in symbols.values() if s.symbol_type == SymbolType.CLASS]
    class_names = [s.name for s in class_symbols]
    assert "BrowserManager" in class_names or "OperationLogger" in class_names

    # 驗證包含關係 (CONTAINS) 邊存在
    contains_edges = [e for e in edges if e.relation == RelationType.CONTAINS]
    assert len(contains_edges) > 0


def test_code_graph_engine_search():
    """驗證圖譜搜尋與自動補全功能"""
    nebula_engine.scan_project()
    results = nebula_engine.search_symbols(query="health", limit=10)

    assert len(results) > 0
    # 搜尋結果應包含 health 相關函數
    names = [r.name.lower() for r in results]
    assert any("health" in n for n in names)


def test_code_graph_engine_subgraph_bfs():
    """驗證以中心符號為核心進行多層級 BFS 子圖裁剪"""
    nebula_engine.scan_project()
    
    # 深度 1 子圖
    graph_d1 = nebula_engine.get_subgraph(center_id="get_health_status", depth=1, direction="both")
    assert graph_d1.center_node is not None
    assert len(graph_d1.nodes) >= 1

    # 深度 2 子圖節點數應大於或等於深度 1
    graph_d2 = nebula_engine.get_subgraph(center_id="get_health_status", depth=2, direction="both")
    assert len(graph_d2.nodes) >= len(graph_d1.nodes)

    # 驗證方向過濾 (downstream vs upstream)
    downstream_graph = nebula_engine.get_subgraph(center_id="get_health_status", depth=2, direction="downstream")
    assert downstream_graph.direction == "downstream"


def test_code_graph_engine_get_code():
    """驗證符號原始碼自省與上下游關聯讀取"""
    nebula_engine.scan_project()
    symbols = nebula_engine.search_symbols(query="get_health_status", limit=5)
    assert len(symbols) > 0

    target_id = symbols[0].id
    code_resp = nebula_engine.get_symbol_code(target_id)
    assert code_resp is not None
    assert "def get_health_status" in code_resp.code or "async def get_health_status" in code_resp.code
    assert code_resp.line_start > 0
    assert code_resp.line_end >= code_resp.line_start


@pytest.mark.asyncio
async def test_nebula_api_scan_endpoint():
    """驗證 POST /api/v1/nebula/scan 端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/nebula/scan", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_symbols"] > 0


@pytest.mark.asyncio
async def test_nebula_api_symbols_search_endpoint():
    """驗證 GET /api/v1/nebula/symbols 搜尋端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/nebula/symbols?q=log&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0


@pytest.mark.asyncio
async def test_nebula_api_graph_endpoint():
    """驗證 GET /api/v1/nebula/graph 星雲圖產出端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/nebula/graph?target=get_health_status&depth=2&direction=both")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["depth"] == 2


@pytest.mark.asyncio
async def test_nebula_api_code_endpoint():
    """驗證 GET /api/v1/nebula/code 代碼自省端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先搜尋符號以取得精準 ID
        search_res = await client.get("/api/v1/nebula/symbols?q=get_health_status")
        symbols = search_res.json()
        assert len(symbols) > 0
        sym_id = symbols[0]["id"]

        code_res = await client.get(f"/api/v1/nebula/code?symbol_id={sym_id}")
        assert code_res.status_code == 200
        code_data = code_res.json()
        assert "code" in code_data
        assert len(code_data["code"]) > 0


@pytest.mark.asyncio
async def test_nebula_api_project_info_and_custom_scan():
    """驗證 GET /api/v1/nebula/project 與自訂路徑切換功能"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 查詢專案資訊
        proj_res = await client.get("/api/v1/nebula/project")
        assert proj_res.status_code == 200
        proj_data = proj_res.json()
        assert "current_project_path" in proj_data
        assert "project_name" in proj_data

        # 2. 測試切換至自訂子目錄 (如 tools/code_nebula)
        scan_res = await client.post("/api/v1/nebula/scan", json={"project_path": "tools/code_nebula"})
        assert scan_res.status_code == 200
        scan_data = scan_res.json()
        assert scan_data["total_symbols"] > 0
        assert "code_nebula" in scan_data["project_path"]

        # 3. 還原為預設專案
        reset_res = await client.post("/api/v1/nebula/scan", json={"project_path": None})
        assert reset_res.status_code == 200


def test_code_graph_engine_max_nodes_cap():
    """驗證 BFS 子圖裁剪時 max_nodes 安全限制"""
    nebula_engine.scan_project()
    graph = nebula_engine.get_subgraph(center_id="get_health_status", depth=5, max_nodes=3)
    assert len(graph.nodes) <= 3


def test_ast_analyzer_local_instance_resolution():
    """驗證 AST 語法分析器能識別本地實例賦值與方法調用"""
    analyzer = ASTCodeAnalyzer()
    analyzer.symbols["core.op_logger:OperationLogger.log"] = SymbolNode(
        id="core.op_logger:OperationLogger.log",
        name="log",
        display_name="OperationLogger.log",
        symbol_type=SymbolType.METHOD,
    )
    res_id = analyzer._resolve_symbol_id(
        expr_name="op_logger.log",
        import_map={},
        current_module="core.op_logger",
        local_instances={"op_logger": "OperationLogger"},
    )
    assert res_id == "core.op_logger:OperationLogger.log"
