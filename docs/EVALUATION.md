# Evaluation

Two scripts in `evaluation/` produce the numbers for the paper and the results slide.

## 1. Consistency checker: defect-injection benchmark

```bash
PYTHONPATH=backend python evaluation/defect_injection.py --seed 7 --json results.json
USE_TRANSFORMER_MODELS=true PYTHONPATH=backend python evaluation/defect_injection.py   # transformer ML layer
LLM_PROVIDER=openai LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... PYTHONPATH=backend python evaluation/defect_injection.py
```

For each brief in `evaluation/briefs/` the script generates a blueprint and then:

1. scores it **without** self-check repair (the *generator-only* baseline, i.e. "LLM-only plan" when an LLM provider is configured),
2. injects known defects: tests removed from 3 requirements, stories removed from 2 FRs, a paraphrased duplicate, a negated (contradicting) requirement and a vague requirement,
3. measures **detection recall** per defect type,
4. runs the full self-check loop and reports the repaired Blueprint Quality Score.

Result with the offline generator and lightweight ML layer (seeds 1, 2, 3 and 7 give the same recall):

| brief | reqs | BQS generator-only | BQS after injection | BQS after self-check | items auto-repaired |
|---|---|---|---|---|---|
| canteen | 17 | 94.4 | 74.8 | 89.0 | 12 |
| clinic | 14 | 93.6 | 65.7 | 84.8 | 12 |
| library | 13 | 98.5 | 73.4 | 91.2 | 12 |

Mean detection recall: missing test 1.00 · missing story 1.00 · duplicate 1.00 · contradiction 1.00 · vague wording 1.00.

**How to report this honestly.** These are *synthetic* defects made by simple edits (a deleted link, a paraphrase, an inserted negation), so they are deliberately easy to detect. The result shows that the checker and repair loop work end to end. It does **not** measure real-world accuracy or false-positive rate. For the paper, also:

- add 10 or more real briefs (public SRS documents from the **PURE** dataset work well) to `evaluation/briefs/`,
- hand-label genuine duplicates and contradictions in them and report **precision as well as recall**,
- compare lightweight against transformer mode, and an LLM-only plan against an LLM plan with self-check (the ablation on slide 5).

## 2. FR/NFR classifier on PROMISE NFR

```bash
python evaluation/train_classifier.py path/to/promise_nfr.arff   # or .csv
```

This reports 10-fold cross-validated precision, recall and F1 for the built-in lexicon baseline and for a TF-IDF + linear SVM (binary FR/NFR and the 12 PROMISE classes). It then saves the SVM to `backend/models/fr_nfr.joblib`, which the API loads automatically on its next start.

The dataset is not bundled: download the PROMISE NFR dataset (625 requirements from 15 projects) from the PROMISE repository or a Zenodo/Kaggle mirror. Cite the dataset in the paper.
