import csv
import sys
import numpy as np

def verify(csv_path):
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = list(csv.DictReader(f))
    
    print(f"Total rows: {len(reader)}")
    classes = {}
    for r in reader:
        c = r['cls']
        classes[c] = classes.get(c, 0) + 1
    print(f"Class counts: {classes}")

    # Check duplicate s2_margin
    margins = [float(r['s2_margin']) for r in reader]
    margin_strs = [f"{float(r['s2_margin']):.6f}" for r in reader]
    duplicates = [x for x in set(margin_strs) if margin_strs.count(x) > 1]
    print(f"Duplicate s2_margin (6 decimals): {len(duplicates)} duplicates found: {duplicates}")

    # Output A: Percentiles per class
    signals = ['s1_top1', 's2_margin', 's3_cov_top3', 's4_unknown', 's5_rare_cov_top3']
    print("\n=== OUTPUT A: PERCENTILES PER CLASS ===")
    print("metric\tclass\tmin\tp10\tmedian\tp90\tmax")
    for sig in signals:
        for c in ['IN', 'A', 'B', 'N']:
            vals = [float(r[sig]) for r in reader if r['cls'] == c]
            if not vals:
                continue
            # Using numpy linear interpolation (standard percentile)
            p_min = np.min(vals)
            p10 = np.percentile(vals, 10)
            p_med = np.median(vals)
            p90 = np.percentile(vals, 90)
            p_max = np.max(vals)
            print(f"{sig}\t{c}\t{p_min:.6f}\t{p10:.6f}\t{p_med:.6f}\t{p90:.6f}\t{p_max:.6f}")

    # Output D: Thresholds at 100% and 90% IN acceptance
    # In-scope: s1, s2, s3, s5 higher is better (accept if val >= threshold)
    # s4 unknown: lower is better (accept if val <= threshold)
    in_rows = [r for r in reader if r['cls'] == 'IN']
    oos_rows = [r for r in reader if r['cls'] != 'IN']
    
    print("\n=== OUTPUT D: THRESHOLDS & OOS REJECTION ===")
    for sig in ['s1_top1', 's3_cov_top3', 's4_unknown']:
        in_vals = [float(r[sig]) for r in in_rows]
        for acc in [1.0, 0.90]:
            if sig == 's4_unknown':
                # lower is better; threshold is percentile(acc * 100) or max for 100%
                # for 100% acceptance of IN: threshold = max(in_vals)
                # for 90% acceptance of IN: threshold = np.percentile(in_vals, 90)
                if acc == 1.0:
                    thresh = np.max(in_vals)
                else:
                    thresh = np.percentile(in_vals, 90)
                
                # OOS accepted if val <= thresh
                accepted_oos = [r for r in oos_rows if float(r[sig]) <= thresh]
                rejected_oos = [r for r in oos_rows if float(r[sig]) > thresh]
            else:
                # higher is better
                if acc == 1.0:
                    thresh = np.min(in_vals)
                else:
                    thresh = np.percentile(in_vals, 10)
                
                # OOS accepted if val >= thresh
                accepted_oos = [r for r in oos_rows if float(r[sig]) >= thresh]
                rejected_oos = [r for r in oos_rows if float(r[sig]) < thresh]
            
            rej_by_cls = {}
            for r in rejected_oos:
                rej_by_cls[r['cls']] = rej_by_cls.get(r['cls'], 0) + 1
            
            acc_ids = [r['id'] for r in accepted_oos]
            print(f"Signal: {sig} | IN Acceptance: {int(acc*100)}% | Thresh: {thresh:.6f}")
            print(f"  Rejected OOS counts: {rej_by_cls} (Total rejected: {len(rejected_oos)}/{len(oos_rows)})")
            print(f"  Accepted OOS count: {len(accepted_oos)} | IDs: {', '.join(acc_ids)}")

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/gate_signals_41449212218.csv'
    verify(path)
