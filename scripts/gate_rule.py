#!/usr/bin/env python3
"""Stage 3.7c: pure refusal-gate decision function.

Evaluates refusal gate signals (s1_top1, s3_cov_top3, s4_unknown) against
preset parameters (t1, t3, k).
"""


def accept(s1, s3, s4, params):
    """Pure refusal-gate decision function.

    Accepts if:
      s1 >= params['t1'] and s3 >= params['t3'] and s4 <= params['k']
    """
    t1 = params["t1"]
    t3 = params["t3"]
    k = params["k"]
    return s1 >= t1 and s3 >= t3 and s4 <= k
