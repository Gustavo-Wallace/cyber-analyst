"""Optional: python -m benchmarks.semantic_quality --runtime PATH --model PATH.

Does not run under pytest. JSON output contains synthetic observations, no local paths.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from jsonschema.validators import validator_for

from cyber_analyst.ai import AIService, LlamaCppProvider, LlamaRuntime, LlamaServerClient
from cyber_analyst.analysis.exploratory import profile_dataset
from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.semantic import SemanticUnderstandingService, SemanticUnderstandingError
from benchmarks.semantic_cases import CASES, ORIGINAL, FOCUSED


class DiagnosticProvider:
    """Observa rejeições por tentativa sem alterar resposta, schema ou retries."""
    def __init__(self, provider):
        self.provider = provider
        self.rejections = []

    def generate_structured(self, messages, schema_name, schema, config):
        text = self.provider.generate_structured(messages, schema_name, schema, config)
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            self.rejections.append({'reason': 'invalid_json' if text else 'empty_content'})
        else:
            errors = list(validator_for(schema)(schema).iter_errors(value))
            if errors:
                self.rejections.append({'reason':'schema_mismatch', 'violations':[
                    {'path':list(error.absolute_path), 'validator':error.validator,
                     'message':error.message} for error in errors
                ]})
        return text


def score(case, result):
    columns = {column.name: column for column in result.columns}
    unknown = {'correct': 0, 'unnecessary': 0, 'invented_under_ambiguity': 0}
    def observe(actual, accepted):
        if actual == 'unknown':
            unknown['correct' if 'unknown' in accepted else 'unnecessary'] += 1
        elif 'unknown' in accepted and actual not in accepted:
            unknown['invented_under_ambiguity'] += 1
    observe(result.dataset_category, case.expected_category)
    for name, accepted in case.expected_column_semantics.items():
        if name in columns:
            observe(columns[name].semantic_type, accepted)
    return {
        'category_correct': int(result.dataset_category in case.expected_category),
        'columns_correct': sum(name in columns and columns[name].semantic_type in accepted for name, accepted in case.expected_column_semantics.items()),
        'columns_total': len(case.expected_column_semantics),
        'identifiers_correct': sum(name in columns and columns[name].is_identifier == expected for name, expected in case.expected_identifier_behavior.items()),
        'identifiers_total': len(case.expected_identifier_behavior),
        'unknown': unknown,
        'hallucinated_columns': len(set(columns) - set(case.expected_column_semantics)),
    }


def aggregate(records):
    good = [record['metrics'] for record in records if 'metrics' in record]
    totals = {key: sum(item[key] for item in good) for key in ('category_correct','columns_correct','identifiers_correct','hallucinated_columns')}
    # Failures remain in the denominators, never inflate accuracy by omission.
    totals.update(cases_total=len(records), failures=len(records)-len(good),
                  columns_total=sum(record['expected_columns'] for record in records),
                  identifiers_total=sum(record['expected_identifiers'] for record in records))
    totals['unknown'] = {key: sum(item['unknown'][key] for item in good) for key in ('correct','unnecessary','invented_under_ambiguity')}
    for label, numerator, denominator in (
        ('category_accuracy', 'category_correct', 'cases_total'),
        ('column_accuracy', 'columns_correct', 'columns_total'),
        ('identifier_accuracy', 'identifiers_correct', 'identifiers_total'),
    ):
        totals[label] = totals[numerator] / totals[denominator] if totals[denominator] else None
    return totals


def divergences(records):
    """Compare labels/identifiers; roles and self-reported confidence are not scored."""
    grouped = {}
    for record in records:
        grouped.setdefault(record['case'], []).append(record)
    return [name for name, rounds in grouped.items() if len({
        (record.get('error'), record.get('category'), tuple(
            (column['name'], column['semantic_type'], column['is_identifier'])
            for column in record.get('columns', [])
        )) for record in rounds
    }) > 1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--rounds', type=int, default=2, choices=(1,2))
    parser.add_argument('--focused', action='store_true', help='Only six final-adjustment cases, once each.')
    args = parser.parse_args()
    started = perf_counter()
    runtime = LlamaRuntime(args.runtime, args.model)
    records = []
    try:
        runtime.start()
        print(json.dumps({'runtime_ready': runtime.is_ready}), flush=True)
        provider = DiagnosticProvider(LlamaCppProvider(LlamaServerClient(runtime.base_url)))
        service = SemanticUnderstandingService(AIService(provider))
        with TemporaryDirectory(prefix='semantic-benchmark-') as directory:
            groups = [('benchmark', FOCUSED, 1)] if args.focused else [('original', ORIGINAL, 1), ('benchmark', CASES, args.rounds)]
            for group, cases, rounds in groups:
                for round_number in range(1, rounds+1):
                    for case in cases:
                        path = Path(directory) / (case.name+'.csv')
                        path.write_text(case.csv, encoding='utf-8')
                        dataset = load_csv(path)
                        profile = profile_dataset(dataset)
                        tick = perf_counter()
                        provider.rejections.clear()
                        record = {'group':group,'case':case.name,'round':round_number,
                                  'expected_columns':len(case.expected_column_semantics),
                                  'expected_identifiers':len(case.expected_identifier_behavior)}
                        try:
                            result = service.understand_dataset(dataset, profile)
                            record.update(category=result.dataset_category, columns=[asdict(c) for c in result.columns],
                                          metrics=score(case,result))
                        except SemanticUnderstandingError as exc:
                            record['error'] = str(exc)
                            cause = exc.__cause__
                            record['error_type'] = type(cause or exc).__name__
                            if hasattr(cause, 'reason'):
                                record['reason'] = cause.reason
                                record['attempts'] = cause.attempts
                        record['rejected_attempts'] = list(provider.rejections)
                        record['seconds'] = round(perf_counter()-tick,3)
                        records.append(record)
                        print(json.dumps(record,ensure_ascii=True),flush=True)
    finally:
        runtime.stop()
        print(json.dumps({'runtime_stopped':not runtime.has_process,'seconds_total':round(perf_counter()-started,3)}),flush=True)
    benchmark = [r for r in records if r['group']=='benchmark']
    print(json.dumps({'aggregate':aggregate(benchmark), 'divergent_cases':divergences(benchmark)}),flush=True)


if __name__ == '__main__':
    main()
