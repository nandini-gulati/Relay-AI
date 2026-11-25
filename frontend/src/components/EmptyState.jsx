import React from 'react';

export default function EmptyState({ onSelectPrompt }) {
  const suggestions = [
    {
      label: 'Explain a concept',
      prompt: 'Explain quantum computing in simple terms with an analogy.',
    },
    {
      label: 'Explore history',
      prompt: 'What are some interesting historical facts about Paris?',
    },
    {
      label: 'Write code',
      prompt: 'Write a clean Python function to count and sort item frequencies.',
    },
    {
      label: 'System design',
      prompt: 'What is the speed of light, and how does distance affect network latency?',
    },
  ];

  return (
    <div className="empty-state-view">
      <div className="hero-section">
        <h1 className="hero-title">What can I help with today?</h1>
        <p className="hero-subtitle">
          Ask questions, brainstorm ideas, write code, or explore complex topics.
        </p>
      </div>

      <div className="suggestions-grid">
        {suggestions.map((item, i) => (
          <button
            key={i}
            type="button"
            className="suggestion-card"
            onClick={() => onSelectPrompt(item.prompt)}
          >
            <span className="suggestion-label">{item.label}</span>
            <span className="suggestion-text">{item.prompt}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
