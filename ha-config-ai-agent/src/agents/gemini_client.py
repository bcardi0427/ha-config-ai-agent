"""Native Gemini API client for Gemini 3 and later models.

Corrected Schema for 0.4.6:
1. Role 'model' -> parts with 'functionCall' AND 'thoughtSignature' (sibling).
2. Role 'user' -> parts with 'functionResponse' (grouped, NO signature).
"""

import json
import logging
import aiohttp
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    """Native Gemini API client for Gemini 3+."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        temperature: Optional[float] = None,
    ):
        self.api_key = api_key
        self.model = model.split('/')[-1] if '/' in model else model
        self.temperature = temperature
        self.endpoint = f"{GEMINI_API_BASE}/models/{self.model}:generateContent"
        self.stream_endpoint = f"{GEMINI_API_BASE}/models/{self.model}:streamGenerateContent"
        
        logger.info(f"Initialized native Gemini 3 client (v0.4.6): {self.model}")

    def _build_tools(self, tool_definitions: List[Dict]) -> List[Dict]:
        """Convert OpenAI tools to Gemini format."""
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
        """Convert message components to Gemini Parts."""
        parts = []
        role = msg.get("role")
        
        # --- 1. Text Content ---
        content = msg.get("content")
        if content:
            text_part = {}
            if isinstance(content, str):
                text_part["text"] = content
            elif isinstance(content, list):
                # Flatten list content to single text part if possible, or multiple
                full_text = ""
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        full_text += item.get("text", "")
                if full_text:
                    text_part["text"] = full_text
            
            if text_part:
                # Attach signature to text part if present (rare but possible per docs)
                sig = msg.get("thought_signature") or msg.get("thoughtSignature")
                if sig and role == "assistant":
                    text_part["thoughtSignature"] = sig
                parts.append(text_part)

        # --- 2. Function Calls (Model Role) ---
        if role == "assistant" and "tool_calls" in msg:
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except:
                    args = {}
                
                part = {
                    "functionCall": {
                        "name": func.get("name", ""),
                        "args": args
                    }
                }
                
                # CRITICAL: thoughtSignature goes HERE (sibling to functionCall)
                sig = tc.get("thought_signature") or tc.get("thoughtSignature")
                # Fallback to message level if not on specific tool call
                if not sig:
                     sig = msg.get("thought_signature") or msg.get("thoughtSignature")
                
                if sig:
                    part["thoughtSignature"] = sig
                
                parts.append(part)

        # --- 3. Function Responses (User Role) ---
        if role == "tool":
            func_name = msg.get("function_name")
            if not func_name:
                # Fallback extraction
                tool_call_id = msg.get("tool_call_id", "")
                func_name = tool_call_id.split("_")[0] if "_" in tool_call_id else tool_call_id
            
            content_str = msg.get("content", "{}")
            try:
                response_data = json.loads(content_str) if isinstance(content_str, str) else content_str
            except:
                response_data = {"result": content_str}
            
            # CRITICAL: NO thoughtSignature on functionResponse parts
            parts.append({
                "functionResponse": {
                    "name": func_name,
                    "response": response_data
                }
            })

        return parts

    def _build_contents(self, messages: List[Dict]) -> List[Dict]:
        """Group messages into alternating 'user' and 'model' turns."""
        contents = []
        
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system": continue
            
            # Map to Gemini Roles: 'assistant' -> 'model', everything else -> 'user'
            gemini_role = "model" if role == "assistant" else "user"
            
            new_parts = self._msg_to_parts(msg)
            if not new_parts: continue
            
            # Grouping Logic:
            # If the last content block has the SAME role, append parts to it.
            # This handles:
            # - Multiple tool results (Role 'user') being merged into one turn.
            # - Model text + function calls being merged (if split in history).
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].extend(new_parts)
            else:
                contents.append({
                    "role": gemini_role,
                    "parts": new_parts
                })
        
        return contents

    async def generate_content_stream(
        self,
        messages: List[Dict],
        tools: List[Dict],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming handler."""
        try:
            contents = self._build_contents(messages)
            
            request_body = {
                "contents": contents,
                "tools": self._build_tools(tools)
            }
            
            # Handle System Prompt
            for msg in messages:
                if msg.get("role") == "system":
                    request_body["systemInstruction"] = {"parts": [{"text": msg.get("content", " ")}]}
                    break

            if self.temperature is not None:
                request_body["generationConfig"] = {"temperature": self.temperature}
            
            url = f"{self.stream_endpoint}?key={self.api_key}&alt=sse"
            logger.debug(f"[GEMINI] REQ Body (Trunk): {json.dumps(request_body)[:500]}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=request_body) as response:
                    if response.status != 200:
                        err = await response.text()
                        logger.error(f"[GEMINI] HTTP {response.status}: {err}")
                        yield {"type": "error", "error": f"API {response.status}: {err}"}
                        return
                    
                    accum_text = ""
                    accum_tool_calls = []
                    msg_thought_sig = None
                    
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if not line.startswith('data: '): continue
                        
                        try:
                            chunk = json.loads(line[6:])
                            candidates = chunk.get("candidates", [])
                            if not candidates: continue
                            
                            content_obj = candidates[0].get("content", {})
                            parts = content_obj.get("parts", [])
                            
                            # Try to find signature in the content object or parts
                            # Note: API might send it in oddly placed fields, check everywhere
                            
                            for part in parts:
                                sig = part.get("thoughtSignature") or part.get("thought_signature")
                                if sig: msg_thought_sig = sig
                                
                                if "text" in part:
                                    t = part["text"]
                                    accum_text += t
                                    yield {"type": "content", "content": t}
                                
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
                                    # Attach signature to tool call for storage
                                    if sig: tc["thought_signature"] = sig
                                    elif msg_thought_sig: tc["thought_signature"] = msg_thought_sig
                                    
                                    accum_tool_calls.append(tc)
                                    yield {"type": "tool_call", "tool_call": tc}
                            
                            # Usage metadata
                            if "usageMetadata" in chunk:
                                usage = chunk["usageMetadata"]
                                yield {
                                    "type": "complete",
                                    "content": accum_text,
                                    "tool_calls": accum_tool_calls,
                                    "thought_signature": msg_thought_sig,
                                    "usage": {
                                        "prompt_tokens": usage.get("promptTokenCount", 0),
                                        "total_tokens": usage.get("totalTokenCount", 0),
                                    },
                                    "finish_reason": "tool_calls" if accum_tool_calls else "stop"
                                }

                        except Exception as e:
                           logger.error(f"Stream Parse Error: {e}")
                           continue
            
        except Exception as e:
            logger.error(f"[GEMINI] Stream Critical: {e}", exc_info=True)
            yield {"type": "error", "error": str(e)}

    async def generate_content(self, messages: List[Dict], tools: List[Dict]) -> Dict[str, Any]:
        result = {"content": "", "tool_calls": [], "usage": {}}
        async for event in self.generate_content_stream(messages, tools):
            if event["type"] == "content": result["content"] += event["content"]
            elif event["type"] == "tool_call": result["tool_calls"].append(event["tool_call"])
            elif event["type"] == "complete":
                result.update({"usage": event["usage"], "thought_signature": event.get("thought_signature")})
        return result


def is_gemini_model(model: str) -> bool:
    m = model.split('/')[-1] if '/' in model else model
    return m.startswith("gemini-")


def is_gemini_3_model(model: str) -> bool:
    m = model.split('/')[-1] if '/' in model else model
    return any(m.startswith(p) for p in ["gemini-3", "gemini-4", "gemini-5"])
