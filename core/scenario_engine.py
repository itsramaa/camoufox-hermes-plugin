"""Advanced Scenario Execution Engine for Camoufox.

Supports:
- Multi-web & multi-tab workflows (named pages)
- AST Control flow: if / elif / else, loop (for-each), while
- Shared runtime context (ctx.vars, ctx.downloads, ctx.pages)
- File staging (download_file, upload_file)
- Human-in-the-loop (interactive pause & resume)
- Per-step resilience (retries, on_error continue/abort)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .exceptions import (
    ScenarioError,
    ScenarioExecutionError,
    ScenarioValidationError,
)
from .instance_registry import REGISTRY
from .scenario_models import (
    ScenarioDefinition,
    ScenarioRunSnapshot,
    Step,
    StepExecutionLog,
)

logger = logging.getLogger(__name__)

VAR_INTERPOLATION_RE = re.compile(r"\{\{([a-zA-Z0-9_\-\.]+)\}\}")


class ExecutionContext:
    """Holds runtime state during scenario execution."""

    def __init__(
        self,
        scenario: ScenarioDefinition,
        instance: Any,
        run_id: str,
        initial_vars: Optional[Dict[str, Any]] = None,
        downloads_dir: Optional[Path] = None,
        on_log: Optional[Callable[[StepExecutionLog], Coroutine[Any, Any, None]]] = None,
    ) -> None:
        self.scenario = scenario
        self.instance = instance
        self.run_id = run_id
        self.vars: Dict[str, Any] = dict(scenario.variables)
        if initial_vars:
            self.vars.update(initial_vars)

        if downloads_dir is None:
            self.temp_dir = tempfile.TemporaryDirectory(prefix="camoufox-run-")
            self.downloads_dir = Path(self.temp_dir.name)
        else:
            self.temp_dir = None
            self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        self.downloads: Dict[str, str] = {}
        self.pages: Dict[str, Any] = {}
        self.logs: List[StepExecutionLog] = []
        self.status: str = "running"
        self.error: Optional[str] = None
        self.pause_event = asyncio.Event()
        self.pause_prompt: Optional[str] = None
        self.on_log = on_log

        # Seed the default page if the instance already has one
        if hasattr(instance, "page") and instance.page is not None:
            self.pages["default"] = instance.page

    def cleanup(self) -> None:
        if self.temp_dir is not None:
            try:
                self.temp_dir.cleanup()
            except Exception as exc:
                logger.debug("Failed cleaning scenario temp_dir: %s", exc)

    async def get_or_create_page(self, name: str) -> Any:
        """Get an existing named page or create a new tab in the browser context."""
        page = self.pages.get(name)
        if page is not None:
            is_closed = False
            try:
                check = getattr(page, "is_closed", None)
                if callable(check):
                    res = check()
                    if isinstance(res, bool):
                        is_closed = res
            except Exception:
                pass
            if not is_closed:
                return page

        # Need to spawn a new page
        context = getattr(self.instance, "context", None)
        browser = getattr(self.instance, "_browser", None) or getattr(self.instance, "browser", None)

        if context is not None and hasattr(context, "new_page"):
            new_page = await context.new_page()
        elif browser is not None:
            if hasattr(browser, "new_page"):
                new_page = await browser.new_page()
            elif hasattr(browser, "contexts") and browser.contexts:
                new_page = await browser.contexts[0].new_page()
            elif hasattr(browser, "new_context"):
                ctx_obj = await browser.new_context()
                new_page = await ctx_obj.new_page()
            else:
                raise ScenarioExecutionError(f"Cannot create page from browser for page {name!r}.")
        else:
            raise ScenarioExecutionError(f"Browser instance is unavailable for page {name!r}.")

        self.pages[name] = new_page
        return new_page

    async def close_page(self, name: str) -> None:
        page = self.pages.pop(name, None)
        if page is not None:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception as exc:
                logger.debug("Error closing page %s: %s", name, exc)

    def interpolate(self, value: Any) -> Any:
        """Replace {{var}} in string templates with runtime variable values."""
        if not isinstance(value, str):
            return value

        def replacer(match: re.Match) -> str:
            var_name = match.group(1).strip()
            # Look up in vars first, then downloads
            if var_name in self.vars:
                return str(self.vars[var_name])
            if var_name in self.downloads:
                return str(self.downloads[var_name])
            return match.group(0)

        return VAR_INTERPOLATION_RE.sub(replacer, value)

    def evaluate_expression(self, expr: str) -> Any:
        """Safely evaluate an expression against the current context."""
        expr_clean = expr.strip()
        safe_globals = {
            "__builtins__": {
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "set": set,
                "min": min,
                "max": max,
                "sum": sum,
                "any": any,
                "all": all,
                "None": None,
                "True": True,
                "False": False,
            }
        }
        safe_locals = {
            "ctx": self,
            "vars": self.vars,
            "downloads": self.downloads,
            "pages": self.pages,
        }
        try:
            return eval(expr_clean, safe_globals, safe_locals)
        except Exception as exc:
            raise ScenarioExecutionError(f"Failed evaluating expression {expr!r}: {exc}") from exc

    async def record_log(self, log: StepExecutionLog) -> None:
        self.logs.append(log)
        if self.on_log:
            try:
                await self.on_log(log)
            except Exception as exc:
                logger.warning("Error invoking on_log callback: %s", exc)


class ScenarioEngine:
    """Executes a ScenarioDefinition using Playwright & Camoufox."""

    def __init__(self) -> None:
        self.active_runs: Dict[str, ExecutionContext] = {}

    def get_run(self, run_id: str) -> Optional[ExecutionContext]:
        return self.active_runs.get(run_id)

    async def resume_run(self, run_id: str) -> bool:
        ctx = self.active_runs.get(run_id)
        if ctx is None or ctx.status != "paused":
            return False
        ctx.status = "running"
        ctx.pause_prompt = None
        ctx.pause_event.set()
        return True

    async def abort_run(self, run_id: str) -> bool:
        ctx = self.active_runs.get(run_id)
        if ctx is None:
            return False
        ctx.status = "aborted"
        ctx.error = "Aborted by user or API."
        ctx.pause_event.set()
        return True

    async def execute(
        self,
        scenario: ScenarioDefinition,
        *,
        initial_vars: Optional[Dict[str, Any]] = None,
        instance_id: Optional[str] = None,
        mode: str = "guest",
        profile: Optional[str] = None,
        proxy: Optional[Any] = None,
        headless: Optional[bool] = None,
        on_log: Optional[Callable[[StepExecutionLog], Coroutine[Any, Any, None]]] = None,
    ) -> ScenarioRunSnapshot:
        """Run a scenario end-to-end."""
        inst = None
        is_ephemeral_instance = False

        if instance_id:
            inst = REGISTRY.get(instance_id)
            if inst is None:
                raise ScenarioError(f"Specified instance {instance_id!r} not found.")
        else:
            # Launch a new instance for this scenario
            is_ephemeral_instance = True
            inst = await REGISTRY.launch(
                mode=mode,
                profile=profile,
                start_url="about:blank",
                proxy=proxy,
                headless=headless,
                ttl_seconds=3600,
            )

        snapshot = ScenarioRunSnapshot(
            scenario_id=scenario.id,
            status="running",
            total_steps=len(scenario.steps),
            vars=dict(scenario.variables),
        )
        if initial_vars:
            snapshot.vars.update(initial_vars)

        ctx = ExecutionContext(
            scenario=scenario,
            instance=inst,
            run_id=snapshot.run_id,
            initial_vars=initial_vars,
            on_log=on_log,
        )
        self.active_runs[ctx.run_id] = ctx

        try:
            await self._run_steps(scenario.steps, ctx)
            ctx.status = "completed"
            snapshot.status = "completed"
        except asyncio.CancelledError:
            ctx.status = "aborted"
            ctx.error = "Execution was cancelled."
            snapshot.status = "aborted"
            snapshot.error = ctx.error
        except Exception as exc:
            ctx.status = "failed"
            ctx.error = str(exc)
            snapshot.status = "failed"
            snapshot.error = str(exc)
            logger.error("Scenario %s execution failed: %s", scenario.id, exc, exc_info=True)
        finally:
            snapshot.vars = dict(ctx.vars)
            snapshot.downloads = dict(ctx.downloads)
            snapshot.logs = list(ctx.logs)
            snapshot.finished_at = time.time()

            if is_ephemeral_instance and scenario.settings.close_on_complete:
                try:
                    await REGISTRY.kill(inst.id)
                except Exception as exc:
                    logger.debug("Failed closing ephemeral instance: %s", exc)

            ctx.cleanup()
            self.active_runs.pop(ctx.run_id, None)

        return snapshot

    async def _run_steps(self, steps: List[Step], ctx: ExecutionContext) -> None:
        for idx, step in enumerate(steps):
            if ctx.status == "aborted":
                raise ScenarioExecutionError("Scenario execution was aborted.")

            # 1. Check if-elif-else Conditional Block
            if step.is_conditional:
                await self._execute_conditional(step, ctx)
                continue

            # 2. Check Loop Block
            if step.is_loop:
                await self._execute_loop(step, ctx)
                continue

            # 3. Standard Action Execution with Retries
            await self._execute_action_step(step, ctx)

    async def _execute_conditional(self, step: Step, ctx: ExecutionContext) -> None:
        cond_str = step.if_cond or "False"
        try:
            result = bool(ctx.evaluate_expression(cond_str))
        except Exception as exc:
            raise ScenarioExecutionError(f"Error evaluating condition {cond_str!r}: {exc}") from exc

        if result:
            if step.then_steps:
                await self._run_steps(step.then_steps, ctx)
            return

        # Check elif blocks
        if step.elif_blocks:
            for elif_block in step.elif_blocks:
                try:
                    elif_res = bool(ctx.evaluate_expression(elif_block.condition))
                except Exception as exc:
                    raise ScenarioExecutionError(f"Error evaluating condition {elif_block.condition!r}: {exc}") from exc
                if elif_res:
                    if elif_block.steps:
                        await self._run_steps(elif_block.steps, ctx)
                    return

        # Fallback to else
        if step.else_steps:
            await self._run_steps(step.else_steps, ctx)

    async def _execute_loop(self, step: Step, ctx: ExecutionContext) -> None:
        if step.loop:
            loop_def = step.loop
            try:
                items = ctx.evaluate_expression(loop_def.over)
            except Exception as exc:
                raise ScenarioExecutionError(f"Error evaluating loop.over {loop_def.over!r}: {exc}") from exc

            if not hasattr(items, "__iter__"):
                raise ScenarioExecutionError(f"Loop expression {loop_def.over!r} did not evaluate to an iterable.")

            for item in items:
                if ctx.status == "aborted":
                    raise ScenarioExecutionError("Loop aborted.")
                ctx.vars[loop_def.as_var] = item
                await self._run_steps(loop_def.steps, ctx)

        elif step.while_loop:
            while_def = step.while_loop
            count = 0
            while count < while_def.max_iterations:
                if ctx.status == "aborted":
                    raise ScenarioExecutionError("While loop aborted.")
                try:
                    cond = bool(ctx.evaluate_expression(while_def.condition))
                except Exception as exc:
                    raise ScenarioExecutionError(f"Error evaluating while.condition {while_def.condition!r}: {exc}") from exc
                if not cond:
                    break
                await self._run_steps(while_def.steps, ctx)
                count += 1
            if count >= while_def.max_iterations:
                logger.warning("While loop reached safety limit (%d iterations).", while_def.max_iterations)

    async def _execute_action_step(self, step: Step, ctx: ExecutionContext) -> None:
        step_name = step.name or f"{step.action} on {step.selector or step.url or step.page}"
        timeout = (step.timeout_ms or ctx.scenario.settings.default_timeout_ms)

        retries_left = step.retries if step.on_error == "retry" else 0
        last_error = None

        while True:
            start_time = time.time()
            try:
                output = await self._dispatch_action(step, ctx, timeout)
                duration = int((time.time() - start_time) * 1000)
                await ctx.record_log(
                    StepExecutionLog(
                        step_name=step_name,
                        action=step.action,
                        page=step.page,
                        status="success",
                        duration_ms=duration,
                        output=output,
                    )
                )
                return
            except Exception as exc:
                last_error = exc
                duration = int((time.time() - start_time) * 1000)
                if retries_left > 0:
                    retries_left -= 1
                    await ctx.record_log(
                        StepExecutionLog(
                            step_name=step_name,
                            action=step.action,
                            page=step.page,
                            status="retrying",
                            duration_ms=duration,
                            error=str(exc),
                        )
                    )
                    await asyncio.sleep(step.retry_delay_ms / 1000.0)
                    continue

                # No more retries
                if step.on_error == "continue":
                    await ctx.record_log(
                        StepExecutionLog(
                            step_name=step_name,
                            action=step.action,
                            page=step.page,
                            status="skipped",
                            duration_ms=duration,
                            error=str(exc),
                        )
                    )
                    return
                else:  # abort
                    await ctx.record_log(
                        StepExecutionLog(
                            step_name=step_name,
                            action=step.action,
                            page=step.page,
                            status="failed",
                            duration_ms=duration,
                            error=str(exc),
                        )
                    )
                    raise ScenarioExecutionError(f"Step {step_name!r} failed: {exc}") from exc

    async def _dispatch_action(self, step: Step, ctx: ExecutionContext, timeout_ms: int) -> Any:
        action = step.action
        if not action:
            return None

        # Standalone context actions that do not require an active browser page
        if action == "set_var":
            if not step.save_to_var:
                raise ScenarioValidationError("set_var requires 'save_to_var'")
            val = step.value if step.value is not None else step.text
            if isinstance(val, str) and ("ctx." in val or "vars[" in val):
                try:
                    val = ctx.evaluate_expression(val)
                except Exception:
                    val = ctx.interpolate(val)
            else:
                val = ctx.interpolate(val)
            ctx.vars[step.save_to_var] = val
            return val

        if action == "delay":
            delay_sec = (step.delay_ms or 1000) / 1000.0
            await asyncio.sleep(delay_sec)
            return delay_sec

        if action == "pause":
            ctx.status = "paused"
            ctx.pause_prompt = step.prompt or "Scenario paused for user interaction."
            ctx.pause_event.clear()
            logger.info("Scenario run %s paused: %s", ctx.run_id, ctx.pause_prompt)
            pause_timeout = (step.timeout_ms or 120000) / 1000.0
            try:
                await asyncio.wait_for(ctx.pause_event.wait(), timeout=pause_timeout)
            except asyncio.TimeoutError:
                raise ScenarioExecutionError(f"Pause timed out after {pause_timeout}s without resume.")
            return True

        if action == "close_page":
            target_page_name = step.page
            await ctx.close_page(target_page_name)
            return target_page_name

        # Resolve target page for browser DOM/Navigation actions
        page = await ctx.get_or_create_page(step.page)

        # Interpolate arguments
        url = ctx.interpolate(step.url)
        selector = ctx.interpolate(step.selector)
        text = ctx.interpolate(step.text)
        value = ctx.interpolate(step.value)
        script = ctx.interpolate(step.script)
        attr = ctx.interpolate(step.attribute)
        wait_for = step.wait_for

        if action == "goto":
            if not url:
                raise ScenarioValidationError("goto action requires a 'url'")
            await page.goto(url, timeout=timeout_ms)
            return url

        elif action == "reload":
            await page.reload(timeout=timeout_ms)
            return True

        elif action == "delay":
            delay_sec = (step.delay_ms or 1000) / 1000.0
            await asyncio.sleep(delay_sec)
            return delay_sec

        elif action == "click":
            if not selector:
                raise ScenarioValidationError("click action requires a 'selector'")
            await page.click(selector, timeout=timeout_ms)
            if wait_for == "networkidle":
                await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return True

        elif action == "fill":
            if not selector:
                raise ScenarioValidationError("fill action requires a 'selector'")
            val_to_fill = str(value if value is not None else (text or ""))
            await page.fill(selector, val_to_fill, timeout=timeout_ms)
            return val_to_fill

        elif action == "type":
            if not selector:
                raise ScenarioValidationError("type action requires a 'selector'")
            val_to_type = str(value if value is not None else (text or ""))
            await page.type(selector, val_to_type, timeout=timeout_ms)
            return val_to_type

        elif action == "press":
            if not selector:
                raise ScenarioValidationError("press action requires a 'selector'")
            key_to_press = str(value if value is not None else (text or "Enter"))
            await page.press(selector, key_to_press, timeout=timeout_ms)
            return key_to_press

        elif action == "hover":
            if not selector:
                raise ScenarioValidationError("hover action requires a 'selector'")
            await page.hover(selector, timeout=timeout_ms)
            return True

        elif action == "check":
            if not selector:
                raise ScenarioValidationError("check action requires a 'selector'")
            await page.check(selector, timeout=timeout_ms)
            return True

        elif action == "select_option":
            if not selector:
                raise ScenarioValidationError("select_option action requires a 'selector'")
            val_opt = value or text
            await page.select_option(selector, val_opt, timeout=timeout_ms)
            return val_opt

        elif action == "scroll":
            delta_y = int(value or 500)
            await page.mouse.wheel(0, delta_y)
            return delta_y

        elif action == "wait_for_selector":
            if not selector:
                raise ScenarioValidationError("wait_for_selector requires a 'selector'")
            await page.wait_for_selector(selector, timeout=timeout_ms)
            return True

        elif action == "wait_for_load_state":
            state = wait_for or "load"
            await page.wait_for_load_state(state, timeout=timeout_ms)
            return state

        elif action == "extract_text":
            if selector:
                extracted = await page.locator(selector).text_content(timeout=timeout_ms)
            else:
                extracted = await page.inner_text("body")
            if step.save_to_var:
                ctx.vars[step.save_to_var] = extracted
            return extracted

        elif action == "extract_html":
            if selector:
                extracted = await page.locator(selector).inner_html(timeout=timeout_ms)
            else:
                extracted = await page.content()
            if step.save_to_var:
                ctx.vars[step.save_to_var] = extracted
            return extracted

        elif action == "extract_attribute":
            if not selector or not attr:
                raise ScenarioValidationError("extract_attribute requires both 'selector' and 'attribute'")
            extracted = await page.locator(selector).get_attribute(attr, timeout=timeout_ms)
            if step.save_to_var:
                ctx.vars[step.save_to_var] = extracted
            return extracted

        elif action == "assert_exists":
            if not selector:
                raise ScenarioValidationError("assert_exists requires a 'selector'")
            count = await page.locator(selector).count()
            if count == 0:
                raise AssertionError(f"Element matching {selector!r} does not exist.")
            if step.save_to_var:
                ctx.vars[step.save_to_var] = True
            return True

        elif action == "assert_text":
            if not selector:
                raise ScenarioValidationError("assert_text requires a 'selector'")
            actual = await page.locator(selector).text_content(timeout=timeout_ms) or ""
            expected = str(value if value is not None else text)
            if expected not in actual:
                raise AssertionError(f"Expected text {expected!r} not found in element {actual!r}.")
            return True

        elif action == "screenshot":
            import base64

            jpeg_bytes = await page.screenshot(type="jpeg", quality=75)
            encoded = f"data:image/jpeg;base64,{base64.b64encode(jpeg_bytes).decode('utf-8')}"
            if step.save_to_var:
                ctx.vars[step.save_to_var] = encoded
            return encoded[:60] + "..."

        elif action == "evaluate_js":
            if not script:
                raise ScenarioValidationError("evaluate_js requires a 'script'")
            res = await page.evaluate(script)
            if step.save_to_var:
                ctx.vars[step.save_to_var] = res
            return res

        elif action == "download_file":
            if not selector:
                raise ScenarioValidationError("download_file requires a trigger 'selector'")
            async with page.expect_download(timeout=timeout_ms) as download_info:
                await page.click(selector, timeout=timeout_ms)
            download = await download_info.value
            target_name = ctx.interpolate(step.save_to_file) or download.suggested_filename
            dest_path = ctx.downloads_dir / target_name
            await download.save_as(str(dest_path))
            ctx.downloads[target_name] = str(dest_path)
            if step.save_to_var:
                ctx.vars[step.save_to_var] = str(dest_path)
            return str(dest_path)

        elif action == "upload_file":
            if not selector:
                raise ScenarioValidationError("upload_file requires a 'selector'")
            raw_files = step.files or ([value] if value else [])
            if not raw_files:
                raise ScenarioValidationError("upload_file requires 'files'")

            resolved_files: List[str] = []
            for item in raw_files:
                interpolated = str(ctx.interpolate(item))
                # Check downloads dictionary
                if interpolated in ctx.downloads:
                    resolved_files.append(ctx.downloads[interpolated])
                elif Path(interpolated).is_file():
                    resolved_files.append(interpolated)
                else:
                    # Check downloads_dir
                    candidate = ctx.downloads_dir / interpolated
                    if candidate.is_file():
                        resolved_files.append(str(candidate))
                    else:
                        raise FileNotFoundError(f"File to upload {interpolated!r} was not found.")

            await page.set_input_files(selector, resolved_files, timeout=timeout_ms)
            return resolved_files

        else:
            raise ScenarioValidationError(f"Unknown action {action!r}")


ENGINE = ScenarioEngine()
