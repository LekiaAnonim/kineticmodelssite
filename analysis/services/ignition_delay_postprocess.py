import csv
import json
import math
import re
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

# Large multi-line Cantera tracebacks can exceed the default 128 KB limit.
csv.field_size_limit(10 * 1024 * 1024)  # 10 MB


def _parse_float(raw_value):
    if raw_value in (None, ''):
        return math.nan
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return math.nan


def _is_valid_delay(row: dict) -> bool:
    if row.get('error'):
        return False
    delay = _parse_float(row.get('ignition_delay_s'))
    return math.isfinite(delay) and delay > 0.0


_CANTERA_HEADER_RE = re.compile(
    r'CanteraError thrown by (\S+):\s*(.+?)(?:\n|$)',
)


def _sanitize_error(raw: str) -> str:
    """Collapse multi-line Cantera tracebacks into a concise single line."""
    if '\n' not in raw:
        return raw
    match = _CANTERA_HEADER_RE.search(raw)
    if match:
        source, headline = match.group(1), match.group(2).strip()
        return f'CanteraError in {source}: {headline}'
    # Non-Cantera multi-line error: keep only the first non-blank line.
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and stripped != '*' * len(stripped):
            return stripped
    return raw.splitlines()[0].strip()


def sanitize_shard_csvs(run_dir: Path) -> dict:
    """Rewrite shard CSVs in-place, collapsing multi-line error fields.

    Returns a summary dict with counts of sanitized rows per shard.
    """
    csv_paths = shard_csv_paths(run_dir)
    total_sanitized = 0
    shard_details = {}

    for csv_path in csv_paths:
        rows = []
        sanitized_in_shard = 0

        with csv_path.open('r', newline='', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            for row in reader:
                raw_error = row.get('error', '')
                clean_error = _sanitize_error(raw_error)
                if clean_error != raw_error:
                    row['error'] = clean_error
                    sanitized_in_shard += 1
                rows.append(row)

        if sanitized_in_shard:
            # Atomic rewrite: write to a temp file then rename.
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=csv_path.parent, suffix='.tmp', prefix=csv_path.stem
            )
            try:
                with open(tmp_fd, 'w', newline='', encoding='utf-8') as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                Path(tmp_path).replace(csv_path)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise

        total_sanitized += sanitized_in_shard
        shard_details[csv_path.name] = sanitized_in_shard

    return {
        'shards_processed': len(csv_paths),
        'rows_sanitized': total_sanitized,
        'shard_details': shard_details,
    }


def shard_csv_paths(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob('ignition_delay_task_*.csv'))


def shard_metadata_paths(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob('ignition_delay_task_*.json'))


def load_shard_metadata(run_dir: Path) -> list[dict]:
    metadata = []
    for path in shard_metadata_paths(run_dir):
        with path.open('r', encoding='utf-8') as handle:
            metadata.append(json.load(handle))
    return metadata


def detect_missing_tasks(metadata: list[dict]) -> list[int]:
    if not metadata:
        return []

    task_counts = {item['task_count'] for item in metadata if 'task_count' in item}
    if len(task_counts) != 1:
        raise ValueError(f'Inconsistent task_count values across shard metadata: {sorted(task_counts)}')

    task_count = task_counts.pop()
    seen = {item['task_index'] for item in metadata if 'task_index' in item}
    return [task_index for task_index in range(task_count) if task_index not in seen]


def merge_shard_csvs(run_dir: Path, merged_csv_path: Path) -> dict:
    csv_paths = shard_csv_paths(run_dir)
    if not csv_paths:
        raise ValueError(f'No shard CSV files found in {run_dir}')

    fieldnames = None
    row_count = 0

    with merged_csv_path.open('w', newline='', encoding='utf-8') as out_handle:
        writer = None

        for csv_path in csv_paths:
            with csv_path.open('r', newline='', encoding='utf-8') as in_handle:
                reader = csv.DictReader(in_handle)
                if fieldnames is None:
                    fieldnames = list(reader.fieldnames or [])
                    writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
                    writer.writeheader()
                elif list(reader.fieldnames or []) != fieldnames:
                    raise ValueError(
                        f'CSV schema mismatch in {csv_path.name}: '
                        f'{reader.fieldnames} != {fieldnames}'
                    )

                for row in reader:
                    writer.writerow(row)
                    row_count += 1

    return {
        'csv_paths': [str(path) for path in csv_paths],
        'row_count': row_count,
        'fieldnames': fieldnames or [],
    }


def compute_condition_statistics(merged_csv_path: Path, output_csv_path: Path) -> dict:
    groups = defaultdict(list)

    with merged_csv_path.open('r', newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            group_key = (
                int(row['condition_index']),
                float(row['temperature_K']),
                float(row['pressure_atm']),
                float(row['phi']),
                row.get('ignition_target') or row.get('criterion', ''),
                row.get('ignition_type') or '',
            )
            groups[group_key].append(row)

    fieldnames = [
        'condition_index',
        'temperature_K',
        'pressure_atm',
        'phi',
        'ignition_target',
        'ignition_type',
        'model_count_total',
        'model_count_success',
        'model_count_failed',
        'success_fraction',
        'mean_ignition_delay_s',
        'std_ignition_delay_s',
        'cv_ignition_delay',
        'cv_percent',
        'min_ignition_delay_s',
        'max_ignition_delay_s',
    ]

    condition_count = 0

    with output_csv_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for key in sorted(groups):
            rows = groups[key]
            delays = [
                _parse_float(row['ignition_delay_s'])
                for row in rows
                if _is_valid_delay(row)
            ]

            model_count_total = len(rows)
            model_count_success = len(delays)
            model_count_failed = model_count_total - model_count_success
            success_fraction = (
                model_count_success / model_count_total
                if model_count_total else math.nan
            )

            if model_count_success:
                mean_delay = statistics.fmean(delays)
                min_delay = min(delays)
                max_delay = max(delays)
            else:
                mean_delay = math.nan
                min_delay = math.nan
                max_delay = math.nan

            if model_count_success >= 2 and mean_delay > 0.0:
                std_delay = statistics.stdev(delays)
                cv_delay = std_delay / mean_delay
                cv_percent = 100.0 * cv_delay
            else:
                std_delay = math.nan
                cv_delay = math.nan
                cv_percent = math.nan

            writer.writerow(
                {
                    'condition_index': key[0],
                    'temperature_K': key[1],
                    'pressure_atm': key[2],
                    'phi': key[3],
                    'ignition_target': key[4],
                    'ignition_type': key[5],
                    'model_count_total': model_count_total,
                    'model_count_success': model_count_success,
                    'model_count_failed': model_count_failed,
                    'success_fraction': success_fraction,
                    'mean_ignition_delay_s': mean_delay,
                    'std_ignition_delay_s': std_delay,
                    'cv_ignition_delay': cv_delay,
                    'cv_percent': cv_percent,
                    'min_ignition_delay_s': min_delay,
                    'max_ignition_delay_s': max_delay,
                }
            )
            condition_count += 1

    return {'condition_count': condition_count}