import React, { useRef, useEffect } from 'react';

export default function Composer({ inputValue, setInputValue, onSend, isLoading }) {
  const textareaRef = useRef(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const h = textareaRef.current.scrollHeight;
      textareaRef.current.style.height = Math.min(Math.max(h, 44), 180) + 'px';
    }
  }, [inputValue]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <footer className="relay-footer">
      <form
        className="composer-form"
        onSubmit={(e) => { e.preventDefault(); onSend(); }}
      >
        <div className="composer-wrapper">
          <textarea
            ref={textareaRef}
            data-testid="chat-input"
            className="composer-input"
            placeholder="Message Relay…"
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
            title="Send"
          >
            {isLoading ? (
              <span className="send-spinner" />
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94l18.04-8.01a.75.75 0 000-1.36L3.478 2.405z" />
              </svg>
            )}
          </button>
        </div>
      </form>
      <p className="footer-fine-print">
        Relay may produce inaccurate responses. Verify important information.
      </p>
    </footer>
  );
}
