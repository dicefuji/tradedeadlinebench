"""Cohen's kappa computation for judge validation.

Used to validate leakage and inference judges against human/second-LLM graders.
Both judge kappas must be >= 0.7 to proceed to Phase 6.
"""

from __future__ import annotations


def cohens_kappa(rater1: list[int], rater2: list[int]) -> float:
    """Compute Cohen's kappa for two raters on ordinal scale.

    Args:
        rater1: list of scores from rater 1
        rater2: list of scores from rater 2 (same length)

    Returns:
        kappa value in [-1, 1]. >= 0.7 is strong agreement.
    """
    if len(rater1) != len(rater2):
        raise ValueError("Rater lists must have same length")
    if not rater1:
        raise ValueError("Empty rater lists")

    n = len(rater1)
    all_categories = sorted(set(rater1) | set(rater2))

    if len(all_categories) <= 1:
        return 1.0

    # Build confusion matrix
    matrix: dict[tuple[int, int], int] = {}
    for cat1 in all_categories:
        for cat2 in all_categories:
            matrix[(cat1, cat2)] = 0

    for r1, r2 in zip(rater1, rater2):
        matrix[(r1, r2)] += 1

    # Observed agreement
    p_o = sum(matrix[(c, c)] for c in all_categories) / n

    # Expected agreement by chance
    p_e = 0.0
    for c in all_categories:
        row_sum = sum(matrix[(c, c2)] for c2 in all_categories) / n
        col_sum = sum(matrix[(c1, c)] for c1 in all_categories) / n
        p_e += row_sum * col_sum

    if p_e >= 1.0:
        return 1.0

    return (p_o - p_e) / (1 - p_e)
