"""Train and evaluate the FR/NFR classifier on the PROMISE NFR dataset.

Download the dataset (625 labelled requirements, 15 projects) — e.g. the ARFF from
the PROMISE repository or the CSV mirror on Zenodo/Kaggle ("PROMISE_exp") — and run:

    python evaluation/train_classifier.py path/to/promise.(csv|arff)

CSV must have columns  RequirementText,_class_   (or text,label).
Labels: F (functional) and A, FT, L, LF, MN, O, PE, PO, SC, SE, US (non-functional).

Outputs 10-fold cross-validated precision/recall/F1 for
  (a) the built-in lexicon baseline and (b) TF-IDF + linear SVM,
and saves the SVM to backend/models/fr_nfr.joblib, which SPECForge loads automatically.
"""
import csv
import pathlib
import re
import sys

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.svm import LinearSVC

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))


def load(path: pathlib.Path) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    if path.suffix == ".arff":
        data = False
        for line in path.read_text(errors="replace").splitlines():
            if line.strip().lower() == "@data":
                data = True
                continue
            if data and line.strip():
                m = re.match(r"\s*\d+\s*,\s*'(.*)'\s*,\s*([A-Z]+)\s*$", line) or re.match(r"\s*'(.*)'\s*,\s*([A-Z]+)\s*$", line)
                if m:
                    texts.append(m.group(1).replace("\\'", "'"))
                    labels.append(m.group(2))
    else:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                t = row.get("RequirementText") or row.get("text")
                lab = row.get("_class_") or row.get("class") or row.get("label")
                if t and lab:
                    texts.append(t.strip())
                    labels.append(lab.strip())
    if not texts:
        sys.exit("No rows parsed — check the file format.")
    return texts, labels


def main():
    texts, labels = load(pathlib.Path(sys.argv[1]))
    binary = ["FR" if lab == "F" else "NFR" for lab in labels]
    print(f"{len(texts)} requirements · {binary.count('FR')} FR · {binary.count('NFR')} NFR\n")

    from app.services.nlp import classify_requirement

    base = [classify_requirement(t)[0] for t in texts]
    p, r, f, _ = precision_recall_fscore_support(binary, base, average="macro", zero_division=0)
    print(f"Lexicon baseline (FR vs NFR)   P={p:.3f} R={r:.3f} F1={f:.3f}")

    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1), LinearSVC(C=0.8, class_weight="balanced"))
    cv = StratifiedKFold(n_splits=10, shuffle=True, random_state=42)
    pred = cross_val_predict(model, texts, labels, cv=cv)
    pred_bin = ["FR" if x == "F" else "NFR" for x in pred]
    p, r, f, _ = precision_recall_fscore_support(binary, pred_bin, average="macro", zero_division=0)
    print(f"TF-IDF + SVM   (FR vs NFR)     P={p:.3f} R={r:.3f} F1={f:.3f}   (10-fold CV)\n")
    print("Per-class (12 PROMISE labels, 10-fold CV):")
    print(classification_report(labels, pred, zero_division=0))

    model.fit(texts, labels)
    out = pathlib.Path(__file__).resolve().parents[1] / "backend" / "models" / "fr_nfr.joblib"
    out.parent.mkdir(exist_ok=True)
    joblib.dump(model, out)
    print(f"Saved model → {out}  (copy into the image or mount at CLASSIFIER_PATH)")


if __name__ == "__main__":
    main()
