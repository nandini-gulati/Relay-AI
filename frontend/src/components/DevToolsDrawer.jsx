import React, { useState, useEffect } from 'react';

/**
 * Dev Tools Drawer - consolidates Failover Simulation, System Prompt,
 * and SQLite Inspector into a single developer panel.
 * This keeps the main chat UI clean for end-users while giving
 * evaluators/developers all the tools they need.
 */

const SIMULATION_PRESETS = [
  { id: 'none', label: 'None (Standard)', header: '', desc: 'Normal gateway routing.' },
  { id: 'key1-429', label: 'key_1=429', header: 'key_1=429', desc: 'Rate limit on key_1 → failover to key_2.' },
  { id: 'key1-500', label: 'key_1=500', header: 'key_1=500', desc: 'Server error on key_1 → failover to key_2.' },
  { id: 'chain', label: 'key_1=429,key_2=500', header: 'key_1=429,key_2=500', desc: 'Cascaded multi-key failover.' },
  { id: 'all-fail', label: '*=429 (All Fail)', header: '*=429', desc: 'All keys fail → clean 503 response.' },
];

const PROMPT_PRESETS = [
  { name: 'Default', prompt: 'You are a helpful, accurate, and concise AI assistant.' },
  { name: 'Senior Architect', prompt: 'You are a principal systems architect. Provide concise, production-ready solutions.' },
  { name: 'Code Mentor', prompt: 'You are an encouraging coding mentor. Explain concepts clearly with clean examples.' },
  { name: 'Ultra Concise', prompt: 'Answer in as few words as possible without omitting essential facts.' },
];

