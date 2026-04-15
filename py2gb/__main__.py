"""CLI: py2gba input.py -o out.s --symbol NAME --kind init|update.

This backend emits lightweight, target-specific assembly entrypoints.
It validates pygame usage but does not emit pygame ABI bridge stubs.
"""

import argparse
import sys
from pathlib import Path

from py2gba.pygame_api import (
	analyze_key_get_pressed_indices,
	analyze_pygame_usage,
	safe_symbol,
)


def emit_asm(
	py_source: str,
	symbol_base: str,
	kind: str,
	target: str = "gba",
	strict_pygame: bool = False,
) -> str:
	base = safe_symbol(symbol_base)
	suffix = "init" if kind == "init" else "update"
	label = "%s_%s" % (base, suffix)
	used, supported, unsupported = analyze_pygame_usage(py_source)
	key_used, key_supported, key_unsupported = analyze_key_get_pressed_indices(py_source)
	if strict_pygame and unsupported:
		raise ValueError(
			"Unsupported pygame API calls: " + ", ".join(sorted(unsupported))
		)
	if strict_pygame and key_unsupported:
		raise ValueError(
			"Unsupported pygame key constants for get_pressed indexing: "
			+ ", ".join(sorted(key_unsupported))
		)
	comment_prefix = ";" if target == "gbc" else "@"
	lines = [
		"%s py2gba lightweight backend" % comment_prefix,
		"%s target=%s kind=%s symbol=%s" % (comment_prefix, target, kind, label),
		"%s used pygame calls=%i supported=%i unsupported=%i"
		% (comment_prefix, len(used), len(supported), len(unsupported)),
		"%s used key constants=%i supported=%i unsupported=%i"
		% (comment_prefix, len(key_used), len(key_supported), len(key_unsupported)),
		"",
	]
	if supported:
		lines.append("%s supported pygame calls:" % comment_prefix)
		for name in sorted(supported):
			lines.append("%s   - %s" % (comment_prefix, name))
		lines.append("")
	if unsupported:
		lines.append("%s unsupported pygame calls:" % comment_prefix)
		for name in sorted(unsupported):
			lines.append("%s   - %s" % (comment_prefix, name))
		lines.append("")
	if key_supported:
		lines.append("%s supported get_pressed key constants:" % comment_prefix)
		for name in sorted(key_supported):
			lines.append("%s   - %s" % (comment_prefix, name))
		lines.append("")
	if key_unsupported:
		lines.append("%s unsupported get_pressed key constants:" % comment_prefix)
		for name in sorted(key_unsupported):
			lines.append("%s   - %s" % (comment_prefix, name))
		lines.append("")
	for line in py_source.splitlines():
		lines.append("%s %s" % (comment_prefix, line.replace("\t", "    ")))
	lines.append("")
	if target == "gbc":
		lines += [
			'SECTION "py2gba_script", ROM0',
			"GLOBAL %s" % label,
			"%s:" % label,
			"\tret",
			"",
		]
	else:
		lines += [
			"\t.global %s" % label,
			"\t.thumb_func",
			"%s:" % label,
			"\tbx\tlr",
			"",
		]
	return "\n".join(lines) + "\n"


def main() -> int:
	p = argparse.ArgumentParser(description="Python to GBA/GBC placeholder assembly")
	p.add_argument("input", type=Path, help="Input .py file")
	p.add_argument("-o", "--output", type=Path, required=True, help="Output .s file")
	p.add_argument("--symbol", default="gba_export", help="Base symbol name (gets _init or _update)")
	p.add_argument("--kind", choices=("init", "update"), default="update")
	p.add_argument("--target", choices=("gba", "gbc"), default="gba")
	p.add_argument(
		"--strict-pygame",
		action="store_true",
		help="Fail if unsupported pygame API calls/key constants are detected",
	)
	args = p.parse_args()
	src = args.input.read_text(encoding="utf-8")
	try:
		asm = emit_asm(
			src,
			args.symbol,
			args.kind,
			target=args.target,
			strict_pygame=args.strict_pygame,
		)
	except ValueError as exc:
		print("py2gba:", exc, file=sys.stderr)
		return 2
	args.output.write_text(asm, encoding="utf-8")
	return 0


if __name__ == "__main__":
	sys.exit(main())