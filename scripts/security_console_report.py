#!/usr/bin/env python3

import json
import re
from pathlib import Path
from collections import defaultdict
import shutil
import argparse
import subprocess
import time
from typing import Optional

# ANSI colors (if terminal supports)
def supports_color():
    return shutil.get_terminal_size(fallback=(80, 24))[0] > 0 and True

COL = {
    'bold': '\033[1m',
    'red': '\033[31m',
    'yellow': '\033[33m',
    'green': '\033[32m',
    'cyan': '\033[36m',
    'reset': '\033[0m'
} if supports_color() else {k: '' for k in ['bold','red','yellow','green','cyan','reset']}

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / 'reports'
BANDIT_FILE = REPORTS_DIR / 'bandit_report.json'
OUT_JSON = REPORTS_DIR / 'security_console_report.json'

EXCLUDE_SEGMENTS = ('/boto3/', '/botocore/', '/build/', '/dist/')



def load_bandit():
    if not BANDIT_FILE.exists():
        return []
    data = json.loads(BANDIT_FILE.read_text(encoding='utf-8'))
    # Bandit may include 'results' list
    results = data.get('results') or []
    parsed = []
    for r in results:
        filename = r.get('filename')
        if not filename:
            continue
        # filter vendor files
        if any(seg in filename for seg in EXCLUDE_SEGMENTS):
            continue
        parsed.append({
            'file': filename,
            'line': r.get('line_number'),
            'test': r.get('test_name'),
            'issue_text': r.get('issue_text'),
            'severity': r.get('issue_severity'),
            'confidence': r.get('issue_confidence'),
        })
    return parsed


def run_pip_audit_on_requirements(req_path: Path, timeout: int = 8) -> Optional[dict]:
    """
    Run pip-audit against a requirements.txt file and return parsed JSON output.
    If pip-audit is not available or the run fails, return None.
    """
    if not req_path.exists():
        return None

    # Prefer the pip-audit CLI if available, otherwise try python -m pip_audit
    cmds = [
        ['pip-audit', '--format', 'json', '-r', str(req_path)],
        ['python3', '-m', 'pip_audit', '--format', 'json', '-r', str(req_path)],
    ]

    for cmd in cmds:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            # mark timeout in stderr-like structure so caller can report it
            return {'__error': f'pip-audit timeout after {timeout}s'}

        if proc.returncode == 0 or proc.stdout:
            try:
                return json.loads(proc.stdout)
            except Exception:
                # some versions might write to stderr
                try:
                    return json.loads(proc.stderr)
                except Exception:
                    return None
    return None


def collect_lambda_files():
    lambdas_dir = ROOT / 'lambdas'
    files = []
    if not lambdas_dir.exists():
        return files
    for p in lambdas_dir.rglob('*.py'):
        if any(seg in str(p) for seg in EXCLUDE_SEGMENTS):
            continue
        files.append(p)
    return files


