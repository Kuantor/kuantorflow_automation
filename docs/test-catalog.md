# KuantorFlow Automation — Test Catalog

**As of 3 August 2026** · Repository: [kuantorflow_automation](https://github.com/Kuantor/kuantorflow_automation) · **579 test cases in 38 files**

Every test in the suite, with a one-sentence description of what it checks, grounded in the test body rather than its name. One section per file, in alphabetical order.

---

## How to run

The suite lives in `tests/` and runs with the repo's own virtualenv:

| Command | What runs |
| --- | --- |
| `.\venv\Scripts\pytest` | Everything — **579 cases: 569 pass, 10 skip.** |
| `.\venv\Scripts\pytest -m "not live"` | The **offline suite** — 573 cases, of which 563 pass and 10 skip. About 18 seconds, no network. |
| `.\venv\Scripts\pytest -m live` | **6 read-only smoke tests** against the deployed site. |

The offline tests import the Flask app from the kuantorflow checkout (`KUANTORFLOW_PATH` in the gitignored `.env`, defaulting to a sibling directory) with the database and every external service stubbed.

**Two markers**, both declared in `pytest.ini`:

- `live` — hits the deployed site over the network; needs `SITE_URL` and the real `ACCESS_KEYWORD` in `.env`. All 6 are in `test_live_site.py`.
- `db` — runs against a **local** MySQL and creates its own scratch database. These 10 are **opt-in**: they skip unless `RUN_DB_ROUNDTRIP=1` is set with `DB_HOST=localhost` and the `DB_*` variables configured. They are the suite's only skips, and they live in `test_apply_schema_db.py` (5), `test_card_editing_db.py` (4) and `test_backup_roundtrip.py` (1).

**"Offline" is a property of the fixtures, not of the network.** A local MySQL usually *is* reachable from a development machine, so a test that forgets to stub a database call will quietly connect to it and pass. Several autouse fixtures exist for exactly that reason.

### Counting

The document reports **cases** — what `pytest --collect-only -q` counts, so the arithmetic reconciles with a test run. 528 test functions expand to 579 cases through `@pytest.mark.parametrize`; where a file's two numbers differ, its heading says so.

---

## Shared fixtures (`conftest.py`)

**Autouse — applied to every test whether it asks or not:**

| Fixture | What it does |
| --- | --- |
| `settings_dir` | Redirects the settings store to a per-test temp directory. Autouse because the store writes a config file on first read (kuantorflow#86), so any test that renders a page would otherwise write into the real checkout. |
| `action_logs` | Redirects `logs/` (kuantorflow#30) to a temp directory — any test that saves a card, looks a word up or uploads a file writes a log line. |
| `chat_logs` | Redirects Mykola's `mykola_logs/` to a temp directory. Tests that need a pre-existing conversation write it here. |
| `block_state` | No account is blocked unless a test says so (kuantorflow#126). Autouse because `current_block()` runs on every signed-in request; without it the offline suite would open a real connection to whatever `DB_*` points at. A test that wants a blocked account calls `block_state.block(...)`. |

**On demand:**

| Fixture | What it gives you |
| --- | --- |
| `app_module` | The imported Flask app module with a known gate keyword, a stubbed topic list, a stubbed anonymous-message counter (kuantorflow#164) and `flashcard_word_exists` returning False (kuantorflow#145) — so no test reaches a real database by accident. |
| `client` | A test client already through the keyword gate. |
| `fresh_client` | A test client with no session at all — still outside the gate. |
| `user_client` | Through the gate **and** signed in, with an `id` in the session as a real one carries since kuantorflow#148 (`TEST_USER_ID = 7`, `TEST_USER_EMAIL = test.user@gmail.com`). |
| `saved` | Captures `save_flashcard()` calls instead of writing to MySQL. A list of entries, with the owner id of each alongside in `.owner_ids` (kuantorflow#89). |
| `keyword` | The gate keyword the app module was patched with. |

---

## test_access_gate.py — the keyword gate (6 cases)

Every page is blocked until the keyword is entered.

| Test | What it checks |
| --- | --- |
| `test_pages_redirect_to_gate_when_unauthenticated` | Home, a flashcards topic and a quiz page all answer 302 to `/enter` for a visitor with no session. |
| `test_write_endpoints_are_gated` | The write endpoints are gated too, not just the pages: `/cards/add` and card deletion both redirect. |
| `test_gate_page_and_static_assets_reachable` | The gate page itself answers 200 with its prompt, and the stylesheet loads — otherwise the gate could not render. |
| `test_wrong_keyword_shows_error` | A wrong keyword re-renders the gate with "Incorrect keyword" rather than redirecting. |
| `test_correct_keyword_opens_site` | The correct keyword redirects, and the home page opens afterwards. |
| `test_fresh_session_is_gated_again` | Access is per session: a brand-new client is gated while another session is inside the site. |

## test_account_deletion.py — delete my account (31 cases)

kuantorflow#165. The operation is irreversible — soft delete was considered and dropped (#159) — so these tests care as much about what is *not* destroyed, and about the order of operations, as about the happy path. Cards are resolved first, then the files, and the users row goes last: `added_by_user_id` is `ON DELETE RESTRICT` (#89), so a path that skipped the card step would fail loudly on the foreign key rather than quietly cascading.

**Resolving the cards**

| Test | What it checks |
| --- | --- |
| `test_keeping_cards_clears_the_owner` | "Keep" issues `UPDATE flashcards SET added_by_user_id = NULL` — the cards stay for everyone else, with no owner — and never a `DELETE`. |
| `test_deleting_cards_removes_them` | "Delete" issues `DELETE FROM flashcards WHERE added_by_user_id = %s` and reports the row count. |
| `test_only_that_users_cards_are_touched` | Both branches carry the `WHERE added_by_user_id = %s` clause bound to that user — never a bare `UPDATE`/`DELETE`. |
| `test_deleting_the_user_row_is_scoped_by_id` | `delete_user()` issues `DELETE FROM users WHERE id = %s` and returns True. |
| `test_a_missing_user_row_reports_false` | A delete that affects no rows returns False rather than claiming success. |

**The orchestration**

| Test | What it checks |
| --- | --- |
| `test_everything_belonging_to_the_account_goes` | One call removes the chat-log directory and the settings file, reports the card count, and confirms the users row went. |
| `test_the_users_row_goes_last` | The recorded step order is cards → row: while the row exists the account is coherent and the deletion can be retried; once it is gone, leftovers have nothing to attribute them to. |
| `test_the_card_choice_is_passed_through` | `keep_cards=False` reaches the card step unchanged rather than being defaulted away. |
| `test_a_user_with_no_files_still_deletes` | Someone who never saved settings and never chatted still deletes cleanly — the two missing files are reported as False, not as a failure. |

**The route**

| Test | What it checks |
| --- | --- |
| `test_a_signed_in_user_can_delete_their_account` | `POST /account/delete` with `cards=keep` calls the deletion for the signed-in id and confirms it on the page. |
| `test_the_delete_choice_is_honoured` | `cards=delete` reaches the deletion as `keep_cards=False` — "delete" must not be read as "keep". |
| `test_a_missing_or_junk_choice_keeps_the_cards` | A missing or nonsense `cards` value falls back to keeping them: the destructive option has to be asked for explicitly. |
| `test_the_session_identity_is_cleared` | The `user` key is gone from the session afterwards. |
| `test_the_gate_pass_survives` | `access_granted` stays: the keyword gate is about the site, not the account, so a deleted user lands back inside it as an anonymous visitor. Clearing that is Reset Auth's job (#98). |
| `test_an_anonymous_visitor_has_no_account_to_delete` | An anonymous POST answers 403 with the sign-in message and touches nothing. |
| `test_a_sign_in_with_no_users_row_is_refused` | A session carrying `id: None` (#148) is refused 403 — there is no account record to remove. |
| `test_a_failure_removes_nothing_and_says_so` | When the deletion raises, the page says nothing was removed **and** the user stays signed in. |
| `test_delete_rejects_get` | `GET /account/delete` answers 405 — deletion is not reachable by following a link. |

**Logging (#30)**

| Test | What it checks |
| --- | --- |
| `test_the_deletion_is_logged` | An `ACCOUNT-DELETE` line records the id, the card count and the choice. |
| `test_the_log_line_carries_no_email` | No `@` anywhere in that line: the point of the operation is removing the identifier, so writing it into a fresh line would undo part of what was asked. |

**The dialog**

| Test | What it checks |
| --- | --- |
| `test_a_signed_in_user_sees_the_control` | The delete button and its modal are rendered for a signed-in visitor. |
| `test_anonymous_visitors_do_not` | Neither appears for an anonymous one. |
| `test_the_dialog_spells_out_the_consequences` | It says "cannot be undone" and names the account record, the Mykola conversation and the settings — with the non-destructive card option preselected. |
| `test_the_dialog_uses_the_danger_styling` | The dialog carries the `danger` class, so it does not look like an ordinary confirmation. |
| `test_the_browser_state_is_cleared_on_submit` | The submit handler clears this browser's own widget state — the account is going, so its leftovers go too. |

**The admin account cannot delete itself (#165)**

| Test | What it checks |
| --- | --- |
| `test_the_admin_account_cannot_be_deleted` | The route refuses with 403 and touches nothing: greying the button is presentation, and a hand-made POST goes straight past it (#162). |
| `test_the_refusal_says_how_to_actually_do_it` | The refusal names `ADMIN_EMAILS` — admin-ness lives there (#158), so that is the way out. A dead end is worse than a signpost. |
| `test_the_admins_control_is_greyed_with_the_reason` | The admin's button carries `aria-disabled="true"` and the reason. |
| `test_a_regular_user_keeps_a_live_control` | A regular user's button has no `aria-disabled` at all. |
| `test_the_greyed_control_explains_itself_on_tap` | Tapping the greyed control opens an explanatory modal — touch devices never see the `title` tooltip. |
| `test_the_greyed_control_has_no_hover_state` | The stylesheet suppresses the hover state on a disabled control, so it does not invite a click. |

## test_action_logs.py — action logs (19 cases)

kuantorflow#30. Three files — `cards.log`, `dict.log`, `parsed_files.log` — written as `<timestamp> ACTION key=value …`.

**cards.log**

| Test | What it checks |
| --- | --- |
| `test_card_creation_is_logged` | One `CREATE` line carries the word, part of speech, topic, the row id the save returned, which translation languages the card holds, the source and the user. |
| `test_signed_in_user_is_named` | The signed-in address appears as `user=` rather than `anonymous`. |
| `test_duplicate_card_is_logged_as_skipped` | A duplicate writes a `SKIP` line with `reason=duplicate` while the response reports the duplicate. |
| `test_automatic_add_is_logged_with_its_own_source` | A card added by the automatic-add setting is logged as `source='automatic add'`, distinguishable from the review popup. |
| `test_card_deletion_is_logged` | A `DELETE` line records the id, the word and the topic. |
| `test_deleting_a_missing_card_is_logged_too` | Deleting a card that is not there writes `DELETE-MISS` and **not** `DELETE` — the attempt is still on record. |
| `test_edit_helper_is_ready_for_an_edit_feature` | `card_edited()` writes an `EDIT` line with the id and the changed fields. Written before the edit route existed, so that feature logged from its first commit. |

**dict.log**

| Test | What it checks |
| --- | --- |
| `test_lookup_logs_every_site_it_used` | A lookup writes one `TRANSLATE` line per language with the provider, the part-of-speech count and the elapsed milliseconds, a `DEFINE` line for the dictionary, and a `RESULT` line with the card count. |
| `test_lookup_logs_the_fallback_provider` | When Bing fails, its line carries the error and Google's carries `fallback_from=bing` — the log shows which site actually answered, for the dictionary as well as the translator. |
| `test_failed_lookup_is_logged` | A lookup that finds nothing raises **and** leaves a `FAILED` line with the reason. |
| `test_lookup_route_logs_the_user_and_their_providers` | The `LOOKUP` line records the word, both configured providers and the user (`anonymous` here). |

**parsed_files.log**

| Test | What it checks |
| --- | --- |
| `test_parsed_file_is_logged` | An uploaded notes file writes a `PARSE` line with the filename, byte count, cards produced, topic, user and duration. |
| `test_rejected_file_is_logged` | An unsupported format writes `REJECT` with the reason and no `PARSE` line. |
| `test_ai_term_split_is_logged` | The AI term split fails silently by design (#134), so the `SPLIT` line — line count, error, model name — is the only trace it leaves. |

**The files themselves**

| Test | What it checks |
| --- | --- |
| `test_the_three_log_files_are_written_where_the_issue_asks` | Exactly `cards.log`, `dict.log` and `parsed_files.log` appear in the log directory — no more, no fewer. |
| `test_logs_rotate_monthly_and_keep_a_year` | The handler is a `TimedRotatingFileHandler` rotating every 30 days and keeping 12 backups. |
| `test_values_with_spaces_are_quoted` | A value containing a space is quoted (`word='lucid dream'`), so the `key=value` format stays parseable. |
| `test_a_broken_log_never_breaks_the_action` | With the logger raising `OSError`, the card is still saved and the response is still a success — logging is never allowed to fail the action. |
| `test_logs_do_not_leak_into_the_app_console` | `propagate=False`: these lines belong in the file, not in the app's stderr. |

## test_admin_identity.py — who is an administrator (16 tests, 32 cases)

kuantorflow#158. `ADMIN_EMAILS` in `.env` decides. The check **fails closed**: not signed in, no verified claim, or not listed all mean "not admin". Written before anything used the privilege, so the resolution was right before #126 (blocking) and #162 (deleting any card) were built on it.

| Test | What it checks |
| --- | --- |
| `test_admin_emails_parsing` | Seven cases: one address, a comma-separated list, surrounding whitespace and tabs, mixed case folded down, and the empty / blank / comma-only strings yielding no admins at all. |
| `test_an_unset_variable_yields_no_admins` | With the variable deleted from the environment, the result is an empty set — never a crash, and never "everyone". |
| `test_a_listed_verified_user_is_an_admin` | A signed-in, listed, verified address resolves to True. |
| `test_an_unlisted_user_is_not` | A verified address that is not listed resolves to False. |
| `test_an_anonymous_visitor_is_never_an_admin` | No session identity at all resolves to False. |
| `test_case_and_whitespace_in_the_session_email_do_not_matter` | The session's address is normalised the same way the configured list is. |
| `test_no_admins_configured_means_nobody_is_an_admin` | An empty `ADMIN_EMAILS` denies even the address that would otherwise match. |
| `test_one_of_several_configured_admins_matches` | Matching any entry in a multi-address list is enough. |
| `test_an_unverified_address_never_matches` | The point of the claim: holding a listed address is not enough if Google has not verified it. |
| `test_a_session_without_the_claim_is_not_an_admin` | A session predating #158 carries no `email_verified` and fails closed — the owner signs in once more rather than silently gaining the privilege, or silently keeping it after the address was unverified. |
| `test_the_verified_claim_is_read_strictly` | Eight cases. `bool("false")` is True, so the claim is compared rather than trusted for truthiness: `True`/`"true"`/`"True"` pass; `False`, `"false"`, `""`, `None` and `"yes"` do not. |
| `test_a_missing_claim_is_not_verified` | An absent claim reads as not verified. |
| `test_the_sign_in_stores_the_claim` | Four cases through the real Google callback: the claim is written into the session as a bool, since `is_admin()` reads the session rather than the provider. |
| `test_is_admin_is_available_to_templates` | A template renders `is_admin` as True for an admin session. |
| `test_templates_see_false_for_everyone_else` | The same template renders False without one. |
| `test_a_rendered_page_carries_the_flag` | Through the real context processor on a real page render, not only by calling the helper directly. |

## test_anonymous_chat_logs.py — an anonymous conversation is not written down (8 cases)

kuantorflow#163. The widget tells a visitor who declines to sign in that "nothing is kept under your name", and their chat went to the shared `mykola_logs/` root instead of a per-user folder. Nothing ever read those files, so the write was removed rather than the promise reworded. These tests assert on the **whole directory tree**, since the criterion is that nothing appears anywhere.

| Test | What it checks |
| --- | --- |
| `test_an_anonymous_chat_writes_nothing` | One anonymous message leaves the log directory empty. |
| `test_a_whole_anonymous_conversation_writes_nothing` | Three messages leave it empty too — in case only the first were skipped. |
| `test_an_anonymous_restart_writes_no_marker` | The automatic restart still happens and still hands the widget a fresh chat id, but opens no log file. The non-obvious path: the restart reads the browser's own last-message timestamp, so an anonymous visitor does reach the writer. |
| `test_an_anonymous_restart_gets_no_recap` | Nothing to review, because their previous chats were never written down. |
| `test_a_signed_in_chat_is_still_logged` | One file in the user's own directory, containing both sides of the exchange. |
| `test_a_signed_in_restart_still_opens_a_log` | The counterpart: for someone with an account the restart marker is exactly the record they were promised. |
| `test_the_shared_root_is_never_a_destination` | `_chat_log_path()` returns None anonymously and a path under the user's folder when signed in — one place decides, so both writers inherit the rule. |
| `test_the_widget_still_makes_the_promise` | The sentence this issue exists to make true is still on the page. If it is ever reworded to say chats *are* kept, this test argues back. |

## test_anonymous_limit.py — how much of Mykola an anonymous visitor gets (11 cases)

kuantorflow#164. Two limits: a per-session allowance they meet first, and a daily ceiling across all anonymous visitors that actually bounds the Anthropic bill. Both are checked **before** the model is called, so a refused message costs nothing.

**The per-session allowance**

| Test | What it checks |
| --- | --- |
| `test_anonymous_visitor_is_allowed_up_to_the_limit` | With the limit at 3, all three messages are answered and the model is called three times. |
| `test_the_next_message_is_refused_without_calling_the_model` | The message past the limit answers 402 with `sign_in_required` and a sign-in prompt, and the model is not called — the whole point. |
| `test_a_refused_message_does_not_consume_more_quota` | Repeated refusals leave the session counter where it was, so the count cannot run away. |
| `test_a_signed_in_visitor_is_never_limited` | Five messages all succeed and no counter is written into the session at all. |
| `test_zero_disables_the_session_limit` | A limit of 0 means unlimited: six messages all answered. |

**The daily ceiling**

| Test | What it checks |
| --- | --- |
| `test_daily_ceiling_refuses_with_its_own_message` | When the day's count is spent the refusal is 402 with its own "come back tomorrow" wording, and the model is not called. |
| `test_the_daily_ceiling_ignores_signed_in_visitors` | Signed-in traffic never touches the day's counter — the stub raises if it is called at all. |
| `test_a_dead_database_does_not_silence_mykola` | Fail open: an unreachable database must not stop everyone chatting, so the message is answered. |
| `test_the_refusal_is_logged` | The refusal writes a `LIMIT kind=session used=1 limit=1` line, so a limit that bites is visible afterwards. |

**The widget**

| Test | What it checks |
| --- | --- |
| `test_widget_offers_sign_in_when_the_allowance_runs_out` | The anonymous page carries the sign-in prompt element and the handler that shows it when the server answers `sign_in_required`. |
| `test_signed_in_widget_has_no_sign_in_offer` | A signed-in page does not carry it at all. |

## test_anonymous_writes.py — only an account may change the database (16 tests, 19 cases)

kuantorflow#125. A visitor with no users-row id cannot add a card by any route — the review popup, the automatic-add path, or Mykola saving one from chat. Reading stays open. The refusal is the **route's**, not the template's: nothing is hidden or disabled in the UI, so every post here is exactly what a visitor's browser sends, and a hand-made post gets the same answer.

**The review popup**

| Test | What it checks |
| --- | --- |
| `test_the_review_popup_is_refused` | `POST /cards/add` answers 403 with `sign_in_required` and the sign-in message, and nothing reaches the database. |
| `test_a_signed_in_user_is_unaffected` | The same post from a signed-in client saves, attributed to their id. |
| `test_a_sign_in_with_no_users_row_is_refused` | A session with `id: None` (#148) is refused — fail closed, since an unowned card could not later be deleted by its author. |
| `test_the_refusal_comes_before_the_duplicate_check` | A refused save is never reported as "already in the database" — the visitor would go looking for a card that was never written. |
| `test_a_missing_word_is_still_a_400` | The refusal does not swallow the older validation error. |

**The automatic-add path**

| Test | What it checks |
| --- | --- |
| `test_automatic_add_saves_nothing` | With cards-automatically on, an anonymous lookup still answers 200 but writes nothing. |
| `test_the_looked_up_cards_are_still_offered` | The lookup already happened, so its cards go to the review popup rather than being thrown away, and the sign-in prompt is raised on load — signing in from it leaves them there. |
| `test_automatic_add_still_works_when_signed_in` | The same path saves, attributed to the signed-in id. |

**Mykola saving a card from chat**

| Test | What it checks |
| --- | --- |
| `test_mykola_cannot_save_for_an_anonymous_visitor` | The saver raises `PermissionError` naming the sign-in, which the agent turns into an error it relays — so Mykola says why instead of claiming a saved card. |
| `test_mykola_still_saves_for_a_signed_in_user` | With an identity in the session the same call saves, attributed correctly. |

**The funnel itself**

| Test | What it checks |
| --- | --- |
| `test_the_save_funnel_refuses_even_without_a_route` | `_save_and_log()` enforces the rule itself, so a future save route that forgets to ask fails loudly instead of writing. |
| `test_the_refusal_is_logged` | One `ADD-DENIED` line with the word, `reason=anonymous` and the source. |

**Reading is untouched**

| Test | What it checks |
| --- | --- |
| `test_reading_pages_stay_open` | Four cases — home, a flashcards topic, the deck and the quiz all answer 200 for an anonymous visitor. |
| `test_looking_a_word_up_stays_open` | Lookup is a read path: it fetches and offers cards, it just cannot save them. Refusing it too would lock anonymous visitors out of the dictionary, which #125 does not ask for. |
| `test_the_prompt_offers_a_working_sign_in_link` | The prompt carries a real `/login/google` link — #125 asks for it to be functional, not decorative. |
| `test_settings_are_unaffected` | Anonymous settings were already frozen by #102 with their own message; #125 must not change that answer. |

## test_apply_schema.py — the deploy step that applies schema changes (17 cases)

kuantorflow#180. Fully offline against a fake database that remembers only which objects exist. The fake learns what a statement created **from the statement itself**, never from the step that ran it — so a migration whose SQL does not build the object its target names shows up as a step that keeps re-applying, which is exactly the failure the idempotency check exists to catch. The end-to-end run against a real MySQL is `test_apply_schema_db.py`.

**`schema.sql` is only ever `CREATE TABLE`**

| Test | What it checks |
| --- | --- |
| `test_a_commented_out_alter_is_not_a_statement` | The #180 bug itself: an `ALTER` inside a comment is parsed away, so nothing applies it — which is how production silently missed a column. |
| `test_parse_statements_splits_and_drops_trailing_noise` | Statements split on `;` with trailing comments and blank lines discarded. |
| `test_schema_sql_is_the_three_tables_in_file_order` | The file yields `anonymous_usage`, `users`, `flashcards` in that order — `users` before `flashcards` because the foreign key needs it to exist first. |
| `test_an_alter_left_in_schema_sql_is_rejected` | A bare `ALTER` in the file raises, and the error names `MIGRATIONS` — so the trap cannot come back quietly. |

**The migration list**

| Test | What it checks |
| --- | --- |
| `test_migrations_are_ordered_column_then_index_then_constraint` | The owner column comes before its index, which comes before the foreign key — each needs the previous one. |
| `test_every_migration_names_the_object_its_sql_creates` | Every step's declared target is actually built by its own statements; otherwise the step is never seen as done and re-runs on every deploy. |

**Running**

| Test | What it checks |
| --- | --- |
| `test_a_fresh_database_gets_its_tables_and_needs_no_migrations` | Three tables created, then every migration already satisfied by them — the two halves of the schema describe the same database. Counted from `MIGRATIONS`, so adding one does not fail this. |
| `test_a_pre_89_database_gets_the_column_index_and_key` | Against the pre-#89 shape the tables are left alone and every migration applies, leaving the owner column, its index and the foreign key in place. |
| `test_a_second_run_changes_nothing` | A re-run applies nothing, skips everything, and executes not a single further statement — existence *is* the idempotency check. |
| `test_a_half_applied_database_finishes_the_rest` | Production had some ALTERs run by hand; the run skips those and completes the remainder rather than choking. |
| `test_dry_run_reports_without_touching_anything` | `--dry-run` reports what would apply, executes nothing, commits nothing. |
| `test_a_failing_statement_names_the_step_that_failed` | A failure raises `StepFailed` carrying the step name and the offending SQL — a deploy log that just says "error" is not actionable. |
| `test_each_step_is_reported_either_way` | Applied and already-present steps print differently, so a deploy that changed nothing does not look like one that did. |

**The command line**

| Test | What it checks |
| --- | --- |
| `test_main_on_a_current_database_says_nothing_to_do` | Exit 0, "nothing to do", no statements — and the connection is closed even then. |
| `test_main_applies_then_becomes_a_no_op` | First run reports changes applied; the second reports nothing to do. |
| `test_main_exits_non_zero_when_a_migration_fails` | Exit 1 with the failing step named on stderr, and the connection still closed. |
| `test_main_dry_run_leaves_the_database_alone` | `--dry-run` from the command line reports pending work and executes nothing. |

## test_apply_schema_db.py — the deploy step against a real MySQL (5 cases, marker `db`)

kuantorflow#180. The offline tests prove the logic against a fake; this proves the thing the outage was actually about. It creates and drops its **own** scratch database (`kuantorflow_apply_schema_test`) and never touches the configured one, and still refuses to run unless `RUN_DB_ROUNDTRIP=1` and `DB_HOST` is localhost.

| Test | What it checks |
| --- | --- |
| `test_an_empty_database_gets_the_whole_schema` | An empty database ends up with all three tables and the owner column already present — the tables `schema.sql` creates need no migrations on top of them. |
| `test_a_pre_89_database_is_migrated_and_keeps_its_cards` | Against the real pre-#89 table: four changes applied, `pos` and `added_by_user_id` added **in the right column positions** so a migrated table matches a fresh one, the index and foreign key created, and the existing card still there untouched. |
| `test_a_second_run_is_a_no_op_and_says_so` | The second run prints "nothing to do" and never the word "applied". |
| `test_dry_run_reports_the_pending_work_without_doing_it` | `--dry-run` reports four pending changes and the column is still absent afterwards. |
| `test_a_broken_migration_exits_non_zero` | A column of the wrong type makes the foreign key impossible; the script exits 1 and names the failing step on stderr. |

## test_backup.py — backup retention logic (4 cases)

Offline checks of the backup helper — no database and no `mysqldump` needed.

| Test | What it checks |
| --- | --- |
| `test_backup_filename_is_timestamped_and_sortable` | The name embeds the timestamp, and lexicographic order equals chronological order — the property the retention logic relies on. |
| `test_select_old_backups_keeps_newest` | With `keep=2`, the two oldest of four are selected for deletion and the two newest survive. |
| `test_select_old_backups_ignores_unrelated_files` | `notes.txt` and `.gitkeep` are never deletion candidates, even at `keep=0`. |
| `test_select_old_backups_nothing_to_delete_when_under_limit` | Nothing is selected while the count is within the retention limit. |

## test_backup_roundtrip.py — restore round-trip (1 case, marker `db`)

Guards the exact bug where restore fed compressed bytes to `mysql` and silently did nothing. Restore **overwrites** the target database, so this is opt-in (`RUN_DB_ROUNDTRIP=1`) and refuses to run unless `DB_HOST` is localhost. It touches only a sentinel row and restores from a backup taken microseconds earlier.

| Test | What it checks |
| --- | --- |
| `test_deleted_card_reappears_after_restore` | Insert a sentinel card → back up → delete it → restore: the card is back. A restore that quietly does nothing fails here. |

## test_blocked_accounts.py — blocking an account (33 tests, 36 cases)

kuantorflow#126. A blocked user keeps reading — flashcards, the deck, the quiz, word lookups and their own settings — but cannot change the database or talk to Mykola, and is shown the admin's address so they can ask for access back. The block lives on the users row and is read live on each request rather than stamped into the session: a session cookie lasts 30 days, and a block has to take effect on the blocked person's next request, not their next sign-in.

**Writing is refused**

| Test | What it checks |
| --- | --- |
| `test_adding_a_card_is_refused` | `POST /cards/add` answers 403 and nothing is saved. |
| `test_the_refusal_says_it_is_a_block_not_a_sign_in` | The message says "blocked" and never "sign in" — a blocked user is signed in already, so that would send them round a loop that changes nothing. |
| `test_the_refusal_names_an_admin_to_write_to` | The configured admin address appears in the message, so there is somewhere to appeal. |
| `test_with_no_admin_configured_the_message_still_makes_sense` | `ADMIN_EMAILS` may be empty (#158) — then the sentence stops rather than trailing off into an empty address. |
| `test_the_automatic_add_path_is_refused` | Nothing is saved and the raised dialog carries the block wording rather than #125's sign-in prompt — matched on the literal-argument call, since the popup's own handler passes a variable and would match too. |
| `test_deleting_a_card_is_refused` | Their own card, which they could delete before the block (#162): the route never reaches the database and the page says why. |
| `test_the_delete_cross_is_greyed_with_the_reason` | Read off the cross itself, not the page — a blocked visitor's page also carries the Settings notice, so `"blocked" in body` would prove nothing. |
| `test_a_blocked_admin_cannot_delete_either` | Admin-ness is checked *after* the block, so an admin who blocked their own account is taken at their word. #165 stops them deleting that account, so it cannot become permanent. |

**Mykola is not available to them**

| Test | What it checks |
| --- | --- |
| `test_the_widget_is_not_rendered` | The chat panel is absent from a blocked visitor's page. |
| `test_the_widget_is_rendered_for_everyone_else` | The control case: an unblocked signed-in visitor still gets it. |
| `test_a_hand_made_chat_request_is_refused` | Hiding the widget is presentation; the route answers 403 and the model is not called. |
| `test_the_recap_endpoint_stays_quiet` | The recap endpoint answers `{"recap": null}` rather than reviewing their history. |
| `test_the_restart_check_answers_no` | The restart check answers `restart: false` with `reason: "blocked"`. |
| `test_mykola_cannot_save_a_card_for_them` | The chat card-saver raises with the block reason, so Mykola relays it rather than claiming a save. |

**Reading is untouched**

| Test | What it checks |
| --- | --- |
| `test_reading_pages_stay_open` | Four cases — home, flashcards, deck and quiz all answer 200 while blocked. |
| `test_looking_a_word_up_still_works` | The lookup returns its result and offers cards for review; it just saves nothing. |
| `test_their_own_settings_still_save` | The block is about shared things; a personal preference is not one. |
| `test_the_settings_popup_tells_them_how_to_ask` | The settings popup carries the block notice and the admin address. |

**Unblocking**

| Test | What it checks |
| --- | --- |
| `test_clearing_the_block_restores_writing` | The same post that was refused succeeds once the block is cleared, attributed to the right owner. |

**The block is read live, not from the session**

| Test | What it checks |
| --- | --- |
| `test_the_block_is_read_once_per_request` | Cached in `g`: the widget, the pages and the save routes all ask, and one page must not become one query per question. |
| `test_an_anonymous_visitor_is_never_looked_up` | No account to block means nothing to ask the database. |
| `test_a_dead_database_does_not_lock_the_site` | A failed lookup means no block is visible, rather than every signed-in visitor being treated as blocked. |

**The stored side — `utils.set_user_blocked`**

| Test | What it checks |
| --- | --- |
| `test_blocking_sets_the_timestamp_and_reason` | The update sets `blocked_at = NOW()` and stores the reason. |
| `test_unblocking_clears_the_reason_too` | Both columns go back to NULL — a note about a block that is over would read as a live one. |
| `test_an_unknown_email_changes_nothing` | A typo reports a miss and issues no `UPDATE`, rather than reporting success on no rows. |
| `test_the_email_is_matched_exactly` | `LOWER(email) = LOWER(%s)` and never a `LIKE`: one block must not catch a bystander. |
| `test_blocking_is_logged` | A `USER-BLOCK` line records the address and the reason. |
| `test_unblocking_is_logged` | Lifting a block writes `USER-UNBLOCK`. |
| `test_unblocking_an_unblocked_account_logs_nothing` | The log counts blocks that were lifted; a no-op is not one of them. |
| `test_reblocking_is_logged_because_the_reason_may_change` | Blocking an already-blocked account still logs, since the reason may be new. |
| `test_get_user_block_reads_none_for_an_unblocked_account` | No timestamp means no block. |
| `test_get_user_block_returns_when_and_why` | A blocked account reads back both the moment and the reason. |
| `test_get_user_block_never_asks_about_nobody` | Called with no user id it returns None without opening a connection at all — the stub raises if it tries. |

## test_card_deletion_rules.py — you may delete only your own cards (23 cases)

kuantorflow#162. Until this landed the delete route had **no identity check at all** — anyone past the keyword gate could delete any card, with the confirmation popup as the only guard. So these tests are as much about the hole as about the feature, and the important ones drive the *route*: greying the cross is presentation, and a hand-made POST goes straight past it.

**The conditional DELETE**

| Test | What it checks |
| --- | --- |
| `test_a_non_admin_delete_is_conditional_on_ownership` | One statement — `WHERE id = %s AND added_by_user_id = %s` — so nothing can change hands between the check and the delete. |
| `test_an_admin_delete_is_unconditional` | An admin's statement carries the id alone. |
| `test_zero_rows_affected_reads_as_denied` | The card exists but the conditional delete matched nothing: the outcome is "denied" and nothing is committed. |
| `test_a_missing_card_is_missing_not_denied` | A card that is not there reports "missing" and no `DELETE` is issued at all — the two outcomes are distinguishable. |
| `test_an_unowned_card_cannot_be_claimed_by_a_regular_user` | `= NULL` never matches, so pre-#89 cards are admin-only. The SQL has to carry the user's real id, not None, for that to hold. |

**The route enforces it**

| Test | What it checks |
| --- | --- |
| `test_a_signed_in_user_deletes_their_own_card` | The call carries their id, `admin=False`, and the page confirms the deletion. |
| `test_the_route_refuses_someone_elses_card` | A denied outcome produces the refusal message and never the success one — the route must not pretend the card was deleted. |
| `test_a_forged_post_for_another_users_card_is_refused` | The UI never offers this; it is a hand-made POST, exactly what template-side greying cannot stop. The user's own id goes into the SQL, so the card id being someone else's changes nothing. |
| `test_an_admin_deletes_any_card` | The call is made with `admin=True` and succeeds. |
| `test_an_anonymous_visitor_never_reaches_the_database` | No identity at all: #125's sign-in prompt rather than #162's message, and the delete is not even attempted. |
| `test_a_sign_in_without_a_users_row_is_treated_as_anonymous` | `id: None` (#148) means nothing can be theirs. |
| `test_a_missing_card_still_reads_as_missing` | "Card not found" survives the new rules. |

**Logging (#30)**

| Test | What it checks |
| --- | --- |
| `test_a_refusal_is_logged` | A `DELETE-DENIED` line with the card id, `reason='not owner'` and the user. |
| `test_an_anonymous_refusal_is_logged_with_its_own_reason` | The anonymous refusal is logged as `reason=anonymous`, distinguishable from the ownership one. |
| `test_a_successful_delete_logs_nothing_denied` | A successful delete writes no refusal line. |

**The cross in the UI**

| Test | What it checks |
| --- | --- |
| `test_your_own_card_keeps_a_live_cross` | No `aria-disabled` and no tooltip on a card you own. |
| `test_someone_elses_card_is_greyed_with_the_message` | Greyed, with the explanation naming admin or another user. |
| `test_an_unowned_card_is_greyed_for_a_regular_user` | A card with no owner is greyed too, matching what the SQL will actually do. |
| `test_the_admin_sees_a_live_cross_on_every_card` | All three ownership cases — unowned, someone else's, their own — stay live for an admin. |
| `test_anonymous_visitors_get_the_sign_in_wording` | Greyed with the sign-in wording, not the ownership wording. |
| `test_the_disabled_attribute_is_not_used` | `disabled` makes the button inert, and hover/tooltip behaviour on inert controls varies by browser; `aria-disabled` keeps it hoverable everywhere. |
| `test_a_greyed_cross_explains_itself_on_tap` | Touch devices have no hover, so the click handler branches on the greyed state and opens an explanatory modal. |
| `test_the_greyed_cross_never_shows_the_red_hover` | The stylesheet suppresses the red hover on a cross you cannot use. |

## test_card_editing.py — editing a saved card (34 cases)

kuantorflow#176, plus #186 on what a duplicate is called. Editing follows #162's rule exactly — the admin edits any card, a signed-in user only their own, nobody else at all — enforced in the route, since greying the pencil is presentation. The interesting part is the word: renaming into an existing word + part of speech would create the duplicate #101 exists to prevent, while the card being edited must not count as its own duplicate.

**The storage layer**

| Test | What it checks |
| --- | --- |
| `test_a_changed_field_is_written_and_named` | The changed field is written and reported back by name, so the caller can log what actually moved. |
| `test_only_the_changed_fields_are_written` | Submitting the whole card with one difference produces an `UPDATE` with exactly one assignment — the log's `changed` list has to be accurate, so the statement is too. |
| `test_submitting_nothing_new_is_not_an_edit` | An edit that changed nothing reports "unchanged" and issues no `UPDATE`: the log counts events, not attempts (the lesson from #126's unblock logging). |
| `test_a_field_that_was_not_submitted_is_left_alone` | The editor renders no field for a language the visitor has hidden (#46/#79/#111), so it must not be blanked — hiding has always been visual only, and an editor that emptied it would make it destructive. |
| `test_an_empty_value_still_clears_the_field` | The other half of that rule: a *missing* key means "leave it", a key holding None means "clear it". |
| `test_examples_are_stored_as_json` | Example lists are serialised as JSON, matching how they are read back. |

**The duplicate rule**

| Test | What it checks |
| --- | --- |
| `test_renaming_onto_an_existing_card_is_refused` | The outcome is "duplicate" carrying the other card's id and word, and no `UPDATE` runs. |
| `test_the_card_does_not_count_as_its_own_duplicate` | The check excludes the card's own id — without it every rename would collide with itself. |
| `test_changing_only_the_part_of_speech_is_checked_too` | word + pos is the key, so either half moving can create a duplicate. |
| `test_the_check_uses_the_values_the_card_will_end_up_with` | With only `pos` submitted the word comes from the stored row — checking a missing word against the database would find nothing. |
| `test_leaving_word_and_pos_alone_skips_the_check` | An edit that cannot create a duplicate does not pay for the query. |

**Ownership**

| Test | What it checks |
| --- | --- |
| `test_a_card_that_is_not_yours_affects_no_rows` | Zero rows affected is the refusal, and nothing is committed. |
| `test_the_owner_is_part_of_the_update_not_a_prior_check` | One conditional statement, as #162 does — no gap between deciding the card is yours and changing it. |
| `test_the_admin_updates_without_the_owner_clause` | An admin's `UPDATE` carries no owner condition. |
| `test_a_missing_card_is_reported` | A card that is not there reports "missing". |

**The route**

| Test | What it checks |
| --- | --- |
| `test_an_anonymous_visitor_is_refused` | 403 with the sign-in message, and the database is not touched. |
| `test_a_blocked_account_is_refused` | 403 with the block message (#126). |
| `test_a_signed_in_user_edits_with_their_own_id` | The call carries their id and `admin=False`. |
| `test_a_word_is_still_required` | A blank word is a 400 before anything is written. |
| `test_examples_are_read_one_per_line` | Examples typed one per line become a list, with blank lines dropped. |
| `test_examples_still_accept_the_review_popup_json` | The JSON form the review popup sends is still understood. |
| `test_a_field_absent_from_the_form_is_absent_from_the_entry` | The route passes on only submitted fields — this is what stops a hidden language being wiped by an edit. |
| `test_a_refused_rename_is_a_409_naming_the_other_card` | A duplicate answers 409 with the clashing word and part of speech in the message, so the user knows what they collided with. |
| `test_someone_elses_card_is_refused_by_the_route` | 403, with an `EDIT-DENIED` line carrying `reason='not owner'`. |
| `test_a_missing_card_is_a_404` | A missing card answers 404, distinct from the refusal. |
| `test_the_edit_is_logged_with_what_changed` | The `EDIT` line names the card and lists the changed fields. |
| `test_an_edit_that_changed_nothing_writes_no_log_line` | Answers 200 with an empty `changed` list and writes no `EDIT` line. |

**The pencil on the page**

| Test | What it checks |
| --- | --- |
| `test_the_pencil_is_rendered_for_your_own_card` | Present and live on a card you own. |
| `test_the_pencil_is_greyed_for_someone_elses_card` | Greyed with the reason on a card you do not. |
| `test_a_hidden_language_never_reaches_the_edit_markup` | With Russian hidden, neither its value nor its input appears — while the visible language still has its field. The whole reason the route reads only submitted fields. |

**#186 — what a duplicate is called**

| Test | What it checks |
| --- | --- |
| `test_no_extra_note_when_the_filter_is_off` | The plain "already in the database" wording is right when the card is visible, so no extra note is added. |
| `test_a_hidden_duplicate_is_explained` | With the individual-cards filter on and the clashing card belonging to someone else, the answer explains why it cannot be seen — otherwise the app appears to contradict itself. |
| `test_your_own_hidden_duplicate_needs_no_explanation` | It is your card and the filter shows it, so the plain message is true. |
| `test_a_dead_database_costs_the_note_not_the_answer` | If the ownership lookup fails, the duplicate answer still arrives — only the explanatory note is missing. |

## test_card_editing_db.py — editing against a real MySQL (4 cases, marker `db`)

kuantorflow#176. Two of the issue's acceptance criteria cannot be proved against a fake. Creates and drops its own scratch database; opt-in via `RUN_DB_ROUNDTRIP=1`.

| Test | What it checks |
| --- | --- |
| `test_an_edit_leaves_created_at_alone` | `created_at` is the card's age, not its last touch. MySQL will happily attach `ON UPDATE CURRENT_TIMESTAMP` to the first timestamp column of a loosely declared table, which would silently reset every card's age. |
| `test_examples_survive_the_round_trip_as_lists` | Stored as JSON and read back as a **list** — not as a string that merely looks like one, which a card page would then render character by character. |
| `test_a_rename_onto_an_existing_card_is_refused_for_real` | The duplicate rule against the real NULL-safe comparison, rather than a fake that always answers the same way. |
| `test_a_card_can_be_renamed_to_a_free_word` | The card must not count as its own duplicate — without the exclusion this is the case that fails. |

## test_card_move.py — moving a card to another topic (23 cases)

kuantorflow#177. Split from #176 because the rules differ: **no duplicate check applies**, since `save_flashcard()` deduplicates on word + part of speech globally, never per topic, so a move cannot create a duplicate where a rename can. Topics are not a table — `get_topics()` derives them with `GROUP BY` — so moving a card to an unknown topic creates it, and moving the last card out of a topic makes that topic cease to exist, which is why the route has to think about where the user lands.

**The storage layer**

| Test | What it checks |
| --- | --- |
| `test_the_card_is_moved_and_its_old_topic_reported` | The move commits and reports the word and the old topic — the caller needs the latter to know whether that topic still exists. |
| `test_only_the_topic_column_is_written` | The `UPDATE` assigns `topic` and nothing else. |
| `test_no_duplicate_check_is_made` | No word lookup is issued at all: the rule is global, so a move can never create a duplicate, and asking would be a query that can only ever answer "no". |
| `test_moving_a_card_to_where_it_already_is_changes_nothing` | Reports "unchanged", issues no `UPDATE` and commits nothing. |
| `test_the_owner_is_part_of_the_update` | The owner condition is in the same statement as the change, bound to the user's real id. |
| `test_the_admin_moves_without_the_owner_clause` | An admin's statement carries no owner condition. |
| `test_someone_elses_card_affects_no_rows` | Zero rows affected reads as "denied" with nothing committed. |
| `test_a_missing_card_is_reported` | A card that is not there reports "missing". |

**The route**

| Test | What it checks |
| --- | --- |
| `test_an_anonymous_visitor_is_refused` | Redirected, and the database is never reached. |
| `test_a_blocked_account_is_refused` | Refused with an `EDIT-DENIED` line in the log (#126). |
| `test_a_signed_in_user_moves_with_their_own_id` | The call carries their id, `admin=False`, and the destination. |
| `test_the_destination_is_trimmed` | Surrounding whitespace is stripped, so `"  character  "` does not become a second topic. |
| `test_an_empty_destination_is_rejected_before_the_database` | A blank destination never reaches the storage layer. |
| `test_a_brand_new_topic_is_accepted` | Topics are derived from the cards, so there is nothing to create — an unknown destination is valid. |
| `test_the_confirmation_names_the_destination` | The flash message names the word and where it went. |
| `test_the_move_is_logged_as_an_edit_of_the_topic` | Logged as an `EDIT` with `changed=topic` and its own source, so a move is distinguishable from a field edit. |
| `test_a_forged_move_of_someone_elses_card_is_refused` | The greyed control is presentation; the route refuses and logs `EDIT-DENIED`. |

**Where the user lands**

| Test | What it checks |
| --- | --- |
| `test_the_user_stays_on_a_topic_that_still_has_cards` | They are returned to the page they were on. |
| `test_emptying_a_topic_sends_the_user_to_the_topic_list` | The topic has just ceased to exist — there is no topics table — so the page they came from would be empty and its chip gone. |
| `test_a_dead_database_leaves_them_where_they_were` | If the topic list cannot be read, the move still succeeded and they land where they were, rather than on an error. |

**The control on the page**

| Test | What it checks |
| --- | --- |
| `test_the_move_control_is_rendered_for_your_own_card` | Live on a card you own. |
| `test_the_move_control_is_greyed_for_someone_elses_card` | Greyed with the reason on a card you do not. |
| `test_the_topic_page_does_not_query_the_topic_list` | Suggestions are fetched from `/topics.json` only when the dialog opens, so a page everyone loads does not pay for a feature few use. |

## test_card_ownership.py — who added a card (20 tests, 21 cases)

kuantorflow#89. Every card the app writes records the id of the signed-in user who saved it. The id comes from the **server-side session only** — the review popup posts hidden fields, so anything the browser says about ownership is ignored. The field is stored, never displayed. Since #125 a visitor with no account cannot write at all, so NULL now means "saved before #89".

**The column reaches the database**

| Test | What it checks |
| --- | --- |
| `test_the_id_is_inserted_with_the_card` | The column is in the `INSERT` and the id is the last bound value. |
| `test_no_id_is_stored_as_null` | A save with no id stores NULL, not a sentinel value. |
| `test_the_id_is_never_read_out_of_the_entry` | The entry dict is built from form data, so a key of that name inside it is ignored rather than trusted. |

**Every save path records the owner**

| Test | What it checks |
| --- | --- |
| `test_review_popup_records_the_signed_in_user` | The popup save is attributed to the session's id. |
| `test_the_review_popup_writes_nothing_for_anonymous` | Before #125 this saved a card with no owner; now it saves nothing. |
| `test_automatic_add_records_the_signed_in_user` | The automatic-add path attributes the same way. |
| `test_automatic_add_writes_nothing_for_anonymous` | And writes nothing without an account. |
| `test_mykola_chat_saver_records_the_owner` | Mykola's saver runs inside the chat request, so it sees the same session as every other save path (ai_agent#20). |

**Sessions from before the users table**

| Test | What it checks |
| --- | --- |
| `test_a_session_without_an_id_key_is_signed_out` | A pre-#148 session has no `id` and no users row behind it, so it would attribute every card to nobody while still looking signed in. It is dropped once; the next sign-in repairs it. |
| `test_dropping_the_identity_keeps_the_gate_pass` | Only the identity goes — being sent back to the keyword gate as well would make an invisible repair very visible. |
| `test_a_gated_request_is_repaired_too` | The check runs before the gate, which would otherwise short-circuit the chain. |
| `test_an_id_of_none_is_left_alone` | A sign-in whose users row could not be written stores `id=None` (#148); that is tolerated by design, since signing in again would fail the same way. |
| `test_a_current_session_is_untouched` | A normal session keeps its id. |
| `test_the_dropped_session_cannot_save_a_card` | The symptom this repairs: the card used to be saved unattributed while the visitor looked signed in. Now the save is refused outright — the louder and more honest failure. |
| `test_a_sign_in_without_a_row_cannot_save` | `id: None` is refused rather than saved unowned — the fail-closed direction, because an unowned card cannot be deleted by the person who added it (#162). |

**Ownership cannot be forged from the browser**

| Test | What it checks |
| --- | --- |
| `test_a_forged_id_from_an_anonymous_visitor_buys_nothing` | Posting an id does not make the visitor signed in: the save is refused and the id never reaches the database either way. |
| `test_a_signed_in_user_cannot_attribute_a_card_to_someone_else` | A posted id of 99 is ignored; the card is attributed to the session. |
| `test_the_posted_field_does_not_reach_the_card_either` | The field is not even carried into the saved entry. |

**Invisible to the user**

| Test | What it checks |
| --- | --- |
| `test_the_owner_is_not_rendered` | Two cases — the flashcards page and the deck. `SELECT *` now returns the column, so the pages must not leak it. |
| `test_the_review_popup_posts_no_owner_field` | The popup markup carries no owner field at all. |

## test_chat_restart.py — automatic chat restart after a break (19 tests, 30 cases)

ai_agent#54. A conversation left untouched for longer than `restart_chat_interval` hours is restarted when the learner comes back: Mykola reviews their last three exchanges, a new chat-log file is opened, and the widget is handed its id and his recap. 0 hours means "never restart".

**The setting**

| Test | What it checks |
| --- | --- |
| `test_default_interval_is_two_hours` | The shipped default is 2. |
| `test_interval_is_validated` | Thirteen cases: the slider's range and "never" pass through; JSON round-trips like `"7"` and `6.0` are coerced; out-of-range, fractional, boolean and nonsense values all fall back to the default. |
| `test_never_restart_is_saved_as_zero` | Posting 0 stores 0 rather than being read as "unset" and defaulted away. |

**The endpoint**

| Test | What it checks |
| --- | --- |
| `test_no_restart_within_the_interval` | Half an hour away is no restart, and the elapsed time is reported back. |
| `test_restart_after_the_interval` | Five hours away restarts, with a fresh chat id for the widget to adopt. |
| `test_zero_interval_never_restarts` | 100 hours away and the answer is still no, with `reason: "disabled"`. |
| `test_without_any_history_there_is_nothing_to_restart` | No logs and no client timestamp means `reason: "no history"`. |
| `test_no_restart_when_mykola_is_unavailable` | With the agent absent the answer is no, whatever the gap. |
| `test_a_future_client_stamp_is_ignored` | A clock-skewed browser must not be able to fake either "no break" or a huge one. |

**What the restart reviews and writes**

| Test | What it checks |
| --- | --- |
| `test_only_the_last_three_exchanges_are_reviewed` | Questions 3–5 reach the recap and question 2 does not, and the away time is passed along. |
| `test_the_restart_opens_a_new_log_file` | A new file named for the chat id, carrying the restart note and the recap, and the recap is returned to the widget. |
| `test_the_break_is_measured_from_the_newest_log` | A signed-in learner who wrote from another device an hour ago is not restarted, whatever this browser's stale stamp says. |
| `test_a_failing_recap_still_restarts` | When the recap raises, the restart happens with `recap: null` — it is a nicety, not a precondition. |
| `test_anonymous_visitors_restart_without_a_recap` | They have no per-user logs, so there is nothing to review; the conversation still starts fresh. |
| `test_away_hours_is_only_sent_to_agents_that_accept_it` | Feature detection, because the two repos deploy in any order: an older `recap()` without the parameter must still be callable. |

**The Settings control**

| Test | What it checks |
| --- | --- |
| `test_settings_popup_has_the_slider_and_never_checkbox` | The 1–24 hour slider, the "never" checkbox, and the handler that disables one when the other is ticked. |
| `test_never_checkbox_is_checked_and_slider_disabled_at_zero` | Stored 0 renders as ticked-and-disabled rather than as a slider sitting at zero. |
| `test_slider_shows_the_stored_hours` | A stored 9 renders as the slider's value and its readout. |
| `test_widget_asks_the_server_on_load` | The widget calls the restart check on load, only when a conversation exists, sending its own last-message timestamp. |

## test_duplicates.py — duplicate prevention (10 cases)

kuantorflow#101. `save_flashcard()` must skip a card whose word + part of speech already exists, and every save path must say so.

**`save_flashcard` against a fake connection**

| Test | What it checks |
| --- | --- |
| `test_duplicate_word_pos_is_skipped` | An existing word + pos means no `INSERT` and no commit. |
| `test_new_card_is_inserted` | A new one is inserted and its row id returned. |
| `test_duplicate_check_is_null_safe_on_pos` | Pos-less cards (from `.mht` imports) deduplicate too, via the NULL-safe `<=>` comparison — `= NULL` would never match. |

**`flashcard_word_exists` — the early-warning check (#145)**

| Test | What it checks |
| --- | --- |
| `test_flashcard_word_exists_true` | Asks for the word alone (no part of speech) and reports True. |
| `test_flashcard_word_exists_false` | Reports False when nothing matches. |

**The save routes report duplicates**

| Test | What it checks |
| --- | --- |
| `test_add_card_reports_duplicate` | `/cards/add` answers `{ok: true, saved: false, duplicate: true}` rather than a plain success. |
| `test_review_popup_knows_the_duplicate_state` | The popup carries the "Already in DB" state its JS shows on a duplicate card's button. |
| `test_auto_add_banner_counts_skipped_duplicates` | With one new card and one duplicate, the banner says exactly that: one added, one skipped. |
| `test_auto_add_banner_when_everything_is_a_duplicate` | All duplicates gets its own wording — "nothing added" — rather than a count of zero. |

**The dedup maintenance script**

| Test | What it checks |
| --- | --- |
| `test_find_duplicates_groups_and_keeps_oldest` | Groups case-insensitively, keeps the oldest of each group, treats a different part of speech as a different card, and groups NULL-pos rows together too. |

## test_id_keyed_stores.py — settings and chat logs keyed on the user id (21 tests, 26 cases)

kuantorflow#174. Both stores used to be named after the email prefix — everything before the `@`. That key was neither stable nor unique: changing your address orphaned your settings and your whole chat history, and `anton@gmail.com` and `anton@outlook.com` collapsed to one `anton`, silently sharing both. They are keyed on the users-table id now, with the address recorded *inside* the file so a directory listing is still readable.

**The settings key**

| Test | What it checks |
| --- | --- |
| `test_the_file_is_named_after_the_id` | `config-7.json` is written and the prefix-named file is not. |
| `test_anonymous_visitors_still_share_the_default` | No id still lands on the shared default file. |
| `test_colliding_email_prefixes_get_separate_files` | The bug the id fixes: two addresses with the same local part keep separate settings. |
| `test_an_email_change_keeps_the_settings` | The other bug: a rename no longer orphans the file. |
| `test_a_junk_id_falls_back_to_the_default` | Six cases — path traversal, an injection attempt, empty, None, a non-numeric string and a float all resolve to the default name, so the file can never escape the settings directory. |

**The email is metadata, not a setting**

| Test | What it checks |
| --- | --- |
| `test_the_file_records_the_owner` | The address is stored inside the file, which is what keeps a directory listing readable. |
| `test_the_email_refreshes_itself_on_save` | A later save rewrites it, so no rename step is ever needed. |
| `test_the_email_is_not_a_setting` | It never appears in what `save()`/`load()` hand back. |
| `test_the_settings_response_carries_no_email` | Nor in the `/settings` JSON response. |

**Migrating pre-#174 files**

| Test | What it checks |
| --- | --- |
| `test_a_legacy_file_is_migrated_on_read` | The prefix-named file is **moved** onto the id-keyed name, not copied. |
| `test_migration_happens_once` | A stale legacy file reappearing later must not clobber the migrated settings. |
| `test_a_user_with_no_legacy_file_just_gets_defaults` | Nothing to migrate is not an error. |
| `test_the_shared_default_is_never_migrated` | An address with no usable prefix was on the shared default, which is everybody's — it must not be adopted as one user's settings. |
| `test_a_numeric_prefix_does_not_hand_over_someone_elses_settings` | The pathological collision: `7@example.com` already owned `config-7.json`, the name user id 7 now wants. The stranger's file is recognised as pre-#174 (no `_email`) and set aside as `.orphaned` rather than deleted or inherited. |
| `test_an_already_migrated_file_is_left_alone` | Once a file carries `_email` it is this user's own, and a legacy leftover must not overwrite it. |
| `test_a_migrated_file_is_stamped_immediately` | The address is written at migration time, not on the user's next save — otherwise a just-migrated file is unreadable in a directory listing, which is most of the point. The settings survive the stamping. |

**The chat log folder**

| Test | What it checks |
| --- | --- |
| `test_the_log_folder_is_named_after_the_id` | A signed-in visitor's directory is the id, not the prefix. |
| `test_anonymous_chats_stay_at_the_top_level` | Anonymous resolves to the shared root — the condition #163 later keyed its refusal on. |
| `test_a_legacy_log_folder_is_migrated` | An old prefix-named folder is moved onto the id, conversation intact. |
| `test_the_folder_records_who_it_belongs_to` | The marker file carries the id, the **full** address (prefixes are exactly what collide) and the name. |
| `test_the_marker_is_never_read_as_a_conversation` | The log reader globs `chat_*.txt`, so `user.txt` can never reach Mykola's recap. |

## test_individual_cards.py — "Use only individual cards" (21 tests, 25 cases)

kuantorflow#127. A per-user view filter: with it on, the topic list, the topic page, the deck, the quiz and the widget's chip refresh show only the cards this user added. Nothing is deleted, nothing changes about who may write, and everyone else still sees the filtered-out cards.

The trap it is built around is **NULL**. `added_by_user_id = 5` is never true for an unowned card, which is what correctly hides pre-#89 rows from an individual view — and is also why "no filter" has to be a *missing clause* rather than an owner of None, which would hide every card instead of none.

**The setting**

| Test | What it checks |
| --- | --- |
| `test_the_setting_exists_and_is_off_by_default` | Off by design: the deck is shared, and a learner who has added nothing would otherwise open an empty site. |
| `test_it_is_a_boolean_setting` | Declared as a boolean, so it goes through the same coercion as the rest. |
| `test_a_junk_value_falls_back_to_the_default` | `"yes please"` stores as False rather than as a truthy string. |
| `test_it_round_trips_through_the_settings_route` | Posting it returns it, so the popup reflects what was saved. |

**Which owner the reads are asked for**

| Test | What it checks |
| --- | --- |
| `test_off_by_default_every_read_is_unfiltered` | Both the home page and a topic page ask for owner None — meaning the shared deck, not "owned by nobody". |
| `test_every_read_path_is_filtered_when_on` | Five cases — home, the topic page, the deck, the quiz and `/topics.json` all pass the user's id. A path that forgot would silently show everyone's cards. |
| `test_an_anonymous_visitor_is_never_filtered` | They share the default config, which #102 makes read-only for them, so a filter left on there would hide the site with no way to turn it back off. |
| `test_the_filter_does_not_change_who_may_write` | It is a view filter; #125's rule about writing is untouched. |

**What the SQL actually asks for**

| Test | What it checks |
| --- | --- |
| `test_no_owner_means_no_clause_at_all` | The whole deck — not "cards owned by NULL", which matches nothing. |
| `test_an_owner_adds_an_equality_clause` | Equality, never inequality: `!= other` would silently drop unowned rows, the NULL trap this setting lives closest to. |
| `test_topics_are_counted_per_owner` | The topic counts are grouped with the owner condition applied. |
| `test_topics_unfiltered_by_default` | And carry no condition at all when off. |
| `test_the_owner_clause_is_bound_never_interpolated` | The id comes from the session, but it still travels as a bound parameter rather than being formatted into the SQL. |

**What the user sees**

| Test | What it checks |
| --- | --- |
| `test_someone_elses_card_disappears` | The filter is applied in SQL, so the page has nothing to show — this checks it copes rather than rendering a stray card. |
| `test_an_empty_topic_page_says_why` | "No flashcards saved under this topic yet" would send the user looking for a bug — the cards are there, they are just not theirs. |
| `test_an_empty_topic_list_says_why` | The topic list explains the filter too. |
| `test_an_empty_deck_says_why` | So does the deck. |
| `test_an_empty_quiz_names_the_filter_as_well` | The quiz has two reasons to be empty — no translations, or the filter — so naming only the first would mislead. |
| `test_the_ordinary_empty_message_is_unchanged_when_off` | With the filter off, the original wording is untouched. |
| `test_the_checkbox_is_in_the_settings_popup` | The control and its label are present. |
| `test_the_checkbox_is_disabled_for_an_anonymous_visitor` | There is no account to filter by, and the default config is shared. |

## test_language_visibility.py — hiding a translation language (10 cases)

kuantorflow#46/#79/#111. The Settings checkboxes hide a language everywhere — flashcards, the lookup review popup, the quiz and Mykola's answers — while the underlying data stays stored.

**The Settings popup (#111)**

| Test | What it checks |
| --- | --- |
| `test_popup_has_visibility_checkboxes_checked_by_default` | Both languages start visible. |
| `test_visibility_round_trip_through_settings_endpoint` | Turning one off is stored, returned, and reflected in the re-rendered checkboxes without disturbing the other. |

**The flashcards page (#46/#79)**

| Test | What it checks |
| --- | --- |
| `test_flashcards_show_both_languages_by_default` | Both translations and their headings render. |
| `test_flashcards_hide_disabled_language` | The hidden language's translation, its examples and its heading are all gone, the visible one stays, and the quiz link survives because one language remains. |
| `test_flashcards_hide_quiz_link_when_no_language_visible` | With both hidden there is nothing to be quizzed on, so the link goes too. |

**The lookup review popup (#46/#79)**

| Test | What it checks |
| --- | --- |
| `test_review_popup_carries_hidden_language_as_hidden_input` | No editable field for the hidden language, but its value still travels as a hidden input — so the saved card stays complete. Hiding is visual, not destructive. |

**The quiz (#46/#79)**

| Test | What it checks |
| --- | --- |
| `test_quiz_falls_back_to_visible_language` | With the quiz language hidden it falls back to the visible one, and the switch no longer offers the hidden one. |
| `test_quiz_explains_itself_when_all_languages_hidden` | It says the languages are hidden in Settings rather than rendering an unanswerable quiz. |

**Mykola (#46/#79)**

| Test | What it checks |
| --- | --- |
| `test_agent_receives_hidden_languages` | The chat call carries `["Russian"]`, so Mykola stops writing those translations. |
| `test_agent_gets_no_hidden_languages_by_default` | Nothing hidden means nothing passed. |

## test_live_site.py — deployed-site smoke tests (6 cases, marker `live`)

Read-only checks against `SITE_URL`. Skipped entirely when it is not set. They never write to the database.

| Test | What it checks |
| --- | --- |
| `test_site_is_up_and_gated` | The deployed site answers 200 and an unauthenticated visit lands on the gate with its prompt. |
| `test_https_is_forced` | An `http://` request ends up on `https://` (skipped when `SITE_URL` is not https). |
| `test_wrong_keyword_rejected` | The gate helper raises when given a wrong keyword — the gate really is closed. |
| `test_correct_keyword_opens_site` | The real keyword opens the site, through `enter_gate()` — the shared helper every scripted session should use. |
| `test_static_assets_served` | The stylesheet, icon, preview and background images all answer 200. |
| `test_link_preview_tags_on_gate` | The gate page carries the Open Graph image and title tags, so a shared link previews correctly. |

## test_lookup_and_cards.py — lookup, the review popup, upload and deletion (16 cases)

The core word-lookup flow: look a word up, review the proposed cards, add the ones you want, and delete cards from a topic page.

**Early duplicate-word warning (#145)**

| Test | What it checks |
| --- | --- |
| `test_existing_word_warns_before_lookup` | A word that already has cards raises a warning modal, does **not** open the review popup, and does not run the slow lookup at all — it waits for the user to confirm. |
| `test_look_up_anyway_bypasses_the_warning` | Confirming goes straight to the review popup with no warning. |
| `test_new_word_skips_the_warning` | A word with no existing cards is never interrupted. |
| `test_warning_check_degrades_on_db_error` | If the check itself fails, "unknown" means proceed — a broken lookup must not block the feature. |

**The review popup**

| Test | What it checks |
| --- | --- |
| `test_lookup_shows_review_popup_without_saving` | The popup renders both proposed cards with their editable values and the topic, and nothing is saved by rendering it. |
| `test_review_popup_has_one_close_cross_for_the_whole_popup` | #146: exactly one popup-level cross alongside the two per-card crosses, and closing is client-side only. |
| `test_add_card_saves_edited_values` | What the user edited is what is saved, and an emptied field becomes NULL rather than an empty string. |
| `test_add_card_preserves_examples_json` | Examples from the Reverso parser (#134) ride along as hidden JSON and survive into the saved card; a field that was never sent stays NULL. |
| `test_add_card_ignores_malformed_examples` | Bad JSON becomes NULL instead of crashing the save. |
| `test_add_card_requires_word` | A blank word is a 400 and saves nothing. |
| `test_empty_word_shows_error_and_no_popup` | An empty lookup shows the error and opens no popup. |

**Upload**

| Test | What it checks |
| --- | --- |
| `test_mht_upload_shows_review_before_saving` | MHT upload no longer auto-saves: the parsed cards go through the same review popup, shown beside the file's content, with an "Add All" button — and nothing is written until the user asks. |

**Deletion**

| Test | What it checks |
| --- | --- |
| `test_flashcards_page_has_delete_cross_and_modal` | The cross carries the card's word and its delete URL, and the confirmation modal is on the page. |
| `test_delete_card_flow` | The delete reaches the database and the page confirms it by name. |
| `test_delete_missing_card_is_friendly` | A card that is not there says "Card not found" rather than failing. |
| `test_delete_rejects_get` | `GET` on the delete URL answers 405 — deletion is not reachable by following a link. |

## test_main_page_layout.py — the main page reordered (21 cases)

kuantorflow#184. Three changes with one thread between them: the page should lead with what a returning learner came for. Browsing sat below two forms they only need when adding something new; the topics were pills, which have nowhere to put the picture #185 will give them; and a whole section was spent on a diagnostic.

**The order of the page**

| Test | What it checks |
| --- | --- |
| `test_browsing_comes_before_looking_up` | The three sections render as Browse flashcards, Look up a word, Upload notes — in that order. |
| `test_browsing_comes_straight_after_the_welcome_caption` | Nothing is inserted between the title and the deck. |
| `test_the_database_section_is_gone` | No Database heading, and the old `test_db` form does not linger behind it. |

**The tiles**

| Test | What it checks |
| --- | --- |
| `test_each_topic_is_a_tile_linking_to_it` | One tile per topic inside the grid, each linking to its page. |
| `test_a_tile_carries_the_name_and_the_count` | The name and the card count are both on the tile. |
| `test_one_card_is_not_one_cards` | The count is read on the tile, so it has to be grammatical in the singular. |
| `test_the_pill_markup_is_gone` | No leftover `chip` class — a cached stylesheet would still render one as a pill, and it would not be square. |
| `test_the_empty_states_are_unchanged` | The tiles replaced the chips; they did not replace the explanations for having none (#127). |
| `test_the_widget_rebuilds_tiles_not_chips` | Mykola refreshes this section in place after saving a card from chat (ai_agent#53), building the markup in JavaScript — so it has to change alongside the template, or a chat save quietly restores the old pills. |

**The database check, now in Settings**

| Test | What it checks |
| --- | --- |
| `test_the_button_is_in_the_settings_popup` | The button and its label are inside the settings modal. |
| `test_the_button_never_submits_the_settings_form` | It sits inside `#settings-form`, so a default-type button would save the settings as a side effect of asking about the database. |
| `test_the_button_works_for_anonymous_visitors` | Read-only settings (#102) freeze the *settings*; this changes nothing, so it stays usable — the same reasoning as Reset Auth. |
| `test_the_button_is_on_every_page_not_just_the_index` | It is in the popup, and the popup is in the base template. |
| `test_a_reachable_database_answers_ok` | `POST /db/test` answers `{"ok": true}`. |
| `test_an_unreachable_database_answers_why` | A failure is an answer to the question that was asked, not a server error — still 200, with the reason, so the popup can show it. |
| `test_the_check_never_redirects` | The whole reason it is JSON: the popup opens on every page, and a redirect would drop the visitor onto the index from wherever they were. |
| `test_the_check_rejects_get` | `GET /db/test` answers 405. |

**The page steps aside for the widget**

| Test | What it checks |
| --- | --- |
| `test_the_page_moves_only_while_the_panel_is_open` | The shift is tied to the open state, so a closed widget leaves no empty strip where the panel is not — and it moves the content, never the header, which a bottom-anchored panel does not cover. |
| `test_the_shift_is_off_where_there_is_no_room` | 860px of page plus a 340px panel do not fit under about 1240px, so below that the page stays put; the clamp keeps it on screen at the narrow end of the range. |
| `test_every_place_that_opens_or_closes_the_panel_syncs_the_space` | Three call sites set `panel.hidden` — open, close, and restoring a stored thread on load. A missed one leaves the page shifted with nothing beside it, or the panel back on top of the content. |
| `test_the_class_lands_on_the_body` | The rule is `body.mykola-open .page`, so the toggle has to be on the body — on the panel it would style nothing. |

## test_mykola_widget.py — the New Chat button (3 cases)

ai_agent#55. The widget only renders when Mykola is available, so these force it. The reset itself is client-side JS the test client does not run; what is pinned here is that the button and its wiring are present.

| Test | What it checks |
| --- | --- |
| `test_new_chat_button_and_confirm_dialog` | The pencil button, its labels, the confirmation dialog and both of its buttons are rendered, and the pencil opens the dialog rather than resetting immediately. |
| `test_new_chat_reruns_recap_for_signed_in` | A signed-in visitor's `newChat()` calls the welcome-back recap. |
| `test_new_chat_no_recap_for_anonymous` | An anonymous visitor's does not — they have no recap to run. |

## test_notes_formats.py — notes uploads in .txt and .docx (15 tests, 16 cases)

kuantorflow#137, extending the `.mht` path. The glued-translation split calls Claude, so it is stubbed to keep these offline.

**Plain text**

| Test | What it checks |
| --- | --- |
| `test_txt_reverso_copy_paste` | A pasted Reverso entry becomes one card: both senses aggregated with the "N." markers stripped, both examples kept, the terms already one per line so they arrive separated, and the source text preserved for display beside the cards. |
| `test_txt_simple_lines_keep_cyrillic_as_translation` | A Cyrillic right-hand side is a translation, not a definition — no explanation is invented. |
| `test_txt_english_right_hand_side_is_still_an_explanation` | An English right-hand side is an explanation, with no translation field. |
| `test_txt_decoding_falls_back_to_cp1251` | A file that is not UTF-8 still decodes, rather than producing mojibake or raising. |
| `test_txt_without_entries_yields_nothing` | Prose with no separator yields no cards rather than junk ones. |

**.docx**

| Test | What it checks |
| --- | --- |
| `test_docx_reverso_and_plain_lines_in_one_file` | Both entry styles in one document, in document order, with the part of speech mapped from the Russian label and the source shown verbatim. |
| `test_docx_single_sense_without_a_marker` | Reverso omits "1." when a word has only one sense, so the parser must not require it — and the Ukrainian translation is detected from its letters. |
| `test_docx_without_entries_yields_nothing` | A document of plain prose yields nothing. |

**Dispatch**

| Test | What it checks |
| --- | --- |
| `test_parse_notes_preview_dispatches_on_the_extension` | Two cases: the extension decides the parser, case-insensitively. |
| `test_parse_notes_preview_rejects_other_formats` | An unsupported extension raises rather than guessing. |

**The upload route**

| Test | What it checks |
| --- | --- |
| `test_txt_upload_shows_the_review_popup` | A `.txt` upload reaches the review popup with its card, and saves nothing first. |
| `test_docx_upload_shows_the_review_popup` | A `.docx` upload reaches it with both cards. |
| `test_unsupported_upload_is_reported` | A `.pdf` is reported as unsupported and opens no popup. |
| `test_empty_upload_reports_no_entries` | A parseable-looking file with no entries says so plainly. |
| `test_upload_panel_lists_the_three_formats` | The panel advertises all three formats and its file input accepts them. |

## test_parsers.py — MHT extraction and list round-tripping (3 cases)

| Test | What it checks |
| --- | --- |
| `test_mht_extraction` | A saved `.mht` yields the expected words in order, with the explanation parsed and the topic applied to every entry. |
| `test_entry_from_line_rejects_plain_text` | An empty line and a line with no separator both yield nothing, rather than a junk card. |
| `test_to_list_round_trip` | The DB text↔list helper handles None, a JSON array (including Cyrillic), newline-separated text, a bare string, and malformed JSON — which is kept whole rather than raising. |

## test_preferred_name.py — Mykola remembers what to call you (15 cases)

ai_agent#62, the KuantorFlow half. The tool itself lives in `ai_agent`; what is tested here is the saver KuantorFlow injects into it — who may store a name, where it goes, and that the change is visible to the very next message rather than only after signing in again. The agent-side half is `ai_agent/test_preferred_name.py`.

**Who may store a name**

| Test | What it checks |
| --- | --- |
| `test_an_anonymous_learner_is_refused` | Raised, not returned: the agent turns the exception into an error status Mykola relays, so he says he cannot remember it instead of pretending. |
| `test_a_signed_in_learner_is_stored` | The name is written against their id and echoed back. |
| `test_clearing_stores_none` | "Use my real name again" clears the column rather than writing the literal first name — otherwise a later Google name change would be shadowed for ever. |
| `test_a_missing_account_is_reported_not_swallowed` | A write that matched no row raises, so the failure reaches the learner. |

**The change is visible immediately**

| Test | What it checks |
| --- | --- |
| `test_the_new_name_is_used_from_the_next_message` | The name resolver reads the session, so the saver updates it — otherwise the new name would only take effect after signing in again. |
| `test_clearing_falls_back_to_the_account_name` | Clearing restores the Google given name in the same request. |
| `test_the_rest_of_the_session_survives` | The saver rewrites the session's user entry and must not drop the email, the verified claim or the id. |
| `test_the_change_is_logged` | A `PREFERRED-NAME` line records the chosen name. |
| `test_clearing_is_logged_as_cleared` | Clearing is logged as `(cleared)`, distinguishable from setting a name. |

**Injection into the agent**

| Test | What it checks |
| --- | --- |
| `test_the_saver_is_injected_when_the_agent_accepts_it` | Both savers are passed to an agent whose constructor accepts them. |
| `test_an_older_agent_without_the_argument_still_works` | The two repos deploy in either order, so KuantorFlow must not pass an argument an installed `ai_agent` has never heard of. |

**The stored side**

| Test | What it checks |
| --- | --- |
| `test_the_update_writes_the_column` | One `UPDATE users SET preferred_name = %s WHERE id = %s`, bound. |
| `test_clearing_binds_null` | Clearing binds NULL rather than an empty string. |
| `test_no_rows_updated_is_reported` | An id that matches nothing reports False. |
| `test_no_account_never_reaches_the_database` | No id means no connection is opened at all — the stub raises if it is. |

## test_providers.py — translation and dictionary providers (13 cases)

kuantorflow#20/#21. Network access is stubbed throughout: the dispatch tests replace the backend functions, the fetcher tests replace `requests.get`/`post` (or the Bing API seam) with responses captured from the real services.

**`lookup_word` dispatch (#20)**

| Test | What it checks |
| --- | --- |
| `test_default_lookup_uses_google` | The default translator is Google, and Bing is not called at all. |
| `test_bing_translator_is_used_when_selected` | Choosing Bing calls Bing and not Google. |
| `test_failing_bing_falls_back_to_google` | A connection error on the chosen provider falls back rather than failing the lookup. |
| `test_empty_bing_falls_back_to_google` | So does an empty result — a provider that answers with nothing is as useless as one that errors. |
| `test_selected_dictionary_provides_definitions` | The chosen dictionary supplies the explanation, and no fallback is attempted when it delivered. |
| `test_empty_dictionary_falls_back_to_reverso` | An empty dictionary falls back to Reverso, and the first choice is tried exactly once. |
| `test_definition_failures_never_break_the_lookup` | With every dictionary down the translation still comes back, simply without an explanation. |

**The Bing fetcher (#21)**

| Test | What it checks |
| --- | --- |
| `test_bing_dictionary_groups_by_pos` | Translations are grouped by part of speech, duplicates dropped, and an unknown tag filed under "other". |
| `test_bing_dictionary_plain_translation_fallback` | A phrase with no dictionary entry falls back to plain translation rather than returning nothing. |

**The scraping fetchers (#21)**

| Test | What it checks |
| --- | --- |
| `test_oxford_follows_sibling_entries_only` | Both senses of the word are collected by following the *sibling* entry (`run_2`) and not unrelated related-entry links like `run-up` or `ladder` — the fetch list is asserted exactly. |
| `test_oxford_unknown_word_returns_empty` | A 404 yields an empty result rather than raising. |
| `test_merriam_webster_parses_entries` | Each entry's part of speech and definitions are parsed, with a repeated definition de-duplicated. |
| `test_merriam_webster_unknown_word_returns_empty` | A 404 yields an empty result. |

## test_quiz.py — grading, language filtering and fallbacks (10 cases)

| Test | What it checks |
| --- | --- |
| `test_default_language_is_ukrainian` | `quiz_lang` defaults to Ukrainian (#113) — the old hardcoded Russian default is gone — and only cards with a Ukrainian translation are quizzed. |
| `test_default_language_follows_quiz_lang_setting` | Switching the setting switches the quiz, and a card with no translation in that language is left out. |
| `test_explicit_lang_overrides_the_setting` | `?lang=ukr` wins over the stored preference, and the page's language attribute follows. |
| `test_hidden_preferred_language_falls_back_to_visible` | A preferred language hidden in Settings (#46/#79) falls back to the visible one rather than producing an empty quiz. |
| `test_unknown_language_falls_back_to_the_setting` | `?lang=hacker` falls back to the setting instead of erroring. |
| `test_grading_accepts_any_variant_case_insensitive` | Any listed translation counts, case and surrounding spaces are ignored, and ё/е are treated alike. |
| `test_grading_in_ukrainian` | The same tolerance applies in Ukrainian mode. |
| `test_russian_answer_rejected_in_ukrainian_mode` | The right word in the wrong language is wrong — the languages are not pooled. |
| `test_wrong_answers_reveal_expected` | A wrong or empty answer shows the accepted translations. |
| `test_empty_topic_message` | A topic with no cards says there is nothing to quiz on. |

## test_reset_auth.py — Reset Auth (6 cases)

kuantorflow#98. The gate pass and the Google identity both live in the signed session cookie; `POST /auth/reset` clears it entirely.

| Test | What it checks |
| --- | --- |
| `test_reset_clears_gate_pass_and_identity` | After the reset both `user` and `access_granted` are gone from the session and pages are gated again. |
| `test_reset_works_for_anonymous_gated_visitors` | A visitor who is only through the gate can reset too, and is gated afterwards. |
| `test_reset_rejects_get` | `GET /auth/reset` answers 405 — not reachable by following a link. |
| `test_reset_preserves_the_settings_file` | Preferences survive a reset: signing back in restores them rather than starting from defaults. |
| `test_reset_button_enabled_even_in_read_only_popup` | #102 freezes the settings controls for anonymous visitors, but Reset Auth is an action, not a setting, so it stays clickable — with its confirmation dialog present. |
| `test_keyword_reentry_after_reset` | The full round-trip: reset, then the keyword opens the site again. |

## test_reverso_parser.py — Reverso copy-paste parsing (6 cases)

kuantorflow#134. The parser detects OneNote copy-pastes of Reverso entries by their colour-coded structure, builds one card per word + part of speech with senses aggregated, and splits the glued translation strings with Claude. The AI split is stubbed; the split function's own parsing and fallback are tested through an injected fake `anthropic` module, since the real package is not in this venv.

| Test | What it checks |
| --- | --- |
| `test_reverso_detected_and_parsed` | One card from a two-sense entry: part of speech mapped from the Russian label, both explanations aggregated, both example sentences kept in order, the glued translations split and de-duplicated across senses, and the readable source preserved. |
| `test_reverso_one_card_per_pos` | A word appearing under two parts of speech yields two distinct cards, not one merged. |
| `test_reverso_ukrainian_pos_and_language` | A Ukrainian entry maps its own part-of-speech label and the translation is filed as Ukrainian — detected from the letters, with no Russian field written. |
| `test_non_reverso_mht_falls_back_to_line_parser` | An ordinary `.mht` still parses through the line parser, which produces no examples. |
| `test_split_glued_translations_parses_model_reply` | The helper parses the model's JSON reply into the split strings. |
| `test_split_glued_translations_falls_back_on_error` | When the client cannot even be constructed, the glued string is kept whole and nothing raises — the split is best-effort by design. |

## test_settings.py — the settings store, endpoint and popup (16 cases)

kuantorflow#86, #13, #20.

**The store**

| Test | What it checks |
| --- | --- |
| `test_first_load_creates_default_config_file` | The first read materialises the shared default file with the default values. |
| `test_first_load_creates_per_user_config_file` | A signed-in read creates that user's own file and **not** the shared one. |
| `test_corrupt_config_falls_back_without_being_overwritten` | A corrupt — possibly hand-edited — file yields defaults and is left exactly as it was, rather than being clobbered. |

**`POST /settings` (#13, #20)**

| Test | What it checks |
| --- | --- |
| `test_settings_endpoint_saves_and_validates` | Valid values are stored, an invalid one falls back to its default, an unknown key is dropped, and the on-disk file matches the response apart from the `_email` metadata (#174). |
| `test_settings_saved_per_identity` | A signed-in save lands in that user's own file only. |
| `test_anonymous_settings_post_is_rejected` | An anonymous save answers 403 (#102) — the default config is shared, so it is read-only for them. |
| `test_settings_popup_read_only_for_anonymous` | The popup's controls are disabled for a visitor with no account. |
| `test_settings_popup_editable_for_signed_in` | And editable once signed in. |
| `test_settings_popup_markup` | The header menu item and the popup's structure are present. |
| `test_settings_popup_two_column_layout` | The four fieldsets sit in a two-column grid with all three action buttons on one row, so nothing spills below the fold. |
| `test_settings_popup_prefilled_from_store` | The popup renders the stored values rather than the defaults. |

**Quiz language**

| Test | What it checks |
| --- | --- |
| `test_quiz_lang_defaults_to_ukrainian_and_validates` | An unknown language falls back to Ukrainian (#113). |
| `test_quiz_lang_toggle_enabled_when_both_languages_visible` | Both radios are live while both languages are shown. |
| `test_quiz_lang_toggle_disabled_when_one_language_hidden` | With one language hidden both radios are disabled and the explanatory hint is shown — there is no choice left to make. |

**Auto-add on lookup (#13)**

| Test | What it checks |
| --- | --- |
| `test_auto_add_saves_without_review_popup` | With the setting on, both cards are saved directly, the banner reports the count, and no review popup is rendered. |
| `test_lookup_receives_the_stored_providers` | The lookup is called with exactly the stored translator and dictionary, so the settings actually reach the network layer. |

## test_translucent_surfaces.py — half-transparent panels, widget and cards (13 tests, 15 cases)

kuantorflow#197. The site sits on a photograph and almost none of it was visible. The content panels are translucent now, and Mykola's panel is too — but less so, because it holds a whole conversation rather than a short form. The opacity is a pair of CSS variables rather than literal alphas, because the values are meant to be tuned by eye.

**The knobs**

| Test | What it checks |
| --- | --- |
| `test_both_opacities_are_variables` | Both are custom properties in a sane range — literals scattered through the stylesheet would make tuning a hunt. |
| `test_the_panels_use_the_panel_variable` | `.panel` reads its alpha from `--panel-alpha`. |
| `test_the_widget_uses_its_own_variable` | `#mykola-panel` reads its own, not the panels'. |
| `test_the_widget_is_the_more_opaque_of_the_two` | The actual requirement: a conversation is the most reading-heavy surface on the site, so it gets more white behind it than a panel holding a short form. |
| `test_neither_surface_is_blurred` | A backdrop blur hides the background, which is the thing being revealed. |

**The flashcards page gets a third (#201)**

| Test | What it checks |
| --- | --- |
| `test_the_cards_have_their_own_opacity` | `--flashcard-alpha` exists and `.card` reads its background from it. |
| `test_a_card_is_more_opaque_than_a_main_page_panel` | Why it needs a number at all: the main page has three panels, a topic page has one per card — dozens, stacked, each carrying a word, a part of speech, an explanation and two translations with their examples. |
| `test_the_plain_panels_on_that_page_are_unaffected` | A topic page also renders an ordinary `.panel` — the empty-topic explanation (#127) — and it keeps the main page's value, because it is doing the main page's job rather than the card's. Decided, not incidental. |

**The part that fails silently**

| Test | What it checks |
| --- | --- |
| `test_the_widgets_inner_panes_do_not_cover_it` | Three cases — the message list, the composer and the auth strip. Each used to be a solid fill spanning the panel; with any one of them opaque again `--widget-alpha` stops meaning anything, and nothing looks wrong: the CSS is valid, the variable is there, the widget just stays opaque. |
| `test_the_message_bubbles_keep_their_fills` | They are content, not the surface behind it — a transparent bubble would leave the two speakers indistinguishable. |

**What must not change**

| Test | What it checks |
| --- | --- |
| `test_the_top_bar_is_untouched` | Excluded from #197 by name. |
| `test_the_settings_dialog_stays_solid` | Dropped from #197: through a translucent dialog you would see the dimmed page rather than the background, which is not the effect. |
| `test_the_topic_tiles_stay_solid` | #185 will put a picture on each; a translucent tile showing the background behind a photograph inside it would be a mess. |

## test_ui_pages.py — pages, banners and link previews (10 cases)

| Test | What it checks |
| --- | --- |
| `test_topic_tiles` | Each topic renders as a tile linking to it, with its card count (#184). |
| `test_no_topics_hint` | An empty deck says "No topics yet" rather than showing nothing. |
| `test_page_survives_db_failure` | A database failure still renders the page with that hint — the home page never 500s over it. |
| `test_submit_buttons_have_loading_feedback` | The lookup button shows a working state and disables itself, so a slow lookup is not clicked twice. |
| `test_about_modal_markup` | The About link, its image and the modal with its close control. |
| `test_preview_meta_on_gate_page` | Crawlers are redirected to the gate, so it carries the Open Graph image, title and description. |
| `test_preview_meta_on_index` | The index carries the full set of OG tags, an absolute image URL and the Twitter card type. |
| `test_proxyfix_makes_absolute_https_urls` | Behind the proxy's forwarded headers the preview URL is absolute and https — otherwise the shared link previews a localhost path. |
| `test_page_specific_titles_in_og_title` | A topic page's OG title names the topic rather than repeating the site title. |
| `test_favicon_and_preview_image_served` | Both images are actually served. |

## test_users_table.py — persisted identities (9 tests, 14 cases)

kuantorflow#148. A Google sign-in writes a row keyed on the OIDC subject, and the session carries the user's id plus the name claims Mykola addresses them by.

**What a sign-in records**

| Test | What it checks |
| --- | --- |
| `test_sign_in_records_the_user` | The subject, email and the three name claims are recorded, and the session carries the id, the given name and a null preferred name. |
| `test_sign_in_survives_a_dead_database` | A failed write must never cost the user their login: they are signed in with `id: None`, which every reader has to tolerate. |
| `test_placeholder_name_is_never_stored` | "there" is a rendering placeholder, not somebody's name — it reaches the page but never the database. |
| `test_blank_claims_become_null` | Whitespace-only claims are stored as NULL rather than as blank strings. |
| `test_sign_in_without_a_subject_is_not_recorded` | `sub` is mandatory in OIDC — if it is missing something is wrong, but the visitor still gets in rather than seeing an error. |

**What Mykola calls them**

| Test | What it checks |
| --- | --- |
| `test_first_name_resolution_order` | Six cases: their own chosen name wins, then the Google given name, then the first word of the display name; blanks are skipped, the placeholder passes through, and an empty session yields nothing. |
| `test_anonymous_visitor_has_no_first_name` | No session identity means no name to use. |

**The query itself**

| Test | What it checks |
| --- | --- |
| `test_upsert_never_overwrites_the_preferred_name` | The upsert leaves `preferred_name` alone — it is the user's own choice (#148 / ai_agent#62) and a sign-in supplies no such claim. It also carries `id = LAST_INSERT_ID(id)`, without which an update leaves the row id at 0 and the caller would put a bogus id in the session. |
| `test_upsert_is_keyed_on_the_google_subject` | Keyed on the subject, not the email — an address change must update the row rather than fork it. |

## test_widget_identity.py — the widget must not replay another identity's chat (14 cases)

kuantorflow#170. The widget keeps its whole thread in `localStorage`. Nothing on the server was leaking it — the transcript was replayed by the browser, because the stored state carried no record of who it belonged to. It is now stamped with an opaque per-identity token and restored only on a match, which is the only thing that covers a sign-out the browser never sees: a session expiring, another tab, or an identity dropped server-side.

**The token itself**

| Test | What it checks |
| --- | --- |
| `test_anonymous_visitors_get_no_token` | No identity means no stamp. |
| `test_a_signed_in_user_gets_an_opaque_token` | A short hex digest, not a readable value. |
| `test_the_token_reveals_nothing_about_the_user` | It lands in `localStorage`, which survives sign-out and is readable by anything on the origin — so neither the address nor its local part may appear in it. |
| `test_different_users_get_different_tokens` | Two identities never collide. |
| `test_the_same_user_gets_a_stable_token` | The same identity stamps the same way, or every page load would drop the thread. |
| `test_the_id_identifies_the_user_when_present` | Keyed on the id where there is one (#148), so the token survives an email change the way the users row does. |
| `test_an_email_only_session_still_gets_a_token` | A sign-in whose users row could not be written has `id: None` and still needs a stamp, or its thread would be treated as anonymous. |

**What the page hands the widget**

| Test | What it checks |
| --- | --- |
| `test_the_page_declares_null_for_anonymous` | The anonymous page declares a null identity. |
| `test_the_page_declares_the_token_when_signed_in` | The signed-in page declares the exact token that identity resolves to. |
| `test_the_stored_state_is_stamped` | The save path writes the identity into the stored state. |
| `test_a_mismatched_thread_is_dropped_on_load` | A thread belonging to someone else is compared, **cleared** — not merely ignored — and the load returns nothing. |
| `test_an_unstamped_thread_is_dropped_rather_than_read_as_anonymous` | The case that made the bug survive its own fix: a thread written before the stamp existed has no `identity` key, and `state.identity \|\| null` turns that into the same null an anonymous visitor carries. The two must be told apart, or the signed-in transcript stays on screen for exactly the anonymous visitor a sign-out just created. |
| `test_the_greeting_is_still_anonymous_for_a_signed_out_visitor` | The server-rendered greeting was never the problem; this locks in that it stays nameless, since it is what a dropped thread falls back to. |
| `test_the_greeting_still_names_a_signed_in_visitor` | And that a signed-in visitor is still greeted by name — the fix must not have cost the personalisation. |

---

## Keeping this current (issue #14)

This document goes stale silently — it claimed 94 tests while the suite had
grown past 500 — so there is a checker rather than a habit:

```
venv\Scripts\python docs\check_catalog.py
```

It runs `pytest --collect-only` and fails on a missing section, a test that is
not documented **in its own section**, a row naming a test that no longer
exists, or a heading whose counts disagree with what pytest collects. Counting
the table rows would not be enough: a parametrized test is one row and several
cases.

When it complains:

1. Update this file — new rows and sections, and the counts in the heading,
   the run table and the marker notes.
2. Re-render the DOCX:
   `python <kuantorflow>/reports/scripts/md_to_docx.py docs/test-catalog.md`
3. Run the checker again.

Normally all of that belongs in the same pull request as the tests themselves.

**Totals as of this revision: 38 files, 528 test functions, 579 collected
cases** (569 passing, 10 opt-in `db` skips).
