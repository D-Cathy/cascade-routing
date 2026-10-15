"""Small pedagogical trace of the original core; no model inference or real labels.

Predictions and responses are synthetic. Tradeoff parameters are explicitly fixed,
not learned or calibrated. Run from repository root with PYTHONPATH=src.
"""
import json
from pathlib import Path
import numpy as np
from selection.cascade_router import CascadeRouter
from selection.quality_computer import BaseQualityComputer
from selection.cost_computer import BaseCostComputer


class IllustrativeQuality(BaseQualityComputer):
    def predict(self, questions, model_answers):
        values = []
        for answers in model_answers:
            q = np.array([.70, .85, .90])
            if answers[0] is not None:
                q[0] = .40
            if answers[1] is not None:
                q[1] = .86
            values.append(q)
        return np.array(values), [None] * len(questions)


class IllustrativeCost(BaseCostComputer):
    def predict(self, questions, model_answers):
        return np.tile([.10, .40, 1.0], (len(questions), 1))


router = CascadeRouter(IllustrativeQuality(), IllustrativeCost(),
                       ['ship', 'shore', 'cloud'], max_expected_cost=1.0,
                       strategies=[], force_order=True)
router.lambdas = [.5, .5, .5]
router.gamma = 0.0
answers = [None, None, None]
rows = []
for step in range(4):
    qualities, sigma = router.quality_computer.predict(['synthetic question'], [answers])
    costs = router.cost_computer.predict(['synthetic question'], [answers])
    next_model = router.predict(['synthetic question'], [answers])[0]
    rows.append({'step': step, 'answers': list(answers),
                 'predicted_quality': qualities[0].tolist(), 'cost': costs[0].tolist(),
                 'next_model': next_model,
                 'selected_answer_model': router.select_answer(['synthetic question'], [answers])[0]})
    if next_model is None:
        break
    answers[router.models.index(next_model)] = f'{next_model}: synthetic response'
result = {'scope': 'pedagogical synthetic example, not experiment or fitted baseline',
          'rows': rows, 'final_model': router.select_answer(['synthetic question'], [answers])[0]}
assert [row['next_model'] for row in rows] == ['ship', 'shore', None]
assert result['final_model'] == 'shore'
Path(__file__).with_name('native_trace.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
