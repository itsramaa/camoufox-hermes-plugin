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
