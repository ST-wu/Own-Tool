from enum import Enum
from pydantic import BaseModel, Field


class SymbolType(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    ASYNC_METHOD = "async_method"
    EXTERNAL = "external"


class RelationType(str, Enum):
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPORTS = "IMPORTS"
    CONTAINS = "CONTAINS"


class SymbolNode(BaseModel):
    """代碼符號節點 (函數、類別、方法、模組)"""
    id: str = Field(..., description="唯一符號標識符 (如 core.browser:BrowserManager.start)")
    name: str = Field(..., description="符號簡短名稱 (如 start)")
    display_name: str = Field(..., description="視覺呈現名稱 (如 BrowserManager.start())")
    symbol_type: SymbolType = Field(..., description="符號類型")
    file_path: str | None = Field(None, description="檔案相對路徑")
    line_start: int | None = Field(None, description="定義起始行號 (1-indexed)")
    line_end: int | None = Field(None, description="定義結束行號")
    docstring: str | None = Field(None, description="說明文件註解")
    signature: str | None = Field(None, description="函式簽名參數")
    module_group: str = Field("default", description="所屬模組群組 (core/api/tasks/tools/etc)")
    is_external: bool = Field(False, description="是否為第三方或內建庫符號")
    call_count: int = Field(0, description="呼叫外部符號次數")
    called_by_count: int = Field(0, description="被其他符號呼叫次數")


class DependencyEdge(BaseModel):
    """符號間依賴關聯邊"""
    source: str = Field(..., description="發起端符號 ID (如調用者 Caller)")
    target: str = Field(..., description="接收端符號 ID (如被調用者 Callee)")
    relation: RelationType = Field(RelationType.CALLS, description="關聯類型")
    line_number: int | None = Field(None, description="調用處行號")
    weight: int = Field(1, description="調用權重/次數")


class CodeGraphResponse(BaseModel):
    """星雲圖資料結構回應"""
    center_id: str
    center_node: SymbolNode | None = None
    depth: int
    direction: str
    nodes: list[SymbolNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    total_project_symbols: int = 0
    execution_time_ms: float = 0.0


class SymbolSearchResult(BaseModel):
    """符號搜尋結果項目"""
    id: str
    name: str
    display_name: str
    symbol_type: SymbolType
    file_path: str | None = None
    module_group: str
    line_start: int | None = None
    signature: str | None = None


class SymbolCodeResponse(BaseModel):
    """單一符號原始碼與詳細自省資料"""
    symbol_id: str
    name: str
    display_name: str
    symbol_type: SymbolType
    file_path: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    code: str
    callers: list[SymbolSearchResult] = Field(default_factory=list)
    callees: list[SymbolSearchResult] = Field(default_factory=list)
