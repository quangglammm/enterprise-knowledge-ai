# Corpus v2

A superset of corpus v1, used by benchmark v2 (ADR-0012). Every v1 document version is copied byte-for-byte; 28 documents are added. The fictional companies are Bamboo Harbor Logistics (`bamboo-harbor`) and Lotus Retail (`lotus-retail`); any resemblance to a real company is unintended. No real company data.

`manifest.jsonl` has the same fields as v1, with source and license per document. The loader rejects a file whose sha256 differs, so documents are never edited in place. The manifest and the benchmark labels are rebuilt by `scripts/build_benchmark.py --version v2` from `scripts/benchmark_data/v2.py`. The PDF and DOCX files come from `scripts/make_corpus_v2.py`.

| Property | v2 |
| --- | --- |
| Documents | 49 (55 versions, 243 chunks at 1200/150) across 2 tenants |
| Languages | 28 Vietnamese, 18 English, 3 bilingual |
| Formats | PDF (one with a table), DOCX, HTML, Markdown |
| Version pairs with different answers | v1's three, plus `hr-overtime-policy`, `hr-training-policy`, `eng-backup-restore` |
| Restricted | 15: `hr`, `managers`, `security`, `engineering` and combinations |
| Near-duplicates | Da Nang hub service levels; Binh Duong cold-store rules; runbooks with identical sections; Lotus Retail copies of Bamboo Harbor policies |
| Stale restatement | `news-digest-2026-q3` repeats the superseded overtime rules |
| Planted instructions | `it-guest-wifi` (v1) and `it-service-desk-faq` |

## Public documents

| Document | Source | License |
| --- | --- | --- |
| `pub-vn-labour-code-working-time` | Bộ luật Lao động 45/2019/QH14, Chương VII, Điều 105–114, transcribed from the Công báo on vi.wikisource.org (revision 106431), retrieved 2026-10-30 | Public domain: legal normative documents are not protected by copyright (Luật Sở hữu trí tuệ, Điều 15) |
| `pub-uk-holiday-entitlement` | https://www.gov.uk/holiday-entitlement-rights, parts "Entitlement", "Booking time off" and "Taking holiday before leaving a job", retrieved 2026-10-30 | Open Government Licence v3.0 |

The Labour Code text is verbatim, with Markdown headings added and the Gazette's page breaks rejoined. Điều 115 (personal and marriage leave) is left out, so v1's unanswerable q013 stays unanswerable. The GOV.UK parts keep their original HTML.

Synthetic ground-truth facts were written and checked by the author, then reviewed by a person on 2026-10-30 as ADR-0005 requires; all were accepted unchanged.
