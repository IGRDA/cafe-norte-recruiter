-- D63 widened the languages Ana answers in to ten; the turns table still allowed only es and
-- en, so every turn after a switch to another language failed to save (22 October 2026).
-- The list must equal `cafe_norte.errors.SWITCHABLE` (tests/unit/test_migrations_languages.py).
alter table turns drop constraint turns_language_check;
alter table turns add constraint turns_language_check
    check (language in ('es', 'en', 'fr', 'pt', 'it', 'de', 'ro', 'ar', 'zh', 'uk'));
