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
	target: str = "gba",
	python_executable: str = "python3",
) -> str:
	"""Transpile Python to target assembly via py2gba CLI/module."""
	py_script_path = str(Path(tmp_dir) / "TempGba.py")
	asm_script_path = py_script_path.replace(".py", ".s")
	Path(py_script_path).write_text(py_code, encoding="utf-8")
	repo_path = Path(repo_root_dir)
	py2gba_repo_candidate = repo_path / "Py2Gb"
	if not py2gba_repo_candidate.exists():
		py2gba_repo_candidate = repo_path / "Py2Gba"
	py2gba_repo_dir = str(py2gba_repo_candidate)
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
			"--target",
			target,
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
			"--target",
			target,
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


def _attr_path(node):
	if isinstance(node, ast.Name):
		return node.id
	if isinstance(node, ast.Attribute):
		base = _attr_path(node.value)
		if base:
			return base + "." + node.attr
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


def _parse_surface_size(node, resolve_name):
	size = _eval_vector2_node(node, resolve_name)
	if size is None:
		return None
	w = max(1, int(round(float(size[0]))))
	h = max(1, int(round(float(size[1]))))
	return [w, h]


def _resolve_surface_ref(node, owner_name, refs):
	path = _attr_path(node)
	if not path:
		return None
	if path in refs:
		return refs[path]
	if owner_name and path.startswith("this."):
		member = path.split(".", 1)[1]
		return {"owner_name": owner_name, "member": member}
	return None


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


def _inject_gbc_runtime_physics_aliases(py_code: str) -> str:
	"""Expose host physics dictionaries/simulation for gbc-py scripts."""
	prelude = (
		'__js13k_runtime_globals = globals()\n'
		'rigidbodies = __js13k_runtime_globals.get("rigidBodiesIds", {})\n'
		'colliders = __js13k_runtime_globals.get("collidersIds", {})\n'
		'physics = __js13k_runtime_globals.get("sim", None)\n'
		'PyRapier2d = __js13k_runtime_globals.get("PyRapier2d", None)\n'
		'get_rigidbody = rigidbodies.get\n'
		'get_collider = colliders.get\n'
	)
	return prelude + (py_code or "")


