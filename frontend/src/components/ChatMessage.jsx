import React, { useState, useEffect } from 'react';
import MarkdownRenderer from './MarkdownRenderer';

export default function ChatMessage({ message, onStreamTick }) {
  const [copied, setCopied] = useState(false);
  const fullContent = message.content || '';
  const shouldAnimate = message.role === 'assistant' && Boolean(message.isNew);
  const [visibleLength, setVisibleLength] = useState(() =>
    shouldAnimate ? 0 : fullContent.length
  );
  const isStreaming = shouldAnimate && visibleLength < fullContent.length;

  useEffect(() => {
    if (!shouldAnimate) {
      setVisibleLength(fullContent.length);
      return;
    }

    setVisibleLength(0);
    const total = fullContent.length;
    if (total === 0) return;

    // Target ~1.2s-2.4s total reveal regardless of response length
    const stepSize = Math.max(3, Math.ceil(total / 90));
    const timer = setInterval(() => {
      setVisibleLength((prev) => {
        const next = Math.min(total, prev + stepSize);
        if (next >= total) {
          clearInterval(timer);
        }
        return next;
      });
    }, 18);

    return () => clearInterval(timer);
  }, [fullContent, shouldAnimate]);

  useEffect(() => {
    if (isStreaming && onStreamTick) {
      onStreamTick();
    }
  }, [visibleLength, isStreaming, onStreamTick]);

  // ── User message ──
  if (message.role === 'user') {
    return (
      <div className="message-row user-row">
        <div className="user-bubble">
          <p className="message-text">{message.content}</p>
        </div>
      </div>
    );
  }

  // ── Error message ──
  if (message.role === 'error') {
    return (
      <div className="message-row error-row">
        <div className="error-card">
          <div className="error-card-top">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span className="error-label">Something went wrong</span>
          </div>
          <p className="error-body-text">{message.content}</p>
        </div>
      </div>
    );
  }

  // ── Assistant message ──
  const meta = message.metadata || {};
  const isCache = meta.resolution_source === 'LLM_CACHE';
  const displayedContent = shouldAnimate
    ? fullContent.slice(0, visibleLength)
    : fullContent;

  const handleCopy = () => {
    navigator.clipboard.writeText(fullContent).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  };

  return (
    <div className="message-row assistant-row" data-testid="assistant-message">
      <div className={`assistant-card ${isStreaming ? 'is-streaming' : ''}`}>
        {/* Response body */}
        <div className="assistant-body">
          <MarkdownRenderer content={displayedContent} />
          {isStreaming && <span className="stream-cursor" aria-hidden="true" />}
        </div>

        {/* Clean copy action (metadata kept visually hidden for end-users) */}
        <div className={`assistant-footer ${isStreaming ? 'footer-hidden' : ''}`}>
          <div className="footer-actions">
            <button type="button" className="btn-msg-action" onClick={handleCopy} title="Copy response">
              {copied ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
              )}
            </button>
          </div>

          {/* Request metadata pills */}
          <div className="footer-meta">
            <span className={`meta-tag ${isCache ? 'tag-cache' : 'tag-live'}`}>
              <span data-testid="meta-source">{meta.resolution_source || 'LIVE_INFERENCE'}</span>
            </span>
            <span className="meta-tag tag-neutral" data-testid="meta-model">
              {meta.model || 'openai/gpt-oss-120b'}
            </span>
            <span className="meta-tag tag-neutral">
              <span data-testid="meta-latency">{meta.latency_ms !== undefined ? `${meta.latency_ms}ms` : '0ms'}</span>
            </span>
            <span className="meta-tag tag-neutral" title="Input / Output tokens">
              <span data-testid="meta-input-tokens">{meta.input_tokens ?? 0}</span>
              <span className="token-slash">/</span>
              <span data-testid="meta-output-tokens">{meta.output_tokens ?? 0}</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
