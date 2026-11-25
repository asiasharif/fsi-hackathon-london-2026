"""PII redaction on the classifier: the detectors catch UK phone numbers, sort codes and the customer's name,
and leave transaction IDs, amounts and dates alone."""

import re

from utils.nodes import UK_PHONE, UK_SORT_CODE, pii_middleware


def test_detectors_catch_uk_phone_and_sort_code():
    assert re.search(UK_PHONE, "call me on 07700 900123")
    assert re.search(UK_PHONE, "or +44 7700 900123")
    assert re.search(UK_SORT_CODE, "sort code 12-34-56")


def test_detectors_ignore_case_data():
    for text in ["TX-5001", "2026-11-02T03:14", "£649.00", "CUST-101", "CMP-025"]:
        assert not re.search(UK_PHONE, text) and not re.search(UK_SORT_CODE, text), text


def test_customer_name_redaction_is_added_only_when_known():
    assert len(pii_middleware(None)) == 4
    assert len(pii_middleware("Priya Shah")) == 5
