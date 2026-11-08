"""Pydantic models and AST definitions for the Camoufox Advanced Scenario Engine."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class LoopDef(BaseModel):
    """Loop definition: iterate over an evaluated collection or variable."""

    over: str = Field(..., description="Expression evaluating to an iterable (e.g. 'ctx.vars.items').")
    as_var: str = Field("item", alias="as", description="Target variable name for the current item.")
    steps: List[Step] = Field(default_factory=list, description="Steps to run for each item.")


class WhileDef(BaseModel):
    """While loop definition with a guard limit."""

    condition: str = Field(..., description="Expression evaluated before each iteration.")
    max_iterations: int = Field(50, description="Safety bound to prevent infinite loops.")
    steps: List[Step] = Field(default_factory=list, description="Steps to repeat while condition holds.")


class ElifBlock(BaseModel):
    """Elif branch definition."""

    condition: str = Field(..., alias="if")
    steps: List[Step] = Field(default_factory=list, alias="then")


class Step(BaseModel):
    """Single scenario step or control-flow node."""

    name: Optional[str] = None
    page: str = Field("default", description="Named page/tab target.")
    action: Optional[str] = Field(
        None,
        description=(
            "Action name: goto, reload, delay, click, fill, type, press, hover, "
            "scroll, check, select_option, wait_for_selector, wait_for_load_state, "
            "extract_text, extract_html, extract_attribute, assert_exists, assert_text, "
            "screenshot, evaluate_js, download_file, upload_file, pause, set_var, close_page."
        ),
    )

    # Action-specific arguments
    url: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[Any] = None
    text: Optional[str] = None
    script: Optional[str] = None
    attribute: Optional[str] = None
    save_to_var: Optional[str] = None
    save_to_file: Optional[str] = None
    files: Optional[List[str]] = None
    timeout_ms: Optional[int] = None
    wait_for: Optional[str] = None
    prompt: Optional[str] = None
    delay_ms: Optional[int] = None

    # Resilience
    on_error: Literal["abort", "continue", "retry"] = "abort"
    retries: int = 0
    retry_delay_ms: int = 1000

    # Control Flow: If-Else
    if_cond: Optional[str] = Field(None, alias="if")
    then_steps: Optional[List[Step]] = Field(None, alias="then")
    elif_blocks: Optional[List[ElifBlock]] = Field(None, alias="elif")
    else_steps: Optional[List[Step]] = Field(None, alias="else")

    # Control Flow: Loops
    loop: Optional[LoopDef] = None
    while_loop: Optional[WhileDef] = Field(None, alias="while")

    model_config = {"populate_by_name": True}

    @property
    def is_conditional(self) -> bool:
        return self.if_cond is not None

    @property
    def is_loop(self) -> bool:
        return self.loop is not None or self.while_loop is not None


# Re-resolve forward references for recursive Step models
LoopDef.model_rebuild()
WhileDef.model_rebuild()
ElifBlock.model_rebuild()
Step.model_rebuild()


class ScenarioSettings(BaseModel):
    """Scenario execution settings."""

    mode: Literal["autonomous", "interactive", "wait_var"] = "autonomous"
    default_timeout_ms: int = 15000
    screenshot_on_failure: bool = True
    close_on_complete: bool = True


class ScenarioDefinition(BaseModel):
    """Complete Scenario specification."""

    id: str = Field(..., description="Unique slug ID of the scenario.")
    name: str = Field(..., description="Human-readable title.")
    description: str = Field("", description="Detailed explanation of what the scenario does.")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Default variables.")
    settings: ScenarioSettings = Field(default_factory=ScenarioSettings)
    steps: List[Step] = Field(default_factory=list, description="Ordered steps or control-flow nodes.")


class StepExecutionLog(BaseModel):
    """Record of a single step execution outcome."""

    step_name: str
    action: Optional[str] = None
    page: str = "default"
    status: Literal["success", "failed", "skipped", "retrying"]
    duration_ms: int = 0
    output: Optional[Any] = None
    error: Optional[str] = None


class ScenarioRunSnapshot(BaseModel):
    """Runtime snapshot of an executing or completed scenario run."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scenario_id: str
    status: Literal["pending", "running", "paused", "completed", "failed", "aborted"] = "pending"
    current_step_index: int = 0
    total_steps: int = 0
    vars: Dict[str, Any] = Field(default_factory=dict)
    downloads: Dict[str, str] = Field(default_factory=dict)
    logs: List[StepExecutionLog] = Field(default_factory=list)
    error: Optional[str] = None
    pause_prompt: Optional[str] = None
    started_at: float = Field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
