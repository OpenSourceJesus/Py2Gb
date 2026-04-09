"""pygame API analysis and ABI stub emission for py2gba."""

from __future__ import annotations

import ast
import re

SUPPORTED_PYGAME_CALLS = {
	"pygame.init",
	"pygame.quit",
	"pygame.display.set_mode",
	"pygame.display.flip",
	"pygame.display.update",
	"pygame.event.get",
	"pygame.event.poll",
	"pygame.event.pump",
	"pygame.key.get_pressed",
	"pygame.key.get_mods",
	"pygame.time.Clock",
	"pygame.time.Clock.tick",
	"pygame.time.get_ticks",
	"pygame.draw.rect",
	"pygame.draw.circle",
	"pygame.draw.line",
	"pygame.draw.polygon",
	"pygame.transform.rotate",
	"pygame.transform.scale",
	"pygame.image.load",
	"pygame.mixer.Sound",
	"pygame.font.Font",
}

SUPPORTED_PYGAME_KEY_CONSTANTS = {
	"pygame.K_LEFT",
	"pygame.K_RIGHT",
	"pygame.K_UP",
	"pygame.K_DOWN",
	"pygame.K_A",
	"pygame.K_B",
	"pygame.K_START",
	"pygame.K_SELECT",
}


def safe_symbol(value: str) -> str:
	text = re.sub(r"[^0-9A-Za-z_]", "_", value)
	return text.strip("_") or "sym"


class _PygameCallAnalyzer(ast.NodeVisitor):
	def __init__(self) -> None:
		self._module_aliases = {"pygame"}
		self._from_aliases = {}
		self.calls = set()
		self.wildcard_import = False

	def visit_Import(self, node: ast.Import) -> None:
		for alias in node.names:
			if alias.name == "pygame":
				self._module_aliases.add(alias.asname or alias.name)
		self.generic_visit(node)

	def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
		if not node.module:
			return
		if node.module == "pygame" or node.module.startswith("pygame."):
			for alias in node.names:
				if alias.name == "*":
					self.wildcard_import = True
					continue
				as_name = alias.asname or alias.name
				self._from_aliases[as_name] = node.module + "." + alias.name
		self.generic_visit(node)

	def visit_Call(self, node: ast.Call) -> None:
		name = self._resolve_name(node.func)
		if name and name.startswith("pygame."):
			self.calls.add(name)
		self.generic_visit(node)

	def _resolve_name(self, node: ast.AST) -> str | None:
		if isinstance(node, ast.Name):
			if node.id in self._from_aliases:
				return self._from_aliases[node.id]
			if node.id in self._module_aliases:
				return "pygame"
			return None
		if isinstance(node, ast.Attribute):
			base = self._resolve_name(node.value)
			if base:
				return base + "." + node.attr
		return None


def analyze_pygame_usage(py_source: str) -> tuple[set[str], set[str], set[str]]:
	tree = ast.parse(py_source)
	analyzer = _PygameCallAnalyzer()
	analyzer.visit(tree)
	used = analyzer.calls
	supported = {name for name in used if name in SUPPORTED_PYGAME_CALLS}
	unsupported = used - supported
	return used, supported, unsupported


def analyze_key_get_pressed_indices(py_source: str) -> tuple[set[str], set[str], set[str]]:
	"""Analyze pygame key constants used to index get_pressed() results."""
	tree = ast.parse(py_source)
	resolver = _PygameCallAnalyzer()
	resolver.visit(tree)
	key_state_vars = set()
	used = set()

	for node in ast.walk(tree):
		if isinstance(node, ast.Assign):
			if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
				continue
			if not isinstance(node.value, ast.Call):
				continue
			if resolver._resolve_name(node.value.func) == "pygame.key.get_pressed":
				key_state_vars.add(node.targets[0].id)
		elif isinstance(node, ast.Subscript):
			is_key_state_index = False
			if isinstance(node.value, ast.Name) and node.value.id in key_state_vars:
				is_key_state_index = True
			elif isinstance(node.value, ast.Call):
				if resolver._resolve_name(node.value.func) == "pygame.key.get_pressed":
					is_key_state_index = True
			if not is_key_state_index:
				continue
			key_name = resolver._resolve_name(node.slice)
			if key_name and key_name.startswith("pygame.K_"):
				used.add(key_name)

	supported = {name for name in used if name in SUPPORTED_PYGAME_KEY_CONSTANTS}
	unsupported = used - supported
	return used, supported, unsupported


def ordered_top_level_pygame_calls(py_source: str) -> list[str]:
	"""Return ordered pygame call names used as top-level expression statements."""
	tree = ast.parse(py_source)
	analyzer = _PygameCallAnalyzer()
	analyzer.visit(tree)
	calls = []
	for stmt in tree.body:
		if not isinstance(stmt, ast.Expr):
			continue
		if not isinstance(stmt.value, ast.Call):
			continue
		name = analyzer._resolve_name(stmt.value.func)
		if name and name.startswith("pygame."):
			calls.append(name)
	return calls


def _abi_symbol(call_name: str) -> str:
	return "py2gba_" + safe_symbol(call_name.replace(".", "_"))


def build_pygame_abi_stubs(supported_calls: set[str]) -> list[str]:
	lines = []
	if not supported_calls:
		return lines
	lines.extend(
		[
			"@ pygame ABI weak stubs (replace by linking your real runtime)",
			"",
		]
	)
	for call_name in sorted(supported_calls):
		sym = _abi_symbol(call_name)
		body = ["\tbx\tlr"]
		if call_name == "pygame.quit":
			# Closest GBA equivalent to "quit": BIOS soft reset.
			body = ["\tswi\t0x00", "\tbx\tlr"]
		lines.extend(
			[
				"\t.weak %s" % sym,
				"\t.thumb_func",
				"%s:" % sym,
				*body,
				"",
			]
		)
	return lines