def main():
    bandit_issues = load_bandit()

    per_file = defaultdict(lambda: {'bandit': []})

    for b in bandit_issues:
        per_file[b['file']]['bandit'].append(b)

    # severity counts
    severity_counts = defaultdict(int)
    for b in bandit_issues:
        sev = (b.get('severity') or 'UNDEFINED').upper()
        severity_counts[sev] += 1

    def render_bar(value, maximum, width=30, style='blocks'):
        if maximum <= 0:
            return ''
        frac = value / maximum
        filled = int(round(frac * width))
    
        # blocks-only style
        bar_filled = '█' * filled
        bar_empty = '░' * (width - filled)
        outer_l, outer_r = '|', '|'

        return f"{outer_l}{bar_filled}{bar_empty}{outer_r} {value}"

    files = collect_lambda_files()
    # We keep a file list for counts, but we no longer run heuristic scans per-file.

    # Run pip-audit per lambda that has a requirements.txt
    dep_vulns_by_lambda = {}
    total_dep_vulns = 0
    dep_severity_counts = defaultdict(int)
    lambdas_dir = ROOT / 'lambdas'
    if lambdas_dir.exists():
        for lam in lambdas_dir.iterdir():
            if not lam.is_dir():
                continue
            req = lam / 'requirements.txt'
            if not req.exists():
                continue
            pd = run_pip_audit_on_requirements(req)
            if not pd:
                dep_vulns_by_lambda[lam.name] = {'error': 'pip-audit not available or failed', 'vulnerabilities': []}
                continue
            # pip-audit JSON commonly is a list of dicts: {"name":"pkg","version":"x","vulns":[...]}.
            # Be defensive: accept list/dict and skip unexpected shapes.
            vulns = []
            pd_list = pd if isinstance(pd, list) else [pd]
            parse_error = False
            for pkg in pd_list:
                if not isinstance(pkg, dict):
                    # unexpected entry, skip
                    parse_error = True
                    continue
                name = pkg.get('name')
                version = pkg.get('version')
                # support different keys that may contain vulnerabilities
                vuln_entries = pkg.get('vulns') or pkg.get('vulnerabilities') or []
                if not isinstance(vuln_entries, list):
                    vuln_entries = []
                for v in vuln_entries:
                    if not isinstance(v, dict):
                        continue
                    sev = (v.get('severity') or 'UNKNOWN').upper()
                    vulns.append({'package': name, 'version': version, 'id': v.get('id'), 'fix': v.get('fix_version') or v.get('fixed_in'), 'severity': sev, 'details': v.get('details')})
                    dep_severity_counts[sev] += 1
                    total_dep_vulns += 1
            if parse_error and not vulns:
                # Mark that parsing had unexpected format but no vulnerabilities extracted
                dep_vulns_by_lambda[lam.name] = {'error': 'unexpected pip-audit output format', 'raw': pd, 'vulnerabilities': []}
                continue
            dep_vulns_by_lambda[lam.name] = {'error': None, 'vulnerabilities': vulns}

    # Build summary
    total_bandit = sum(len(v['bandit']) for v in per_file.values())
    total_heur = 0

    report_lines = []
    report_lines.append(f"{COL['bold']}{COL['cyan']}Security console report{COL['reset']}")
    report_lines.append(f"{COL['cyan']}{'=' * 30}{COL['reset']}")
    report_lines.append(f'Total files scanned (python under lambdas/): {len(files)}')
    report_lines.append(f'Total Bandit issues (filtered): {total_bandit}')
    report_lines.append('\n')

    # Severity summary
    # parse CLI args for style
    parser = argparse.ArgumentParser(add_help=False)
    # bar style is fixed to 'blocks' to keep output consistent
    parser.add_argument('--width', type=int, default=30)
    # capture only from sys.argv if main script
    import sys
    args, _ = parser.parse_known_args(sys.argv[1:])

    report_lines.append('Severity summary (Bandit):')
    max_sev = max(severity_counts.values()) if severity_counts else 0
    for sev in ['HIGH', 'MEDIUM', 'LOW', 'UNDEFINED']:
        count = severity_counts.get(sev, 0)
        color = COL['red'] if sev == 'HIGH' else (COL['yellow'] if sev == 'MEDIUM' else COL['green'])
        bar = render_bar(count, max_sev, width=args.width)
        report_lines.append(f"  {color}{sev:<9}{COL['reset']} : {bar}")
    report_lines.append('')

    # Totals visual bars
    total_max = max(max_sev, total_bandit, 1)
    report_lines.append('Totals visual:')
    report_lines.append(f"  Bandit issues : {render_bar(total_bandit, total_max, width=args.width)}")
    # include dependency vuln totals
    report_lines.append(f"  Dependency vulns: {render_bar(total_dep_vulns, total_max, width=args.width)}")
    report_lines.append('')
    report_lines.append('')

    for fname in sorted(per_file.keys()):
        data = per_file[fname]
        if not data['bandit'] and not data['heuristics']:
            continue
        report_lines.append(f'-- {fname} --')
        if data['bandit']:
            report_lines.append(f' Bandit issues: {len(data["bandit"])}')
            for b in data['bandit']:
                report_lines.append(f'  - line {b.get("line")}: [{b.get("severity")}/{b.get("confidence")}] {b.get("test")}: {b.get("issue_text")}')
        report_lines.append('')

    summary = {
        'total_files': len(files),
        'total_bandit': total_bandit,
        'total_heuristic': total_heur,
        'severity_summary': dict(severity_counts),
        'dependency_vulnerabilities': {
            'total': total_dep_vulns,
            'by_severity': dict(dep_severity_counts),
            'by_lambda': dep_vulns_by_lambda
        },
        'files': {k: v for k, v in per_file.items() if v['bandit'] or v['heuristics']}
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding='utf-8')

    # Print concise summary to console
    print('\n'.join(report_lines))
    print(f"\nReports written to: {OUT_JSON}")


if __name__ == '__main__':
    raise SystemExit(main())
