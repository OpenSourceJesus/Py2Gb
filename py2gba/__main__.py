'''CLI: py2gba input.py -o out.s --symbol NAME --kind init|update

Emits a valid Thumb function NAME_init or NAME_update (bx lr) and embeds the source as comments.
Swap this for a real Python→assembly pipeline and keep the same CLI so Main.py stays unchanged.
'''

import argparse
import re
import sys
from pathlib import Path


def _safe_symbol(s: str) -> str:
	t = re.sub(r'[^0-9A-Za-z_]', '_', s)
	return t.strip('_') or 'sym'


def emit_stub(py_source: str, symbol_base: str, kind: str) -> str:
	base = _safe_symbol(symbol_base)
	suffix = 'init' if kind == 'init' else 'update'
	label = '%s_%s' % (base, suffix)
	lines = ['@ py2gba stub — generated Thumb placeholders; plug in your translator.', '@ kind=%s symbol=%s' % (kind, label), '']
	for line in py_source.splitlines():
		lines.append('@ ' + line.replace('\t', '    '))
	lines += [
		'',
		'\t.global %s' % label,
		'\t.thumb_func',
		'%s:' % label,
		'\tbx\tlr',
		'',
	]
	return '\n'.join(lines)


def main() -> int:
	p = argparse.ArgumentParser(description='Python → GBA Thumb assembly (stub)')
	p.add_argument('input', type=Path, help='Input .py file')
	p.add_argument('-o', '--output', type=Path, required=True, help='Output .s file')
	p.add_argument('--symbol', default='gba_export', help='Base symbol name (gets _init or _update)')
	p.add_argument('--kind', choices=('init', 'update'), default='update')
	args = p.parse_args()
	src = args.input.read_text(encoding='utf-8')
	asm = emit_stub(src, args.symbol, args.kind)
	args.output.write_text(asm, encoding='utf-8')
	return 0


if __name__ == '__main__':
	sys.exit(main())
