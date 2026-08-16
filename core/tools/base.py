"""
Tool registry.

A tool declares its arguments once, as a Pydantic model. The Gemini function
declaration is derived from that model, so the schema and the implementation
can never drift apart (they used to be written twice, by hand).
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from google.genai import types
from pydantic import BaseModel, ValidationError

from core.workspace import Workspace


@dataclass
class ToolResult:
    """What a tool reports back."""

    message: str
    ok: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # what the model sees
        return self.message


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch during a run."""

    workspace: Workspace
    finished: Optional[Dict[str, Any]] = None
    question: Optional[str] = None


ToolFn = Callable[[ToolContext, BaseModel], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: Type[BaseModel]
    fn: ToolFn

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=pydantic_to_genai_schema(self.args_model),
        )

    def run(self, ctx: ToolContext, raw_args: Dict[str, Any]) -> ToolResult:
        try:
            args = self.args_model(**(raw_args or {}))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}"
                for err in exc.errors()
            )
            return ToolResult(f"Error: invalid arguments for '{self.name}' ({problems})", ok=False)
        except TypeError as exc:
            return ToolResult(f"Error: invalid arguments for '{self.name}' ({exc})", ok=False)

        try:
            return self.fn(ctx, args)
        except Exception as exc:  # noqa: BLE001 - reported to the model, never fatal
            return ToolResult(f"Error: {self.name} failed: {exc}", ok=False)


class ToolRegistry:
    """Holds the tools available to a run."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def gemini_tool(self) -> types.Tool:
        return types.Tool(
            function_declarations=[self._tools[name].declaration() for name in self.names()]
        )


REGISTRY = ToolRegistry()


def tool(name: str, description: str, args_model: Type[BaseModel]) -> Callable[[ToolFn], ToolFn]:
    """Decorator registering a function as an agent tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        REGISTRY.register(
            ToolSpec(name=name, description=description, args_model=args_model, fn=fn)
        )
        return fn

    return decorator


# --- Pydantic JSON schema -> Gemini schema ----------------------------------

_TYPE_MAP = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _resolve(node: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
    """Follow $ref and collapse Optional[...] unions to their concrete branch."""
    if "$ref" in node:
        ref_name = node["$ref"].rsplit("/", 1)[-1]
        resolved = dict(defs.get(ref_name, {}))
        resolved.update({k: v for k, v in node.items() if k != "$ref"})
        return resolved

    for key in ("anyOf", "oneOf"):
        if key in node:
            branches = [b for b in node[key] if b.get("type") != "null"]
            if branches:
                merged = _resolve(branches[0], defs)
                if "description" in node:
                    merged.setdefault("description", node["description"])
                return merged
    return node


def _convert(node: Dict[str, Any], defs: Dict[str, Any]) -> types.Schema:
    node = _resolve(node, defs)

    enum_values = node.get("enum")
    json_type = node.get("type") or ("string" if enum_values else "object")
    schema_type = _TYPE_MAP.get(json_type, types.Type.STRING)

    schema = types.Schema(type=schema_type)
    if node.get("description"):
        schema.description = node["description"]
    if enum_values:
        schema.enum = [str(value) for value in enum_values]

    if schema_type == types.Type.ARRAY:
        schema.items = _convert(node.get("items", {"type": "string"}), defs)

    if schema_type == types.Type.OBJECT:
        properties = node.get("properties", {})
        if properties:
            schema.properties = {
                key: _convert(value, defs) for key, value in properties.items()
            }
        required = node.get("required")
        if required:
            schema.required = list(required)

    return schema


def pydantic_to_genai_schema(model: Type[BaseModel]) -> types.Schema:
    """Build a Gemini parameter schema from a Pydantic model."""
    json_schema = model.model_json_schema()
    defs = json_schema.get("$defs", {})
    return _convert(json_schema, defs)
