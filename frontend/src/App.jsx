import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const RAW_API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_URL = RAW_API_URL.replace(/\/+$/, '');

export default function App() {
  // Generate a unique session_id with crypto.randomUUID() on page load
  const [sessionId, setSessionId] = useState(() => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return 'sess-' + Math.random().toString(36).substring(2, 11);
  });

  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [backendHealth, setBackendHealth] = useState(null);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Check health on mount
  useEffect(() => {
    async function checkHealth() {
      try {
        const res = await fetch(`${API_URL}/health`);
        if (res.ok) {
          const data = await res.json();
          setBackendHealth(data);
        } else {
          setBackendHealth({ status: 'unhealthy' });
        }
      } catch (err) {
        setBackendHealth({ status: 'offline' });
      }
    }
    checkHealth();
  }, []);

  // Reset to a brand new session
  const handleNewChat = () => {
    const newId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'sess-' + Math.random().toString(36).substring(2, 11);
    setSessionId(newId);
    setMessages([]);
    setInputValue('');
    if (inputRef.current) {
      inputRef.current.focus();
    }
  };

  const handleSend = async (overrideText) => {
    const textToSend = (overrideText || inputValue).trim();
    if (!textToSend || isLoading) return;

    // 1. Append user message locally
    const userMsg = {
      role: 'user',
      content: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setIsLoading(true);

    // 2. Prepare payload
    // "Include the system prompt in the request body only when the field is non-empty."
    const payload = {
      session_id: sessionId,
      message: textToSend,
    };
    if (systemPrompt && systemPrompt.trim()) {
      payload.system_prompt = systemPrompt.trim();
    }

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        // Handle API errors (422, 503, etc.)
        let errorMsg = 'Failed to get a response.';
        if (response.status === 422) {
          if (Array.isArray(data?.detail)) {
            errorMsg = `Validation error: ${data.detail.map((d) => d.msg || JSON.stringify(d)).join(', ')}`;
          } else {
            errorMsg = data?.detail || 'Request validation error (422). Please verify your message.';
          }
        } else if (response.status === 503) {
          errorMsg = data?.detail === 'all providers unavailable'
            ? 'All AI provider keys are currently unavailable or rate-limited. Please try again shortly.'
            : (data?.detail || 'Service temporarily unavailable (503).');
        } else {
          errorMsg = data?.detail || `Server error (${response.status}).`;
        }

        setMessages((prev) => [
          ...prev,
          {
            role: 'error',
            content: errorMsg,
            status: response.status,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
      } else {
        // Success: assistant response
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.reply,
            metadata: data.metadata,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
      }
    } catch (err) {
      // Handle network failure or cold-start timeouts
      setMessages((prev) => [
        ...prev,
        {
          role: 'error',
          content: 'Network connection failed. The backend service may be cold-starting or temporarily unreachable.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="relay-app">
      {/* Top Header */}
      <header className="relay-header">
        <div className="header-left">
          <div className="logo-badge">
            <span className="logo-dot"></span>
            <span className="logo-text">Relay</span>
          </div>
          <span className="header-desc">Multi-Key Resilient AI Gateway</span>
        </div>

        <div className="header-right">
          <div className="session-tag" title={`Current Session: ${sessionId}`}>
            <span className="session-label">Session</span>
            <span className="session-id">{sessionId.slice(0, 8)}…</span>
          </div>

          <button
            type="button"
            className={`btn-system-toggle ${showSystemPrompt ? 'active' : ''}`}
            onClick={() => setShowSystemPrompt(!showSystemPrompt)}
            title="Configure Session System Prompt"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
            <span>Prompt</span>
          </button>

          <button
            type="button"
            className="btn-new-chat"
            onClick={handleNewChat}
            title="Start a fresh conversation"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            <span>New Chat</span>
          </button>
        </div>
      </header>

      {/* Optional Collapsible System Prompt Drawer */}
      {showSystemPrompt && (
        <div className="system-prompt-panel">
          <div className="prompt-panel-header">
            <label htmlFor="system-prompt-input" className="prompt-label">
              Session System Prompt (Optional)
            </label>
            <span className="prompt-hint">Sets the persona or guidelines for this session</span>
          </div>
          <textarea
            id="system-prompt-input"
            data-testid="system-prompt-input"
            className="system-prompt-textarea"
            placeholder="e.g. You are a concise software engineering mentor..."
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={2}
          />
        </div>
      )}

      {/* Main Conversation Container */}
      <main className="relay-chat-container">
        {messages.length === 0 ? (
          <div className="empty-state">
            <div className="empty-avatar">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
            </div>
            <h2>Welcome to Relay</h2>
            <p className="empty-subtitle">
              Resilient AI chat with automatic multi-key failover and deterministic response caching.
            </p>
            <div className="starter-chips">
              <button
                type="button"
                className="chip-btn"
                onClick={() => handleSend("What is the capital of France?")}
              >
                "What is the capital of France?"
              </button>
              <button
                type="button"
                className="chip-btn"
                onClick={() => handleSend("Explain quantum computing in simple terms.")}
              >
                "Explain quantum computing in simple terms."
              </button>
              <button
                type="button"
                className="chip-btn"
                onClick={() => handleSend("Write a 4-line poem about high availability.")}
              >
                "Write a 4-line poem about high availability."
              </button>
            </div>
          </div>
        ) : (
          <div className="message-list">
            {messages.map((msg, index) => {
              if (msg.role === 'user') {
                return (
                  <div key={index} className="message-row user-row">
                    <div className="user-bubble">
                      <p className="message-text">{msg.content}</p>
                      <span className="message-time">{msg.timestamp}</span>
                    </div>
                  </div>
                );
              }

              if (msg.role === 'error') {
                return (
                  <div key={index} className="message-row error-row">
                    <div className="error-bubble">
                      <div className="error-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="12" cy="12" r="10"/>
                          <line x1="12" y1="8" x2="12" y2="12"/>
                          <line x1="12" y1="16" x2="12.01" y2="16"/>
                        </svg>
                      </div>
                      <div className="error-content">
                        <span className="error-title">Request Issue</span>
                        <p className="error-detail">{msg.content}</p>
                      </div>
                    </div>
                  </div>
                );
              }

              // Assistant message matching EXACT testid specifications
              const meta = msg.metadata || {};
              const isCache = meta.resolution_source === 'LLM_CACHE';

              return (
                <div
                  key={index}
                  className="message-row assistant-row"
                  data-testid="assistant-message"
                >
                  <div className="assistant-card">
                    <div className="assistant-header">
                      <div className="assistant-avatar">R</div>
                      <span className="assistant-name">Relay</span>
                      <span className="message-time">{msg.timestamp}</span>
                    </div>

                    <div className="assistant-content">
                      <p className="message-text">{msg.content}</p>
                    </div>

                    {/* Metadata Footer */}
                    <div className="assistant-metadata">
                      <div className="meta-left">
                        {/* data-testid: meta-source (exactly LIVE_INFERENCE or LLM_CACHE) */}
                        <span
                          className={`meta-pill pill-source ${isCache ? 'pill-cache' : 'pill-live'}`}
                          data-testid="meta-source"
                        >
                          {meta.resolution_source || 'LIVE_INFERENCE'}
                        </span>

                        {/* data-testid: meta-model */}
                        <span className="meta-pill pill-model" data-testid="meta-model">
                          {meta.model || 'gemini-2.5-flash-lite'}
                        </span>
                      </div>

                      <div className="meta-right">
                        {/* data-testid: meta-latency */}
                        <span className="meta-chip chip-latency" title="Server response latency">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10"/>
                            <polyline points="12 6 12 12 16 14"/>
                          </svg>
                          <span data-testid="meta-latency">
                            {meta.latency_ms !== undefined ? `${meta.latency_ms} ms` : '0 ms'}
                          </span>
                        </span>

                        {/* Token stats (per-request only) */}
                        <div className="meta-tokens" title="Tokens used for this request only">
                          <span className="token-label">in:</span>
                          <span className="token-val" data-testid="meta-input-tokens">
                            {meta.input_tokens ?? 0}
                          </span>
                          <span className="token-divider">/</span>
                          <span className="token-label">out:</span>
                          <span className="token-val" data-testid="meta-output-tokens">
                            {meta.output_tokens ?? 0}
                          </span>
                        </div>

                        {meta.fallback_attempts > 0 && (
                          <span className="meta-fallback" title={`Failed over ${meta.fallback_attempts} times before answering`}>
                            failover: {meta.fallback_attempts}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}

            {isLoading && (
              <div className="message-row assistant-row loading-row">
                <div className="assistant-card loading-card">
                  <div className="assistant-header">
                    <div className="assistant-avatar">R</div>
                    <span className="assistant-name">Relay</span>
                  </div>
                  <div className="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </main>

      {/* Bottom Composer */}
      <footer className="relay-footer">
        <form
          className="composer-form"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
        >
          <textarea
            ref={inputRef}
            data-testid="chat-input"
            className="composer-textarea"
            placeholder="Send a message to Relay... (Enter to send, Shift+Enter for newline)"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={1}
          />
          <button
            type="submit"
            data-testid="send-button"
            className="btn-send"
            disabled={isLoading || !inputValue.trim()}
            title="Send Message"
          >
            {isLoading ? (
              <span className="send-spinner"></span>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
            )}
          </button>
        </form>
        <div className="footer-notes">
          <span>Relay AI • Automatic failover on 429/5xx • Deterministic caching</span>
        </div>
      </footer>
    </div>
  );
}
