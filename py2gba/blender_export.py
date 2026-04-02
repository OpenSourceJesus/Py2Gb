"""Blender-facing helpers for py2gba integration.

This module keeps Python->GBA assembly export logic inside the py2gba package so
host tools (like Main.py) can stay thin and delegate all GBA transpile details.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

from py2gba.pygame_api import safe_symbol


def _source_name(txt_block) -> str:
	source = str(txt_block)
	if isinstance(txt_block, str):
		return source
	return (
		getattr(txt_block, "filename", None)
		or getattr(txt_block, "filepath", None)
		or getattr(txt_block, "name", None)
		or source
	)


def py2gba_asm(
	py_code: str,
	tmp_dir: str,
	repo_root_dir: str,
	txt_block=None,
	symbol_base: str = "gba_export",
	kind: str = "update",
	python_executable: str = "python3",
) -> str:
	"""Transpile Python to ARM Thumb assembly via py2gba CLI/module."""
	py_script_path = str(Path(tmp_dir) / "TempGba.py")
	asm_script_path = py_script_path.replace(".py", ".s")
	Path(py_script_path).write_text(py_code, encoding="utf-8")
	py2gba_repo_dir = str(Path(repo_root_dir) / "Py2Gba")
	env = None
	if _which("py2gba"):
		cmd = [
			"py2gba",
			py_script_path,
			"-o",
			asm_script_path,
			"--symbol",
			symbol_base,
			"--kind",
			kind,
		]
	else:
		cmd = [
			python_executable,
			"-m",
			"py2gba",
			py_script_path,
			"-o",
			asm_script_path,
			"--symbol",
			symbol_base,
			"--kind",
			kind,
		]
		env = os.environ.copy()
		env["PYTHONPATH"] = py2gba_repo_dir + os.pathsep + env.get("PYTHONPATH", "")
	print(" ".join(cmd))
	try:
		subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
	except subprocess.CalledProcessError as exc:
		if txt_block:
			print(_source_name(txt_block) + f": py2gba error: {exc.stderr}")
		else:
			print("py2gba error:", exc.stderr, py_code)
		return ""
	return Path(asm_script_path).read_text(encoding="utf-8")


def _which(name: str) -> str | None:
	for directory in os.environ.get("PATH", "").split(os.pathsep):
		if not directory:
			continue
		candidate = Path(directory) / name
		if candidate.is_file() and os.access(str(candidate), os.X_OK):
			return str(candidate)
	return None


def _build_pygame_resolver(tree):
	pygame_aliases = {"pygame"}
	from_aliases = {}
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				if alias.name == "pygame":
					pygame_aliases.add(alias.asname or alias.name)
		elif isinstance(node, ast.ImportFrom):
			if node.module and (node.module == "pygame" or node.module.startswith("pygame.")):
				for alias in node.names:
					if alias.name == "*":
						continue
					from_aliases[alias.asname or alias.name] = node.module + "." + alias.name

	def resolve_name(node):
		if isinstance(node, ast.Name):
			if node.id in from_aliases:
				return from_aliases[node.id]
			if node.id in pygame_aliases:
				return "pygame"
			return None
		if isinstance(node, ast.Attribute):
			base = resolve_name(node.value)
			if base:
				return base + "." + node.attr
		return None

	return resolve_name


def _eval_number_node(node):
	if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
		return float(node.value)
	if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
		value = _eval_number_node(node.operand)
		return -value if value is not None else None
	return None


def _eval_vector2_node(node, resolve_name):
	if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 2:
		x = _eval_number_node(node.elts[0])
		y = _eval_number_node(node.elts[1])
		if x is not None and y is not None:
			return [x, y]
	if isinstance(node, ast.Call):
		name = resolve_name(node.func)
		if name in ("pygame.Vector2", "pygame.math.Vector2") and len(node.args) >= 2:
			x = _eval_number_node(node.args[0])
			y = _eval_number_node(node.args[1])
			if x is not None and y is not None:
				return [x, y]
	return None


def _eval_color_node(node, resolve_name):
	if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 3:
		r = _eval_number_node(node.elts[0])
		g = _eval_number_node(node.elts[1])
		b = _eval_number_node(node.elts[2])
		a = _eval_number_node(node.elts[3]) if len(node.elts) >= 4 else 255.0
		if r is not None and g is not None and b is not None and a is not None:
			return [int(round(r)), int(round(g)), int(round(b)), int(round(a))]
	if isinstance(node, ast.Call):
		name = resolve_name(node.func)
		if name == "pygame.Color" and len(node.args) >= 3:
			r = _eval_number_node(node.args[0])
			g = _eval_number_node(node.args[1])
			b = _eval_number_node(node.args[2])
			a = _eval_number_node(node.args[3]) if len(node.args) >= 4 else 255.0
			if r is not None and g is not None and b is not None and a is not None:
				return [int(round(r)), int(round(g)), int(round(b)), int(round(a))]
	return None


def _parse_builtin_circle_call(call_node, resolve_name):
	name = resolve_name(call_node.func)
	if name != "pygame.draw.circle" or len(call_node.args) < 4:
		return None
	surface_arg = call_node.args[0]
	if not isinstance(surface_arg, ast.Call) or resolve_name(surface_arg.func) != "pygame.display.get_surface":
		return None
	color = _eval_color_node(call_node.args[1], resolve_name)
	center = _eval_vector2_node(call_node.args[2], resolve_name)
	radius = _eval_number_node(call_node.args[3])
	width = _eval_number_node(call_node.args[4]) if len(call_node.args) >= 5 else 0.0
	if color is None or center is None or radius is None or width is None:
		return None
	center = [center[0], -center[1]]
	return {
		"center": [center[0], center[1]],
		"radius": max(0.0, float(radius)),
		"color": [
			max(0, min(255, color[0])),
			max(0, min(255, color[1])),
			max(0, min(255, color[2])),
			max(0, min(255, color[3])),
		],
		"width": max(0.0, float(width)),
	}


def _script_calls_pygame_quit(py_code: str):
	try:
		tree = ast.parse(py_code)
	except Exception:
		return False
	resolve_name = _build_pygame_resolver(tree)
	for node in ast.walk(tree):
		if isinstance(node, ast.Call) and resolve_name(node.func) == "pygame.quit":
			return True
	return False


def extract_builtin_script_info(py_code: str):
	output = {"uses_quit": False, "circle_ops": [], "only_builtin": True}
	try:
		tree = ast.parse(py_code)
	except Exception:
		output["only_builtin"] = False
		output["uses_quit"] = _script_calls_pygame_quit(py_code)
		return output
	resolve_name = _build_pygame_resolver(tree)
	for stmt in tree.body:
		if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
			continue
		if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Pass)):
			continue
		if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
			call_name = resolve_name(stmt.value.func)
			if call_name == "pygame.quit":
				output["uses_quit"] = True
				continue
			circle = _parse_builtin_circle_call(stmt.value, resolve_name)
			if circle is not None:
				output["circle_ops"].append(circle)
				continue
		output["only_builtin"] = False
	return output


def export_gba_py_assembly(
	script_entries: list[dict],
	gba_out_path: str,
	tmp_dir: str,
	repo_root_dir: str,
):
	"""Compile script entries and write combined .s next to gba_out_path.

	Each script entry is a dict with:
	  - code: str
	  - is_init: bool
	  - script_obj: original script object (or name string)
	  - symbol_hint: str
	"""
	init_asm_chunks = []
	update_asm_chunks = []
	script_count = 0
	init_quit = False
	update_quit = False
	init_draw_circles = []
	update_draw_circles = []
	builtin_only_quit = True
	sym_i = 0
	for entry in script_entries:
		script_txt = entry["code"]
		is_init = bool(entry["is_init"])
		script_obj = entry.get("script_obj")
		sym_hint = entry.get("symbol_hint", "script")
		script_count += 1
		builtin_info = extract_builtin_script_info(script_txt)
		uses_quit = bool(builtin_info["uses_quit"])
		if is_init and uses_quit:
			init_quit = True
		if (not is_init) and uses_quit:
			update_quit = True
		if is_init:
			init_draw_circles += builtin_info["circle_ops"]
		else:
			update_draw_circles += builtin_info["circle_ops"]
		if not builtin_info["only_builtin"]:
			builtin_only_quit = False
		sym_i += 1
		base = "gba_%s_%i" % (safe_symbol(sym_hint), sym_i)
		kind = "init" if is_init else "update"
		asm = py2gba_asm(
			script_txt,
			tmp_dir=tmp_dir,
			repo_root_dir=repo_root_dir,
			txt_block=script_obj,
			symbol_base=base,
			kind=kind,
		)
		if asm:
			if is_init:
				init_asm_chunks.append(asm)
			else:
				update_asm_chunks.append(asm)
	if init_asm_chunks or update_asm_chunks:
		base_path = os.path.splitext(os.path.abspath(gba_out_path))[0] + "_gba_py.s"
		header = "\t.syntax unified\n\t.cpu arm7tdmi\n\t.fpu softvfp\n\t.thumb\n\t.section .text\n"
		combined = header + "\n".join(init_asm_chunks + update_asm_chunks) + "\n"
		Path(base_path).write_text(combined, encoding="utf-8")
		print(
			"GBA Python→assembly export:",
			base_path,
			"(%i init + %i update chunk(s))" % (len(init_asm_chunks), len(update_asm_chunks)),
		)
		if init_quit or update_quit:
			print("Built-in bitmap ROM hook: pygame.quit() triggers BIOS soft reset (SWI 0x00).")
		if init_draw_circles:
			print("Built-in bitmap ROM hook: pygame.draw.circle() from init scripts is baked into the exported bitmap.")
		if update_draw_circles:
			print(
				"Built-in bitmap ROM hook: pygame.draw.circle() from update scripts is baked once at export time (static snapshot)."
			)
		if script_count > 0 and not builtin_only_quit:
			print(
				"Note: exported gba-py assembly is not auto-linked/called by the built-in bitmap ROM; "
				"link/invoke symbols in your own GBA runtime to execute scripts."
			)
	return {
		"script_count": script_count,
		"init_quit": init_quit,
		"update_quit": update_quit,
		"init_draw_circles": init_draw_circles,
		"update_draw_circles": update_draw_circles,
		"builtin_only_quit": builtin_only_quit,
	}
