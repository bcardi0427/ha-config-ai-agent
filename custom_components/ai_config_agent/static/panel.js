class AiConfigAgentPanel extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._hass = null;
        this._messages = [];
        this._connected = false;
    }

    set hass(hass) {
        this._hass = hass;
        if (!this._connected) {
            this._connected = true;
            this._render();
            this._connectWebSocket();
        }
    }

    _connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/ai_config_agent/ws/chat`;

        this._ws = new WebSocket(wsUrl);

        this._ws.onopen = () => {
            console.log('Connected to AI Agent');
        };

        this._ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this._handleMessage(data);
        };

        this._ws.onerror = (error) => {
            console.error('WebSocket Error:', error);
            this._addSystemMessage("Error connecting to server.");
        };
    }

    _handleMessage(msg) {
        if (msg.event === 'token') {
            this._appendToLastMessage(msg.data.token || msg.data.content);
        } else if (msg.event === 'tool_call') {
            this._addSystemMessage(`🔧 Calling tools: ${msg.data.tool_calls.map(tc => tc.function.name).join(', ')}`);
        } else if (msg.event === 'tool_result') {
            const result = msg.data.result;
            if (msg.data.function === 'propose_config_changes' && result.success) {
                this._addApprovalCard(result, msg.data.tool_call_id);
            } else {
                this._addSystemMessage(`✅ Tool result: ${JSON.stringify(result).substring(0, 100)}...`);
            }
        } else if (msg.event === 'error') {
            this._addSystemMessage(`❌ Error: ${msg.data.error}`);
        }
    }

    _addApprovalCard(result, toolCallId) {
        const output = this.shadowRoot.getElementById('chat-output');
        const card = document.createElement('div');
        card.classList.add('message', 'assistant', 'approval-card');
        card.innerHTML = `
        <div style="font-weight: bold; margin-bottom: 8px;">📝 Configuration Changes Proposed</div>
        <div>Files: ${result.files.map(f => `<code>${f}</code>`).join(', ')}</div>
        <div style="margin-top: 12px; display: flex; gap: 8px;">
            <button class="approve-btn">✓ Approve & Apply</button>
            <button class="reject-btn" style="background: var(--error-color);">✗ Reject</button>
        </div>
      `;

        const approveBtn = card.querySelector('.approve-btn');
        approveBtn.onclick = () => this._handleApproval(result.changeset_id, true, card);

        const rejectBtn = card.querySelector('.reject-btn');
        rejectBtn.onclick = () => this._handleApproval(result.changeset_id, false, card);

        output.appendChild(card);
        output.scrollTop = output.scrollHeight;
    }

    async _handleApproval(changeId, approved, cardElement) {
        try {
            // Disable buttons
            const buttons = cardElement.querySelectorAll('button');
            buttons.forEach(b => b.disabled = true);

            const response = await fetch('/api/ai_config_agent/api/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    change_id: changeId,
                    approved: approved,
                    validate: true
                })
            });

            const data = await response.json();
            if (data.success) {
                this._addSystemMessage(approved ? "✅ Changes applied successfully!" : "❌ Changes rejected.");
            } else {
                this._addSystemMessage(`⚠️ Error: ${data.error}`);
                buttons.forEach(b => b.disabled = false);
            }
        } catch (e) {
            console.error("Approval error:", e);
            this._addSystemMessage(`Error sending approval: ${e.message}`);
        }
    }

    _appendToLastMessage(text) {
        const output = this.shadowRoot.getElementById('chat-output');
        if (output.lastElementChild && output.lastElementChild.classList.contains('assistant') && !output.lastElementChild.classList.contains('approval-card')) {
            output.lastElementChild.innerText += text;
        } else {
            const msg = document.createElement('div');
            msg.classList.add('message', 'assistant');
            msg.innerText = text;
            output.appendChild(msg);
        }
        output.scrollTop = output.scrollHeight;
    }

    _addSystemMessage(text) {
        const output = this.shadowRoot.getElementById('chat-output');
        const msg = document.createElement('div');
        msg.classList.add('message', 'system');
        msg.innerText = text;
        output.appendChild(msg);
    }

    _addUserMessage(text) {
        const output = this.shadowRoot.getElementById('chat-output');
        const msg = document.createElement('div');
        msg.classList.add('message', 'user');
        msg.innerText = text;
        output.appendChild(msg);
        output.scrollTop = output.scrollHeight;

        // Send to backend
        this._ws.send(JSON.stringify({
            type: 'chat',
            message: text,
            conversation_history: [] // TODO: Maintain history
        }));
    }

    _exportHtml() {
        const chatContent = this.shadowRoot.getElementById('chat-output').innerHTML;
        const styles = this.shadowRoot.querySelector('style').outerHTML;

        const html = `
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>AI Agent Conversation Export</title>
    ${styles}
    <style>
        body { margin: 0; padding: 0; background: var(--primary-background-color); }
        .container { max-width: 800px; margin: 0 auto; min-height: 100vh; }
        #chat-output { overflow: visible !important; height: auto !important; }
        /* Hide buttons in export */
        button { display: none !important; }
    </style>
