"""Native Gemini API client for Gemini 3 and later models.

This module provides native Gemini API support using direct HTTP requests,
which is required for proper function calling with Gemini 3 models that
use the thought_signature mechanism.
"""

import json
import logging
import aiohttp
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    """Native Gemini API client with fixed role/signature schema for Gemini 3+."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        temperature: Optional[float] = None,
    ):
        """Initialize the Gemini client."""
        self.api_key = api_key
        # Clean model name (remove provider prefix)
        self.model = model.split('/')[-1] if '/' in model else model
        self.temperature = temperature
        self.endpoint = f"{GEMINI_API_BASE}/models/{self.model}:generateContent"
        self.stream_endpoint = f"{GEMINI_API_BASE}/models/{self.model}:streamGenerateContent"
        
        logger.info(f"Initialized native Gemini client for {self.model}")

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
        content = msg.get("content")

        # 1. Text
        if content:
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append({"text": item.get("text", "")})

        # 2. Assistant Function Calls
        if role == "assistant" and "tool_calls" in msg:
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except:
                    args = {}
                
                parts.append({
                    "functionCall": {
                        "name": func.get("name", ""),
                        "args": args
                    }
                })

        # 3. Tool Responses (Results)
        if role == "tool":
            func_name = msg.get("function_name")
            if not func_name:
                tool_call_id = msg.get("tool_call_id", "")
                func_name = tool_call_id.split("_")[0] if "_" in tool_call_id else tool_call_id
            
            content_str = msg.get("content", "{}")
            try:
                response_data = json.loads(content_str) if isinstance(content_str, str) else content_str
            except:
                response_data = {"result": content_str}
            
            parts.append({
                "functionResponse": {
                    "name": func_name,
                    "response": response_data
                }
            })

        return parts

    def _build_contents(self, messages: List[Dict]) -> List[Dict]:
        """Group into alternating user/model content blocks with signatures at the TOP level."""
        contents = []
        
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system": continue
            
            # CRITICAL: Gemini 3 only allows 'user' or 'model'. 
            # Tool results are sent as a 'user' turn.
            gemini_role = "model" if role == "assistant" else "user"
            
            parts = self._msg_to_parts(msg)
            if not parts: continue
            
            content_block = {
                "role": gemini_role,
                "parts": parts
            }
            
            # CRITICAL: signature belongs to the CONTENT object, not parts
            # Check tool_calls for signatures if role == model
            thought_sig = None
            if role == "assistant" and "tool_calls" in msg:
                for tc in msg.get("tool_calls", []):
                    if tc.get("thought_signature"):
                        thought_sig = tc["thought_signature"]
                        break
            
            # Check message level signature (text reasoning)
            if not thought_sig:
                thought_sig = msg.get("thought_signature") or msg.get("thoughtSignature")
                
            if thought_sig:
                content_block["thoughtSignature"] = thought_sig
                
            # If the last block has the same role, try to merge parts (required for parallel results)
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].extend(parts)
                # Keep original signature if it was already set
            else:
                contents.append(content_block)
        
        return contents

    async def generate_content_stream(
        self,
        messages: List[Dict],
        tools: List[Dict],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming with strictly fixed Gemini 3 schema."""
        try:
            contents = self._build_contents(messages)
            request_body = {
                "contents": contents,
                "tools": self._build_tools(tools)
            }
            
            # System instruction
            for msg in messages:
                if msg.get("role") == "system":
                    request_body["systemInstruction"] = {"parts": [{"text": msg.get("content", " ")}]}
                    break

            if self.temperature is not None:
                request_body["generationConfig"] = {"temperature": self.temperature}
            
            url = f"{self.stream_endpoint}?key={self.api_key}&alt=sse"
            logger.debug(f"[GEMINI] Native Request: {json.dumps(request_body)[:500]}...")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=request_body) as response:
                    if response.status != 200:
                        err = await response.text()
                        logger.error(f"[GEMINI] Status {response.status}: {err}")
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
                            for candidate in chunk.get("candidates", []):
                                # Capture top-level signature from Content or Candidate
                                content_obj = candidate.get("content", {})
                                sig = content_obj.get("thoughtSignature") or content_obj.get("thought_signature")
                                if sig: msg_thought_sig = sig
                                
                                for part in content_obj.get("parts", []):
                                    # Signature might also be in a part (fallback)
                                    part_sig = part.get("thoughtSignature") or part.get("thought_signature")
                                    if part_sig: msg_thought_sig = part_sig
                                    
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
                                        # Use the signature found so far
                                        if msg_thought_sig:
                                            tc["thought_signature"] = msg_thought_sig
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
                                        "total_tokens": usage.get("totalTokenCount", 0),
                                    },
                                    "finish_reason": "tool_calls" if accum_tool_calls else "stop"
                                }
                        except:
                            continue
            
        except Exception as e:
            logger.error(f"[GEMINI] Critical: {e}", exc_info=True)
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
