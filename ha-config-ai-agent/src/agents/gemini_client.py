"""Native Gemini API client for Gemini 3 and later models.

Implements the official Gemini 3 "Thinking" protocol via direct HTTP:
1. Protocol: Server-Sent Events (SSE).
2. Schema: 
   - 'model' role allows 'functionCall' + 'thoughtSignature'.
   - 'user' role is used for 'functionResponse'.
3. Robustness: Strict parsing to prevent "undefined" UI errors.
"""

import json
import logging
import aiohttp
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    """Robust, native Gemini 3 client using aiohttp."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        temperature: Optional[float] = None,
    ):
        self.api_key = api_key
        # Clean model name (handle 'custom_app/gemini-3...' etc)
        self.model = model.split('/')[-1] if '/' in model else model
        self.temperature = temperature
        self.endpoint = f"{GEMINI_API_BASE}/models/{self.model}:generateContent"
        self.stream_endpoint = f"{GEMINI_API_BASE}/models/{self.model}:streamGenerateContent"
        
        logger.info(f"Initialized native Gemini client for {self.model}")

    def _build_tools(self, tool_definitions: List[Dict]) -> List[Dict]:
        """Convert OpenAI tools to Gemini format."""
        if not tool_definitions: return []
        
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
        """Convert message to Gemini parts with correct signature placement."""
        parts = []
        role = msg.get("role")
        content = msg.get("content")

        # 1. Text Parts
        if content:
            text_str = ""
            if isinstance(content, str):
                text_str = content
            elif isinstance(content, list):
                # Join text parts
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_str += item.get("text", "")
            
            if text_str:
                part = {"text": text_str}
                # If assistant text, might have a signature sibling
                if role == "assistant":
                    sig = msg.get("thought_signature") or msg.get("thoughtSignature")
                    if sig: part["thoughtSignature"] = sig
                parts.append(part)

        # 2. Function Calls (Model Role)
        if role == "assistant" and "tool_calls" in msg:
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                args = {}
                try:
                    args_str = func.get("arguments", "{}")
                    if isinstance(args_str, str):
                        args = json.loads(args_str)
                    else:
                        args = args_str
                except:
                    pass

                part = {
                    "functionCall": {
                        "name": func.get("name", ""),
                        "args": args
                    }
                }
                
                # Check for signature on the tool call or valid global signature
                sig = tc.get("thought_signature") or tc.get("thoughtSignature")
                # Fallback: if message has signature and this is the first tool call
                if not sig:
                     sig = msg.get("thought_signature") or msg.get("thoughtSignature")
                
                if sig:
                    part["thoughtSignature"] = sig
                
                parts.append(part)

        # 3. Function Responses (User Role)
        if role == "tool":
            func_name = msg.get("function_name")
            if not func_name:
                # Try to extract from ID if name missing
                tool_call_id = msg.get("tool_call_id", "")
                if "_" in tool_call_id:
                     func_name = tool_call_id.split("_")[0]
                else:
                     func_name = tool_call_id

            response_payload = {"result": str(content)}
            try:
                if isinstance(content, str):
                    parsed = json.loads(content)
                    if isinstance(parsed, (dict, list)):
                        response_payload = parsed
                elif isinstance(content, (dict, list)):
                    response_payload = content
            except:
                pass

            parts.append({
                "functionResponse": {
                    "name": func_name,
                    "response": response_payload
                }
            })

        return parts

    async def generate_content_stream(
        self,
        messages: List[Dict],
        tools: List[Dict],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Reliable streaming."""
        try:
            # Group Content
            contents = []
            for msg in messages:
                role = msg.get("role", "user")
                if role == "system": continue
                
                # Role map: assistant -> model, others -> user
                g_role = "model" if role == "assistant" else "user"
                
                new_parts = self._msg_to_parts(msg)
                if not new_parts: continue

                # Merge identical adjacent roles
                if contents and contents[-1]["role"] == g_role:
                    contents[-1]["parts"].extend(new_parts)
                else:
                    contents.append({"role": g_role, "parts": new_parts})

            request_body = {
                "contents": contents,
                "tools": self._build_tools(tools)
            }
            
            # System Instruction
            for msg in messages:
                if msg.get("role") == "system":
                    request_body["systemInstruction"] = {"parts": [{"text": msg.get("content", " ")}]}
                    break

            if self.temperature is not None:
                request_body["generationConfig"] = {"temperature": self.temperature}

            url = f"{self.stream_endpoint}?key={self.api_key}&alt=sse"
            
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=request_body) as response:
                    if response.status != 200:
                        err_text = await response.text()
                        logger.error(f"[GEMINI] API Error {response.status}: {err_text}")
                        yield {"type": "error", "error": f"Gemini Error {response.status}: {err_text}"}
                        return

                    accum_text = ""
                    accum_tool_calls = []
                    msg_sig = None
                    
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if not line.startswith('data: '): continue
                        
                        try:
                            json_str = line[6:]
                            if not json_str or json_str == '[DONE]': continue
                            
                            chunk = json.loads(json_str)
                            candidates = chunk.get("candidates", [])
                            if not candidates: continue
                            
                            cand = candidates[0]
                            content_obj = cand.get("content", {})
                            parts = content_obj.get("parts", [])
                            
                            # Scan parts
                            for part in parts:
                                # Safe get signature
                                sig = part.get("thoughtSignature") or part.get("thought_signature")
                                if sig: msg_sig = sig
                                
                                # Safe get text
                                if "text" in part:
                                    t = part["text"]
                                    if t: # ONLY yield if string is not empty
                                        accum_text += t
                                        yield {"type": "content", "content": t}
                                
                                # Safe get function call
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
                                    # Attach signature if found
                                    if sig: tc["thought_signature"] = sig
                                    elif msg_sig: tc["thought_signature"] = msg_sig
                                    
                                    accum_tool_calls.append(tc)
                                    yield {"type": "tool_call", "tool_call": tc}
                                    
                        except Exception as e:
                            logger.debug(f"Chunk parsing warning: {e}")
                            continue
                            
                    # Finished stream
                    yield {
                        "type": "complete",
                        "content": accum_text,
                        "tool_calls": accum_tool_calls,
                        "thought_signature": msg_sig,
                        "usage": {"total_tokens": 0}, # Usage optional
                        "finish_reason": "tool_calls" if accum_tool_calls else "stop"
                    }

        except Exception as e:
            logger.error(f"[GEMINI] Exception: {e}", exc_info=True)
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
