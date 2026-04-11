"""General-use GBC control-mode helpers for py2gba.

This module centralizes control-mode encoding/decoding so host tools can avoid
hardcoded string checks and share one compatibility layer.
"""

from __future__ import annotations

import ast

CONTROL_MODE_NONE = "none"
CONTROL_MODE_DPAD_LR = "input:dpad_lr"
CONTROL_MODE_DPAD_LR_A_JUMP = "input:dpad_lr+jump_a"
CONTROL_MODE_VX_FROM_VY_PREFIX = "motion:vx_from_vy_mul:"

_LEGACY_DPAD_LR = "dpad_lr"
_LEGACY_DPAD_LR_A_JUMP = "dpad_lr_a_jump"
_LEGACY_VX_FROM_VY = "vx_from_vy"
_LEGACY_VX_FROM_VY_PREFIX = "vx_from_vy_mul_"


def normalize_control_mode(control_mode: str | None) -> str:
	mode = str(control_mode or "").strip()
	if not mode or mode == CONTROL_MODE_NONE:
		return CONTROL_MODE_NONE
	if mode in (CONTROL_MODE_DPAD_LR, CONTROL_MODE_DPAD_LR_A_JUMP):
		return mode
	if mode == _LEGACY_DPAD_LR:
		return CONTROL_MODE_DPAD_LR
	if mode == _LEGACY_DPAD_LR_A_JUMP:
		return CONTROL_MODE_DPAD_LR_A_JUMP
	if mode == _LEGACY_VX_FROM_VY:
		return encode_vx_from_vy_mode(1) or CONTROL_MODE_NONE
	scale = decode_vx_from_vy_mode_scale(mode)
	if scale is not None:
		return encode_vx_from_vy_mode(scale) or CONTROL_MODE_NONE
	return CONTROL_MODE_NONE


def make_dpad_lr_mode(with_jump_a: bool = False) -> str:
	return CONTROL_MODE_DPAD_LR_A_JUMP if with_jump_a else CONTROL_MODE_DPAD_LR


def encode_vx_from_vy_mode(scale) -> str | None:
	if scale is None:
		return None
	try:
		value = float(scale)
	except Exception:
		return None
	n = int(round(value))
	if abs(value - float(n)) > 1e-6:
		return None
	n = max(-4, min(4, n))
	if n == 0:
		return None
	return CONTROL_MODE_VX_FROM_VY_PREFIX + str(n)


def decode_vx_from_vy_mode_scale(control_mode: str | None) -> int | None:
	mode = str(control_mode or "").strip()
	if not mode:
		return None
	if mode in (_LEGACY_VX_FROM_VY, CONTROL_MODE_VX_FROM_VY_PREFIX + "1"):
		return 1
	prefix = CONTROL_MODE_VX_FROM_VY_PREFIX
	legacy_prefix = _LEGACY_VX_FROM_VY_PREFIX
	if mode.startswith(prefix):
		raw = mode[len(prefix) :]
	elif mode.startswith(legacy_prefix):
		raw = mode[len(legacy_prefix) :]
	else:
		return None
	try:
		n = int(raw)
	except Exception:
		return None
	if n == 0:
		return None
	return max(-4, min(4, n))


def inspect_control_mode(control_mode: str | None) -> dict:
	normalized = normalize_control_mode(control_mode)
	scale = decode_vx_from_vy_mode_scale(normalized)
	return {
		"mode": normalized,
		"dpad_lr": normalized in (CONTROL_MODE_DPAD_LR, CONTROL_MODE_DPAD_LR_A_JUMP),
		"a_jump": normalized == CONTROL_MODE_DPAD_LR_A_JUMP,
		"vx_from_vy_scale": scale,
	}


def _literal_truthy_from_ast_node(node):
	try:
		val = ast.literal_eval(node)
	except Exception:
		return None
	if isinstance(val, bool):
		return val
	if isinstance(val, (int, float)):
		return bool(val)
	return None


def _walk_statically_reachable_stmts(stmts):
	for stmt in list(stmts or []):
		yield stmt
		if isinstance(stmt, ast.If):
			truth = _literal_truthy_from_ast_node(stmt.test)
			if truth is True:
				for inner in _walk_statically_reachable_stmts(stmt.body):
					yield inner
			elif truth is False:
				for inner in _walk_statically_reachable_stmts(stmt.orelse):
					yield inner


def _extract_rigidbody_name_expr(node):
	if isinstance(node, ast.Name):
		return ("name_ref", node.id)
	if isinstance(node, ast.Subscript):
		base = node.value
		if isinstance(base, ast.Name) and base.id in ("rigidBodies", "rigidBodiesIds"):
			key = None
			if isinstance(node.slice, ast.Constant):
				key = node.slice.value
			elif hasattr(ast, "Index") and isinstance(node.slice, ast.Index) and isinstance(node.slice.value, ast.Constant):
				key = node.slice.value.value
			if isinstance(key, str):
				return ("key", key)
	if isinstance(node, ast.Call):
		if isinstance(node.func, ast.Name) and node.func.id == "get_rigidbody" and len(node.args or []) >= 1:
			arg0 = node.args[0]
			if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
				return ("key", arg0.value)
	return (None, None)


def _ast_subscript_int_index(node):
	if not isinstance(node, ast.Subscript):
		return None
	slc = node.slice
	if isinstance(slc, ast.Constant) and isinstance(slc.value, int):
		return int(slc.value)
	if hasattr(ast, "Index") and isinstance(slc, ast.Index) and isinstance(slc.value, ast.Constant) and isinstance(slc.value.value, int):
		return int(slc.value.value)
	return None


