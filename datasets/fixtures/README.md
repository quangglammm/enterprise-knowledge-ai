# Parser fixtures

Small synthetic documents from the fictional Bamboo Harbor Logistics corpus (ADR-0005), used by unit tests for parsing and chunking. Regenerate with:

```bash
uv run python scripts/make_fixtures.py
```

| File | Format | Language | Exercises |
| --- | --- | --- | --- |
| `leave-policy-vi.pdf` | PDF, 2 pages | Vietnamese | Diacritics, `Điều N.` headings, page numbers, wrapped lines |
| `vpn-runbook-en.docx` | DOCX | English | Heading styles, numbered list, table |
| `handbook-mixed.html` | HTML | Mixed | Boilerplate removal (script, nav, header, footer), hidden elements, lists |
| `onboarding-vi.md` | Markdown | Vietnamese | Markdown headings |

Corrupt, empty, encrypted and oversized inputs are generated inside the tests.

All content is fictional. Any resemblance to a real company is unintended.