export default function DevToolsDrawer({
  isOpen,
  onClose,
  simulateHeader,
  onSetSimulateHeader,
  systemPrompt,
  onSetSystemPrompt,
  sessionId,
  apiUrl,
  onNewChat,
}) {
  const [activeTab, setActiveTab] = useState('failover');
  const [customSim, setCustomSim] = useState(simulateHeader || '');
  const [dbHistory, setDbHistory] = useState(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [copiedId, setCopiedId] = useState(false);

  useEffect(() => {
    if (isOpen && activeTab === 'sqlite') fetchHistory();
  }, [isOpen, activeTab, sessionId]);

  const fetchHistory = async () => {
    setIsLoadingHistory(true);
    setHistoryError(null);
    try {
      const res = await fetch(`${apiUrl}/sessions/${sessionId}/messages`);
      if (res.status === 404) setDbHistory({ session_id: sessionId, messages: [] });
      else if (!res.ok) setHistoryError(`HTTP ${res.status}`);
      else setDbHistory(await res.json());
    } catch { setHistoryError('Cannot connect to backend.'); }
    finally { setIsLoadingHistory(false); }
  };

  if (!isOpen) return null;

  const handleCopyId = () => {
    navigator.clipboard.writeText(sessionId).then(() => {
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 2000);
    }).catch(() => {});
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-container" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="drawer-header">
          <h3 className="drawer-title">Developer Tools</h3>
          <button type="button" className="drawer-close" onClick={onClose}>&times;</button>
        </div>

        {/* Session Info */}
        <div className="dev-session-bar">
          <div className="dev-session-info">
            <span className="dev-session-label">Session</span>
            <code className="dev-session-id">{sessionId.slice(0, 12)}…</code>
          </div>
          <div className="dev-session-actions">
            <button type="button" className="btn-sm-ghost" onClick={handleCopyId}>
              {copiedId ? '✓ Copied' : 'Copy ID'}
            </button>
            <button type="button" className="btn-sm-ghost" onClick={() => { onNewChat(); onClose(); }}>
              New Session
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="drawer-tabs">
          {[
            { key: 'failover', label: 'Failover Hook' },
            { key: 'prompt', label: 'System Prompt' },
            { key: 'sqlite', label: 'SQLite Inspector' },
          ].map((t) => (
            <button
              key={t.key}
              type="button"
              className={`drawer-tab-btn ${activeTab === t.key ? 'active' : ''}`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="drawer-body">
          {/* Failover Simulation Tab */}
          {activeTab === 'failover' && (
            <div className="tab-content">
              <div className="dev-status-row">
                <span className="dev-status-label">Active Header:</span>
                {simulateHeader ? (
                  <code className="dev-status-active">{simulateHeader}</code>
                ) : (
                  <span className="dev-status-none">None</span>
                )}
              </div>

              <div className="presets-stack">
                {SIMULATION_PRESETS.map((p) => (
                  <div
                    key={p.id}
                    className={`preset-row ${simulateHeader === p.header ? 'selected' : ''}`}
                    onClick={() => { onSetSimulateHeader(p.header); setCustomSim(p.header); }}
                  >
                    <div className="preset-row-top">
                      <span className="preset-row-label">{p.label}</span>
                    </div>
                    <span className="preset-row-desc">{p.desc}</span>
                  </div>
                ))}
              </div>

              <form className="custom-sim-form" onSubmit={(e) => { e.preventDefault(); onSetSimulateHeader(customSim.trim()); }}>
                <input
                  type="text"
                  className="dev-input"
                  placeholder="Custom: e.g. key_1=429,key_2=500"
                  value={customSim}
                  onChange={(e) => setCustomSim(e.target.value)}
                />
                <button type="submit" className="btn-sm-primary">Apply</button>
                {simulateHeader && (
                  <button type="button" className="btn-sm-ghost" onClick={() => { onSetSimulateHeader(''); setCustomSim(''); }}>
                    Clear
                  </button>
                )}
              </form>
            </div>
          )}

          {/* System Prompt Tab */}
          {activeTab === 'prompt' && (
            <div className="tab-content">
              <textarea
                data-testid="system-prompt-input"
                className="dev-textarea"
                placeholder="e.g. You are a concise software engineering mentor..."
                value={systemPrompt}
                onChange={(e) => onSetSystemPrompt(e.target.value)}
                rows={4}
              />
              <div className="prompt-presets-row">
                {PROMPT_PRESETS.map((p, i) => (
                  <button key={i} type="button" className="btn-preset-chip" onClick={() => onSetSystemPrompt(p.prompt)}>
                    {p.name}
                  </button>
                ))}
                {systemPrompt && (
                  <button type="button" className="btn-preset-chip btn-clear-chip" onClick={() => onSetSystemPrompt('')}>
                    ✕ Clear
                  </button>
                )}
              </div>
            </div>
          )}

          {/* SQLite Inspector Tab */}
          {activeTab === 'sqlite' && (
            <div className="tab-content">
              <div className="inspector-toolbar">
                <span className="inspector-endpoint">
                  GET /sessions/<code>{sessionId.slice(0, 8)}</code>/messages
                </span>
                <button type="button" className="btn-sm-ghost" onClick={fetchHistory} disabled={isLoadingHistory}>
                  {isLoadingHistory ? 'Loading…' : '↻ Refresh'}
                </button>
              </div>

              {isLoadingHistory ? (
                <div className="inspector-status"><span className="send-spinner" /> Loading…</div>
              ) : historyError ? (
                <div className="inspector-status inspector-error-text">{historyError}</div>
              ) : !dbHistory || dbHistory.messages.length === 0 ? (
                <div className="inspector-status">No messages in SQLite for this session yet.</div>
              ) : (
                <div className="db-scroll">
                  {dbHistory.messages.map((m, i) => (
                    <div key={i} className={`db-row db-row-${m.role}`}>
                      <div className="db-row-header">
                        <span className={`db-role db-role-${m.role}`}>{m.role}</span>
                        {m.metadata?.resolution_source && (
                          <span className="db-meta-tag">
                            {m.metadata.resolution_source} · in:{m.metadata.input_tokens}/out:{m.metadata.output_tokens}
                          </span>
                        )}
                      </div>
                      <p className="db-row-body">{m.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="drawer-footer">
          <span className="drawer-footer-note">
            Failover hook requires ENABLE_FAILURE_SIMULATION=true on backend.
          </span>
          <button type="button" className="btn-sm-primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
