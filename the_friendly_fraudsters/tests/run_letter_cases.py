
import sys

from evals.test_sets import check_letter, letter_cases
from tests.letter_cases import state_for_case
from utils.customer_letter import write_customer_letter


def main(only: list[str]) -> int:
    cases = [c for c in letter_cases() if not only or c["letter_id"] in only]
    passed = 0
    for case in cases:
        out = write_customer_letter(state_for_case(case))
        quality, letter = out["letter_quality"], out["customer_letter"]
        problems = check_letter(letter, case)
        passed += not problems
        print(f"{case['letter_id']} {case['complaint_id']:8} {quality['letter_type']:24} source={quality['source']:16} "
              f"attempts={quality['attempts']} words={len(letter.split()):3}  {'PASS' if not problems else problems}")
        if only or problems or quality["source"] == "template_fallback":
            print(letter, "\n", quality, "\n", sep="")
    print(f"\nAsia's letter rules: {passed}/{len(cases)} letters pass")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
