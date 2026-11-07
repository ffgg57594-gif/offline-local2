#!/usr/bin/env python3
"""Stage 3.7c / K4b: pure refusal-gate decision function.

Evaluates refusal gate signals (s1_top1, s3_cov_top3, s4_unknown) against
preset parameters (t1, t3, k).

K4b adds a 1e-6 comparison epsilon so Python and Kotlin agree on values that
differ only by float rounding (for example s3 = 4/7 measured as 0.571429 in a
CSV versus 0.571428571428... in a JVM Double). The epsilon is applied to both
lower-bound comparisons; the upper bound on s4 is exact integer arithmetic.
"""

EPSILON = 1e-6


def accept(s1, s3, s4, params):
    """Pure refusal-gate decision function.

    Accepts if:
      s1 + EPSILON >= params['t1']
      and s3 + EPSILON >= params['t3']
      and s4 <= params['k']
    """
    t1 = params["t1"]
    t3 = params["t3"]
    k = params["k"]
    return s1 + EPSILON >= t1 and s3 + EPSILON >= t3 and s4 <= k
