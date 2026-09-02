import time
from pathlib import Path
from collections import deque
from typing import Any, Literal
from core.logger import logger
from tools.code_nebula.models import (
    SymbolNode,
    SymbolType,
    DependencyEdge,
    RelationType,
    CodeGraphResponse,
    SymbolSearchResult,
    SymbolCodeResponse,
)
from tools.code_nebula.analyzer import ASTCodeAnalyzer


class CodeGraphEngine:
    """
    代碼星雲圖引擎 (Code Nebula Engine)
    維護全域代碼知識圖譜快取，提供 BFS 中心輻射子圖抽取與符號原始碼自省
    """

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path.cwd()
        self.analyzer = ASTCodeAnalyzer(self.workspace_root)
        self.symbols: dict[str, SymbolNode] = {}
        self.adj_out: dict[str, list[DependencyEdge]] = {}
        self.adj_in: dict[str, list[DependencyEdge]] = {}
        self._last_scan_time: float = 0.0

    def scan_project(self, target_dir: Path | str | None = None) -> int:
        """掃描專案並建立全域關係圖快取 (支援動態切換任意自訂專案目錄)"""
        t0 = time.perf_counter()
        if target_dir:
            self.workspace_root = Path(target_dir).resolve()
            self.analyzer.workspace_root = self.workspace_root

        scan_path = self.workspace_root
        self.symbols, edges = self.analyzer.analyze_directory(scan_path)

        # 重建鄰接表
        self.adj_out = {s_id: [] for s_id in self.symbols}
        self.adj_in = {s_id: [] for s_id in self.symbols}

        for edge in edges:
            if edge.source not in self.adj_out:
                self.adj_out[edge.source] = []
            if edge.target not in self.adj_in:
                self.adj_in[edge.target] = []

            self.adj_out[edge.source].append(edge)
            self.adj_in[edge.target].append(edge)

        self._last_scan_time = time.time()
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"代碼星雲圖掃描完成 [{self.workspace_root.name}]: 符號數={len(self.symbols)}, 依賴邊數={len(edges)}, 耗時={elapsed:.2f}ms")
        return len(self.symbols)

    def get_project_info(self) -> dict[str, Any]:
        """獲取當前載入之專案基本資訊"""
        self._ensure_scanned()
        return {
            "current_project_path": str(self.workspace_root),
            "project_name": self.workspace_root.name,
            "total_symbols": len(self.symbols),
            "last_scan_time": self._last_scan_time,
        }

    def _ensure_scanned(self) -> None:
        """Guard clause: 確保圖譜已載入快取"""
        if not self.symbols:
            self.scan_project()

    def search_symbols(self, query: str, limit: int = 25) -> list[SymbolSearchResult]:
        """模糊搜尋符號清單 (支援函數名、類別名、檔名比對)"""
        self._ensure_scanned()
        q = query.strip().lower()

        results: list[SymbolSearchResult] = []
        # 依相關性權重排序 (精準名稱比對 > 前綴比對 > 模糊包含)
        matches: list[tuple[int, SymbolNode]] = []

        for sym in self.symbols.values():
            if sym.symbol_type == SymbolType.MODULE:
                continue

            name_lower = sym.name.lower()
            id_lower = sym.id.lower()
            file_lower = (sym.file_path or "").lower()

            if not q:
                # 若無搜尋字串，優先回傳專案主要函式與類別
                priority = 10 if sym.symbol_type in (SymbolType.CLASS, SymbolType.FUNCTION) else 20
                matches.append((priority, sym))
                continue

            if name_lower == q:
                matches.append((1, sym))
            elif name_lower.startswith(q):
                matches.append((2, sym))
            elif q in name_lower:
                matches.append((3, sym))
            elif q in id_lower or q in file_lower:
                matches.append((5, sym))

        matches.sort(key=lambda x: (x[0], x[1].name))

        for _, sym in matches[:limit]:
            results.append(
                SymbolSearchResult(
                    id=sym.id,
                    name=sym.name,
                    display_name=sym.display_name,
                    symbol_type=sym.symbol_type,
                    file_path=sym.file_path,
                    module_group=sym.module_group,
                    line_start=sym.line_start,
                    signature=sym.signature,
                )
            )

        return results

    def get_subgraph(
        self,
        center_id: str,
        depth: int = 1,
        direction: Literal["upstream", "downstream", "both"] = "both",
        include_external: bool = False,
        max_nodes: int = 200,
    ) -> CodeGraphResponse:
        """
        以中心符號為核心，自訂深度與方向進行 BFS 廣度搜尋，裁剪星雲子圖
        :param center_id: 中心符號 ID
        :param depth: 輻射深度 (1 ~ 5)
        :param direction: 搜尋方向 ("upstream", "downstream", "both")
        :param include_external: 是否納入第三方或內建外部庫
        :param max_nodes: 子圖最大節點安全上限 (預設 200，防範巨型專案渲染卡頓)
        """
        t0 = time.perf_counter()
        self._ensure_scanned()

        # Guard clause: 若未傳入 center_id 或為空，自動選取第一個可用符號
        if not center_id or not center_id.strip():
            non_mod_symbols = [s for s in self.symbols.values() if s.symbol_type != SymbolType.MODULE]
            actual_center_id = non_mod_symbols[0].id if non_mod_symbols else (list(self.symbols.keys())[0] if self.symbols else "")
        else:
            actual_center_id = center_id

        # 若精準 ID 不存在則嘗試以名稱比對
        if actual_center_id not in self.symbols:
            for s_id, sym in self.symbols.items():
                if sym.name.lower() == actual_center_id.lower() or s_id.endswith(f":{actual_center_id}"):
                    actual_center_id = s_id
                    break

        center_node = self.symbols.get(actual_center_id)
        if not center_node:
            return CodeGraphResponse(
                center_id=center_id,
                center_node=None,
                depth=depth,
                direction=direction,
                nodes=[],
                edges=[],
                total_project_symbols=len(self.symbols),
                execution_time_ms=(time.perf_counter() - t0) * 1000,
            )

        # BFS 走訪結構
        visited_nodes: set[str] = {actual_center_id}
        collected_edges: list[DependencyEdge] = []
        edge_signatures: set[tuple[str, str, str]] = set()

        # 佇列結構: (node_id, current_depth)
        queue: deque[tuple[str, int]] = deque([(actual_center_id, 0)])

        while queue:
            curr_id, curr_d = queue.popleft()
            if curr_d >= depth or len(visited_nodes) >= max_nodes:
                continue

            # 1. 往下游搜尋 (Callee 我呼叫了誰)
            if direction in ("downstream", "both"):
                for edge in self.adj_out.get(curr_id, []):
                    target_id = edge.target
                    target_node = self.symbols.get(target_id)
                    if not target_node:
                        continue
                    if not include_external and target_node.is_external:
                        continue

                    edge_sig = (edge.source, edge.target, edge.relation.value)
                    if edge_sig not in edge_signatures:
                        edge_signatures.add(edge_sig)
                        collected_edges.append(edge)

                    if target_id not in visited_nodes:
                        visited_nodes.add(target_id)
                        queue.append((target_id, curr_d + 1))

            # 2. 往上游搜尋 (Caller 誰呼叫了我)
            if direction in ("upstream", "both"):
                for edge in self.adj_in.get(curr_id, []):
                    source_id = edge.source
                    source_node = self.symbols.get(source_id)
                    if not source_node:
                        continue
                    if not include_external and source_node.is_external:
                        continue

                    edge_sig = (edge.source, edge.target, edge.relation.value)
                    if edge_sig not in edge_signatures:
                        edge_signatures.add(edge_sig)
                        collected_edges.append(edge)

                    if source_id not in visited_nodes:
                        visited_nodes.add(source_id)
                        queue.append((source_id, curr_d + 1))

        # 收集子圖中的所有節點物件
        subgraph_nodes = [self.symbols[n_id] for n_id in visited_nodes if n_id in self.symbols]

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return CodeGraphResponse(
            center_id=actual_center_id,
            center_node=center_node,
            depth=depth,
            direction=direction,
            nodes=subgraph_nodes,
            edges=collected_edges,
            total_project_symbols=len(self.symbols),
            execution_time_ms=elapsed_ms,
        )

    def get_symbol_code(self, symbol_id: str) -> SymbolCodeResponse | None:
        """獲取指定符號的完整原始碼、行號區間、註解與直接呼叫者/被呼叫者清單"""
        self._ensure_scanned()
        sym = self.symbols.get(symbol_id)
        if not sym:
            return None

        code_text = ""
        if sym.file_path and sym.line_start is not None and sym.line_end is not None:
            full_file = self.workspace_root / sym.file_path
            if full_file.exists():
                try:
                    lines = full_file.read_text(encoding="utf-8").splitlines()
                    # 轉為 0-indexed 範圍安全裁切
                    s_idx = max(0, sym.line_start - 1)
                    e_idx = min(len(lines), sym.line_end)
                    code_text = "\n".join(lines[s_idx:e_idx])
                except Exception as e:
                    code_text = f"# 讀取原始碼失敗: {e}"

        # 收集直接呼叫者 (Callers)
        callers: list[SymbolSearchResult] = []
        for edge in self.adj_in.get(symbol_id, []):
            caller_node = self.symbols.get(edge.source)
            if caller_node and caller_node.symbol_type != SymbolType.MODULE:
                callers.append(
                    SymbolSearchResult(
                        id=caller_node.id,
                        name=caller_node.name,
                        display_name=caller_node.display_name,
                        symbol_type=caller_node.symbol_type,
                        file_path=caller_node.file_path,
                        module_group=caller_node.module_group,
                        line_start=caller_node.line_start,
                        signature=caller_node.signature,
                    )
                )

        # 收集直接被呼叫者 (Callees)
        callees: list[SymbolSearchResult] = []
        for edge in self.adj_out.get(symbol_id, []):
            callee_node = self.symbols.get(edge.target)
            if callee_node and callee_node.symbol_type != SymbolType.MODULE:
                callees.append(
                    SymbolSearchResult(
                        id=callee_node.id,
                        name=callee_node.name,
                        display_name=callee_node.display_name,
                        symbol_type=callee_node.symbol_type,
                        file_path=callee_node.file_path,
                        module_group=callee_node.module_group,
                        line_start=callee_node.line_start,
                        signature=callee_node.signature,
                    )
                )

        return SymbolCodeResponse(
            symbol_id=sym.id,
            name=sym.name,
            display_name=sym.display_name,
            symbol_type=sym.symbol_type,
            file_path=sym.file_path or "unknown",
            line_start=sym.line_start or 1,
            line_end=sym.line_end or 1,
            signature=sym.signature,
            docstring=sym.docstring,
            code=code_text,
            callers=callers,
            callees=callees,
        )


# 全域單例圖譜引擎
nebula_engine = CodeGraphEngine()
