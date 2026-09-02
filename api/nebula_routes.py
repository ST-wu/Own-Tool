from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from core.op_logger import op_logger
from tools.code_nebula.graph import nebula_engine
from tools.code_nebula.models import (
    CodeGraphResponse,
    SymbolSearchResult,
    SymbolCodeResponse,
)

nebula_router = APIRouter(prefix="/api/v1/nebula", tags=["Code Nebula"])


class ScanProjectRequest(BaseModel):
    project_path: str | None = Field(None, description="自訂專案目錄路徑 (為空則掃描當前專案)")


class ScanProjectResponse(BaseModel):
    success: bool
    total_symbols: int
    project_path: str
    message: str


@nebula_router.post("/scan", response_model=ScanProjectResponse)
async def scan_project_endpoint(payload: ScanProjectRequest | None = None) -> ScanProjectResponse:
    """觸發專案代碼語法樹掃描與符號索引建構"""
    target_path = Path(payload.project_path) if payload and payload.project_path else None
    
    # Guard clause: 檢查自訂路徑是否存在
    if target_path and not target_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"指定之專案路徑不存在: {target_path}",
        )

    count = nebula_engine.scan_project(target_path)
    scanned_str = str(target_path or nebula_engine.workspace_root)
    op_logger.log("TOOL:NEBULA_SCAN", "INFO", details=f"掃描專案代碼完成 | 路徑={scanned_str} | 總符號數={count}")

    return ScanProjectResponse(
        success=True,
        total_symbols=count,
        project_path=scanned_str,
        message=f"成功解析專案 AST，共建構 {count} 個符號節點",
    )


@nebula_router.get("/project")
async def get_project_info_endpoint():
    """獲取當前星雲圖載入之專案路徑與基本資訊"""
    return nebula_engine.get_project_info()


@nebula_router.get("/symbols", response_model=list[SymbolSearchResult])
async def search_symbols_endpoint(
    q: str = Query("", description="搜尋關鍵字 (模糊比對函數/類別名稱)"),
    limit: int = Query(25, ge=1, le=100, description="最大筆數"),
) -> list[SymbolSearchResult]:
    """模糊搜尋與自動補全專案代碼符號清單"""
    return nebula_engine.search_symbols(query=q, limit=limit)


@nebula_router.get("/graph", response_model=CodeGraphResponse)
async def get_nebula_graph_endpoint(
    target: str = Query(..., description="中心函數或類別符號 ID/名稱"),
    depth: int = Query(1, ge=1, le=5, description="輻射關聯深度 (1~5)"),
    direction: Literal["upstream", "downstream", "both"] = Query("both", description="關聯方向"),
    include_external: bool = Query(False, description="是否包含第三方或內建庫符號"),
) -> CodeGraphResponse:
    """依據指定中心符號、自訂深度與呼叫方向產生星雲子圖結構"""
    resp = nebula_engine.get_subgraph(
        center_id=target,
        depth=depth,
        direction=direction,
        include_external=include_external,
    )
    
    # 若找不到中心節點
    if not resp.center_node and not resp.nodes:
        op_logger.log("TOOL:NEBULA_GRAPH", "WARNING", details=f"未找到符號: {target}")
    else:
        op_logger.log(
            "TOOL:NEBULA_GRAPH",
            "INFO",
            details=f"產出星雲圖: 中心={target} | 深度={depth} | 方向={direction} | 節點數={len(resp.nodes)}",
        )
    return resp


@nebula_router.get("/code", response_model=SymbolCodeResponse)
async def get_symbol_code_endpoint(
    symbol_id: str = Query(..., description="符號唯一標識 ID"),
) -> SymbolCodeResponse:
    """獲取指定符號之原始碼片段、行號區間、註解與直接呼叫者/被呼叫者"""
    code_data = nebula_engine.get_symbol_code(symbol_id)
    if not code_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未在知識圖譜中找到指定符號: {symbol_id}",
        )
    return code_data
