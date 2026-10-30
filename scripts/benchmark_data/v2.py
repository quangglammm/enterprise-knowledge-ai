"""Corpus v2 and benchmark v2 authoring data (ADR-0012). Built by build_benchmark.py.

v2 is a superset of v1: every v1 document version is copied byte-for-byte and every v1
question is kept, so the drop on the same questions shows what the new distractors cost.
Where a new document legitimately restates a v1 answer, that document is added to the v1
question as an alternative in its evidence group; where it competes without answering, the
question gains the near-duplicate type. No new document answers a v1 unanswerable question.
"""

# Questions and answers are natural-language data; splitting them only hurts review.
# ruff: noqa: E501

from typing import Any

from benchmark_data import v1
from benchmark_data.v1 import (
    ACCESS,
    BAMBOO,
    EN,
    ENGINEER,
    HR,
    LICENSE,
    LOTUS,
    LOTUS_STAFF,
    MANAGER,
    MULTI,
    NONE,
    SECURITY,
    SOURCE,
    STAFF,
    TENANT,
    VERSION,
    VI,
    Group,
    Quote,
    X,
)

__all__ = ["LICENSE", "MANIFEST", "PROVENANCE", "QUESTIONS", "SOURCE"]

NEAR = "near-duplicate"

PROVENANCE: dict[str, tuple[str, str]] = {
    "pub-vn-labour-code-working-time": (
        "public: Bộ luật Lao động số 45/2019/QH14, Chương VII, Điều 105-114, Công báo số 993+994/2019, "
        "transcribed from https://vi.wikisource.org (revision 106431), retrieved 2026-10-30",
        "public domain: legal normative documents are not protected by copyright (Luật Sở hữu trí tuệ 2005, Điều 15)",
    ),
    "pub-uk-holiday-entitlement": (
        "public: https://www.gov.uk/holiday-entitlement-rights, parts 'Entitlement', 'Booking time off' "
        "and 'Taking holiday before leaving a job', retrieved 2026-10-30",
        "Open Government Licence v3.0",
    ),
}