def extract_builtin_script_info(py_code: str, owner_name: str | None = None):
	output = {"uses_quit": False, "circle_ops": [], "surface_ops": [], "only_builtin": True}
	try:
		tree = ast.parse(py_code)
	except Exception:
		output["only_builtin"] = False
		output["uses_quit"] = _script_calls_pygame_quit(py_code)
		return output
	resolve_name = _build_pygame_resolver(tree)
	surface_refs = {}
	if owner_name:
		surface_refs["this.surface"] = {"owner_name": owner_name, "member": "surface"}
	for stmt in tree.body:
		if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
			continue
		if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Pass)):
			continue
		if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
			target = stmt.targets[0]
			target_path = _attr_path(target)
			if target_path:
				value = stmt.value
				if isinstance(value, ast.Call) and resolve_name(value.func) == "pygame.Surface" and len(value.args) >= 1:
					size = _parse_surface_size(value.args[0], resolve_name)
					if size is not None:
						ref = {"owner_name": owner_name, "member": None}
						if owner_name:
							if target_path.startswith("this."):
								ref["member"] = target_path.split(".", 1)[1]
							else:
								ref["member"] = "__local_" + safe_symbol(target_path)
						surface_refs[target_path] = ref
						if ref["member"] is not None:
							output["surface_ops"].append(
								{
									"op": "create_surface_member",
									"owner_name": owner_name,
									"member": ref["member"],
									"size": size,
								}
							)
						continue
				src_ref = _resolve_surface_ref(value, owner_name, surface_refs)
				if src_ref is not None:
					surface_refs[target_path] = src_ref
					if owner_name and target_path.startswith("this."):
						dst_member = target_path.split(".", 1)[1]
						output["surface_ops"].append(
							{
								"op": "assign_surface_member",
								"owner_name": owner_name,
								"member": dst_member,
								"src_owner_name": src_ref.get("owner_name"),
								"src_member": src_ref.get("member"),
							}
						)
					continue
		if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
			call_name = resolve_name(stmt.value.func)
			if call_name == "pygame.quit":
				output["uses_quit"] = True
				continue
			fill_func = stmt.value.func
			if isinstance(fill_func, ast.Attribute) and fill_func.attr == "fill" and len(stmt.value.args) >= 1:
				surface_ref = _resolve_surface_ref(fill_func.value, owner_name, surface_refs)
				color = _eval_color_node(stmt.value.args[0], resolve_name)
				if surface_ref is not None and color is not None and surface_ref.get("member") is not None:
					output["surface_ops"].append(
						{
							"op": "fill_surface_member",
							"owner_name": surface_ref.get("owner_name"),
							"member": surface_ref.get("member"),
							"color": [
								max(0, min(255, color[0])),
								max(0, min(255, color[1])),
								max(0, min(255, color[2])),
								max(0, min(255, color[3])),
							],
						}
					)
					continue
			if call_name == "pygame.draw.circle" and len(stmt.value.args) >= 4:
				surface_ref = _resolve_surface_ref(stmt.value.args[0], owner_name, surface_refs)
				color = _eval_color_node(stmt.value.args[1], resolve_name)
				center = _eval_vector2_node(stmt.value.args[2], resolve_name)
				radius = _eval_number_node(stmt.value.args[3])
				width = _eval_number_node(stmt.value.args[4]) if len(stmt.value.args) >= 5 else 0.0
				if (
					surface_ref is not None
					and surface_ref.get("member") is not None
					and color is not None
					and center is not None
					and radius is not None
					and width is not None
				):
					output["surface_ops"].append(
						{
							"op": "draw_circle_surface_member",
							"owner_name": surface_ref.get("owner_name"),
							"member": surface_ref.get("member"),
							"center": [float(center[0]), float(center[1])],
							"radius": max(0.0, float(radius)),
							"color": [
								max(0, min(255, color[0])),
								max(0, min(255, color[1])),
								max(0, min(255, color[2])),
								max(0, min(255, color[3])),
							],
							"width": max(0.0, float(width)),
						}
					)
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
	surface_ops = []
	target = "gbc" if str(gba_out_path).lower().endswith(".gbc") else "gba"
	sym_i = 0
	for entry in script_entries:
		script_txt = entry["code"]
		compile_script_txt = _inject_gbc_runtime_physics_aliases(script_txt) if target == "gbc" else script_txt
		is_init = bool(entry["is_init"])
		script_obj = entry.get("script_obj")
		sym_hint = entry.get("symbol_hint", "script")
		script_count += 1
		builtin_info = extract_builtin_script_info(script_txt, owner_name=entry.get("owner_name"))
		uses_quit = bool(builtin_info["uses_quit"])
		if is_init and uses_quit:
			init_quit = True
		if (not is_init) and uses_quit:
			update_quit = True
		if is_init:
			init_draw_circles += builtin_info["circle_ops"]
		else:
			update_draw_circles += builtin_info["circle_ops"]
		surface_ops += builtin_info.get("surface_ops", [])
		if not builtin_info["only_builtin"]:
			builtin_only_quit = False
		sym_i += 1
		base = "gba_%s_%i" % (safe_symbol(sym_hint), sym_i)
		kind = "init" if is_init else "update"
		asm = py2gba_asm(
			compile_script_txt,
			tmp_dir=tmp_dir,
			repo_root_dir=repo_root_dir,
			txt_block=script_obj,
			symbol_base=base,
			kind=kind,
			target=target,
		)
		if asm:
			if is_init:
				init_asm_chunks.append(asm)
			else:
				update_asm_chunks.append(asm)
	if init_asm_chunks or update_asm_chunks:
		base_path = os.path.splitext(os.path.abspath(gba_out_path))[0] + "_gba_py.s"
		if target == "gbc":
			header = "; py2gba gbc export\n"
		else:
			header = "\t.syntax unified\n\t.cpu arm7tdmi\n\t.fpu softvfp\n\t.thumb\n\t.section .text\n"
		combined = header + "\n".join(init_asm_chunks + update_asm_chunks) + "\n"
		Path(base_path).write_text(combined, encoding="utf-8")
		print(
			("%s Python→assembly export:" % target.upper()),
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
		if surface_ops:
			print(
				"Built-in bitmap ROM hook: pygame.Surface member changes in gba-py scripts are baked into exported image surfaces."
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
		"surface_ops": surface_ops,
		"builtin_only_quit": builtin_only_quit,
	}
