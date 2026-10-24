"""Partmap CLI: project-scoped JSON in/out, no GUI or third-party packages."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys

# Also works under Python isolated mode (-I) when launched by the dispatcher.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tool_runtime as runtime

COMMANDS = ('read', 'write', 'validate', 'analyze', 'export')


def load(root, path):
    if not isinstance(path, str) or not path.lower().endswith('.json'):
        raise ValueError('Use a project-local .json file.')
    result = runtime.read_text(root, path, whole=True)
    return {key: value for key, value in result.items() if key != 'content'} | {'project': runtime.validate_parts(json.loads(result['content']))}


def analyze(project):
    nodes = project['nodes']; lookup = {n['id']: n for n in nodes}
    categories = {}; warnings = []; connections = []
    for node in nodes:
        category = categories.setdefault(node['category'], {'parts': 0, 'units': 0})
        category['parts'] += 1; category['units'] += node['quantity']
        if not node['ready']: warnings.append({'part': node['id'], 'issue': 'Not marked sourced/ready.'})
        for wire in node['connections']:
            connections.append({'source': node['id'], **wire})
            target = lookup[wire['target']]
            for part, pin in ((node, wire['local']), (target, wire['remote'])):
                if part['pins'] and pin not in {p['name'] for p in part['pins']}:
                    warnings.append({'part': part['id'], 'issue': 'Wiring references an unlisted pin: '+pin})
    return {'name': project['name'], 'part_count': len(nodes), 'total_units': sum(n['quantity'] for n in nodes),
            'ready_parts': sum(n['ready'] for n in nodes), 'categories': categories,
            'root_parts': [n['id'] for n in nodes if n['parent'] is None], 'connections': connections,
            'warnings': warnings, 'note': 'Structural inventory checks only; electrical compatibility and firmware are not verified.'}


def export(project, format):
    if format == 'json': return json.dumps(project, ensure_ascii=False, indent=2)
    if format == 'csv':
        stream = io.StringIO(newline=''); writer = csv.writer(stream)
        columns = ('id', 'name', 'category', 'quantity', 'parent', 'ready', 'model', 'voltage', 'interface', 'notes', 'firmware')
        writer.writerow(columns)
        for node in project['nodes']:
            values = [str(node.get(key, '') if node.get(key) is not None else '') for key in columns]
            writer.writerow(["'"+value if value.lstrip().startswith(('=', '+', '-', '@')) else value for value in values])
        return stream.getvalue()
    if format == 'markdown':
        clean = lambda value: str(value).replace('\r', ' ').replace('\n', ' ').replace('|', '\\|')
        lines = ['# '+clean(project['name']), '', '| ID | Part | Category | Quantity | Parent | Ready |', '| --- | --- | --- | --- | --- | --- |']
        for node in project['nodes']:
            lines.append('| '+' | '.join(clean(node.get(key) if node.get(key) is not None else '') for key in ('id', 'name', 'category', 'quantity', 'parent', 'ready'))+' |')
        lines += ['', '## Wiring and firmware', '']
        for node in project['nodes']:
            lines.append('### '+clean(node['name'])+' ('+clean(node['id'])+')')
            for key in ('model', 'voltage', 'interface', 'notes', 'firmware'):
                if node.get(key): lines.append('- '+key+': '+clean(node[key]))
            for wire in node['connections']: lines.append('- '+clean(wire['local'])+' → '+clean(wire['target'])+' / '+clean(wire['remote']))
            lines.append('')
        return '\n'.join(lines)
    raise ValueError('Export format must be json, csv, or markdown.')


def execute(root, command, args):
    if command not in COMMANDS or not isinstance(args, dict): raise ValueError('Unknown Partmap command or arguments.')
    allowed = {'path', 'project', 'expected_sha256'} if command == 'write' else {'path', 'format', 'output', 'expected_sha256'} if command == 'export' else {'path'}
    if set(args) - allowed: raise ValueError('Unsupported arguments for '+command+'.')
    path = args.get('path', 'parts.json')
    if command == 'write':
        if not isinstance(path, str) or not path.lower().endswith('.json'): raise ValueError('Use a .json file for Partmap projects.')
        project = runtime.validate_parts(args.get('project'))
        result = runtime.write_text(root, path, json.dumps(project, ensure_ascii=False, indent=2), args.get('expected_sha256', ''))
        # Read the saved bytes back; this receipt is based on disk contents.
        saved = load(root, result['path'])
        if saved['sha256'] != result['sha256']: raise ValueError('The project changed immediately after writing. Read it again.')
        return {**result, 'written': True, 'verified': True, 'part_count': len(saved['project']['nodes'])}
    result = load(root, path); project = result['project']
    if command == 'read': return result
    if command == 'validate': return {'valid': True, 'path': result['path'], 'sha256': result['sha256'], 'part_count': len(project['nodes'])}
    if command == 'analyze': return {'path': result['path'], 'sha256': result['sha256'], **analyze(project)}
    content = export(project, args.get('format', 'json'))
    if not args.get('output'): return {'format': args.get('format', 'json'), 'content': content}
    # Exporting onto the source would destroy the shared project file.
    if runtime.scoped(root, args['output']) == runtime.scoped(root, path): raise ValueError('Export to a separate file, not the source project JSON.')
    receipt = runtime.write_text(root, args['output'], content, args.get('expected_sha256', ''))
    if runtime.digest(runtime.scoped(root, receipt['path']).read_bytes()) != receipt['sha256']: raise ValueError('The export changed immediately after writing. Read it again.')
    return {**receipt, 'format': args.get('format', 'json'), 'written': True, 'verified': True}


class Parser(argparse.ArgumentParser):
    def error(self, message): raise ValueError(message)


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--workspace', required=True, help='Existing project folder; all file paths are scoped here.')
        parser.add_argument('--request', action='store_true', help='Read a dispatcher command/arguments JSON object from stdin.')
        sub = parser.add_subparsers(dest='command')
        for command in COMMANDS:
            item = sub.add_parser(command); item.add_argument('--path', default='parts.json')
            if command in ('write', 'export'): item.add_argument('--expected-sha256', default='')
            if command == 'write': item.add_argument('--input', default='-', help='Project JSON from stdin (-) or a project-local file.')
            if command == 'export':
                item.add_argument('--format', choices=('json', 'csv', 'markdown'), default='json')
                item.add_argument('--output', help='Project-local export file; omit to return content in stdout JSON.')
        options = parser.parse_args(argv)
        if not options.workspace.strip(): raise ValueError('Choose an existing project workspace.')
        root = Path(runtime.project_directory(options.workspace, Path(__file__).resolve().parent))
        if options.request:
            raw = sys.stdin.read(600001)
            if len(raw) > 600000: raise ValueError('CLI request is too large.')
            request = json.loads(raw)
            if not isinstance(request, dict) or set(request) != {'command', 'arguments'}: raise ValueError('Request needs command and arguments only.')
            command, args = request['command'], request['arguments']
        else:
            if not options.command: raise ValueError('Choose read, write, validate, analyze, or export.')
            command = options.command; args = {'path': options.path}
            if command in ('write', 'export'): args['expected_sha256'] = options.expected_sha256
            if command == 'write':
                raw = sys.stdin.read(300001) if options.input == '-' else runtime.read_text(root, options.input, whole=True)['content']
                if len(raw.encode('utf-8')) > 300000: raise ValueError('Input project must fit within 300 KB.')
                args['project'] = json.loads(raw)
            if command == 'export': args.update(format=options.format, output=options.output)
        print(json.dumps({'ok': True, 'command': command, 'result': execute(root, command, args)}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False)); return 1


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8'); sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
