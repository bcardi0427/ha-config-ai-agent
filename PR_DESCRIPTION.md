# Pull Request: Native Tools, OpenAI Consolidation, and Stability Fixes

## Summary

This release (v0.6.0) significantly enhances the Agent's capabilities by adding **Native Tools** for direct interaction with Home Assistant (Services, States, Templates, Logs). It also consolidates the logic to use the **OpenAI-compatible API only**, removing the complex and crash-prone Gemini native client.

## Changes

### 🛠️ New Native Tools (Capabilities)

The Agent can now "see" and "test" your Home Assistant instance directly:

| Tool Name | Description |
| :--- | :--- |
| `get_services(domain)` | Lists available services (e.g., `light.turn_on`, `script.reload`) to prevent hallucinated service calls. |
| `get_entity_states(id)` | Checks the current state/attributes of entities to verify if automations are triggering correctly. |
| `validate_template(tmpl)` | Renders Jinja2 templates (e.g., `{{ states('sensor.time') }}`) to verify logic before applying changes. |
| `check_config()` | Triggers a Home Assistant Core configuration check to ensure YAML validity. |
| `read_logs(lines)` | Reads the tail of `home-assistant.log` to diagnose errors after a failed reload. |

### 🧹 OpenAI Consolidation

- **Removed Native Gemini Client**: The project now uses the standard OpenAI-compatible client for *all* providers (Gemini, OpenAI, Claude, Local).
- **Simplified Dependency Chain**: Removed `google-genai` dependency to prevent conflicts and installation issues.
- **Unified Logic**: All AI interactions now flow through a single, stable code path.

### 🐛 Bug Fixes

- **Fixed "Bad Gateway" (502) Error**: Resolved a critical startup crash caused by an `IndentationError` in `agent_system.py`.
- **Fixed Crash Loop**: Removed orphaned code blocks that were causing the add-on to exit immediately.

## Files Changed

| File | Description |
| :--- | :--- |
| `src/agents/tools.py` | Added implementation for 5 new tools (`get_services`, `read_logs`, etc.) |
| `src/ha/ha_websocket.py` | Added WebSocket support for service listing, state fetching, and template rendering |
| `src/agents/agent_system.py` | Registered new tools with OpenAI client; removed Gemini native code |
| `requirements.txt` | Cleaned up dependencies |
| `config.yaml`, `build.yaml`, `manifest.json` | Version bump to 0.6.0 |

## Testing

- **Native Tools**: Verified that the agent can successfully list services and read logs via WebSocket/File API.
- **Stability**: Verified that the add-on starts successfully and maintains a stable connection.
- **OpenAI Streaming**: Verified that chat responses stream correctly without the native Gemini client.

---

### 📄 Documentation Upgrade

- **Service Schema Awareness**: Updated the Agent's system prompt to explicitly inform it that `get_services` returns full field schemas (arguments, types, selectors). This "unlocks" the ability for the agent to validate its own service calls against the actual definitions in your specific Home Assistant instance.

---

**Version:** 0.6.2
