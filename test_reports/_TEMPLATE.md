# Test Report — <Feature name>

**PR:** kuantorflow#<n> (+ kuantorflow_automation#<n> if applicable) · **Issue:** kuantorflow#<n> · **Date:** YYYY-MM-DD

## Summary

<One or two sentences: what shipped and the headline verification result.>

## What changed

- <Bullet list of the actual changes — files/behaviour, not the whole diff.>

## Automated tests

- **Added / updated:** <which test files, how many new tests, what they assert.>
- **Suite result:** `pytest -m "not live"` — **<N> passed** (was <M>), <skips/deselects>.

## Manual & browser verification

<The exact checks driven in the browser (or CLI), each with its outcome —
what was observed, not just "it works". Note viewport sizes for UI, and any
cleanup of test data.>

- <check → outcome>

## Result

<Pass/fail statement; anything deferred or flagged for follow-up.>
