# Code Quality Report — Shift Coverage

**Reviewer role:** Engineering manager, evaluating this repository as a candidate submission
**Scope:** Full repository as of the current `HEAD` (Django app, `coverage/` + `shift_coverage/` + `templates/`)
**Verdict up front:** Hire-track strong. Not flawless, but the flaws are the kind you coach a mid-level engineer through, not the kind that make you worried about their judgment.

---

## Important caveat before anything else

This codebase was built collaboratively with an AI coding assistant (Claude Code) across an iterative session, not typed from scratch by a human in isolation. I know this because I'm the assistant that wrote most of it. A hiring manager reading a report like this one needs to know that up front, because it changes what the artifact can and can't tell you:

- **It does not, by itself, prove raw from-memory coding ability** the way a cold take-home or whiteboard exercise would.
- **It does demonstrate a different, increasingly real skill**: the applicant drove the direction (what to build, in what order), caught and reported real bugs through active exploratory testing rather than assuming AI output was correct, asked for a security-minded second pass, insisted on test coverage rather than accepting "it works," and pushed back on stale documentation. That's product judgment and quality-bar-setting, not typing speed — and it's a legitimate thing to hire for, but it's not the same thing as "can this person independently implement a cascading notification state machine at 2am with no help."
- **My recommendation**: use this repo as a conversation-starter in an interview, not as a standalone signal. Ask the applicant to walk through `coverage_service.py` unprompted, explain why `handle_response()` checks the request's status and not just the response's, or extend the cascade to skip employees on PTO. How they reason about code they (with help) shipped is the real signal here, not the diff itself.

With that on the table, here's the assessment of the code as it stands.

---

## What the app does

An internal Django tool for scheduling shift coverage: an employee posts a shift they can't work, the app asks people below them in a seniority list one at a time until someone accepts, and everyone gets real-time in-app notifications instead of texts or email. ~2,200 lines across the app and templates, 171 passing tests.

---

## Architecture & code organization

**Good:**
- Clean separation of concerns: `coverage_service.py` owns the state machine, `notifications.py` owns notification creation/text/retention, `views.py` owns HTTP orchestration, `models.py` stays mostly declarative. A reviewer can find "where does X happen" without guessing.
- The realtime layer (`consumers.py`, `routing.py`, `realtime.py`, `asgi.py`) is a genuinely well-executed addition. `coverage/time_format.py` deliberately mirrors Django's own `timezone.activate()`/`deactivate()` contextvar pattern instead of inventing something novel — that's the kind of "know the framework's own idioms and follow them" instinct that's hard to teach and easy to spot its absence.
- Decorators (`login_required_employee`, `manager_required`) and a shared `_safe_next_url()` helper are used consistently rather than copy-pasted per view.
- The `Employee.is_manager` flag is kept deliberately separate from Django's own `is_staff`/superuser concept. That's a real design decision, not an accident — conflating "can manage shifts" with "can access the Django admin" is a common beginner mistake, and it wasn't made here.

**Weaker:**
- `views.py` is a single 363-line file holding every view for the app — dashboard, roster, settings, manager pages, shift request CRUD, and the notification endpoints. It's still readable today because it's well-commented with section dividers, but it's the first file that will hurt at the next round of feature growth. A stronger structural instinct would split this into `views/dashboard.py`, `views/manager.py`, `views/notifications.py` once it crossed ~200 lines, rather than after it becomes a problem.
- No pagination anywhere — the roster page, the manager dashboard's employee/request tables, and the notifications page all render the full queryset. Fine at team-of-5 scale (this app's actual current scale); would need attention before it could serve a 500-person org. This is a completely normal thing to defer, but it's also completely normal for a reviewer to ask "what happens at 10x?" and I'd want to hear "pagination, obviously" as the answer, not silence.

---

## Big O / efficiency

Nothing here is asymptotically wrong — there's no accidental O(n²) hiding in a loop, no full-table scan where an index should carry the query, no N+1 query pattern in the parts of the code that render lists (`select_related` is used correctly and consistently in every dashboard/roster/manager query I checked). That's worth stating plainly: **this is not a submission with a Big-O red flag in it.**