</head>
<body>
    <div class="container">
        <header>Conversation Export - ${new Date().toLocaleString()}</header>
        <div id="chat-output">
            ${chatContent}
        </div>
    </div>
</body>
</html>`;

        const blob = new Blob([html], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ha-agent-chat-${new Date().toISOString().slice(0, 10)}.html`;
        a.click();
        URL.revokeObjectURL(url);
    }

    _render() {
        this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100vh;
          background-color: var(--primary-background-color);
          color: var(--primary-text-color);
          font-family: var(--paper-font-body1_-_font-family);
        }
        .container {
          display: flex;
          flex-direction: column;
          height: 100%;
          max-width: 800px;
          margin: 0 auto;
          background: var(--card-background-color);
        }
        header {
          padding: 16px;
          background: var(--app-header-background-color);
          color: var(--app-header-text-color, white);
          font-size: 20px;
          font-weight: 500;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        header button {
            background: transparent;
            border: 1px solid rgba(255,255,255,0.3);
            font-size: 14px;
            padding: 4px 12px;
        }
        #chat-output {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .message {
          padding: 12px 16px;
          border-radius: 12px;
          max-width: 80%;
          line-height: 1.5;
        }
        .message.user {
          align-self: flex-end;
          background-color: var(--primary-color);
          color: var(--text-primary-color);
        }
        .message.assistant {
          align-self: flex-start;
          background-color: var(--secondary-background-color);
        }
        .message.system {
          align-self: center;
          font-size: 0.9em;
          color: var(--secondary-text-color);
        }
        #input-area {
          padding: 16px;
          border-top: 1px solid var(--divider-color);
          display: flex;
          gap: 8px;
        }
        input {
          flex: 1;
          padding: 12px;
          border-radius: 24px;
          border: 1px solid var(--divider-color);
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          font-size: 16px;
        }
        button {
          padding: 0 24px;
          border-radius: 24px;
          border: none;
          background: var(--primary-color);
          color: var(--text-primary-color);
          font-weight: 500;
          cursor: pointer;
        }
      </style>
      <div class="container">
        <header>
            <span>AI Configuration Agent</span>
            <button id="export-btn" title="Download Conversation">💾 Save Chat</button>
        </header>
        <div id="chat-output">
             <div class="message system">Connected to Home Assistant AI Agent v0.9.1</div>
        </div>
        <div id="input-area">
          <input type="text" id="chat-input" placeholder="Ask me to configure something..." autocomplete="off">
          <button id="send-btn">Send</button>
        </div>
      </div>
    `;

        const input = this.shadowRoot.getElementById('chat-input');
        const btn = this.shadowRoot.getElementById('send-btn');
        const exportBtn = this.shadowRoot.getElementById('export-btn');

        const sendMessage = () => {
            const text = input.value.trim();
            if (text) {
                this._addUserMessage(text);
                input.value = '';
            }
        };

        btn.addEventListener('click', sendMessage);
        exportBtn.addEventListener('click', () => this._exportHtml());

        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
    }
}

customElements.define('ha-config-agent-panel', AiConfigAgentPanel);
