import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createElement, setAttributes, clearChildren, formatFileSize, showToast } from '../../js/utils/dom.js';

describe('createElement', () => {
  it('creates an element with the given tag', () => {
    const el = createElement('div');
    expect(el.tagName).toBe('DIV');
  });

  it('sets className from attributes', () => {
    const el = createElement('span', { className: 'btn btn-primary' });
    expect(el.className).toBe('btn btn-primary');
  });

  it('sets textContent from attributes', () => {
    const el = createElement('p', { textContent: 'Hello world' });
    expect(el.textContent).toBe('Hello world');
  });

  it('sets standard HTML attributes', () => {
    const el = createElement('input', { type: 'text', id: 'my-input', placeholder: 'Enter name' });
    expect(el.getAttribute('type')).toBe('text');
    expect(el.getAttribute('id')).toBe('my-input');
    expect(el.getAttribute('placeholder')).toBe('Enter name');
  });

  it('attaches event listeners for on* attributes', () => {
    const handler = vi.fn();
    const el = createElement('button', { onClick: handler });
    el.click();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('appends child elements', () => {
    const child = createElement('span', { textContent: 'child' });
    const parent = createElement('div', {}, [child]);
    expect(parent.children.length).toBe(1);
    expect(parent.firstChild).toBe(child);
  });

  it('appends text string children as text nodes', () => {
    const el = createElement('p', {}, ['Hello ', 'world']);
    expect(el.textContent).toBe('Hello world');
    expect(el.childNodes.length).toBe(2);
  });

  it('skips null/undefined/false attribute values', () => {
    const el = createElement('div', { 'data-active': null, 'data-hidden': undefined, 'data-x': false });
    expect(el.hasAttribute('data-active')).toBe(false);
    expect(el.hasAttribute('data-hidden')).toBe(false);
    expect(el.hasAttribute('data-x')).toBe(false);
  });

  it('sets ARIA attributes', () => {
    const el = createElement('button', { 'aria-label': 'Close', role: 'alert' });
    expect(el.getAttribute('aria-label')).toBe('Close');
    expect(el.getAttribute('role')).toBe('alert');
  });
});

describe('setAttributes', () => {
  it('sets attributes on an existing element', () => {
    const el = document.createElement('input');
    setAttributes(el, { type: 'email', required: 'true' });
    expect(el.getAttribute('type')).toBe('email');
    expect(el.getAttribute('required')).toBe('true');
  });

  it('removes attributes when value is null or false', () => {
    const el = document.createElement('div');
    el.setAttribute('data-visible', 'true');
    setAttributes(el, { 'data-visible': null });
    expect(el.hasAttribute('data-visible')).toBe(false);
  });
});

describe('clearChildren', () => {
  it('removes all child nodes from an element', () => {
    const parent = document.createElement('div');
    parent.appendChild(document.createElement('span'));
    parent.appendChild(document.createElement('p'));
    parent.appendChild(document.createTextNode('text'));
    expect(parent.childNodes.length).toBe(3);

    clearChildren(parent);
    expect(parent.childNodes.length).toBe(0);
  });

  it('handles an already-empty element', () => {
    const parent = document.createElement('div');
    clearChildren(parent);
    expect(parent.childNodes.length).toBe(0);
  });
});

describe('formatFileSize', () => {
  it('formats 0 bytes', () => {
    expect(formatFileSize(0)).toBe('0 Bytes');
  });

  it('formats bytes (< 1 KB)', () => {
    expect(formatFileSize(512)).toBe('512 Bytes');
  });

  it('formats exact 1 KB', () => {
    expect(formatFileSize(1024)).toBe('1 KB');
  });

  it('formats kilobytes', () => {
    expect(formatFileSize(256 * 1024)).toBe('256 KB');
  });

  it('formats megabytes with decimals', () => {
    expect(formatFileSize(1.5 * 1024 * 1024)).toBe('1.5 MB');
  });

  it('formats exact megabytes', () => {
    expect(formatFileSize(10 * 1024 * 1024)).toBe('10 MB');
  });

  it('formats gigabytes', () => {
    expect(formatFileSize(2.5 * 1024 * 1024 * 1024)).toBe('2.5 GB');
  });

  it('formats 500 MB (max upload size)', () => {
    expect(formatFileSize(500 * 1024 * 1024)).toBe('500 MB');
  });
});

describe('showToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    // Clean up any toasts left in the DOM
    document.querySelectorAll('.toast').forEach(el => el.remove());
  });

  it('creates a toast element in the DOM', () => {
    showToast('Test message');
    const toast = document.querySelector('.toast');
    expect(toast).not.toBeNull();
    expect(toast.textContent).toContain('Test message');
  });

  it('applies the error type class', () => {
    showToast('Error occurred', 'error');
    const toast = document.querySelector('.toast');
    expect(toast.classList.contains('toast--error')).toBe(true);
  });

  it('applies the success type class', () => {
    showToast('Upload complete', 'success');
    const toast = document.querySelector('.toast');
    expect(toast.classList.contains('toast--success')).toBe(true);
  });

  it('applies the info type class by default', () => {
    showToast('Info message');
    const toast = document.querySelector('.toast');
    expect(toast.classList.contains('toast--info')).toBe(true);
  });

  it('includes a close button', () => {
    showToast('Message');
    const closeBtn = document.querySelector('.toast__close');
    expect(closeBtn).not.toBeNull();
    expect(closeBtn.getAttribute('aria-label')).toBe('Close notification');
  });

  it('removes the toast when close button is clicked', () => {
    showToast('Message');
    const closeBtn = document.querySelector('.toast__close');
    closeBtn.click();
    expect(document.querySelector('.toast')).toBeNull();
  });

  it('auto-dismisses after the specified duration', () => {
    showToast('Temporary', 'info', 3000);
    expect(document.querySelector('.toast')).not.toBeNull();

    vi.advanceTimersByTime(3000);
    expect(document.querySelector('.toast')).toBeNull();
  });

  it('does not auto-dismiss when duration is 0', () => {
    showToast('Persistent', 'info', 0);
    vi.advanceTimersByTime(10000);
    expect(document.querySelector('.toast')).not.toBeNull();
  });

  it('sets role=alert and aria-live=assertive for accessibility', () => {
    showToast('Accessible toast');
    const toast = document.querySelector('.toast');
    expect(toast.getAttribute('role')).toBe('alert');
    expect(toast.getAttribute('aria-live')).toBe('assertive');
  });
});
