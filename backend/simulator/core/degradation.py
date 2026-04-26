from __future__ import annotations

import math
from collections.abc import Mapping

from .component import Component
from ..schema import COMPONENT_IDS


def compute_cross_factors(
    components: Mapping[str, Component],
    couplings_cfg: Mapping,
) -> dict[str, float]:
    """Return per-target cross multipliers from a consistent health snapshot."""
    threshold = float(couplings_cfg.get("critical_threshold", 0.4))
    pair_cap = float(couplings_cfg.get("pair_product_cap", math.inf))
    matrix = couplings_cfg.get("matrix", {})

    active_edges: dict[tuple[str, str], float] = {}
    for source, targets in matrix.items():
        if components[source].H <= threshold:
            for target, multiplier in targets.items():
                active_edges[(source, target)] = float(multiplier)

    for source, targets in matrix.items():
        for target in targets:
            forward = (source, target)
            reverse = (target, source)
            if source >= target or forward not in active_edges or reverse not in active_edges:
                continue
            product = active_edges[forward] * active_edges[reverse]
            if product > pair_cap:
                scale = math.sqrt(pair_cap / product)
                active_edges[forward] *= scale
                active_edges[reverse] *= scale

    factors = {component_id: 1.0 for component_id in COMPONENT_IDS}
    for (_source, target), multiplier in active_edges.items():
        factors[target] *= multiplier
    return factors


def compute_lambda(
    component: Component,
    drivers: Mapping[str, float],
    f_cross: float,
) -> float:
    """Compute lambda_i = lambda0_i * f_ext * f_int * f_cross, per day."""
    spec = component.spec
    f_ext = _variable_product(spec.get("ext_vars", ()), drivers)
    f_int = _maintenance_factor(component) * _life_factor(component)
    f_int *= _variable_product(spec.get("int_vars", ()), drivers)
    return component.lambda0_per_d * f_ext * f_int * float(f_cross)


def validate_components_config(components_cfg: Mapping) -> None:
    components = components_cfg["components"]
    for component_id in COMPONENT_IDS:
        spec = components[component_id]
        l_nom_d = float(spec["L_nom_d"])
        lambda0 = float(spec["lambda0_per_d"])
        # lambda0 is empirically calibrated against the simulator (driver and
        # cross-coupling effects shift it away from the analytic 0.9/target
        # baseline). We just require it to be positive and finite; the
        # calibration is documented in components.yaml's header comment.
        if not (math.isfinite(lambda0) and lambda0 > 0.0):
            raise ValueError(f"{component_id}: lambda0_per_d must be positive and finite")
        if l_nom_d <= 0:
            raise ValueError(f"{component_id}: L_nom_d must be positive")
        target = spec.get("first_failure_target_d")
        if target is not None and (not math.isfinite(float(target)) or float(target) <= 0):
            raise ValueError(f"{component_id}: first_failure_target_d must be positive when set")
        if "alpha_sigma" in spec:
            sigma = float(spec["alpha_sigma"])
            if not (0.0 < sigma < 1.0):
                raise ValueError(f"{component_id}: alpha_sigma must be in (0, 1)")
        if float(spec["tau_nom_d"]) <= 0:
            raise ValueError(f"{component_id}: tau_nom_d must be positive")
        for variable in (*spec.get("ext_vars", ()), *spec.get("int_vars", ())):
            if variable.get("enabled", True) is False:
                continue
            if float(variable["ref"]) <= 0:
                raise ValueError(f"{component_id}.{variable['name']}: ref must be positive")


def _maintenance_factor(component: Component) -> float:
    tau_nom = float(component.spec["tau_nom_d"])
    if math.isinf(tau_nom):
        return 1.0
    return (1.0 + component.tau_mant_d / tau_nom) ** float(component.spec["b_M"])


def _life_factor(component: Component) -> float:
    return (1.0 + component.L_d / float(component.spec["L_nom_d"])) ** float(component.spec["b_L"])


def _variable_product(variables: list[Mapping] | tuple[Mapping, ...], drivers: Mapping[str, float]) -> float:
    product = 1.0
    for variable in variables:
        if variable.get("enabled", True) is False:
            continue
        name = variable["name"]
        ref = float(variable["ref"])
        value = float(drivers[name])
        if name == "H":
            value = max(value, 1.0)
        if value < 0:
            raise ValueError(f"driver {name} must be non-negative")
        product *= (value / ref) ** float(variable["exp"])
    return product