# (id, version, tenant, title, language, format, file, allowed groups); v1 before v2.
MANIFEST: list[tuple[str, int, str, str, str, str, str, list[str]]] = [
    *v1.MANIFEST,
    (
        "hr-overtime-policy",
        1,
        BAMBOO,
        "Quy định làm thêm giờ",
        "vi",
        "md",
        "hr-overtime-policy-v1.md",
        ["all-staff"],
    ),
    (
        "hr-overtime-policy",
        2,
        BAMBOO,
        "Quy định làm thêm giờ (sửa đổi tháng 9 năm 2026)",
        "vi",
        "md",
        "hr-overtime-policy-v2.md",
        ["all-staff"],
    ),
    (
        "hr-training-policy",
        1,
        BAMBOO,
        "Chính sách đào tạo và phát triển",
        "vi",
        "md",
        "hr-training-policy-v1.md",
        ["all-staff"],
    ),
    (
        "hr-training-policy",
        2,
        BAMBOO,
        "Chính sách đào tạo và phát triển (cập nhật năm 2026)",
        "vi",
        "md",
        "hr-training-policy-v2.md",
        ["all-staff"],
    ),
    (
        "hr-travel-booking",
        1,
        BAMBOO,
        "Quy trình đặt vé và lưu trú khi đi công tác",
        "vi",
        "md",
        "hr-travel-booking.md",
        ["all-staff"],
    ),
    (
        "hr-wellbeing-program",
        1,
        BAMBOO,
        "Chương trình chăm sóc sức khỏe tinh thần",
        "vi",
        "html",
        "hr-wellbeing-program.html",
        ["all-staff"],
    ),
    (
        "hr-code-of-conduct",
        1,
        BAMBOO,
        "Bộ quy tắc ứng xử",
        "vi",
        "docx",
        "hr-code-of-conduct.docx",
        ["all-staff"],
    ),
    (
        "hr-payroll-calendar",
        1,
        BAMBOO,
        "Lịch chốt công và tính lương",
        "vi",
        "md",
        "hr-payroll-calendar.md",
        ["hr"],
    ),
    (
        "mgr-hiring-approval",
        1,
        BAMBOO,
        "Quy trình phê duyệt tuyển dụng",
        "vi",
        "md",
        "mgr-hiring-approval.md",
        ["managers"],
    ),
    (
        "mgr-budget-delegation",
        1,
        BAMBOO,
        "Quy định phân cấp phê duyệt chi tiêu",
        "vi",
        "md",
        "mgr-budget-delegation.md",
        ["managers"],
    ),
    (
        "ops-cold-chain-sop",
        1,
        BAMBOO,
        "Quy trình vận chuyển hàng lạnh",
        "vi",
        "pdf",
        "ops-cold-chain-sop.pdf",
        ["all-staff"],
    ),
    (
        "ops-coldstore-binh-duong",
        1,
        BAMBOO,
        "Nội quy an toàn kho lạnh Bình Dương",
        "vi",
        "md",
        "ops-coldstore-binh-duong.md",
        ["all-staff"],
    ),
    (
        "it-software-request",
        1,
        BAMBOO,
        "Quy trình yêu cầu cài đặt phần mềm",
        "vi",
        "md",
        "it-software-request.md",
        ["all-staff"],
    ),
    (
        "news-digest-2026-q3",
        1,
        BAMBOO,
        "Bản tin nội bộ quý 3 năm 2026",
        "vi",
        "html",
        "news-digest-2026-q3.html",
        ["all-staff"],
    ),
    (
        "pub-vn-labour-code-working-time",
        1,
        BAMBOO,
        "Bộ luật Lao động 2019 - Chương VII (trích)",
        "vi",
        "md",
        "pub-vn-labour-code-working-time.md",
        ["all-staff"],
    ),
    (
        "eng-db-failover-runbook",
        1,
        BAMBOO,
        "Database Failover Runbook",
        "en",
        "docx",
        "eng-db-failover-runbook.docx",
        ["engineering"],
    ),
    (
        "eng-queue-backlog-runbook",
        1,
        BAMBOO,
        "Job Queue Backlog Runbook",
        "en",
        "md",
        "eng-queue-backlog-runbook.md",
        ["engineering"],
    ),
    (
        "eng-cert-rotation-runbook",
        1,
        BAMBOO,
        "TLS Certificate Rotation Runbook",
        "en",
        "md",
        "eng-cert-rotation-runbook.md",
        ["engineering", "security"],
    ),
    (
        "eng-backup-restore",
        1,
        BAMBOO,
        "Database Backup and Restore Runbook",
        "en",
        "md",
        "eng-backup-restore-v1.md",
        ["engineering"],
    ),
    (
        "eng-backup-restore",
        2,
        BAMBOO,
        "Database Backup and Restore Runbook (revision 2)",
        "en",
        "md",
        "eng-backup-restore-v2.md",
        ["engineering"],
    ),
    (
        "eng-api-rate-limits",
        1,
        BAMBOO,
        "Public API Rate Limits",
        "en",
        "md",
        "eng-api-rate-limits.md",
        ["all-staff"],
    ),
    (
        "sec-access-review-standard",
        1,
        BAMBOO,
        "Access Review Standard",
        "en",
        "md",
        "sec-access-review-standard.md",
        ["security"],
    ),
    (
        "sec-vendor-security",
        1,
        BAMBOO,
        "Vendor Security Requirements",
        "en",
        "md",
        "sec-vendor-security.md",
        ["security", "managers"],
    ),
    (
        "sec-acceptable-use",
        1,
        BAMBOO,
        "Acceptable Use Policy",
        "en",
        "md",
        "sec-acceptable-use.md",
        ["all-staff"],
    ),
    (
        "ops-returns-process",
        1,
        BAMBOO,
        "Customer Returns Process",
        "en",
        "md",
        "ops-returns-process.md",
        ["all-staff"],
    ),
    (
        "ops-shipping-sla-danang",
        1,
        BAMBOO,
        "Delivery Service Levels - Da Nang Hub",
        "en",
        "md",
        "ops-shipping-sla-danang.md",
        ["all-staff"],
    ),
    (
        "pub-uk-holiday-entitlement",
        1,
        BAMBOO,
        "Holiday entitlement (GOV.UK)",
        "en",
        "html",
        "pub-uk-holiday-entitlement.html",
        ["all-staff"],
    ),
    (
        "it-service-desk-faq",
        1,
        BAMBOO,
        "Câu hỏi thường gặp về IT / IT Service Desk FAQ",
        "mixed",
        "md",
        "it-service-desk-faq.md",
        ["all-staff"],
    ),
    (
        "lotus-expense-policy",
        1,
        LOTUS,
        "Quy định công tác phí - Lotus Retail",
        "vi",
        "md",
        "lotus-expense-policy.md",
        ["all-staff"],
    ),
    (
        "lotus-remote-work",
        1,
        LOTUS,
        "Chính sách làm việc từ xa - Lotus Retail",
        "vi",
        "md",
        "lotus-remote-work.md",
        ["all-staff"],
    ),
    (
        "lotus-password-standard",
        1,
        LOTUS,
        "Lotus Retail Password Standard",
        "en",
        "md",
        "lotus-password-standard.md",
        ["all-staff"],
    ),
]

