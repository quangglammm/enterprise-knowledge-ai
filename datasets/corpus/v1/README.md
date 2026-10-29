# Corpus v1

Fictional documents for two fictional companies, Bamboo Harbor Logistics (`bamboo-harbor`) and Lotus Retail (`lotus-retail`), used by benchmark v1 (ADR-0005, ADR-0011). Any resemblance to a real company is unintended. No real company data.

`manifest.jsonl` lists every document version: ID, version, tenant, title, language, format, file, allowed groups, source, license and sha256. The loader rejects a file whose sha256 differs, so documents are never edited in place. A change means a new corpus version, with the manifest and the benchmark labels rebuilt by `scripts/build_benchmark.py`.

| Property | v1 |
| --- | --- |
| Documents | 21 (24 versions) across 2 tenants |
| Languages | 13 Vietnamese, 6 English, 2 bilingual |
| Formats | PDF, DOCX, HTML, Markdown |
| Version pairs with different answers | `hr-leave-policy`, `hr-expense-policy`, `eng-deploy-guide` |
| Restricted | 6: `hr`, `hr`+`managers`, `managers`, `security`, `engineering` (2) |
| Planted | Bilingual FAQ repeating another policy (`hr-faq-bilingual`); assistant-directed instructions (`it-guest-wifi`) |

The first four files are copies of the parser fixtures in `datasets/fixtures/`.

Ground-truth facts were written and checked by the author. ADR-0005 also asks for a review by another person, which is still pending.
