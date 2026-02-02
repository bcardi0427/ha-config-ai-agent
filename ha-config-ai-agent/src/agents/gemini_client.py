"""Native Gemini API client for Gemini 3 and later models.

This module provides native Gemini API support using direct HTTP requests,
which is required for proper function calling with Gemini 3 models that
use the thought_signature mechanism.

Gemini 3+ enforces thought_signature pass-through:
1. When Gemini returns a response, it may include a thought_signature in any part.
2. For parallel tool calls, the signature is only on the FIRST part.
3. We MUST echo these signatures back exactly in the history.
4. Parallel function responses MUST be grouped together (not interleaved).
"""

import json
import logging
import aiohttp
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    """Native Gemini API client with proper thought_signature handling for Gemini 3+."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        temperature: Optional[float] = None,
    ):
        """Initialize the Gemini client."""
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.endpoint = f"{GEMINI_API_BASE}/models/{model}:generateContent"
        self.stream_endpoint = f"{GEMINI_API_BASE}/models/{model}:streamGenerateContent"
        
        logger.info(f"Initialized native Gemini client with model: {model}")

    def _build_tools(self, tool_definitions: List[Dict]) -> List[Dict]:
        """Convert OpenAI-style tool definitions to Gemini format."""
        function_declarations = []
        for tool in tool_definitions:
            if tool.get("type") == "function":
                func = tool["function"]
                function_declarations.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {})
                })
        return [{"functionDeclarations": function_declarations}]

    def _msg_to_parts(self, msg: Dict) -> List[Dict]:
        """Convert a single OpenAI-style message into one or more Gemini parts."""
        parts = []
        role = msg.get("role")
        content = msg.get("content")

        # 1. Handle Text Content
        if content:
            if isinstance(content, str):
                part = {"text": content}
                # Preserve thought_signature for text parts if present
                if msg.get("thought_signature"):
                    part["thought_signature"] = msg["thought_signature"]
                parts.append(part)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        part = {"text": item.get("text", "")}
                        if msg.get("thought_signature"): # Attach to first text part
                             part["thought_signature"] = msg["thought_signature"]
                        parts.append(part)

        # 2. Handle Function Calls (Assistant Role)
        if role == "assistant" and "tool_calls" in msg:
            for i, tc in enumerate(msg.get("tool_calls", [])):
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {}
                
                fc_part = {
                    "functionCall": {
                        "name": func.get("name", ""),
                        "args": args
                    }
                }
                
                # Echo thought_signature if it was provided
                # Note: For parallel calls, it's usually only on the first part
                thought_sig = tc.get("thought_signature")
                if thought_sig:
                    fc_part["functionCall"]["thought_signature"] = thought_sig
                
                parts.append(fc_part)

        # 3. Handle Function Responses (Tool Role)
        if role == "tool":
            func_name = msg.get("function_name")
            if not func_name:
                tool_call_id = msg.get("tool_call_id", "")
                func_name = tool_call_id.split("_")[0] if "_" in tool_call_id else tool_call_id
            
            content_str = msg.get("content", "{}")
            try:
                response_data = json.loads(content_str) if isinstance(content_str, str) else content_str
            except json.JSONDecodeError:
                response_data = {"result": content_str}
            
            parts.append({
                "functionResponse": {
                    "name": func_name,
                    "response": response_data
                }
            })

        return parts

    def _build_contents(self, messages: List[Dict]) -> List[Dict]:
        """Convert OpenAI messages to Gemini format with role grouping."""
        contents = []
        last_role = None
        current_content = None

        for msg in messages:
            role = msg.get("role", "user")
            
            if role == "system": continue
            
            # Map roles: system/user -> user, assistant -> model, tool -> function
            gemini_role = "model" if role == "assistant" else ("function" if role == "tool" else "user")

            # Gemini requires alternating roles (user/model). 
            # Sequential 'function' roles MUST be grouped into a single content block.
            if current_content and gemini_role == last_role:
                parts = self._msg_to_parts(msg)
                current_content["parts"].extend(parts)
            else:
                parts = self._msg_to_parts(msg)
                if parts:
                    current_content = {"role": gemini_role, "parts": parts}
                    contents.append(current_content)
                    last_role = gemini_role
        
        return contents

    async def generate_content_stream(
        self,
        messages: List[Dict],
        tools: List[Dict],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming generator that handles Gemini 3's strict signature requirements."""
        try:
            contents = self._build_contents(messages)
            request_body = {
                "contents": contents,
                "tools": self._build_tools(tools)
            }
            
            # Add system instruction if present
            for msg in messages:
                if msg.get("role") == "system":
                    request_body["systemInstruction"] = {"parts": [{"text": msg.get("content", "")}]}
                    break

            if self.temperature is not None:
                request_body["generationConfig"] = {"temperature": self.temperature}
            
            url = f"{self.stream_endpoint}?key={self.api_key}&alt=sse"
            logger.info(f"[GEMINI] Calling {self.model}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=request_body) as response:
                    if response.status != 200:
                        err = await response.text()
                        logger.error(f"[GEMINI] API Error {response.status}: {err}")
                        yield {"type": "error", "error": f"API Error {response.status}: {err[:500]}"}
                        return
                    
                    accum_text = ""
                    accum_tool_calls = []
                    msg_thought_sig = None  # Signature for the overall message/text
                    
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if not line.startswith('data: '): continue
                        
                        try:
                            chunk = json.loads(line[6:])
                            for candidate in chunk.get("candidates", []):
                                content_obj = candidate.get("content", {})
                                for part in content_obj.get("parts", []):
                                    # Capture signatures from ANY part
                                    # Support both variants: thought_signature and thoughtSignature
                                    sig = part.get("thought_signature") or part.get("thoughtSignature")
                                    
                                    if "text" in part:
                                        if sig: msg_thought_sig = sig
                                        accum_text += part["text"]
                                        yield {"type": "content", "content": part["text"]}
                                    
                                    if "functionCall" in part:
                                        fc = part["functionCall"]
                                        tc = {
                                            "id": f"{fc['name']}_{len(accum_tool_calls)}",
                                            "type": "function",
                                            "function": {
                                                "name": fc["name"],
                                                "arguments": json.dumps(fc.get("args", {}))
                                            }
                                        }
                                        if sig: tc["thought_signature"] = sig
                                        accum_tool_calls.append(tc)
                                        yield {"type": "tool_call", "tool_call": tc}
                            
                            if "usageMetadata" in chunk:
                                usage = chunk["usageMetadata"]
                                yield {
                                    "type": "complete",
                                    "content": accum_text,
                                    "tool_calls": accum_tool_calls,
                                    "thought_signature": msg_thought_sig,
                                    "usage": {
                                        "prompt_tokens": usage.get("promptTokenCount", 0),
                                        "completion_tokens": usage.get("candidatesTokenCount", 0),
                                        "total_tokens": usage.get("totalTokenCount", 0),
                                    },
                                    "finish_reason": "tool_calls" if accum_tool_calls else "stop"
                                }
                        except Exception as e:
                            logger.debug(f"[GEMINI] Chunk parse error: {e}")
            
        except Exception as e:
            logger.error(f"[GEMINI] Stream error: {e}", exc_info=True)
            yield {"type": "error", "error": str(e)}

    async def generate_content(self, messages: List[Dict], tools: List[Dict]) -> Dict[str, Any]:
        result = {"content": "", "tool_calls": [], "usage": {}, "thought_signature": None}
        async for event in self.generate_content_stream(messages, tools):
            if event["type"] == "content": result["content"] += event["content"]
            elif event["type"] == "tool_call": result["tool_calls"].append(event["tool_call"])
            elif event["type"] == "complete":
                result.update({
                    "usage": event["usage"],
                    "thought_signature": event.get("thought_signature"),
                    "finish_reason": event["finish_reason"]
                })
        return result


def is_gemini_model(model: str) -> bool:
    return model.startswith("gemini-")


def is_gemini_3_model(model: str) -> bool:
    return any(model.startswith(p) for p in ["gemini-3", "gemini-4"])