# v1 questions by number (q001 = 1): (group index, alternative) for new documents that
# restate the answer, and types gained from new distractors.
EXTRA_EVIDENCE: dict[int, list[tuple[int, Quote]]] = {
    14: [(0, ("it-service-desk-faq", "passwords must be at least 14 characters long"))],
    15: [(0, ("it-service-desk-faq", "Tài khoản bị khóa 15 phút sau 10 lần đăng nhập sai"))],
    30: [(0, ("it-service-desk-faq", "mật khẩu phải dài tối thiểu 14 ký tự"))],
    32: [
        (0, ("ops-cold-chain-sop", "giữ trong khoảng 2 đến 8 độ C")),
        (0, ("ops-coldstore-binh-duong", "Buồng lạnh được duy trì từ 2 đến 8 độ C")),
    ],
}
EXTRA_TYPES: dict[int, list[str]] = {
    1: [NEAR],  # the news digest announces new meal allowances without the amount
    21: [NEAR],  # Da Nang hub service levels use the same wording
    25: [NEAR],  # the Labour Code (12 days) and GOV.UK (28 days) state other entitlements
    31: [NEAR],  # Da Nang hub express delivery
}


def _carried_over(
    number: int, question: tuple[str, list[str], dict[str, Any], str, list[Group], str | None]
) -> tuple[str, list[str], dict[str, Any], str, list[Group], str | None]:
    language, types, principal, text, groups, answer = question
    groups = [list(group) for group in groups]
    for index, quote in EXTRA_EVIDENCE.get(number, []):
        groups[index].append(quote)
    return language, types + EXTRA_TYPES.get(number, []), principal, text, groups, answer


