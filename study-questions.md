# Study Questions — Shift Coverage

Interview questions an engineering manager might ask the developer who submitted this project, to check they actually understand how it works (not just that an AI assistant wrote it). Grouped from "explain the big picture" up to "trick questions" that probe specific edge cases in the code.

---

## Warm-up: the big picture

1. Walk me through what happens, end to end, from the moment someone clicks "Find coverage" to the moment a shift is either covered or marked uncovered.
2. Why is there only one `Employee` model instead of separate `Manager`/`Employee` types? What's the tradeoff of using a boolean flag instead?
3. Why does this app use WebSockets instead of the browser just polling every few seconds? What would break (or just get worse) if you ripped out Channels and polled instead?
4. `is_manager` and Django's built-in `is_staff`/superuser are two different flags. Why does the app need both, and what would go wrong if `is_manager` access was granted via `is_staff` instead?

---

## State machine and data model

5. What are all the statuses a `ShiftRequest` can be in, and which ones are terminal? How does the code enforce that a terminal request can't be reopened?
6. `CoverageEvent` rows are never updated or deleted — only added. Why design it as an append-only log instead of just tracking current state on `ShiftRequest`? What would you lose if it worked the other way?
7. Where does `_ask_candidate()` create a `ShiftResponse` — before or after the notification is sent? Why does the order matter?

---

## The trick questions

8. **The stale-button race.** Employee B gets asked to cover a shift. Before B responds, the requester cancels the request. B still has the notification open and clicks "Yes." Walk through exactly what happens in the code — does B's shift get marked covered? Why or why not? *(Answer they should find: `cancel_request()` deliberately leaves B's `ShiftResponse` as `PENDING` — it's not touched. `handle_response()` separately checks `sr.status != SEARCHING` and raises before ever looking at the answer. So B's stale "Yes" is rejected. Ask them to explain **why** the fix lives in `handle_response()` rather than in `cancel_request()` reaching out and marking every pending response as stale.)*

9. **The double-decline.** Suppose the same employee is asked twice for the same `ShiftRequest` — is that possible given `_ask_candidate()`'s use of `get_or_create`? What field would need to exist (and doesn't) for it to happen?

10. **The seniority swap.** In the admin, you edit Alice from rank 1 to rank 2 and Bob from rank 2 to rank 1 in the same bulk save, then click Save. Trace through `EmployeeChangeListForm`, `EmployeeChangeListFormSet.clean()`, and `EmployeeAdmin.save_model()` and explain why this doesn't throw an `IntegrityError`, given `seniority_rank` is a unique, positive-only field. What's the one scenario, mentioned directly in the code comments, that *can* still cause a 500 here?

11. **The placeholder overflow.** The bump-out-of-the-way placeholder is `1_000_000 + occupant.pk`. Is there any realistic scenario where this placeholder value itself collides with someone else's real or bumped rank? What has to be true about the roster size for this to be a real risk, and is that a legitimate concern for this app?

12. **The declined-but-still-counted candidate.** `_find_next_untried_candidate()` walks `remaining_roster` filtered to `is_active=True`, skipping anyone in `already_answered_ids`. If a manager deactivates an employee (`is_active=False`) *while* they're the current pending candidate on an active search, what happens to that in-flight ask? Does the app notice, or does it just sit there until they respond?

13. **The notification that won't die.** `prune_notifications()` exempts a notification from both the 24-hour cutoff and the 10-item cap if it's `actionable` — tied to a `PENDING` response on a still-`SEARCHING` request. If that same employee never responds and the request sits in `SEARCHING` for a week, what happens to that one notification? Is that a bug or intentional? What's the actual failure mode if *nobody* in the entire remaining roster ever responds?

14. **The re-entrant swap during pruning.** `prune_notifications` runs on every `notify()` call and on both notification views loading. Two tabs open for the same employee both trigger a page load at nearly the same instant. Is there a race condition here that could delete a notification a user is actively looking at, or double-count something? What Django/DB guarantee (or lack of one) makes this safe or unsafe?

15. **The channel layer swap.** The dev setup uses `InMemoryChannelLayer`. If this got deployed to production behind two `daphne`/`gunicorn` worker processes without switching to `channels_redis`, what specifically breaks? Would it fail loudly (an error) or silently (things just don't work)? How would you notice this in a code review if you didn't already know to look for it?

16. **The timezone vs. clock-time distinction.** A shift's start/end time is stored as a plain clock time with no timezone attached, but a notification's `created_at` is a real timezone-aware timestamp. Why does the app draw that distinction, and what would go wrong for a distributed/multi-timezone team if shift times *did* carry a timezone?

17. **Deactivation doesn't block login.** The README calls this out directly as a known gap: `is_active=False` stops someone from being asked for coverage but not from logging in. Ask the candidate to argue *both sides* — when is this the right default behavior, and when would it be a real security/access-control problem? What's the minimal fix?

18. **The 404-not-403 pattern.** Both the manager routes and other employees' shift request details return 404 instead of 403 when access is denied. What's the security reasoning here, and what's the cost (e.g., debuggability, honest error messages) of that choice?

---

## If you want to really stump them

19. Nothing in `handle_response()` uses a DB transaction or row-level locking around the "check pending → save answer → maybe advance to next candidate" sequence. Construct a scenario — real or contrived — where two near-simultaneous requests against the *same* `ShiftResponse` could both pass the `answer != PENDING` check before either has saved. Would this ever actually happen given how Django/WSGI/ASGI request handling works here, and if it's currently safe, is it safe *by design* or by accident?
20. `save_model()`'s bump-and-swap trick relies on the whole bulk-edit batch being one transaction, so the bumped-out occupant's real save happens before commit. What Django admin behavior guarantees that all rows in a `list_editable` save happen in one transaction? Is that documented, guessable, or something you'd only find by reading source — and how would *they* have verified it, if they were the one writing this fix?
