"""Create the fixed dev/test split and save it to evals/splits.json.

Split by *filing*, not by question: every question about the same document
lands on the same side. Otherwise tuning on dev questions about, say, 3M's
2018 10-K would leak into test questions about the same pages.

Run once. The output is committed, so the split never changes afterwards.
"""
import json
import random
from collections import Counter, defaultdict

from filinglens import config
from filinglens.dataset import load_questions

SEED = 2026
TEST_TARGET = 50

questions = load_questions()
by_doc = defaultdict(list)
for q in questions:
    by_doc[q.doc_name].append(q)

docs = sorted(by_doc)
random.Random(SEED).shuffle(docs)

test_docs, test_count = [], 0
for doc in docs:
    if test_count >= TEST_TARGET:
        break
    test_docs.append(doc)
    test_count += len(by_doc[doc])

test_ids = sorted(q.id for d in test_docs for q in by_doc[d])
dev_ids = sorted(q.id for q in questions if q.id not in set(test_ids))

out = {"seed": SEED, "grouped_by": "doc_name", "dev": dev_ids, "test": test_ids}
config.EVALS_DIR.mkdir(exist_ok=True)
(config.EVALS_DIR / "splits.json").write_text(json.dumps(out, indent=1) + "\n")

for name, ids in [("dev", dev_ids), ("test", test_ids)]:
    qs = [q for q in questions if q.id in set(ids)]
    print(name, len(qs), "questions,", len({q.doc_name for q in qs}), "docs,",
          dict(Counter(q.question_type for q in qs)))