What I *would* flag in review, all minor:

1. **`Employee.get_next_in_roster()`** (`models.py:85`) issues a fresh indexed query (`filter(seniority_rank__gt=..., is_active=True).order_by(...).first()`) every time it's called — each call is O(log n) at the DB layer thanks to the unique index on `seniority_rank`, which is correct. The rough edge is *how often* it's called: the decline-cascade in `_handle_no()` (`coverage_service.py:150`) calls it in a `while` loop that also runs a `ShiftResponse.objects.filter(...).exclude(...).exists()` query on every iteration, to skip people who've already answered. In the worst case (a long roster where many people have already declined) that's O(k) sequential DB round-trips for a single decline, where a stronger solution would fetch the remaining active roster once and the set of already-answered employee IDs once, then walk both in Python — O(1) queries instead of O(k). For a small team's roster this is invisible; for a 200-person roster it would show up in a query log. This is exactly the kind of thing I'd want an applicant to be able to spot and fix on request, and I'd bet they could — the surrounding code shows they understand `select_related` and query cost everywhere else.
2. **`prune_notifications()`** (`notifications.py:50`) runs 3–4 queries every time a notification is created (age-based delete, exempt-set lookup, keep-set lookup, cap-based delete). Bounded and cheap (nothing here scales with total notification volume, only with one employee's ~10-notification window), so this is a non-issue in practice, just worth naming as "more round-trips than strictly needed" rather than "efficient."
3. Everything else I checked — `manager_dashboard`'s `[:25]` slice (DB-level `LIMIT`, not a Python slice of a fully-materialized queryset), the roster ordering, the notification retention cap — does the efficient thing by default.

**Verdict:** correct and reasonably efficient. The gaps are "would ask about it in a follow-up round," not "would reject the submission."

---

## Code quality & attention to detail

**Strong evidence of attention to detail:**
- Real edge cases are handled, not just the happy path: a candidate declining after already answering, the entire roster being exhausted, an inactive employee being skipped in the cascade, a manager trying to act on someone else's request (view access is allowed, write access explicitly is not), a stale Yes/No answer arriving after the request was already cancelled.
- That last one is the standout data point in this review. The cancel feature wasn't built and left alone — a real race condition (an in-flight ask outliving the cancellation of its parent request) was caught, root-caused, and fixed with a status check in `handle_response()` rather than a band-aid, *and* the same class of staleness bug was independently checked and fixed in three other places that shared the same underlying assumption (the dashboard's "waiting on you" query, the notification bell's actionable-button logic, and the retention/pruning exemption logic). Finding one instance of a bug is normal. Recognizing it as a *pattern* and hunting down every other place the same assumption was baked in is a senior-leaning habit, not a junior one.
- Known limitations are documented in the README instead of hidden: deactivating an employee doesn't block their login, the in-memory channel layer doesn't survive multiple worker processes. Both are called out explicitly with the actual fix path named. I would much rather receive a submission that says "here's what I didn't finish and why" than one that pretends to be complete.

**Weaker:**
- Inline `style="..."` attributes are used throughout the templates instead of CSS classes — I counted 114 occurrences across the template directory. It works, and it's consistent (the same spacing/color patterns repeat rather than drifting), but it's a DRY violation a design-system-minded reviewer would flag immediately. Change the card padding once, and it's a find-and-replace across a dozen files instead of one CSS rule.
- `coverage/admin.py`'s `Employee` admin allows bulk-editing `seniority_rank` via `list_editable`. The model correctly enforces `unique=True` at the database level, but the admin UI doesn't pre-validate that — an admin bulk-editing two rows to the same rank would hit a raw `IntegrityError` (a 500-style failure) instead of a friendly form validation message. Low-traffic surface (only staff/superusers reach it), but it's the one spot in the app where an error would reach a user as a stack trace instead of a message.
- Test names and structure are excellent (`test_no_skips_a_candidate_who_already_answered`, `test_manager_still_cannot_activate_someone_elses_draft` — these read like specifications), but a chunk of the suite's breadth came from a dedicated audit pass rather than being written test-first alongside each feature. That's a legitimate and common way to work, but it's worth knowing that "171 passing tests" reflects a deliberate coverage sweep, not necessarily TDD discipline throughout.

---

## Security

This is a genuine strength. Over the course of the sessions that built this:
- An **open redirect** was found (an unvalidated `next` parameter on two POST endpoints) and fixed with Django's own `url_has_allowed_host_and_scheme` rather than a hand-rolled check.
- XSS was checked, not assumed — templates were specifically verified to have zero `|safe` filters and zero `autoescape off` blocks, and a payload was actually run through the form to confirm Django's default escaping holds.
- CSRF protection was verified to actually reject a request missing a token (403), not just assumed present because Django defaults to it.
- Authorization checks consistently use 404 rather than 403 for "you can't see this" (both "doesn't exist" and "exists but not yours" look identical from the outside) — a small, correct, deliberate choice that a lot of engineers get wrong by default.
- The one honest limitation here — deactivated employees can still log in — is flagged as a known gap, not silently shipped.

---

## Testing

171 tests, organized one file per concern (`test_models.py`, `test_forms.py`, `test_coverage_service.py`, `test_views.py`, `test_auth_linking.py`, `test_admin.py`, `test_realtime.py`), using a lightweight `factories.py` instead of a heavyweight fixture framework — appropriately scaled to the project's size. Tests read as documentation: a new engineer could learn the cancellation state machine's edge cases just from `test_coverage_service.py`'s test names, without reading the implementation.

The WebSocket consumer tests are a nice detail: rather than only testing the consumer in isolation (which would silently pass even if the URL routing were broken), there's a dedicated test that goes through the *actual* ASGI application and its real `URLRouter`, catching a class of bug that consumer-only tests would miss entirely.

One thing worth naming: a couple of tests are explicitly named `test_..._is_currently_accepted` — they pin down behavior that isn't actually validated (e.g., a shift's end time before its start time is accepted, not rejected) specifically so a future change to that behavior fails loudly instead of silently. That's a sophisticated testing instinct — using a test to document a *known gap* rather than only to assert correctness — and I don't see it often even from experienced engineers.

