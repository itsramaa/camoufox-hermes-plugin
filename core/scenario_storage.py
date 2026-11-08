"""Filesystem storage manager for Camoufox scenarios."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .exceptions import ScenarioNotFoundError, ScenarioValidationError
from .scenario_models import ScenarioDefinition

logger = logging.getLogger(__name__)

ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


class ScenarioStorage:
    """Manages scenario YAML/JSON files on disk."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        if storage_dir is None:
            self.storage_dir = Path(__file__).resolve().parent.parent / "scenarios"
        else:
            self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _safe_id(self, scenario_id: str) -> str:
        clean = scenario_id.strip()
        if not ID_PATTERN.match(clean):
            raise ScenarioValidationError(
                f"Invalid scenario ID {scenario_id!r}. Only alphanumeric, dash, and underscore allowed."
            )
        return clean

    def _file_path(self, scenario_id: str) -> Path:
        clean = self._safe_id(scenario_id)
        yaml_path = self.storage_dir / f"{clean}.yaml"
        if yaml_path.is_file():
            return yaml_path
        yml_path = self.storage_dir / f"{clean}.yml"
        if yml_path.is_file():
            return yml_path
        json_path = self.storage_dir / f"{clean}.json"
        if json_path.is_file():
            return json_path
        return yaml_path

    def list(self) -> List[Dict[str, Any]]:
        """List summary metadata of all available scenarios."""
        summaries: List[Dict[str, Any]] = []
        for file in sorted(self.storage_dir.iterdir()):
            if not file.is_file() or file.suffix.lower() not in (".yaml", ".yml", ".json"):
                continue
            try:
                content = file.read_text(encoding="utf-8")
                if file.suffix.lower() == ".json":
                    data = json.loads(content)
                else:
                    data = yaml.safe_load(content)
                if isinstance(data, dict):
                    summaries.append(
                        {
                            "id": data.get("id", file.stem),
                            "name": data.get("name", file.stem),
                            "description": data.get("description", ""),
                            "variables": list(data.get("variables", {}).keys()),
                            "steps_count": len(data.get("steps", [])),
                            "filename": file.name,
                        }
                    )
            except Exception as exc:
                logger.warning("Failed reading scenario %s: %s", file.name, exc)
        return summaries

    def get(self, scenario_id: str) -> ScenarioDefinition:
        """Load and parse a scenario by ID."""
        path = self._file_path(scenario_id)
        if not path.is_file():
            raise ScenarioNotFoundError(f"Scenario {scenario_id!r} not found.")

        try:
            content = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".json":
                raw = json.loads(content)
            else:
                raw = yaml.safe_load(content)
            return ScenarioDefinition.model_validate(raw)
        except Exception as exc:
            if isinstance(exc, ScenarioNotFoundError):
                raise
            raise ScenarioValidationError(f"Invalid scenario format in {path.name}: {exc}") from exc

    def save(self, data: ScenarioDefinition | dict[str, Any]) -> ScenarioDefinition:
        """Create or update a scenario definition."""
        if isinstance(data, dict):
            scenario = ScenarioDefinition.model_validate(data)
        else:
            scenario = data

        clean_id = self._safe_id(scenario.id)
        path = self.storage_dir / f"{clean_id}.yaml"

        dumped = scenario.model_dump(by_alias=True, exclude_none=True)
        yaml_content = yaml.dump(dumped, sort_keys=False, allow_unicode=True)
        path.write_text(yaml_content, encoding="utf-8")
        return scenario

    def delete(self, scenario_id: str) -> bool:
        """Delete a scenario file."""
        path = self._file_path(scenario_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    def seed_defaults_if_empty(self) -> None:
        """Seed a representative example scenario if none exists."""
        if any(self.storage_dir.glob("*.yaml")) or any(self.storage_dir.glob("*.json")):
            return

        example = ScenarioDefinition(
            id="sample-google-search",
            name="Sample: Google Search & Extract",
            description="Navigates to Google, searches for a query, extracts results with if-check.",
            variables={"query": "Nous Research Hermes", "max_results": 3},
            steps=[
                {
                    "name": "Navigate to Google",
                    "action": "goto",
                    "url": "https://www.google.com",
                },
                {
                    "name": "Check Search Box",
                    "action": "wait_for_selector",
                    "selector": "textarea[name='q'], input[name='q']",
                    "timeout_ms": 10000,
                },
                {
                    "name": "Type Query",
                    "action": "fill",
                    "selector": "textarea[name='q'], input[name='q']",
                    "value": "{{query}}",
                },
                {
                    "name": "Submit Search",
                    "action": "press",
                    "selector": "textarea[name='q'], input[name='q']",
                    "value": "Enter",
                    "wait_for": "domcontentloaded",
                },
                {
                    "name": "Extract Search Results Title",
                    "action": "extract_text",
                    "selector": "title",
                    "save_to_var": "page_title",
                },
                {
                    "if": "'Hermes' in ctx.vars.get('page_title', '')",
                    "then": [
                        {
                            "name": "Log Success",
                            "action": "set_var",
                            "save_to_var": "search_status",
                            "value": "found_matching_keyword",
                        }
                    ],
                    "else": [
                        {
                            "name": "Log Fallback",
                            "action": "set_var",
                            "save_to_var": "search_status",
                            "value": "keyword_not_in_title",
                        }
                    ],
                },
            ],
        )
        self.save(example)


STORAGE = ScenarioStorage()
