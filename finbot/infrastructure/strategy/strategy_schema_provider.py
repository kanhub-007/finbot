"""StrategySchemaProvider — canonical strategy JSON schema."""


class StrategySchemaProvider:
    """Provide the canonical JSON Schema for strategy definitions."""

    def get_schema(self) -> dict:
        """Return the strategy definition JSON Schema."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://finbar.local/schemas/strategy-definition.schema.json",
            "title": "Finbar Strategy Definition",
            "type": "object",
            "required": ["schema_version", "name", "sides"],
            "additionalProperties": True,
            "properties": {
                "schema_version": {"const": "2.0"},
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "parameters": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "required": ["type", "default"],
                        "properties": {
                            "type": {"enum": ["int", "float", "bool", "string"]},
                            "default": {},
                            "minimum": {"type": "number"},
                            "maximum": {"type": "number"},
                            "description": {"type": "string"},
                        },
                    },
                },
                "timeframes": {"$ref": "#/$defs/timeframes"},
                "indicators": {"type": "array"},
                "features": {"type": "array"},
                "risk": {
                    "type": "object",
                    "properties": {
                        "stop_loss": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "type": {"enum": ["none", "atr", "fixed_pct"]},
                                "pct": {},
                                "multiplier": {},
                                "indicator": {"type": "string"},
                            },
                        },
                        "take_profit": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "type": {
                                    "enum": ["none", "atr", "fixed_pct", "risk_reward"]
                                },
                                "pct": {},
                                "ratio": {},
                                "multiplier": {},
                                "indicator": {"type": "string"},
                            },
                        },
                    },
                },
                "sides": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {
                        "type": "object",
                        "required": ["entry"],
                        "properties": {
                            "entry": {"$ref": "#/$defs/side_spec"},
                            "exit": {"$ref": "#/$defs/side_spec"},
                            "direction": {"type": "string"},
                            "entry_confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "exit_confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                    },
                },
                "metadata": {"type": "object"},
            },
            "$defs": {
                "side_spec": {
                    "oneOf": [
                        {"$ref": "#/$defs/condition_group"},
                        {
                            "type": "object",
                            "required": ["condition"],
                            "properties": {
                                "condition": {"$ref": "#/$defs/condition_group"}
                            },
                        },
                    ],
                },
                "condition_group": {
                    "oneOf": [
                        {
                            "type": "object",
                            "required": ["all"],
                            "properties": {
                                "all": {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/condition_group"},
                                }
                            },
                        },
                        {
                            "type": "object",
                            "required": ["any"],
                            "properties": {
                                "any": {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/condition_group"},
                                }
                            },
                        },
                        {
                            "type": "object",
                            "required": ["not"],
                            "properties": {"not": {"$ref": "#/$defs/condition_group"}},
                        },
                        {"$ref": "#/$defs/atomic_condition"},
                    ],
                },
                "atomic_condition": {
                    "type": "object",
                    "required": ["operator", "left"],
                    "properties": {
                        "operator": {"$ref": "#/$defs/operators"},
                        "left": {},
                        "right": {},
                    },
                },
                "timeframes": {
                    "type": "object",
                    "required": ["primary"],
                    "properties": {
                        "primary": {"type": "string"},
                        "informative": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "required": ["alias", "interval"],
                                "properties": {
                                    "alias": {"type": "string", "minLength": 1},
                                    "interval": {"type": "string", "minLength": 1},
                                },
                            },
                        },
                    },
                },
                "operators": {
                    "enum": [
                        "<",
                        ">",
                        "<=",
                        ">=",
                        "==",
                        "!=",
                        "crosses_above",
                        "crosses_below",
                        "between",
                        "not_between",
                        "is_true",
                        "is_false",
                        "exists",
                        "missing",
                    ]
                },
            },
        }
