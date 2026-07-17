# KuantorFlow Automation — Test Catalog

**As of 18 July 2026** · Repository: [kuantorflow_automation](https://github.com/Kuantor/kuantorflow_automation) · **94 tests in 11 files**

---

## How to run

The suite lives in `tests/` and runs with the repo's own virtualenv:

- `.\venv\Scripts\pytest -m "not live"` — the **offline suite**: 88 tests that import the Flask app from the kuantorflow checkout (`KUANTORFLOW_PATH` in `.env`) with the database and all external services stubbed. **87 pass; 1 is skipped** unless a local MySQL is configured (marker `db`). Runs in about 2 seconds, fully offline.
- `.\venv\Scripts\pytest -m live` — **6 read-only smoke tests** against the deployed site (`SITE_URL` + real `ACCESS_KEYWORD` from the gitignored `.env`).
- `.\venv\Scripts\pytest` — everything.

Shared fixtures (`conftest.py`): `client` (a test client already through the keyword gate), `fresh_client` (no session — still gated), `saved` (captures `save_flashcard()` calls instead of writing to MySQL), and an autouse `settings_dir` fixture that redirects the settings store into a per-test temp directory so page renders never write into the real checkout.

---

## test_access_gate.py — the keyword gate (6 tests)

Every page is blocked until the keyword is entered.

| Test | What it checks |
| --- | --- |
| `test_pages_redirect_to_gate_when_unauthenticated` | Home, flashcards and quiz pages all answer 302 to `/enter` for a visitor without the keyword. |
| `test_write_endpoints_are_gated` | Write endpoints (`/cards/add`, card deletion) are gated too — not just the pages. |
| `test_gate_page_and_static_assets_reachable` | The gate page itself and static assets (CSS) load without the keyword, so the gate can render. |
| `test_wrong_keyword_shows_error` | A wrong keyword re-renders the gate with the "Incorrect keyword" error. |
| `test_correct_keyword_opens_site` | The correct keyword redirects into the site, and pages open afterwards. |
| `test_fresh_session_is_gated_again` | Access is per session: a brand-new client is gated even while another session is inside. |

## test_backup.py — backup retention logic (4 tests)

Offline checks of the backup helper — no database or `mysqldump` needed.

| Test | What it checks |
| --- | --- |
| `test_backup_filename_is_timestamped_and_sortable` | Backup names embed the timestamp (`kuantorflow_2026-07-13_020000.sql.gz`) and lexicographic order equals chronological order — the property the retention logic relies on. |
| `test_select_old_backups_keeps_newest` | With `keep=2`, the two oldest of four backups are selected for deletion, the two newest survive. |
| `test_select_old_backups_ignores_unrelated_files` | Unrelated files in the backup folder (`notes.txt`, `.gitkeep`) are never deletion candidates. |
| `test_select_old_backups_nothing_to_delete_when_under_limit` | Nothing is selected while the backup count is within the retention limit. |

## test_backup_roundtrip.py — restore round-trip (1 test, marker `db`)

Runs only against a locally configured MySQL; **skipped otherwise** (this is the suite's one skip).

| Test | What it checks |
| --- | --- |
| `test_deleted_card_reappears_after_restore` | Full backup → delete a card → restore round-trip: the deleted card is back after restoring the dump, proving the backup is actually restorable. |

## test_duplicates.py — duplicate prevention, kuantorflow#101 (8 tests)

| Test | What it checks |
| --- | --- |
| `test_duplicate_word_pos_is_skipped` | `save_flashcard()` skips a card whose word + part of speech already exists: no `INSERT`, no commit (driven against a fake DB connection). |
| `test_new_card_is_inserted` | A new word+POS is inserted and the new row id returned. |
| `test_duplicate_check_is_null_safe_on_pos` | Pos-less cards (`.mht` imports) deduplicate too — the check uses the NULL-safe `<=>` comparison. |
| `test_add_card_reports_duplicate` | `/cards/add` answers `{ok: true, saved: false, duplicate: true}` for a duplicate. |
| `test_review_popup_knows_the_duplicate_state` | The review popup carries the "Already in DB" state its JS shows on a duplicate card's button. |
| `test_auto_add_banner_counts_skipped_duplicates` | The automatic-add banner counts skips: "Added 1 card(s) …, skipped 1 already in the database." |
| `test_auto_add_banner_when_everything_is_a_duplicate` | When every card is a duplicate, the "already in the database — nothing added" banner shows. |
| `test_find_duplicates_groups_and_keeps_oldest` | The dedup maintenance script groups by word (case-insensitive) + pos (NULL grouped), keeping the oldest card of each group. |

## test_language_visibility.py — visibility switches, kuantorflow#46/#79/#111 (10 tests)

| Test | What it checks |
| --- | --- |
| `test_popup_has_visibility_checkboxes_checked_by_default` | Both "Show … translation" checkboxes render in the Settings popup, checked by default. |
| `test_visibility_round_trip_through_settings_endpoint` | `POST /settings` persists the switches and the popup pre-fill reflects them on the next render. |
| `test_flashcards_show_both_languages_by_default` | With default settings, cards show Ukrainian and Russian translations. |
| `test_flashcards_hide_disabled_language` | A disabled language's translations **and examples** disappear from cards while the other language stays; the quiz link survives. |
| `test_flashcards_hide_quiz_link_when_no_language_visible` | With both languages hidden, "Take quiz" disappears from flashcards pages. |
| `test_review_popup_carries_hidden_language_as_hidden_input` | A hidden language's translation travels as a filled hidden input in the review popup — the saved card stays complete. |
| `test_quiz_falls_back_to_visible_language` | The quiz falls back to the visible language and drops the hidden one from its language switch. |
| `test_quiz_explains_itself_when_all_languages_hidden` | With both languages hidden the quiz shows an explanation instead of a form. |
| `test_agent_receives_hidden_languages` | The Mykola chat endpoint passes `hidden_languages=["Russian"]` to the agent when Russian is hidden. |
| `test_agent_gets_no_hidden_languages_by_default` | With nothing hidden the agent receives `hidden_languages=None`. |

## test_live_site.py — deployed-site smoke tests (6 tests, marker `live`)

Read-only HTTP checks against `SITE_URL`; never write to the database.

| Test | What it checks |
| --- | --- |
| `test_site_is_up_and_gated` | The site is up and an unauthenticated visit lands on the gate. |
| `test_https_is_forced` | `http://` redirects to `https://`. |
| `test_wrong_keyword_rejected` | The shared `gate.py` helper raises its clear error on a wrong keyword. |
| `test_correct_keyword_opens_site` | `enter_gate()` with the real `ACCESS_KEYWORD` opens the site (the helper is exercised on every live run). |
| `test_static_assets_served` | CSS, favicon, preview and background images all answer 200. |
| `test_link_preview_tags_on_gate` | Open Graph tags are present on the gate, so link previews survive the keyword wall. |

## test_lookup_and_cards.py — lookup, cards, MHT, deletion (9 tests)

| Test | What it checks |
| --- | --- |
| `test_lookup_shows_review_popup_without_saving` | A word lookup opens the review popup with one editable card per part of speech — and saves nothing yet. |
| `test_add_card_saves_edited_values` | `/cards/add` saves the (possibly edited) reviewed values; empty fields become NULL. |
| `test_add_card_requires_word` | A blank word is rejected with 400 and nothing is saved. |
| `test_empty_word_shows_error_and_no_popup` | An empty lookup shows "Please enter a word." and no popup. |
| `test_mht_upload_shows_review_before_saving` | MHT upload goes through the same review popup — two columns (file content beside cards) with "Add All" — and saves nothing before review. |
| `test_flashcards_page_has_delete_cross_and_modal` | Cards carry the delete cross with the card's word and URL, plus the confirmation modal. |
| `test_delete_card_flow` | Deleting a card calls the DB layer and confirms with a "Deleted card" banner. |
| `test_delete_missing_card_is_friendly` | Deleting a non-existent card shows a friendly "Card not found" message. |
| `test_delete_rejects_get` | The delete endpoint answers 405 to GET — deletion is POST-only. |

## test_parsers.py — MHT and text parsing (3 tests)

| Test | What it checks |
| --- | --- |
| `test_mht_extraction` | 'word — explanation' lines are extracted from an MHT file (all separator variants), duplicates skipped, topic attached. |
| `test_entry_from_line_rejects_plain_text` | Lines without a separator produce no entry. |
| `test_to_list_round_trip` | Stored example lists deserialize from JSON arrays, newline-separated text, plain strings and NULL. |

## test_providers.py — provider dispatch and fetchers, kuantorflow#20/#21 (13 tests)

Fully offline: dispatch tests swap the backend functions; fetcher tests run against canned responses captured from the real services.

| Test | What it checks |
| --- | --- |
| `test_default_lookup_uses_google` | The default lookup uses Google Translate and never calls Bing. |
| `test_bing_translator_is_used_when_selected` | `translator="bing"` routes to the Bing backend and skips Google. |
| `test_failing_bing_falls_back_to_google` | A Bing network failure falls back to Google — the lookup still produces cards. |
| `test_empty_bing_falls_back_to_google` | An empty Bing result falls back to Google as well. |
| `test_selected_dictionary_provides_definitions` | The chosen dictionary's definitions land on the cards, with no Reverso fallback when it delivered. |
| `test_empty_dictionary_falls_back_to_reverso` | An empty dictionary result falls back to Reverso's definitions. |
| `test_definition_failures_never_break_the_lookup` | Even with every definition source down, the lookup still returns translation cards. |
| `test_bing_dictionary_groups_by_pos` | Bing responses group by mapped part of speech (NOUN→noun …), deduplicate terms, cap at the maximum, unknown tags land in "other". |
| `test_bing_dictionary_plain_translation_fallback` | Multiword phrases without a dictionary entry fall back to a plain translation under "other". |
| `test_oxford_follows_sibling_entries_only` | The Oxford fetcher follows same-headword sibling entries (`run` → `run_2`) and ignores lookalikes (`run-up_1`, `ladder_1`). |
| `test_oxford_unknown_word_returns_empty` | An Oxford 404 yields `{}` — unknown words never raise. |
| `test_merriam_webster_parses_entries` | The M-W fetcher parses per-entry definitions grouped by part of speech, deduplicated. |
| `test_merriam_webster_unknown_word_returns_empty` | An M-W 404 yields `{}`. |

## test_quiz.py — quiz behaviour and grading (10 tests)

| Test | What it checks |
| --- | --- |
| `test_default_language_is_ukrainian` | The quiz opens in Ukrainian out of the box (`quiz_lang` default, kuantorflow#113) — the old hardcoded Russian default is gone. |
| `test_default_language_follows_quiz_lang_setting` | With `quiz_lang: russian` saved, the quiz opens in Russian; cards without a Russian translation are excluded. |
| `test_explicit_lang_overrides_the_setting` | An explicit `?lang=` from the in-page switch beats the stored preference. |
| `test_hidden_preferred_language_falls_back_to_visible` | A preferred language hidden by the visibility switches falls back to the visible one. |
| `test_unknown_language_falls_back_to_the_setting` | An unknown `?lang=` value lands on the stored preference. |
| `test_grading_accepts_any_variant_case_insensitive` | Any stored comma-separated variant is accepted, case-insensitively, with ё/е tolerated. |
| `test_grading_in_ukrainian` | Grading works in Ukrainian mode with its own translations. |
| `test_russian_answer_rejected_in_ukrainian_mode` | A Russian answer is wrong in a Ukrainian quiz — languages are graded separately. |
| `test_wrong_answers_reveal_expected` | Wrong answers show the expected translation with the score. |
| `test_empty_topic_message` | A topic without cards shows "nothing to quiz on" instead of an empty form. |

## test_settings.py — settings store, popup, auto-add, kuantorflow#86/#13/#20/#113 (12 tests)

| Test | What it checks |
| --- | --- |
| `test_first_load_creates_default_config_file` | The first read materialises `settings/config-default.json` with the defaults. |
| `test_first_load_creates_per_user_config_file` | A signed-in identity gets its own `config-<email-prefix>.json`; the default file is untouched. |
| `test_corrupt_config_falls_back_without_being_overwritten` | A corrupt config yields defaults and is never silently overwritten — hand-edited files stay inspectable. |
| `test_settings_endpoint_saves_and_validates` | `POST /settings` persists valid values, resets invalid enum values to their default, drops unknown keys — and the file on disk matches the response. |
| `test_settings_saved_per_identity` | Anonymous and signed-in settings live in separate files and don't leak into each other. |
| `test_settings_popup_markup` | The popup renders the menu item, the auto-add checkbox and all four provider radio values. |
| `test_settings_popup_prefilled_from_store` | Saved values pre-check the popup controls, and the lookup panel title follows the chosen translator. |
| `test_quiz_lang_defaults_to_ukrainian_and_validates` | `quiz_lang` defaults to `ukrainian`; invalid values reset to it; `russian` round-trips. |
| `test_quiz_lang_toggle_enabled_when_both_languages_visible` | The quiz-language toggle is enabled and pre-checked when both languages are visible. |
| `test_quiz_lang_toggle_disabled_when_one_language_hidden` | With one language hidden, both quiz-language radios render disabled and the explanatory hint is shown. |
| `test_auto_add_saves_without_review_popup` | With auto-add on, a lookup saves every card, shows the "Added N card(s)" banner, and opens no review popup. |
| `test_lookup_receives_the_stored_providers` | The lookup call receives exactly the stored `translator` and `explanatory_dictionary` values. |

## test_ui_pages.py — index UI, banners, link previews (12 tests)

| Test | What it checks |
| --- | --- |
| `test_topic_chips` | Topic chips render with links and card counts. |
| `test_no_topics_hint` | With no topics, the "No topics yet" hint shows instead of chips. |
| `test_page_survives_db_failure` | A database outage still renders the page (200) with the no-topics hint — the DB is optional for browsing. |
| `test_submit_buttons_have_loading_feedback` | Submit buttons carry the "Looking up…" loading feedback and disable on submit. |
| `test_about_modal_markup` | The About link, modal, image and close button are all present. |
| `test_db_success_banner_is_green` | "Test DB Connection" success lands in the green confirmation banner. |
| `test_db_failure_banner_is_red` | A DB failure renders the red error banner with the message. |
| `test_preview_meta_on_gate_page` | The gate page carries the Open Graph tags (crawlers land there), with image, title and description. |
| `test_preview_meta_on_index` | The index page has the full OG set plus the Twitter summary-card tag. |
| `test_proxyfix_makes_absolute_https_urls` | Behind the proxy headers, absolute URLs (og:image) use https and the real host — the ProxyFix wiring works. |
| `test_page_specific_titles_in_og_title` | Inner pages put their specific title (e.g. the topic) into og:title. |
| `test_favicon_and_preview_image_served` | The favicon and preview image are served with 200. |

---

*Generated 18 July 2026 from the test sources (`tests/*.py`) at the current main of kuantorflow_automation. Offline suite status at generation time: 87 passed, 1 skipped (the `db`-marked restore round-trip), 6 live tests deselected.*
