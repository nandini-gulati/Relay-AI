import React, { useState, useMemo } from 'react';

function getPasswordChecks(pw) {
  return [
    { id: 'len', label: 'At least 8 characters', met: pw.length >= 8 },
    { id: 'upper', label: 'One uppercase letter (A-Z)', met: /[A-Z]/.test(pw) },
    { id: 'lower', label: 'One lowercase letter (a-z)', met: /[a-z]/.test(pw) },
    { id: 'num', label: 'One number (0-9)', met: /\d/.test(pw) },
    { id: 'special', label: 'One special character (!@#$...)', met: /[^A-Za-z0-9]/.test(pw) },
  ];
}

export default function AuthView({ apiUrl, onAuthSuccess, isDarkMode, onToggleTheme, onClose }) {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLeaving, setIsLeaving] = useState(false);

  const passwordChecks = useMemo(() => getPasswordChecks(password), [password]);
  const passedCount = passwordChecks.filter((c) => c.met).length;
  const isStrongPassword = passedCount === passwordChecks.length;

  const strengthLabel =
    passedCount <= 1 ? 'Weak' : passedCount <= 3 ? 'Fair' : passedCount === 4 ? 'Good' : 'Strong';
  const strengthClass =
    passedCount <= 1 ? 'weak' : passedCount <= 3 ? 'fair' : passedCount === 4 ? 'good' : 'strong';

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMessage('');

    if (mode === 'register' && !isStrongPassword) {
      setErrorMessage('Please choose a stronger password that meets all requirements.');
      return;
    }

    setIsSubmitting(true);

    const endpoint = mode === 'login' ? '/auth/login' : '/auth/register';
    try {
      const res = await fetch(`${apiUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
        setErrorMessage(
          detail || (mode === 'login' ? 'Invalid email or password.' : 'Could not create account.')
        );
        setIsSubmitting(false);
      } else if (data.token && data.user) {
        setIsLeaving(true);
        setTimeout(() => {
          onAuthSuccess(data.token, data.user);
        }, 260);
      } else {
        setIsSubmitting(false);
      }
    } catch {
      setErrorMessage('Could not reach the server. Please try again.');
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-screen">
      <button
        type="button"
        className="btn-icon-ghost auth-theme-btn"
        onClick={onToggleTheme}
        title={isDarkMode ? 'Light Mode' : 'Dark Mode'}
        aria-label="Toggle theme"
      >
        {isDarkMode ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
      </button>

      <div className={`auth-card ${isLeaving ? 'leaving' : ''}`}>
        <div className="auth-brand-row">
          <div className="auth-brand">
            <div className="logo-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <span className="auth-brand-name">Relay</span>
          </div>
          {onClose && (
            <button
              type="button"
              className="btn-icon-ghost"
              onClick={onClose}
              aria-label="Close"
              title="Close"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>

        <h1 className="auth-title">
          {mode === 'login' ? 'Sign in to continue' : 'Create your account'}
        </h1>
        <p className="auth-subtitle">
          {mode === 'login'
            ? 'Access your private conversation history from any session.'
            : 'Create an account to save your own private chat history.'}
        </p>

        {errorMessage && <div className="auth-alert auth-alert-error">{errorMessage}</div>}

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-label">
            <span>Email</span>
            <input
              type="email"
              className="auth-input"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </label>
          <label className="auth-label">
            <span>Password</span>
            <div className="auth-password-wrap">
              <input
                type={showPassword ? 'text' : 'password'}
                className="auth-input auth-input-password"
                placeholder={mode === 'login' ? 'Enter your password' : 'Create a strong password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="auth-eye-btn"
                onClick={() => setShowPassword((prev) => !prev)}
                title={showPassword ? 'Hide password' : 'Show password'}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                    <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
                  </svg>
                ) : (
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </label>

          {mode === 'register' && (
            <div className="password-strength-box">
              <div className="strength-header">
                <span className="strength-title">Password strength</span>
                {password && (
                  <span className={`strength-badge strength-${strengthClass}`}>
                    {strengthLabel}
                  </span>
                )}
              </div>
              <div className="strength-bars">
                {[1, 2, 3, 4, 5].map((n) => (
                  <span
                    key={n}
                    className={`strength-bar ${passedCount >= n ? `active strength-bg-${strengthClass}` : ''}`}
                  />
                ))}
              </div>
              <ul className="strength-checklist">
                {passwordChecks.map((rule) => (
                  <li key={rule.id} className={rule.met ? 'met' : ''}>
                    <span className="check-dot" aria-hidden="true">
                      {rule.met ? '✓' : '•'}
                    </span>
                    <span>{rule.label}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="submit"
            className="auth-submit-btn"
            disabled={isSubmitting || (mode === 'register' && !isStrongPassword)}
          >
            {isSubmitting
              ? mode === 'login'
                ? 'Signing in...'
                : 'Creating account...'
              : mode === 'login'
                ? 'Sign in'
                : 'Create account'}
          </button>
        </form>

        <div className="auth-links">
          {mode === 'login' ? (
            <span className="auth-link-sep">
              New here?{' '}
              <button
                type="button"
                className="auth-link-btn strong"
                onClick={() => {
                  setErrorMessage('');
                  setPassword('');
                  setShowPassword(false);
                  setMode('register');
                }}
              >
                Create an account
              </button>
            </span>
          ) : (
            <span className="auth-link-sep">
              Already have an account?{' '}
              <button
                type="button"
                className="auth-link-btn strong"
                onClick={() => {
                  setErrorMessage('');
                  setPassword('');
                  setShowPassword(false);
                  setMode('login');
                }}
              >
                Sign in
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
