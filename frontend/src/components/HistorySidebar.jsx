import React from 'react';

function formatRelativeDate(isoStr) {
  if (!isoStr) return '';
  try {
    const date = new Date(isoStr);
    const now = new Date();
    const diffDays = Math.floor((now - date) / (1000 * 60 * 60 * 24));
    if (diffDays <= 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export default function HistorySidebar({
  isOpen,
  onClose,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  user,
  onLogout,
  onOpenAuth,
}) {
  return (
    <>
      {isOpen && <div className="sidebar-backdrop" onClick={onClose} />}
      <aside className={`history-sidebar ${isOpen ? 'open' : ''}`} aria-label="Chat history">
        <div className="sidebar-header">
          <button
            type="button"
            className="btn-sidebar-new"
            onClick={() => {
              onNewChat();
              if (window.innerWidth < 768) onClose();
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span>New Chat</span>
          </button>
          <button
            type="button"
            className="btn-icon-ghost sidebar-close-btn"
            onClick={onClose}
            title="Close sidebar"
            aria-label="Close sidebar"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="sidebar-section-label">Recent Chats</div>

        <div className="sidebar-list">
          {!user ? (
            <div className="sidebar-empty">
              Sign in to save your private chat history across sessions.
            </div>
          ) : sessions.length === 0 ? (
            <div className="sidebar-empty">
              No saved conversations yet. Start chatting to save your history.
            </div>
          ) : (
            sessions.map((s) => {
              const isActive = s.session_id === activeSessionId;
              return (
                <div
                  key={s.session_id}
                  className={`sidebar-item ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    onSelectSession(s.session_id);
                    if (window.innerWidth < 768) onClose();
                  }}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelectSession(s.session_id);
                      if (window.innerWidth < 768) onClose();
                    }
                  }}
                >
                  <div className="sidebar-item-content">
                    <span className="sidebar-item-title">{s.title}</span>
                    <span className="sidebar-item-date">{formatRelativeDate(s.updated_at)}</span>
                  </div>
                  <button
                    type="button"
                    className="btn-sidebar-delete"
                    title="Delete chat"
                    aria-label="Delete chat"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(s.session_id);
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                    </svg>
                  </button>
                </div>
              );
            })
          )}
        </div>

        {user ? (
          <div className="sidebar-user-footer">
            <div className="sidebar-user-info">
              <span className="sidebar-user-avatar">
                {(user.email || 'U').charAt(0).toUpperCase()}
              </span>
              <span className="sidebar-user-email" title={user.email}>
                {user.email}
              </span>
            </div>
            <button
              type="button"
              className="btn-sidebar-logout"
              onClick={onLogout}
              title="Sign out"
            >
              Sign out
            </button>
          </div>
        ) : (
          <div className="sidebar-user-footer">
            <button
              type="button"
              className="btn-sidebar-login"
              onClick={onOpenAuth}
            >
              Sign in / Create account
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