# (language, types, principal, question, evidence groups, reference answer)
QUESTIONS: list[tuple[str, list[str], dict[str, Any], str, list[Group], str | None]] = [
    *(_carried_over(n, q) for n, q in enumerate(v1.QUESTIONS, start=1)),
    # Overtime, training, travel: versions, statutory limits and a stale news digest
    (
        "vi",
        [VI, VERSION, NEAR],
        STAFF,
        "Theo quy định của công ty, mỗi người lao động được làm thêm tối đa bao nhiêu giờ trong một tháng?",
        [[("hr-overtime-policy", "không quá 25 giờ trong một tháng")]],
        "Không quá 25 giờ trong một tháng (và không quá 180 giờ trong một năm).",
    ),
    (
        "en",
        [X],
        STAFF,
        "What is the minimum overtime pay rate on a weekly rest day?",
        [[("hr-overtime-policy", "200% vào ngày nghỉ hằng tuần")]],
        "At least 200% of the normal wage rate.",
    ),
    (
        "vi",
        [VI, NEAR],
        STAFF,
        "Theo Bộ luật Lao động 2019, số giờ làm thêm của người lao động không được quá bao nhiêu giờ trong một năm?",
        [[("pub-vn-labour-code-working-time", "không quá 200 giờ trong 01 năm")]],
        "Không quá 200 giờ trong một năm, trừ một số ngành, nghề được làm đến 300 giờ.",
    ),
    (
        "vi",
        [VI, VERSION, NEAR],
        STAFF,
        "Đăng ký làm thêm giờ phải gửi trước ít nhất bao lâu?",
        [
            [
                (
                    "hr-overtime-policy",
                    "Người lao động đăng ký làm thêm giờ trên hệ thống nhân sự trước ít nhất 2 ngày làm việc",
                )
            ]
        ],
        "Trước ít nhất 2 ngày làm việc, và phải được trưởng bộ phận phê duyệt trên hệ thống.",
    ),
    (
        "en",
        [X],
        STAFF,
        "Can I take time off instead of overtime pay, and by when must it be used?",
        [[("hr-overtime-policy", "nghỉ bù thay cho tiền lương làm thêm giờ")]],
        "Yes, for weekday overtime: 1 hour off per overtime hour, used within 3 months.",
    ),
    (
        "vi",
        [VI, VERSION],
        STAFF,
        "Công ty hỗ trợ học phí tối đa bao nhiêu cho mỗi người lao động trong một năm?",
        [[("hr-training-policy", "tối đa 30 triệu đồng cho mỗi người lao động trong một năm")]],
        "Tối đa 30 triệu đồng mỗi năm.",
    ),
    (
        "en",
        [X, VERSION],
        STAFF,
        "If the company pays more than 20 million VND for my course, how long must I keep working there afterwards?",
        [[("hr-training-policy", "ít nhất 24 tháng sau khi hoàn thành khóa học")]],
        "At least 24 months after finishing the course.",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "Đề nghị đặt vé máy bay đi công tác phải gửi trước ngày khởi hành bao lâu?",
        [[("hr-travel-booking", "trước ngày khởi hành ít nhất 7 ngày")]],
        "Ít nhất 7 ngày trước ngày khởi hành.",
    ),
    (
        "en",
        [X],
        STAFF,
        "Who must approve a business trip abroad?",
        [[("hr-travel-booking", "Chuyến công tác nước ngoài phải được Tổng giám đốc phê duyệt")]],
        "The CEO (Tổng giám đốc), before tickets are booked.",
    ),
    # Benefits and conduct
    (
        "vi",
        [VI],
        STAFF,
        "Người lao động được tư vấn tâm lý miễn phí bao nhiêu buổi mỗi năm?",
        [[("hr-wellbeing-program", "tối đa 6 buổi mỗi năm")]],
        "Tối đa 6 buổi mỗi năm.",
    ),
    (
        "en",
        [X, NEAR],
        STAFF,
        "How much is the monthly sports allowance?",
        [[("hr-wellbeing-program", "phụ cấp thể thao 300.000 đồng mỗi tháng")]],
        "300,000 VND a month, paid with salary after submitting a receipt.",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "Giá trị quà tặng tối đa mà nhân viên được nhận từ đối tác mỗi lần là bao nhiêu?",
        [[("hr-code-of-conduct", "không quá 500.000 đồng mỗi lần")]],
        "Không quá 500.000 đồng mỗi lần, và không quá hai lần một năm từ cùng một đối tác.",
    ),
    (
        "en",
        [X],
        STAFF,
        "Within how many working days must a conflict of interest be declared?",
        [[("hr-code-of-conduct", "trong vòng 5 ngày làm việc kể từ khi phát sinh")]],
        "Within 5 working days of it arising, in the HR system.",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "Có thể báo cáo vi phạm quy tắc ứng xử một cách ẩn danh không?",
        [[("hr-code-of-conduct", "cho phép báo cáo ẩn danh")]],
        "Có, qua đường dây nóng đạo đức do một đơn vị độc lập vận hành.",
    ),
    # Restricted HR and manager documents
    (
        "vi",
        [VI, ACCESS],
        HR,
        "Bảng chấm công được chốt vào ngày nào hằng tháng?",
        [[("hr-payroll-calendar", "được chốt vào ngày 25 hằng tháng")]],
        "Ngày 25 hằng tháng.",
    ),
    (
        "vi",
        [VI, ACCESS, NONE],
        STAFF,
        "Bảng chấm công được chốt vào ngày nào hằng tháng?",
        [],
        None,
    ),
    (
        "vi",
        [VI, ACCESS],
        MANAGER,
        "Mức lương đề xuất vượt trần khung lương bao nhiêu phần trăm thì phải được Trưởng phòng Nhân sự phê duyệt?",
        [[("mgr-hiring-approval", "vượt quá 10% so với mức trần của khung lương")]],
        "Khi vượt quá 10% so với mức trần của khung lương.",
    ),
    (
        "vi",
        [VI, ACCESS, NONE],
        STAFF,
        "Mức lương đề xuất vượt trần khung lương bao nhiêu phần trăm thì phải được Trưởng phòng Nhân sự phê duyệt?",
        [],
        None,
    ),
    (
        "vi",
        [VI, ACCESS],
        MANAGER,
        "Trưởng phòng được phê duyệt khoản chi tối đa bao nhiêu?",
        [
            [
                (
                    "mgr-budget-delegation",
                    "Trưởng phòng được phê duyệt khoản chi tối đa 100 triệu đồng",
                )
            ]
        ],
        "Tối đa 100 triệu đồng.",
    ),
    (
        "en",
        [X, MULTI, ACCESS],
        MANAGER,
        "What is a department head's spending approval limit, and who must approve a new position outside the approved headcount?",
        [
            [
                (
                    "mgr-budget-delegation",
                    "Trưởng phòng được phê duyệt khoản chi tối đa 100 triệu đồng",
                )
            ],
            [
                (
                    "mgr-hiring-approval",
                    "ngoài định biên đã duyệt trong kế hoạch năm phải được Giám đốc khối phê duyệt",
                )
            ],
        ],
        "Up to 100 million VND; a new position outside the approved headcount needs the division director's approval.",
    ),
    (
        "vi",
        [VI, NONE],
        MANAGER,
        "Hạn mức phê duyệt chi tiêu của Tổng giám đốc là bao nhiêu?",
        [],
        None,
    ),
    # Cold chain and the Binh Duong cold store
    (
        "vi",
        [VI],
        STAFF,
        "Nhiệt độ thùng xe lạnh được ghi lại bao lâu một lần?",
        [[("ops-cold-chain-sop", "ghi lại nhiệt độ thùng xe mỗi 15 phút")]],
        "Mỗi 15 phút.",
    ),
    (
        "en",
        [X],
        STAFF,
        "How long before loading must a refrigerated truck be pre-cooled?",
        [[("ops-cold-chain-sop", "làm lạnh thùng xe trước khi xếp hàng ít nhất 30 phút")]],
        "At least 30 minutes, and loading starts only when the box is within 2 to 8 °C.",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "Nhiệt độ thùng xe lạnh ra ngoài dải cho phép quá bao lâu thì tài xế phải báo điều phối?",
        [[("ops-cold-chain-sop", "liên tục quá 20 phút")]],
        "Khi nhiệt độ ra ngoài dải cho phép liên tục quá 20 phút.",
    ),
    (
        "en",
        [X],
        STAFF,
        "How long are cold-chain temperature records kept?",
        [[("ops-cold-chain-sop", "lưu trên hệ thống trong 2 năm")]],
        "2 years.",
    ),
    (
        "vi",
        [VI, NEAR],
        STAFF,
        "Ở kho lạnh Bình Dương, nhân viên được làm việc liên tục trong buồng lạnh tối đa bao lâu?",
        [[("ops-coldstore-binh-duong", "làm việc liên tục trong buồng lạnh tối đa 2 giờ")]],
        "Tối đa 2 giờ, sau đó nghỉ ít nhất 15 phút tại khu vực ấm.",
    ),
    (
        "en",
        [X, NEAR],
        STAFF,
        "What protective equipment is needed to enter the cold rooms at the Binh Duong warehouse?",
        [[("ops-coldstore-binh-duong", "mặc áo giữ nhiệt, đeo găng tay cách nhiệt")]],
        "A thermal jacket, insulated gloves, a hard hat and non-slip safety shoes.",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "Kho lạnh Bình Dương bắt đầu hoạt động từ ngày nào?",
        [[("news-digest-2026-q3", "đi vào hoạt động từ ngày 15 tháng 8 năm 2026")]],
        "Từ ngày 15 tháng 8 năm 2026.",
    ),
    ("vi", [VI, NONE], STAFF, "Kho lạnh Bình Dương có bao nhiêu buồng lạnh?", [], None),
    # IT
    (
        "vi",
        [VI],
        STAFF,
        "Yêu cầu cài đặt phần mềm được IT service desk xử lý trong bao lâu?",
        [[("it-software-request", "xử lý yêu cầu cài đặt phần mềm trong vòng 3 ngày làm việc")]],
        "Trong vòng 3 ngày làm việc; phần mềm ngoài danh mục có thể cần thêm 5 ngày làm việc.",
    ),
    (
        "en",
        [X],
        STAFF,
        "Who approves a software licence that costs more than 10 million VND a year?",
        [[("it-software-request", "trên 10 triệu đồng mỗi năm phải được Giám đốc khối phê duyệt")]],
        "The division director (Giám đốc khối).",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "IT service desk làm việc vào giờ nào?",
        [[("it-service-desk-faq", "làm việc từ 8 giờ đến 18 giờ, thứ Hai đến thứ Sáu")]],
        "Từ 8 giờ đến 18 giờ, thứ Hai đến thứ Sáu; ngoài giờ, sự cố khẩn cấp báo qua số máy lẻ 1234.",
    ),
    (
        "en",
        [EN],
        STAFF,
        "Where can I reset my password myself?",
        [[("it-service-desk-faq", "self-service portal id.bambooharbor.example")]],
        "At the self-service portal id.bambooharbor.example, after multi-factor authentication.",
    ),
    # Second tenant: same questions as Bamboo Harbor ones, different answers
    (
        "vi",
        [VI, TENANT],
        LOTUS_STAFF,
        "Nhân viên được phụ cấp ăn uống bao nhiêu mỗi ngày khi đi công tác?",
        [[("lotus-expense-policy", "phụ cấp ăn uống 280.000 đồng")]],
        "280.000 đồng cho mỗi ngày công tác.",
    ),
    (
        "vi",
        [VI, TENANT],
        LOTUS_STAFF,
        "Nhân viên văn phòng được làm việc từ xa tối đa mấy ngày mỗi tuần?",
        [[("lotus-remote-work", "tối đa 3 ngày mỗi tuần")]],
        "Tối đa 3 ngày mỗi tuần.",
    ),
    (
        "en",
        [EN, TENANT],
        LOTUS_STAFF,
        "What is the minimum password length?",
        [[("lotus-password-standard", "at least 12 characters long")]],
        "At least 12 characters.",
    ),
    # Public documents: statutory rules next to company rules
    (
        "vi",
        [VI, NEAR],
        STAFF,
        "Theo Bộ luật Lao động 2019, người làm công việc trong điều kiện bình thường được nghỉ hằng năm bao nhiêu ngày?",
        [
            [
                (
                    "pub-vn-labour-code-working-time",
                    "12 ngày làm việc đối với người làm công việc trong điều kiện bình thường",
                )
            ]
        ],
        "12 ngày làm việc.",
    ),
    (
        "vi",
        [VI],
        STAFF,
        "Theo Bộ luật Lao động, giờ làm việc ban đêm được tính từ mấy giờ đến mấy giờ?",
        [[("pub-vn-labour-code-working-time", "từ 22 giờ đến 06 giờ sáng ngày hôm sau")]],
        "Từ 22 giờ đến 06 giờ sáng ngày hôm sau.",
    ),
    (
        "en",
        [X],
        STAFF,
        "Under the Vietnamese Labour Code, how many days off are given for Lunar New Year?",
        [[("pub-vn-labour-code-working-time", "Tết Âm lịch: 05 ngày")]],
        "5 days.",
    ),
    (
        "vi",
        [VI, MULTI, NEAR],
        STAFF,
        "Số ngày phép năm theo quy chế của công ty nhiều hơn mức của Bộ luật Lao động cho công việc bình thường bao nhiêu ngày?",
        [
            [("hr-leave-policy", "được nghỉ 14 ngày làm việc mỗi năm")],
            [
                (
                    "pub-vn-labour-code-working-time",
                    "12 ngày làm việc đối với người làm công việc trong điều kiện bình thường",
                )
            ],
        ],
        "Nhiều hơn 2 ngày: quy chế công ty cho 14 ngày, Bộ luật Lao động quy định 12 ngày.",
    ),
    (
        "en",
        [EN, NEAR],
        STAFF,
        "According to GOV.UK, how much paid annual leave must most workers on a 5-day week receive?",
        [[("pub-uk-holiday-entitlement", "must receive at least 28 days")]],
        "At least 28 days a year (5.6 weeks).",
    ),
    (
        "en",
        [EN],
        STAFF,
        "Under the GOV.UK guidance, how much notice does a worker give for 1 day of leave?",
        [[("pub-uk-holiday-entitlement", "a worker would give 3 days")]],
        "3 days' notice.",
    ),
    # Engineering and security runbooks with identical layouts
    (
        "en",
        [EN, ACCESS],
        ENGINEER,
        "What is the maximum replication lag allowed before promoting a database replica?",
        [[("eng-db-failover-runbook", "replication lag is below 30 seconds")]],
        "Below 30 seconds.",
    ),
    (
        "en",
        [EN, ACCESS, NONE],
        STAFF,
        "What is the maximum replication lag allowed before promoting a database replica?",
        [],
        None,
    ),
    (
        "vi",
        [X, ACCESS],
        ENGINEER,
        "Mục tiêu thời gian khôi phục (RTO) khi chuyển đổi dự phòng cơ sở dữ liệu là bao lâu?",
        [
            [
                (
                    "eng-db-failover-runbook",
                    "The recovery time objective (RTO) for a database failover is 15 minutes",
                )
            ]
        ],
        "15 phút; mục tiêu điểm khôi phục (RPO) là 1 phút dữ liệu.",
    ),
    (
        "en",
        [EN, ACCESS],
        ENGINEER,
        "How many worker tasks may the worker service be scaled to during a queue backlog?",
        [[("eng-queue-backlog-runbook", "up to a maximum of 20 tasks")]],
        "At most 20 tasks.",
    ),
    (
        "en",
        [EN, ACCESS],
        ENGINEER,
        "How long are messages kept in the dead-letter queue?",
        [[("eng-queue-backlog-runbook", "where they are kept for 14 days")]],
        "14 days.",
    ),
    (
        "en",
        [EN, ACCESS],
        ENGINEER,
        "How many days before expiry must a TLS certificate be rotated?",
        [[("eng-cert-rotation-runbook", "at least 30 days before they expire")]],
        "At least 30 days before expiry.",
    ),
    (
        "en",
        [EN, VERSION, ACCESS],
        ENGINEER,
        "How long are production database backups retained?",
        [[("eng-backup-restore", "Backups are retained for 35 days")]],
        "35 days.",
    ),
    (
        "vi",
        [X, VERSION, ACCESS],
        ENGINEER,
        "Bao lâu thì thử khôi phục bản sao lưu cơ sở dữ liệu một lần?",
        [[("eng-backup-restore", "A restore test is performed every month")]],
        "Mỗi tháng một lần.",
    ),
    (
        "en",
        [EN],
        STAFF,
        "What is the request limit per API key for the public tracking API?",
        [[("eng-api-rate-limits", "up to 100 requests per minute")]],
        "100 requests per minute, with short bursts of up to 200.",
    ),
    (
        "vi",
        [X],
        STAFF,
        "API theo dõi vận đơn trả về mã lỗi gì khi vượt giới hạn?",
        [[("eng-api-rate-limits", "rejected with HTTP status 429")]],
        "HTTP 429, kèm header Retry-After cho biết số giây phải chờ.",
    ),
    ("en", [EN, NONE], STAFF, "What is the rate limit for the internal admin API?", [], None),
    (
        "en",
        [EN, ACCESS],
        SECURITY,
        "How often is privileged access reviewed?",
        [[("sec-access-review-standard", "reviewed every month by the security team")]],
        "Every month, by the security team.",
    ),
    ("en", [EN, ACCESS, NONE], STAFF, "How often is privileged access reviewed?", [], None),
    (
        "en",
        [EN, ACCESS],
        SECURITY,
        "How quickly must a leaver's accounts be disabled?",
        [[("sec-access-review-standard", "all accounts must be disabled within 4 hours")]],
        "Within 4 hours.",
    ),
    (
        "en",
        [EN, ACCESS],
        MANAGER,
        "Which certification must a vendor that processes Restricted data hold?",
        [[("sec-vendor-security", "SOC 2 Type II report or ISO/IEC 27001")]],
        "A current SOC 2 Type II report or ISO/IEC 27001 certification.",
    ),
    (
        "en",
        [EN],
        STAFF,
        "Can I paste confidential data into a public AI chatbot?",
        [[("sec-acceptable-use", "must never be pasted into public AI chatbots")]],
        "No; only the company-approved AI assistant may be used for work tasks.",
    ),
    (
        "vi",
        [X, MULTI],
        STAFF,
        "Thông tin lương có được dán vào chatbot AI công cộng không?",
        [
            [("sec-data-classification", "Restricted data includes salary information")],
            [("sec-acceptable-use", "must never be pasted into public AI chatbots")],
        ],
        "Không. Thông tin lương là dữ liệu Restricted, và dữ liệu Confidential hoặc Restricted không bao giờ được dán vào chatbot AI công cộng.",
    ),
    # Operations
    (
        "en",
        [EN],
        STAFF,
        "Within how many days can customers return unwanted goods?",
        [[("ops-returns-process", "within 30 days of delivery")]],
        "Within 30 days of delivery, unused and in the original packaging.",
    ),
    (
        "vi",
        [X],
        STAFF,
        "Khách hàng được hoàn tiền trong bao lâu sau khi hàng trả về đạt kiểm tra?",
        [[("ops-returns-process", "within 5 working days after the inspection is passed")]],
        "Trong vòng 5 ngày làm việc.",
    ),
    (
        "en",
        [EN, NEAR],
        STAFF,
        "How long does standard delivery between Da Nang and Hanoi take?",
        [
            [
                (
                    "ops-shipping-sla-danang",
                    "Standard delivery between Da Nang and Hanoi or Ho Chi Minh City is completed within 36 hours",
                )
            ]
        ],
        "Within 36 hours.",
    ),
    (
        "vi",
        [X, NEAR],
        STAFF,
        "Giao hàng hỏa tốc giữa Đà Nẵng và TP.HCM mất bao lâu?",
        [[("ops-shipping-sla-danang", "completed within 18 hours")]],
        "Trong vòng 18 giờ.",
    ),
    # Near-miss unanswerable: the topic is covered, the asked fact is not
    (
        "vi",
        [VI, NONE],
        STAFF,
        "Làm thêm giờ vào ban đêm được trả thêm bao nhiêu phần trăm?",
        [],
        None,
    ),
    (
        "en",
        [EN, NONE],
        STAFF,
        "How many days of paid sick leave do employees get each year?",
        [],
        None,
    ),
]
