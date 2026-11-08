"""JSON schemas for the four camoufox model tools."""

from __future__ import annotations

CAMOUFOX_NAVIGATE_SCHEMA = {
    "description": "Launch a Camoufox browser instance and navigate to a URL.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["guest", "persistent"],
                "default": "guest",
            },
            "profile": {
                "type": "string",
                "description": "Profile name (persistent mode only).",
            },
            "url": {"type": "string", "description": "URL to navigate to."},
            "proxy": {
                "type": "object",
                "description": "Proxy spec {server,username,password,bypass}.",
            },
            "headless": {
                "type": "boolean",
                "description": "Headless flag (default from settings).",
            },
            "ttl_seconds": {"type": "integer", "description": "Idle TTL override."},
        },
        "additionalProperties": False,
    },
}

CAMOUFOX_ACTION_SCHEMA = {
    "description": "Perform a browser action on an existing instance (click, fill, type, hover, scroll, evaluate).",
    "parameters": {
        "type": "object",
        "properties": {
            "instance_id": {"type": "string"},
            "action": {
                "type": "string",
                "enum": ["click", "fill", "type", "hover", "scroll", "evaluate"],
            },
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "value": {"type": "string"},
            "script": {"type": "string"},
        },
        "required": ["instance_id", "action"],
        "additionalProperties": False,
    },
}

CAMOUFOX_EXTRACT_SCHEMA = {
    "description": "Extract content from a page (title, url, html, text, screenshot).",
    "parameters": {
        "type": "object",
        "properties": {
            "instance_id": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["title", "url", "html", "text", "screenshot"],
                "default": "text",
            },
            "selector": {"type": "string"},
        },
        "required": ["instance_id"],
        "additionalProperties": False,
    },
}

CAMOUFOX_CLOSE_SCHEMA = {
    "description": "Close a Camoufox browser instance and release its resources.",
    "parameters": {
        "type": "object",
        "properties": {"instance_id": {"type": "string"}},
        "required": ["instance_id"],
        "additionalProperties": False,
    },
}

CAMOUFOX_LIST_SCENARIOS_SCHEMA = {
    "description": "List all saved declarative browser scenarios available in Camoufox.",
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

CAMOUFOX_INSPECT_SCENARIO_SCHEMA = {
    "description": "Get detailed step definition, variables, and logic of a scenario.",
    "parameters": {
        "type": "object",
        "properties": {
            "scenario_id": {"type": "string", "description": "Scenario ID to inspect."},
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
}

CAMOUFOX_RUN_SCENARIO_SCHEMA = {
    "description": "Execute a declarative browser scenario with parameters (supporting if/else, loops, multi-tab, and file upload).",
    "parameters": {
        "type": "object",
        "properties": {
            "scenario_id": {"type": "string", "description": "The scenario ID to run."},
            "variables": {
                "type": "object",
                "description": "Dynamic variable overrides for the scenario run (key-value pairs).",
            },
            "instance_id": {
                "type": "string",
                "description": "Optional existing instance ID to run on. If omitted, launches an isolated instance.",
            },
            "mode": {
                "type": "string",
                "enum": ["guest", "persistent"],
                "default": "guest",
                "description": "Browser session mode if launching a new instance.",
            },
            "profile": {
                "type": "string",
                "description": "Profile name (if mode is persistent).",
            },
            "headless": {
                "type": "boolean",
                "description": "Headless browser flag (defaults to plugin setting).",
            },
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
}

CAMOUFOX_SAVE_SCENARIO_SCHEMA = {
    "description": "Save or update a declarative browser scenario (in YAML or JSON format).",
    "parameters": {
        "type": "object",
        "properties": {
            "scenario": {
                "type": "object",
                "description": "Full scenario specification object containing id, name, description, variables, settings, and steps.",
            },
        },
        "required": ["scenario"],
        "additionalProperties": False,
    },
}

CAMOUFOX_DELETE_SCENARIO_SCHEMA = {
    "description": "Delete a scenario from storage.",
    "parameters": {
        "type": "object",
        "properties": {
            "scenario_id": {"type": "string", "description": "Scenario ID to delete."},
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
}