def _ast_numeric_literal(node):
	try:
		v = ast.literal_eval(node)
	except Exception:
		return None
	if isinstance(v, (int, float)):
		return float(v)
	return None


def _is_same_rigidbody_ref(node, target_kind, target_value, aliases):
	rb_kind, rb_value = _extract_rigidbody_name_expr(node)
	if rb_kind == "name_ref" and rb_value in aliases:
		rb_kind, rb_value = aliases.get(rb_value, (rb_kind, rb_value))
	return (rb_kind == target_kind) and (rb_value == target_value)


def _is_get_linear_velocity_y_for_body(node, target_kind, target_value, aliases):
	if _ast_subscript_int_index(node) != 1:
		return False
	base = node.value if isinstance(node, ast.Subscript) else None
	if not isinstance(base, ast.Call):
		return False
	func = base.func
	if not (
		isinstance(func, ast.Attribute)
		and func.attr == "get_linear_velocity"
		and isinstance(func.value, ast.Name)
		and func.value.id in ("sim", "physics")
		and len(base.args or []) >= 1
	):
		return False
	return _is_same_rigidbody_ref(base.args[0], target_kind, target_value, aliases)


def _extract_get_linear_velocity_y_scale(node, target_kind, target_value, aliases):
	if _is_get_linear_velocity_y_for_body(node, target_kind, target_value, aliases):
		return 1.0
	if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
		inner = _extract_get_linear_velocity_y_scale(node.operand, target_kind, target_value, aliases)
		if inner is not None:
			return -float(inner)
	if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
		left_scale = _extract_get_linear_velocity_y_scale(node.left, target_kind, target_value, aliases)
		right_scale = _extract_get_linear_velocity_y_scale(node.right, target_kind, target_value, aliases)
		left_num = _ast_numeric_literal(node.left)
		right_num = _ast_numeric_literal(node.right)
		if left_scale is not None and right_num is not None:
			return float(left_scale) * float(right_num)
		if right_scale is not None and left_num is not None:
			return float(right_scale) * float(left_num)
	return None


def infer_control_mode_from_code(code: str, target_keys: set[str]):
	try:
		tree = ast.parse(code or "")
	except Exception:
		return None
	target_keys = {str(k) for k in (target_keys or set()) if isinstance(k, str) and k}
	if not target_keys:
		return None
	aliases = {}
	vel_expr_aliases = {}
	has_lr_key_tokens = ("pygame.K_LEFT" in str(code or "")) and ("pygame.K_RIGHT" in str(code or ""))
	has_a_key_token = "pygame.K_A" in str(code or "")
	for stmt in _walk_statically_reachable_stmts(getattr(tree, "body", [])):
		if isinstance(stmt, ast.Assign):
			rb_kind = None
			rb_value = None
			if stmt.value is not None:
				rb_kind, rb_value = _extract_rigidbody_name_expr(stmt.value)
			for target in list(stmt.targets or []):
				if isinstance(target, ast.Name):
					if rb_kind in ("name_ref", "key"):
						aliases[target.id] = (rb_kind, rb_value)
					else:
						aliases.pop(target.id, None)
					if isinstance(stmt.value, (ast.List, ast.Tuple)) and len(stmt.value.elts) >= 2:
						vel_expr_aliases[target.id] = stmt.value
					else:
						vel_expr_aliases.pop(target.id, None)
			continue
		if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
			rb_kind = None
			rb_value = None
			if stmt.value is not None:
				rb_kind, rb_value = _extract_rigidbody_name_expr(stmt.value)
			if rb_kind in ("name_ref", "key"):
				aliases[stmt.target.id] = (rb_kind, rb_value)
			else:
				aliases.pop(stmt.target.id, None)
			if isinstance(stmt.value, (ast.List, ast.Tuple)) and len(stmt.value.elts) >= 2:
				vel_expr_aliases[stmt.target.id] = stmt.value
			else:
				vel_expr_aliases.pop(stmt.target.id, None)
			continue
		if isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
			aliases.pop(stmt.target.id, None)
			vel_expr_aliases.pop(stmt.target.id, None)
			continue
		if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
			call = stmt.value
			func = call.func
			if not (isinstance(func, ast.Attribute) and func.attr == "set_linear_velocity"):
				continue
			if not (isinstance(func.value, ast.Name) and func.value.id in ("sim", "physics")):
				continue
			if len(call.args or []) < 2:
				continue
			rb_kind, rb_value = _extract_rigidbody_name_expr(call.args[0])
			if rb_kind == "name_ref" and rb_value in aliases:
				rb_kind, rb_value = aliases[rb_value]
			if rb_kind != "key" or not isinstance(rb_value, str) or rb_value not in target_keys:
				continue
			vel = call.args[1]
			if isinstance(vel, ast.Name):
				vel = vel_expr_aliases.get(vel.id, vel)
			if isinstance(vel, (ast.List, ast.Tuple)) and len(vel.elts) >= 2:
				s0 = _extract_get_linear_velocity_y_scale(vel.elts[0], rb_kind, rb_value, aliases)
				if s0 is not None:
					mode = encode_vx_from_vy_mode(s0)
					if mode is not None:
						return mode
			if has_lr_key_tokens:
				return make_dpad_lr_mode(has_a_key_token)
	return None


def infer_control_mode_from_scripts(update_codes: list[str], init_codes: list[str], target_keys: set[str]):
	for code in list(update_codes or []) + list(init_codes or []):
		mode = infer_control_mode_from_code(code, target_keys)
		if isinstance(mode, str) and mode:
			return mode
	return CONTROL_MODE_NONE
