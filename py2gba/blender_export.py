"""Blender-facing helpers for py2gba integration.

This module keeps Python->GBA assembly export logic inside the py2gba package so
host tools (like Main.py) can stay thin and delegate all GBA transpile details.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

from py2gba.pygame_api import safe_symbol

RUNTIME_SCRIPT_BINDING_NAMES = frozenset(
	(
		"colliders",
		"collidersIds",
		"get_collider",
		"rigidBodies",
		"rigidBodiesIds",
		"get_rigidbody",
		"sim",
		"physics",
	)
)


def is_runtime_script_binding_name(name) -> bool:
	return isinstance(name, str) and (name in RUNTIME_SCRIPT_BINDING_NAMES)


def augment_runtime_physics_maps(runtime_globals, rigid_bodies_runtime, colliders_runtime, get_var_name_for_object):
	"""Populate mirror-runtime physics maps with exported-object aliases."""
	if not isinstance(rigid_bodies_runtime, dict):
		rigid_bodies_runtime = {}
	if not isinstance(colliders_runtime, dict):
		colliders_runtime = {}
	if not isinstance(runtime_globals, dict):
		return rigid_bodies_runtime, colliders_runtime
	try:
		bpy_mod = runtime_globals.get("bpy")
		if bpy_mod is not None and hasattr(bpy_mod, "data") and hasattr(bpy_mod.data, "objects"):
			synth_rb = {}
			synth_col = {}
			for ob in list(getattr(bpy_mod.data, "objects", []) or []):
				if not bool(getattr(ob, "exportOb", False)):
					continue
				key = ""
				try:
					key = str(get_var_name_for_object(ob))
				except Exception:
					key = ""
				name_key = str(getattr(ob, "name", "") or "")
				if bool(getattr(ob, "rigidBodyExists", False)):
					if key:
						synth_rb.setdefault(key, key)
					if name_key:
						synth_rb.setdefault(name_key, key if key else name_key)
						synth_rb.setdefault("_" + name_key, key if key else name_key)
				if bool(getattr(ob, "colliderExists", False)):
					col_val = (key + "Collider") if key else name_key
					if key:
						synth_col.setdefault(key, col_val)
					if name_key:
						synth_col.setdefault(name_key, col_val if col_val else name_key)
						synth_col.setdefault("_" + name_key, col_val if col_val else name_key)
			for k, v in synth_rb.items():
				rigid_bodies_runtime.setdefault(k, v)
			for k, v in synth_col.items():
				colliders_runtime.setdefault(k, v)
	except Exception:
		pass
	return rigid_bodies_runtime, colliders_runtime


def gbc_script_physics_prelude() -> str:
	"""Return gbc-py runtime compatibility prelude source."""
	return (
		'try:\n'
		'    rigidBodiesRaw = rigidBodiesIds\n'
		'except:\n'
		'    try:\n'
		'        rigidBodiesRaw = rigidBodies\n'
		'    except:\n'
		'        rigidBodiesRaw = {}\n'
		'try:\n'
		'    collidersRaw = collidersIds\n'
		'except:\n'
		'    try:\n'
		'        collidersRaw = colliders\n'
		'    except:\n'
		'        collidersRaw = {}\n'
		'rigidBodies = {}\n'
		'colliders = {}\n'
		'for k, v in (list(rigidBodiesRaw.items()) if isinstance(rigidBodiesRaw, dict) else []):\n'
		'    if not ((k in rigidBodies) and (rigidBodies.get(k) is not None) and (v is None)):\n'
		'        rigidBodies[k] = v\n'
		'    if isinstance(k, str) and k.startswith("_") and len(k) > 1:\n'
		'        k2 = k[1:]\n'
		'        if (k2 not in rigidBodies) or (rigidBodies.get(k2) is None):\n'
		'            rigidBodies[k2] = v\n'
		'for k, v in (list(collidersRaw.items()) if isinstance(collidersRaw, dict) else []):\n'
		'    if not ((k in colliders) and (colliders.get(k) is not None) and (v is None)):\n'
		'        colliders[k] = v\n'
		'    if isinstance(k, str) and k.startswith("_") and len(k) > 1:\n'
		'        k2 = k[1:]\n'
		'        if (k2 not in colliders) or (colliders.get(k2) is None):\n'
		'            colliders[k2] = v\n'
		'def _gbc_norm_key(_name):\n'
		'    try:\n'
		'        s = str(_name)\n'
		'    except:\n'
		'        return ""\n'
		'    s = s.lstrip("_").lower()\n'
		'    out = ""\n'
		'    for ch in s:\n'
		'        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or (ch == "_"):\n'
		'            out += ch\n'
		'    return out\n'
		'def _gbc_lookup_handle(_dict, _name):\n'
		'    if not isinstance(_dict, dict):\n'
		'        return None\n'
		'    if _name in _dict:\n'
		'        direct_exact = _dict[_name]\n'
		'        if direct_exact is not None:\n'
		'            return direct_exact\n'
		'    if isinstance(_name, str):\n'
		'        if _name.startswith("_"):\n'
		'            direct = _dict.get(_name[1:])\n'
		'            if direct is not None:\n'
		'                return direct\n'
		'        else:\n'
		'            direct = _dict.get("_" + _name)\n'
		'            if direct is not None:\n'
		'                return direct\n'
		'        name_norm = _gbc_norm_key(_name)\n'
		'        for k, v in list(_dict.items()):\n'
		'            if not isinstance(k, str):\n'
		'                continue\n'
		'            k_norm = _gbc_norm_key(k)\n'
		'            if k_norm == name_norm or k_norm.endswith("_" + name_norm) or k_norm.endswith(name_norm):\n'
		'                return v\n'
		'    return None\n'
		'class _GbcLookupDict(dict):\n'
		'    def __getitem__(self, _name):\n'
		'        if dict.__contains__(self, _name):\n'
		'            return dict.__getitem__(self, _name)\n'
		'        val = _gbc_lookup_handle(self, _name)\n'
		'        return val\n'
		'    def get(self, _name, _default = None):\n'
		'        if dict.__contains__(self, _name):\n'
		'            return dict.get(self, _name, _default)\n'
		'        val = _gbc_lookup_handle(self, _name)\n'
		'        if val is None:\n'
		'            return _default\n'
		'        return val\n'
		'    def __contains__(self, _name):\n'
		'        if dict.__contains__(self, _name):\n'
		'            return True\n'
		'        return _gbc_lookup_handle(self, _name) is not None\n'
		'rigidBodies = _GbcLookupDict(rigidBodies)\n'
		'colliders = _GbcLookupDict(colliders)\n'
		'class _GbcPhysicsSimCompat:\n'
		'    def __init__(self):\n'
		'        self._lin_vel = {}\n'
		'        self._ang_vel = {}\n'
		'        self._rb_pos = {}\n'
		'        self._rb_rot = {}\n'
		'    def _key(self, handle):\n'
		'        try:\n'
		'            if handle is None:\n'
		'                return "__none__"\n'
		'            return str(handle)\n'
		'        except:\n'
		'            return "__unknown__"\n'
		'    def set_linear_velocity(self, rigidBody, vel, wakeUp = True):\n'
		'        try:\n'
		'            vx = float(vel[0])\n'
		'            vy = float(vel[1])\n'
		'        except:\n'
		'            vx = 0.0\n'
		'            vy = 0.0\n'
		'        self._lin_vel[self._key(rigidBody)] = [vx, vy]\n'
		'    def get_linear_velocity(self, rigidBody):\n'
		'        return list(self._lin_vel.get(self._key(rigidBody), [0.0, 0.0]))\n'
		'    def set_angular_velocity(self, rigidBody, angVel, wakeUp = True):\n'
		'        try:\n'
		'            self._ang_vel[self._key(rigidBody)] = float(angVel)\n'
		'        except:\n'
		'            self._ang_vel[self._key(rigidBody)] = 0.0\n'
		'    def get_angular_velocity(self, rigidBody):\n'
		'        return float(self._ang_vel.get(self._key(rigidBody), 0.0))\n'
		'    def set_rigid_body_position(self, rigidBody, pos, wakeUp = True):\n'
		'        try:\n'
		'            self._rb_pos[self._key(rigidBody)] = [float(pos[0]), float(pos[1])]\n'
		'        except:\n'
		'            self._rb_pos[self._key(rigidBody)] = [0.0, 0.0]\n'
		'    def get_rigid_body_position(self, rigidBody):\n'
		'        return list(self._rb_pos.get(self._key(rigidBody), [0.0, 0.0]))\n'
		'    def set_rigid_body_rotation(self, rigidBody, rot, wakeUp = True):\n'
		'        try:\n'
		'            self._rb_rot[self._key(rigidBody)] = float(rot)\n'
		'        except:\n'
		'            self._rb_rot[self._key(rigidBody)] = 0.0\n'
		'    def get_rigid_body_rotation(self, rigidBody):\n'
		'        return float(self._rb_rot.get(self._key(rigidBody), 0.0))\n'
		'    def __getattr__(self, _name):\n'
		'        if isinstance(_name, str) and _name.startswith("get_"):\n'
		'            return (lambda *args, **kwargs: None)\n'
		'        return (lambda *args, **kwargs: 0)\n'
		'try:\n'
		'    sim = sim\n'
		'except:\n'
		'    try:\n'
		'        sim = physics\n'
		'    except:\n'
		'        sim = _GbcPhysicsSimCompat()\n'
		'if sim is None:\n'
		'    sim = _GbcPhysicsSimCompat()\n'
		'if not hasattr(sim, "set_linear_velocity"):\n'
		'    sim = _GbcPhysicsSimCompat()\n'
		'def _js13k_gbc_resolve_rb_handle(_rb):\n'
		'    try:\n'
		'        if isinstance(_rb, str):\n'
		'            h = _gbc_lookup_handle(rigidBodies, _rb)\n'
		'            if h is not None:\n'
		'                return h\n'
		'    except:\n'
		'        pass\n'
		'    return _rb\n'
		'if hasattr(sim, "get_rigid_body_position") and not getattr(sim, "_js13k_gbc_get_rbpos_safe", False):\n'
		'    _js13k_gbc_orig_get_rigid_body_position = sim.get_rigid_body_position\n'
		'    def _js13k_gbc_get_rigid_body_position_safe(rigidBody):\n'
		'        rb_resolved = _js13k_gbc_resolve_rb_handle(rigidBody)\n'
		'        pos = None\n'
		'        try:\n'
		'            pos = _js13k_gbc_orig_get_rigid_body_position(rb_resolved)\n'
		'        except:\n'
		'            pos = None\n'
		'        if (pos is None) and (rb_resolved is not rigidBody):\n'
		'            try:\n'
		'                pos = _js13k_gbc_orig_get_rigid_body_position(rigidBody)\n'
		'            except:\n'
		'                pos = None\n'
		'        try:\n'
		'            return [float(pos[0]), float(pos[1])]\n'
		'        except:\n'
		'            return [0.0, 0.0]\n'
		'    sim.get_rigid_body_position = _js13k_gbc_get_rigid_body_position_safe\n'
		'    sim._js13k_gbc_get_rbpos_safe = True\n'
		'if hasattr(sim, "set_linear_velocity") and not getattr(sim, "_js13k_gbc_flip_linvel_y", False):\n'
		'    _js13k_gbc_orig_set_linear_velocity = sim.set_linear_velocity\n'
		'    def _js13k_gbc_set_linear_velocity_flipy(rigidBody, vel, wakeUp = True):\n'
		'        try:\n'
		'            vx = vel[0]\n'
		'            vy = -vel[1]\n'
		'            vel2 = [vx, vy]\n'
		'        except:\n'
		'            vel2 = vel\n'
		'        return _js13k_gbc_orig_set_linear_velocity(rigidBody, vel2, wakeUp)\n'
		'    sim.set_linear_velocity = _js13k_gbc_set_linear_velocity_flipy\n'
		'    sim._js13k_gbc_flip_linvel_y = True\n'
		'if hasattr(sim, "get_linear_velocity") and hasattr(sim, "get_rigid_body_position") and not getattr(sim, "_js13k_gbc_get_linvel_safe", False):\n'
		'    _js13k_gbc_orig_get_linear_velocity = sim.get_linear_velocity\n'
		'    _js13k_gbc_prev_linvel_pos = {}\n'
		'    _js13k_gbc_prev_linvel_t = {}\n'
		'    def _js13k_gbc_get_linear_velocity_safe(rigidBody):\n'
		'        rigidBody = _js13k_gbc_resolve_rb_handle(rigidBody)\n'
		'        key = str(rigidBody)\n'
		'        vel = None\n'
		'        try:\n'
		'            vel = _js13k_gbc_orig_get_linear_velocity(rigidBody)\n'
		'        except:\n'
		'            vel = None\n'
		'        vx = 0.0\n'
		'        vy = 0.0\n'
		'        has_nonzero_vel = False\n'
		'        try:\n'
		'            vx = float(vel[0])\n'
		'            vy = float(vel[1])\n'
		'            has_nonzero_vel = (abs(vx) > 1e-6) or (abs(vy) > 1e-6)\n'
		'        except:\n'
		'            pass\n'
		'        try:\n'
		'            pos = sim.get_rigid_body_position(rigidBody)\n'
		'            px = float(pos[0])\n'
		'            py = float(pos[1])\n'
		'            try:\n'
		'                t_now = float(pygame.time.get_ticks()) * 0.001\n'
		'            except:\n'
		'                t_now = None\n'
		'            prev_pos = _js13k_gbc_prev_linvel_pos.get(key)\n'
		'            prev_t = _js13k_gbc_prev_linvel_t.get(key)\n'
		'            _js13k_gbc_prev_linvel_pos[key] = [px, py]\n'
		'            _js13k_gbc_prev_linvel_t[key] = t_now\n'
		'            if (not has_nonzero_vel) and (prev_pos is not None) and (t_now is not None) and (prev_t is not None):\n'
		'                dt = t_now - prev_t\n'
		'                if dt > 1e-6:\n'
		'                    vx = (px - float(prev_pos[0])) / dt\n'
		'                    vy = (py - float(prev_pos[1])) / dt\n'
		'        except:\n'
		'            pass\n'
		'        return [vx, vy]\n'
		'    sim.get_linear_velocity = _js13k_gbc_get_linear_velocity_safe\n'
		'    sim._js13k_gbc_get_linvel_safe = True\n'
		'rigidbodies = rigidBodies\n'
		'physics = sim\n'
		'try:\n'
		'    PyRapier2d = PyRapier2d\n'
		'except:\n'
		'    PyRapier2d = None\n'
		'if PyRapier2d is None:\n'
		'    class _GbcPyRapier2dCompat:\n'
		'        Simulation = _GbcPhysicsSimCompat\n'
		'    PyRapier2d = _GbcPyRapier2dCompat()\n'
		'get_rigidbody = (lambda name : _gbc_lookup_handle(rigidBodies, name))\n'
		'get_collider = (lambda name : _gbc_lookup_handle(colliders, name))\n'
	)


def normalize_gb_script_code(code: str, is_init: bool, script_type: str = "", owner_name: str = ""):
	"""Normalize gba/gbc script source before py2gba compilation."""
	if not code:
		return code
	code2 = code
	prefix = ""
	if script_type == "gbc-py":
		# Normalize common direct-lookup patterns to tolerant helpers first.
		# This avoids KeyError in toolchains that still expose plain dicts.
		code2 = re.sub(r"\bcolliders\s*\[\s*this\s*\.\s*id\s*\]", "get_collider(this.id)", code2)
		code2 = re.sub(r"\brigidBodies\s*\[\s*this\s*\.\s*id\s*\]", "get_rigidbody(this.id)", code2)
		# Local gbc-py scripts can use this.id to refer to the Blender object name.
		if owner_name and owner_name != "__world__":
			code2 = re.sub(r"\bthis\s*\.\s*id\b", repr(owner_name), code2)
		prefix += gbc_script_physics_prelude()
	uses_ticks = bool(re.search(r"pygame\s*\.\s*time\s*\.\s*get_ticks\s*\(\s*\)", code2, flags=re.IGNORECASE))
	if uses_ticks:
		code2 = re.sub(
			r"pygame\s*\.\s*time\s*\.\s*get_ticks\s*\(\s*\)",
			"js13k_get_ticks()",
			code2,
			flags=re.IGNORECASE,
		)
		if is_init:
			prefix += (
				"global __js13k_ticks\n"
				"__js13k_ticks = 0\n"
				"def js13k_get_ticks():\n"
				"    return __js13k_ticks\n"
			)
		else:
			# Keep a monotonic millisecond-ish counter for update scripts.
			prefix += (
				"global __js13k_ticks\n"
				"try:\n"
				"    __js13k_ticks += 16\n"
				"except:\n"
				"    __js13k_ticks = 0\n"
				"def js13k_get_ticks():\n"
				"    return __js13k_ticks\n"
			)
	if prefix:
		code2 = prefix + code2
	return code2


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
				dst_member = None
				if owner_name:
					if target_path.startswith("this."):
						dst_member = target_path.split(".", 1)[1]
					else:
						dst_member = "__local_" + safe_symbol(target_path)
				value = stmt.value
				if isinstance(value, ast.Call) and resolve_name(value.func) == "pygame.Surface" and len(value.args) >= 1:
					size = _parse_surface_size(value.args[0], resolve_name)
					if size is not None:
						ref = {"owner_name": owner_name, "member": None}
						if owner_name:
							ref["member"] = dst_member
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
				if isinstance(value, ast.Call):
					transform_name = resolve_name(value.func)
					if transform_name in {
						"pygame.transform.scale",
						"pygame.transform.smoothscale",
						"pygame.transform.rotozoom",
					}:
						src_node = value.args[0] if len(value.args) >= 1 else None
						src_ref = _resolve_surface_ref(src_node, owner_name, surface_refs) if src_node is not None else None
						if (
							owner_name
							and dst_member is not None
							and src_ref is not None
							and src_ref.get("member") is not None
						):
							op = {
								"op": "transform_surface_member",
								"owner_name": owner_name,
								"member": dst_member,
								"src_owner_name": src_ref.get("owner_name"),
								"src_member": src_ref.get("member"),
							}
							if transform_name in {"pygame.transform.scale", "pygame.transform.smoothscale"} and len(value.args) >= 2:
								size = _parse_surface_size(value.args[1], resolve_name)
								if size is not None:
									op["method"] = "smoothscale" if transform_name.endswith(".smoothscale") else "scale"
									op["size"] = size
									output["surface_ops"].append(op)
									surface_refs[target_path] = {"owner_name": owner_name, "member": dst_member}
									continue
							if transform_name == "pygame.transform.rotozoom" and len(value.args) >= 3:
								angle = _eval_number_node(value.args[1])
								scale = _eval_number_node(value.args[2])
								if angle is not None and scale is not None:
									op["method"] = "rotozoom"
									op["angle"] = float(angle)
									op["scale"] = float(scale)
									output["surface_ops"].append(op)
									surface_refs[target_path] = {"owner_name": owner_name, "member": dst_member}
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
