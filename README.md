# AIassistant for Home Assistant

An AI-powered Home Assistant configuration assistant with approval workflow.

**Chat with your configuration:**
- "Enable debug logging for the MQTT integration"
- "Show me all my automations that involve lights"
- "Rename my 'Office Button' device to 'Desk Button'"
- "Create an automation that turns on the porch light at sunset"

## Supported AI Providers

| Provider | Models | Notes |
|----------|--------|-------|
| **OpenAI** | GPT-4o, GPT-4.1, GPT-4.1-mini, o4-mini | Default provider |
| **Google Gemini** | Gemini 2.5 Pro/Flash, Gemini 2.0 Flash, Gemini 1.5 | Gemini 3 models supported |
| **Anthropic** | Claude Sonnet 4, Claude 3.5 Sonnet/Haiku/Opus | Via Claude API |
| **OpenRouter** | Any model on OpenRouter | Access multiple providers |
| **Ollama** | Llama 3.3, Qwen 2.5, DeepSeek-R1, Mistral | Local models, no API key needed |
| **Custom** | Any OpenAI-compatible API | For self-hosted or other providers |

# Installation

## Option 1: HACS Custom Component (Recommended for Core/Container)

1. **Add to HACS:**
   - Open HACS → Integrations
   - Click ⋮ → Custom repositories
   - Add: `https://github.com/bcardi0427/AIassistant`
   - Category: Integration

2. **Install:**
   - Search for "AIassistant"
   - Click Download
   - Restart Home Assistant

3. **Configure:**
   - Settings → Devices & Services → Add Integration
   - Search "AIassistant"
   - **Step 1:** Select your AI provider (OpenAI, Gemini, Anthropic, etc.)
   - **Step 2:** Enter your API key and select a model

## Option 2: Home Assistant Add-on (Supervisor Required)

1. Navigate to Settings → Add-ons → Add-on Store
2. Click ⋮ → Repositories
3. Add: `https://github.com/bcardi0427/AIassistant`
4. Find "AIassistant" and click Install
5. Configure:
   - **Provider:** Select your AI provider
   - **API Key:** Enter your API key
   - **Model:** Select from the dropdown or choose "custom"
6. Start the add-on

# Configuration

## Using the Provider Dropdown

When configuring the agent, simply select your AI provider from the dropdown. The API URL will be automatically configured for you:

| Provider | Auto-configured URL |
|----------|---------------------|
| OpenAI | `https://api.openai.com/v1` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Anthropic | `https://api.anthropic.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama | `http://localhost:11434/v1` |
| Custom | Enter your own URL |

## Configuration Options

| Option | Description | Required |
|--------|-------------|----------|
| `provider` | AI provider (openai, gemini, anthropic, openrouter, ollama, custom) | Yes |
| `api_key` | Your API key for the selected provider | Yes* |
| `model` | The model to use (select from dropdown or enter custom) | Yes |
| `api_url` | Custom API URL (leave empty for auto-detection) | No |
| `log_level` | Logging verbosity (debug, info, warning, error) | No |
| `temperature` | Model temperature (0.0 - 2.0) | No |
| `system_prompt_file` | Path to custom system prompt file | No |
| `enable_cache_control` | Enable prompt caching (reduces costs) | No |
| `usage_tracking` | Token usage tracking method | No |

*Ollama doesn't require an API key for local models.

# Features

* 🤖 **Natural Language Interface** - No YAML expertise required
* ✅ **Approval Workflow** - Review visual diffs before applying changes
* 🔒 **Safe Operations** - Automatic backups, validation, and rollback
* 📊 **Visual Diffs** - See exactly what will change
* 🔌 **Multi-Provider Support** - OpenAI, Gemini, Anthropic, OpenRouter, Ollama, or any OpenAI-compatible API
* 🎛️ **Easy Configuration** - Provider dropdown with auto-URL detection
* 📋 **Model Selection** - Pre-populated model lists for each provider
* 📝 **Configuration Management** - Automations, scripts, Lovelace, devices, entities, and areas
* 🔄 **Auto-Reload** - Home Assistant configuration reloads automatically after changes

# Troubleshooting

## Gemini 3 Models
If you're using Gemini 3 models (like `gemini-3-flash-preview`) and encounter a "thought_signature" error, make sure you're using version 0.3.0 or later which includes the fix for this issue.

## Custom Models
If your model isn't in the dropdown, select "custom" from the model list and enter your model name in the API URL field, or use the options flow to enter a custom model name after initial setup.

# Credits

This project is a fork of [ha-config-ai-agent](https://github.com/yinzara/ha-config-ai-agent) by @yinzara, renamed for personal distribution and custom features.

# License

MIT License - See [LICENSE](LICENSE) file for details.
