-- Accept every reply language supported by the runtime.
alter table turns drop constraint turns_language_check;
alter table turns add constraint turns_language_check
    check (language in ('es', 'en', 'fr', 'pt', 'it', 'de', 'ro', 'ar', 'zh', 'uk'));
