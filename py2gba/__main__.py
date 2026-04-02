"""CLI: py2gba input.py -o out.s --symbol NAME --kind init|update.

The current backend emits a valid Thumb symbol plus pygame ABI bridge stubs.
It is intentionally conservative: unsupported pygame calls are reported and can
optionally fail the build with --strict-pygame.
"""

import argparse
import sys
from pathlib import Path

from py2gba.pygame_api import (
	analyze_pygame_usage,
	build_pygame_abi_stubs,
	ordered_top_level_pygame_calls,
	safe_symbol,
)


def emit_stub(py_source: str, symbol_base: str, kind: str, strict_pygame: bool = False) -> str:
	base = safe_symbol(symbol_base)
	suffix = "init" if kind == "init" else "update"
	label = "%s_%s" % (base, suffix)
	used, supported, unsupported = analyze_pygame_usage(py_source)
	if strict_pygame and unsupported:
		raise ValueError(
			"Unsupported pygame API calls: " + ", ".join(sorted(unsupported))
		)
	lines = [
		"@ py2gba pygame-aware stub backend",
		"@ kind=%s symbol=%s" % (kind, label),
		"@ used pygame calls=%i supported=%i unsupported=%i"
		% (len(used), len(supported), len(unsupported)),
		"",
	]
	if supported:
		lines.append("@ supported pygame calls:")
		for name in sorted(supported):
			lines.append("@   - " + name)
		lines.append("")
	if unsupported:
		lines.append("@ unsupported pygame calls:")
		for name in sorted(unsupported):
			lines.append("@   - " + name)
		lines.append("")
	ordered_calls = ordered_top_level_pygame_calls(py_source)
	supported_ordered_calls = [name for name in ordered_calls if name in supported]
	if supported_ordered_calls:
		lines.append("@ emitted top-level pygame call shims:")
		for name in supported_ordered_calls:
			lines.append("@   - " + name)
		lines.append("")
	for line in py_source.splitlines():
		lines.append("@ " + line.replace("\t", "    "))
	lines += [
		"",
		"\t.global %s" % label,
		"\t.thumb_func",
		"%s:" % label,
	]
	for name in supported_ordered_calls:
		lines.append("\tbl\tpy2gba_%s" % safe_symbol(name.replace(".", "_")))
	lines += [
		"\tbx\tlr",
		"",
	]
	lines.extend(build_pygame_abi_stubs(supported))
	return "\n".join(lines) + "\n"


def main() -> int:
	p = argparse.ArgumentParser(description="Python to GBA Thumb assembly (pygame-aware stub)")
	p.add_argument("input", type=Path, help="Input .py file")
	p.add_argument("-o", "--output", type=Path, required=True, help="Output .s file")
	p.add_argument("--symbol", default="gba_export", help="Base symbol name (gets _init or _update)")
	p.add_argument("--kind", choices=("init", "update"), default="update")
	p.add_argument(
		"--strict-pygame",
		action="store_true",
		help="Fail if unsupported pygame API calls are detected",
	)
	args = p.parse_args()
	src = args.input.read_text(encoding="utf-8")
	try:
		asm = emit_stub(src, args.symbol, args.kind, strict_pygame=args.strict_pygame)
	except ValueError as exc:
		print("py2gba:", exc, file=sys.stderr)
		return 2
	args.output.write_text(asm, encoding="utf-8")
	return 0


if __name__ == "__main__":
	sys.exit(main())