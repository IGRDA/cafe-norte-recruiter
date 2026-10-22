# `tests/unit`

Pure code, value in and value out, plus static checks of the repository (import rules,
settings, schema files). No store, runtime, handler, app or adapter: the architecture test
`test_unit_tests_import_only_pure_code` holds it. Properties live here. `make test-unit` runs
the folder in about two seconds.
