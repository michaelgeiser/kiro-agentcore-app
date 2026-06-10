import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

describe('Test runner sanity check', () => {
  it('should run a basic assertion', () => {
    expect(1 + 1).toBe(2);
  });

  it('should have access to jsdom environment', () => {
    const div = document.createElement('div');
    div.textContent = 'hello';
    expect(div.textContent).toBe('hello');
  });

  it('should run a fast-check property', () => {
    fc.assert(
      fc.property(fc.integer(), fc.integer(), (a, b) => {
        expect(a + b).toBe(b + a);
      })
    );
  });
});
