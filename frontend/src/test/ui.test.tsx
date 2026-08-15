import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SeverityBadge, Confidence, EmptyState, LoadingState, ErrorState } from '../components/Ui';

describe('SeverityBadge', () => {
  it('renders the band label', () => {
    render(<SeverityBadge band="critical" />);
    expect(screen.getByText('critical')).toBeInTheDocument();
  });
});

describe('Confidence', () => {
  it('renders percentage for 0-1 values', () => {
    render(<Confidence value={0.75} />);
    expect(screen.getByText('75%')).toBeInTheDocument();
  });

  it('renders percentage for 0-100 values', () => {
    render(<Confidence value={75} />);
    expect(screen.getByText('75%')).toBeInTheDocument();
  });
});

describe('EmptyState', () => {
  it('shows default text when no props given', () => {
    render(<EmptyState />);
    expect(screen.getByText('No records available')).toBeInTheDocument();
  });

  it('shows custom title and detail', () => {
    render(<EmptyState title="No data" detail="Nothing here yet" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
  });
});

describe('LoadingState', () => {
  it('renders loading text', () => {
    render(<LoadingState />);
    expect(screen.getByText('Loading intelligence data…')).toBeInTheDocument();
  });
});

describe('ErrorState', () => {
  it('renders error message and retry button', () => {
    const retry = vi.fn();
    render(<ErrorState error="Failed to fetch" retry={retry} />);
    expect(screen.getByText('Failed to fetch')).toBeInTheDocument();
    expect(screen.getByText('Request failed')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: /try again/i });
    button.click();
    expect(retry).toHaveBeenCalled();
  });

  it('uses intent-aware titles instead of a generic API outage', () => {
    const retry = vi.fn();
    const { rerender } = render(
      <ErrorState error="Request validation failed" retry={retry} code="request_validation_failed" />,
    );
    expect(screen.getByText('Invalid request')).toBeInTheDocument();
    rerender(<ErrorState error="Unable to reach the API" retry={retry} />);
    expect(screen.getByText('API unavailable')).toBeInTheDocument();
    rerender(<ErrorState error="Bearer token required" retry={retry} code="unauthenticated" />);
    expect(screen.getByText('Sign in required')).toBeInTheDocument();
  });
});
