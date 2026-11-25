import React, { useState, useEffect, useRef, useCallback } from 'react';
import Header from './components/Header';
import ChatMessage from './components/ChatMessage';
import Composer from './components/Composer';
import EmptyState from './components/EmptyState';
import DevToolsDrawer from './components/DevToolsDrawer';
import HistorySidebar from './components/HistorySidebar';
import AuthView from './components/AuthView';
import './App.css';

const RAW_API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_URL = RAW_API_URL.replace(/\/+$/, '');
const AUTH_TOKEN_KEY = 'relay_auth_token';

function createSessionId() {
  return crypto?.randomUUID?.() || 'sess-' + Math.random().toString(36).substring(2, 11);
}

function activeSessionStorageKey(userId) {
  return userId ? `relay_active_session_${userId}` : 'relay_active_session_guest';
}

export default function App() {
  const [authToken, setAuthToken] = useState(() => localStorage.getItem(AUTH_TOKEN_KEY) || '');
  const [currentUser, setCurrentUser] = useState(null);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [justLoggedIn, setJustLoggedIn] = useState(false);

  // PDF Section 5: "A new session starts on each page load."
  const [sessionId, setSessionId] = useState(() => createSessionId());

  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [backendHealth, setBackendHealth] = useState(null);
  const [simulateHeader, setSimulateHeader] = useState('');
  const [isDevToolsOpen, setIsDevToolsOpen] = useState(false);

  const [isDarkMode, setIsDarkMode] = useState(() => {
    const saved = localStorage.getItem('relay_theme');
    return saved ? saved === 'dark' : true;
  });

  const messagesEndRef = useRef(null);

  // Theme
  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDarkMode);
    document.documentElement.classList.toggle('light', !isDarkMode);
    localStorage.setItem('relay_theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  // Scroll
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Secret shortcut Cmd+Shift+D / Ctrl+Shift+D to open Dev Tools when needed
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault();
        setIsDevToolsOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Verify existing auth token silently on mount (never blocks chat UI)
  useEffect(() => {
    if (!authToken) {
      setCurrentUser(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_URL}/auth/me`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (cancelled) return;
        if (r.ok) {
          const user = await r.json();
          setCurrentUser(user);
        } else {
          localStorage.removeItem(AUTH_TOKEN_KEY);
          setAuthToken('');
          setCurrentUser(null);
        }
      } catch {
        if (!cancelled) setCurrentUser(null);
      }
    })();
    return () => { cancelled = true; };
  }, [authToken]);

  const fetchSessions = useCallback(async () => {
    if (!authToken) {
      setSessions([]);
      return;
    }
    try {
      const r = await fetch(`${API_URL}/sessions`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (r.ok) {
        const data = await r.json();
        setSessions(data.sessions || []);
      }
    } catch { /* ignore */ }
  }, [authToken]);

  const loadSessionMessages = useCallback(async (targetId) => {
    try {
      const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
      const r = await fetch(`${API_URL}/sessions/${encodeURIComponent(targetId)}/messages`, { headers });
      if (r.ok) {
        const data = await r.json();
        setMessages((data.messages || []).map((m) => ({ ...m, isNew: false })));
      } else {
        setMessages([]);
      }
    } catch {
      setMessages([]);
    }
  }, [authToken]);

  // Load user's saved chat list in sidebar once authenticated
  useEffect(() => {
    if (currentUser?.id && authToken) {
      fetchSessions();
    }
  }, [currentUser?.id, authToken, fetchSessions]);

  const handleAuthSuccess = (token, user) => {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    const freshSess = createSessionId();
    setSessionId(freshSess);
    setMessages([]);
    setJustLoggedIn(true);
    setIsAuthModalOpen(false);
    setAuthToken(token);
    setCurrentUser(user);
  };

  const handleLogout = () => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    setAuthToken('');
    setCurrentUser(null);
    setSessions([]);
    setMessages([]);
    setIsSidebarOpen(false);
    setSessionId(createSessionId());
  };

  // Health check
  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch(`${API_URL}/health`);
        setBackendHealth(r.ok ? await r.json() : { status: 'unhealthy' });
      } catch { setBackendHealth({ status: 'offline' }); }
    };
    check();
    const iv = setInterval(check, 30000);
    return () => clearInterval(iv);
  }, []);

  const handleNewChat = () => {
    const fresh = createSessionId();
    setSessionId(fresh);
    setMessages([]);
    setInputValue('');
  };

  const handleSelectSession = (targetId) => {
    if (targetId === sessionId) return;
    setSessionId(targetId);
    loadSessionMessages(targetId);
  };

  const handleDeleteSession = async (targetId) => {
    try {
      await fetch(`${API_URL}/sessions/${encodeURIComponent(targetId)}`, {
        method: 'DELETE',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      setSessions((prev) => prev.filter((s) => s.session_id !== targetId));
      if (targetId === sessionId) {
        handleNewChat();
      }
    } catch { /* ignore */ }
  };

  const handleSend = async (overrideText) => {
    const text = (overrideText || inputValue).trim();
    if (!text || isLoading) return;

    setMessages((prev) => [...prev, {
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }]);
    setInputValue('');
    setIsLoading(true);

    const payload = { session_id: sessionId, message: text };
    if (systemPrompt.trim()) payload.system_prompt = systemPrompt.trim();

    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    if (simulateHeader.trim()) headers['X-Simulate-Failure'] = simulateHeader.trim();

    try {
      const res = await fetch(`${API_URL}/chat`, { method: 'POST', headers, body: JSON.stringify(payload) });
      const data = await res.json().catch(() => null);

      if (!res.ok) {
        let msg = 'Something went wrong.';
        if (res.status === 422) msg = data?.detail || 'Invalid request.';
        else if (res.status === 503) msg = data?.detail === 'all providers unavailable'
          ? 'All AI providers are temporarily unavailable. Please try again shortly.'
          : (data?.detail || 'Service temporarily unavailable.');
        else msg = data?.detail || `Server error (${res.status}).`;

        setMessages((prev) => [...prev, { role: 'error', content: msg, status: res.status,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }]);
      } else {
        setMessages((prev) => [...prev, {
          role: 'assistant', content: data.reply, metadata: data.metadata, isNew: true,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }]);
        fetchSessions();
      }
    } catch {
      setMessages((prev) => [...prev, {
        role: 'error',
        content: 'Could not connect to the server. It may be starting up — please try again in a moment.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={`relay-app-wrapper ${isDarkMode ? 'dark-theme' : 'light-theme'}`}>
      <HistorySidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        sessions={sessions}
        activeSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        user={currentUser}
        onLogout={handleLogout}
        onOpenAuth={() => {
          setIsSidebarOpen(false);
          setIsAuthModalOpen(true);
        }}
      />

      {isAuthModalOpen && (
        <div className="drawer-overlay" onClick={() => setIsAuthModalOpen(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <AuthView
              apiUrl={API_URL}
              onAuthSuccess={handleAuthSuccess}
              isDarkMode={isDarkMode}
              onToggleTheme={() => setIsDarkMode(!isDarkMode)}
              onClose={() => setIsAuthModalOpen(false)}
            />
          </div>
        </div>
      )}

      <div className={`relay-app ${isSidebarOpen ? 'with-sidebar' : ''} ${justLoggedIn ? 'app-enter' : ''}`}>
        <Header
          onNewChat={handleNewChat}
          isDarkMode={isDarkMode}
          onToggleTheme={() => setIsDarkMode(!isDarkMode)}
          onToggleSidebar={() => setIsSidebarOpen((prev) => !prev)}
        />

        <main className="relay-chat-container">
          {messages.length === 0 ? (
            <EmptyState onSelectPrompt={(t) => handleSend(t)} />
          ) : (
            <div className="message-list">
              {messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} onStreamTick={scrollToBottom} />
              ))}

              {isLoading && (
                <div className="message-row assistant-row">
                  <div className="assistant-card loading-card">
                    <div className="typing-indicator">
                      <span /><span /><span />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </main>

        <Composer
          inputValue={inputValue}
          setInputValue={setInputValue}
          onSend={() => handleSend()}
          isLoading={isLoading}
        />

        <DevToolsDrawer
          isOpen={isDevToolsOpen}
          onClose={() => setIsDevToolsOpen(false)}
          simulateHeader={simulateHeader}
          onSetSimulateHeader={setSimulateHeader}
          systemPrompt={systemPrompt}
          onSetSystemPrompt={setSystemPrompt}
          sessionId={sessionId}
          apiUrl={API_URL}
          onNewChat={handleNewChat}
        />
      </div>
    </div>
  );
}