---

## Documentation

The README is unusually good for a project this size — not just "how to run it" but "here's the mental model, here's why this file exists, here's what this decision trades off." It's written for a specific, named audience (a newer engineer joining the project) and it succeeds at that. The fact that it stayed current across six-plus feature additions in one sitting, rather than rotting after the second one, is itself a signal: someone was treating documentation as part of the deliverable, not an afterthought bolted on at the end.

---

## Overall assessment: is this person hirable?

Based on the artifact alone — yes, on a positive trajectory, with the interview caveat stated at the top of this report firmly in place. The signals that matter most to me as a hiring manager aren't "did they write clever code" (this isn't clever code, and it doesn't need to be — it's an internal tool, and over-engineering it would itself be a red flag). What I'm looking for is:

- **Do they find their own bugs, or wait for someone else to?** Found their own, repeatedly, through actual exploratory testing rather than assumption.
- **When they find a bug, do they fix the instance or the pattern?** Fixed the pattern (see the stale-notification case above).
- **Do they know what they don't know?** Yes — the README's "known gaps" section and the in-memory channel layer caveat are both unprompted admissions of scope, not defensive hedging.
- **Do they default to the simplest correct thing, or reach for complexity?** Simplest correct thing, consistently — no unnecessary abstraction layers, no premature microservices, no framework-fighting.
- **Security instinct?** Present and active, not just "Django defaults handled it for me."

What I'd want to see in a follow-up interview, specifically: independent reasoning about the roster-cascade query pattern flagged above (can they see it and propose the fix without me pointing at it first?), and some sense of how much of the architecture decisions (the `time_format.py` contextvar mirroring Django's own timezone pattern, in particular) were their instinct versus a suggestion they accepted. Both are answerable in a 20-minute conversation, and either answer is fine — I just want to know which one I'm getting.
