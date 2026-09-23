from pydantic import BaseModel, Field


class ColorTheme(BaseModel):
    id: str
    name: str
    description: str
    background: str
    glow_color: str
    trail_colors: list[str]


class PendulumPreset(BaseModel):
    id: str
    name: str
    num_links: int = Field(2, ge=2, le=6)
    speed: float = Field(1.0, ge=0.1, le=5.0)
    damping: float = Field(0.0, ge=0.0, le=0.01)
    swarm_count: int = Field(1, ge=1, le=50)
    trail_persistence: float = Field(0.96, ge=0.8, le=0.999)
    theme_id: str
