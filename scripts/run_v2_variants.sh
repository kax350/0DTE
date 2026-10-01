#!/bin/sh
# V2 ML robustness retrains (prereg §10 K15/K19-K22, §11 ablation), confirmatory windows only, sequential.
# Each run uses 4 LightGBM threads; running two at once oversubscribed the 4 cores (~15x slowdown).
cd "$(dirname "$0")/.." || exit 1
W=WF3,WF4,OOT,EXT_B
for v in "_corr080 --corr 0.80" "_corr090 --corr 0.90" "_roll3y --rolling3y" "_seed1 --seed-offset 1" \
         "_nomacro --drop-groups macro" "_top5 --topk 5 --topk-src A-LAG" "_top10 --topk 10 --topk-src A-LAG" \
         "_top20 --topk 20 --topk-src A-LAG"; do
  set -- $v
  tag=$1
  shift
  if [ -f "results/A-LAG$tag/EXT_B/meta.json" ]; then continue; fi
  python3 -W ignore scripts/run_walkforward.py --policy A-LAG --windows $W --end 2026-12-31 --tag "$tag" "$@" \
    > "logs/wf_A-LAG$tag.log" 2>&1
  echo "$(date +%H:%M) done $tag"
done
echo V2VARIANTS-ALL-DONE
