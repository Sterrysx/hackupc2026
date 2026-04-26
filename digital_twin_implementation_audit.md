# Auditoría: Spec vs. Implementación del Digital Twin HP Metal Jet S100

> Comparación punto por punto entre `digital_twin_hp_metal_jet_s100_spec.md` y el código realmente ejecutado en `backend/simulator/`.
>
> Archivos analizados: `backend/simulator/core/{simulator,degradation,component,weather}.py`, `backend/simulator/config/{components,couplings}.yaml`, `backend/simulator/generate.py`.

---

## 1. Contexto y objetivo

| Spec | Implementado |
|---|---|
| Simulación 24/7 durante **5 años** | ❌ La generación real es de **10 años reales (2016-2025)** + 10 años proyectados (2026-2035), no 5. Ver `backend/simulator/generate.py:23-26`. |
| Paso `Δt = 1 hora` | ❌ **El simulador trabaja en pasos de 1 día**, no 1 hora. Todas las unidades del config son `_d` (days). Ver `simulator.py:287` (`advance_time(1.0)`) y todas las claves `lambda0_per_d`, `tau_nom_d`, `L_nom_d`. |
| Optimizador de τ_nom | ⚠️ Existe el hook (RL `PrinterStepper` con `agent_action`), pero el barrido masivo de τ no es el flujo principal — hay PPO en `ml/03_rl+ssl`. |
| Restricción disponibilidad ≥ 95 % | ❌ No se calcula ni se aplica como restricción en el simulador. |

---

## 2. Datos verificados HP

No se modeliza el hardware HP literal. Solo viven en el simulador como **constantes de proceso** (`process_constants` en `components.yaml:1-15`): `T_fab=25`, `T_set=180`, `v=150`, `f_d=20`, `E_d=3`, `layer_thickness=50µm`, `P_B=0`. **No hay** modelado de potencia eléctrica, peso, número de toberas, redundancia 4×, etc. — todo eso es decorativo del documento.

---

## 3. Estructura del modelo

| Spec | Implementado |
|---|---|
| 3 subsistemas, 6 componentes (C1–C6) | ✅ `backend/simulator/schema.py` define `COMPONENT_IDS` y los componentes están en `components.yaml`. |
| Health Index $H_i \in [0,1]$ | ✅ `Component.H`, recortado en `apply_degradation` (`component.py:31-32`). |
| Estados OK/WARNING/CRITICAL/FAILED con umbrales 0.7 / 0.4 / 0.1 | ✅ Idéntico al spec, ver `component.py:22-29`. |

---

## 4. Costes y vidas útiles

| Componente | $L_{nom}$ spec (h) | $L_{nom}$ código (días) | Equivalente (h asumiendo 24/7) | ¿Coincide? |
|---|---|---|---|---|
| C1 | 800 h | 33.33 d | 800 h | ✅ |
| C2 | 18.000 h | 750 d | 18.000 h | ✅ |
| C3 | 3.500 h | **50 d** | **1.200 h** | ❌ recalibrado a la baja (comentario en yaml: "TIJ printheads operator-replaceable consumables") |
| C4 | 5.000 h | 208.33 d | 5.000 h | ✅ |
| C5 | 12.000 h | 500 d | 12.000 h | ✅ |
| C6 | 30.000 h | **2.500 d** | **60.000 h** | ❌ duplicado (comentario: "BJT insulation rated 1260C, real life dominated by humidity/dust") |

Costes (€) y downtimes coinciden con el spec. ✅ están en `components.yaml`.

**Crucial:** `lambda0_per_d` **no es** $1/L_{nom,i}$ como dice el spec §5.1. Está **calibrado empíricamente** para que el MTTF observado en simulación se acerque a `first_failure_target_d`. Ver el comentario en `components.yaml:17-25` y los valores: e.g. C1 tiene `lambda0_per_d=0.014097` cuando el spec implicaría `1/33.33 = 0.030`.

---

## 5. Modelo de degradación

### 5.1 Fórmula maestra
✅ `compute_lambda` en `degradation.py:43-53` calcula exactamente:
$$\lambda_i = \lambda_{0,i} \cdot \alpha_i \cdot f_{ext,i} \cdot f_{int,i} \cdot f_{cross,i}$$

Con un factor extra **`alpha_i`** por impresora (no documentado en el spec): ruido `Normal(1.0, 0.05)` clipeado a [0.5, 2.0] que escala `lambda0` por impresora — `generate.py:63-75`, `component.py:18-20`.

### 5.2 Factor externo
✅ Ley de potencias `(x/x_ref)^a` por variable, en `_variable_product` (`degradation.py:97-110`).

⚠️ **Hack escondido:** la línea 105-106 hace `if name == "H": value = max(value, 1.0)` — es decir, la humedad nunca degrada por debajo del valor 1.0 (no del ref). Esto evita división por cero pero distorsiona el factor externo en climas secos.

### 5.3 Factor interno
✅ Forma `(1 + τ/τ_nom)^bM · (1 + L/L_nom)^bL · ∏(y/y_ref)^c` en `_maintenance_factor`, `_life_factor`, y `_variable_product` (`degradation.py:86-94`).

### 5.4 Update del Health Index
⚠️ `H(t+Δt) = H(t) - λ·Δt`. Pero hay dos diferencias relevantes:
1. **Cap de variación:** `MAX_DH_PER_DAY = 1.2` (`simulator.py:16, 267`). El spec pide cap 0.05 por hora — no equivalente.
2. `apply_degradation` recorta H a [0,1] (`component.py:31-32`).

### 5.5 Eventos de mantenimiento
✅ Preventivo: `H ← min(H+0.5, 1.0)`, `τ_mant ← 0` (`component.py:34-37`).
✅ Correctivo: `H ← 1.0`, `τ_mant ← 0`, `L ← 0` (`component.py:39-44`).
✅ Trigger preventivo cuando `τ_mant ≥ τ_nom` (`simulator.py:154`).
✅ Trigger correctivo cuando `H ≤ 0.1` (`simulator.py:159`).

---

## 6. Variables y exponentes por componente (lo que **realmente** afecta a cada uno)

Esto es lo que está **literalmente cargado en el simulador** (`components.yaml`):

### C1 — Recoater blade
- **Externas:** `T` (ref 25, exp 0.3), `H` (ref 40, exp 1.5)
- **Internas:** `v` (150, 1.2), `N_c` (30000, **0.8**), `phi_R` (0.20, 1.0)
- `b_M=1.5`, `b_L=1.2`, `τ_nom=25 d`

✅ Coincide con spec §6.1.

### C2 — Guía lineal
- **Externas:** `T` (25, 0.5), `H` (40, 0.8), `c_p` (50, 1.5)
- **Internas:** `v` (150, 1.0), `N_iv` (500.000, 1.0)
- `b_M=1.8`, `b_L=1.2`, `τ_nom=166.67 d`

✅ Coincide con spec §6.2.

### C3 — Nozzle plate
- **Externas:** `T` (35, 1.2), `H` (40, 0.6), `c_p` (50, 1.3)
- **Internas:** `N_f` (5e10, 1.0), `P_B` (**desactivado** — comentario yaml l.87-89: "regulated deviation, ratio undefined")
- `b_M=2.0`, `b_L=1.0`, `τ_nom=7 d`

⚠️ **El spec contempla `P_B` con exponente 1.5; en la práctica está desactivado.**

### C4 — TIJ resistors
- **Externas:** `T` (35, **1.5** — softened de 2.0, ver yaml l.104)
- **Internas:** `N_f` (5e10, **1.0** — softened de 1.2), `E_d` (3, 1.8), `f_d` (20, 1.0)
- `b_M=1.3`, `b_L=1.0`, `τ_nom=41.67 d`

⚠️ **Dos exponentes "ablandados" respecto al spec** para evitar runaway numérico (Arrhenius muy agresivo).

### C5 — Calefactores
- **Externas:** `T_fab` (25, 0.5), `H` (40, 0.3)
- **Internas:** `T_set` (180, 2.0), `Q` (1.0, **1.5** — softened de 2.0), `N_on` (5000, 0.8)
- `b_M=1.4`, `b_L=1.3`, `τ_nom=166.67 d`

⚠️ Exponente de `Q` ablandado para amortiguar el bucle térmico C5↔C6.

### C6 — Paneles aislantes
- **Externas:** `T_max` (180, 1.5), `T_fab` (25, 0.4), `H` (40, 0.8)
- **Internas:** `N_TC` (10000, 1.0)
- `b_M=1.2`, `b_L=1.0`, `τ_nom=333.33 d`

✅ Coincide con spec §6.6.

---

## 7. Acoplamientos cross-component — ¿el fallo de uno acelera a otro?

**Sí, hay dos mecanismos distintos** (uno está en el spec; el otro es un add-on no documentado).

### 7.1 Mecanismo A: matriz de multiplicadores (spec §7)
✅ Implementado en `compute_cross_factors` (`degradation.py:10-40`) con la matriz exacta de `couplings.yaml`:

```
C1 → C2 (×1.4)   C1 → C3 (×2.0)
C2 → C1 (×1.4)
C3 → C4 (×1.4)
C4 → C3 (×1.5)
C5 → C6 (×1.6)
C6 → C5 (×1.7)
```

✅ **Activación on/off** en `H ≤ 0.4` (umbral CRITICAL exacto del spec).
✅ **Cap de producto par** en `2.5` (`couplings.yaml:2`) — ver `degradation.py:25-35` (escalado simétrico vía `sqrt(cap/product)`).
✅ Salvaguarda **C5/C6 ambos en CRITICAL → fuerza correctivo del peor** (`simulator.py:162-165`).

### 7.2 Mecanismo B: cascada continua a través de drivers físicos (no en spec)
**Este es el bucle de retroalimentación que sí actúa siempre, no solo en CRITICAL**, y es el que más distorsiona la simulación respecto al documento:

`simulator.py:257-258`:
```python
c_p     = c_p0 * _cascade_factor(H_C1)   # afecta a C2 y C3
q_demand = Q0  * _cascade_factor(H_C6)   # afecta a C5
```

donde `_cascade_factor(H) = 1 + (1 - H)²` (`simulator.py:219-228`):
- `H=1.0 → factor 1.0` (sin efecto)
- `H=0.5 → factor 1.25`
- `H=0.0 → factor 2.0`

Es decir:
- **C1 degradándose levanta `c_p`** → empeora a C2 (vía `c_p` ext) y a C3 (vía `c_p` ext) **en todo momento**, no solo cuando C1 entra en CRITICAL.
- **C6 degradándose levanta `Q`** → empeora a C5 vía la variable interna `Q`, también continuo.

El comentario del código (l.220-227) reconoce que reemplazó la fórmula `(2 - H)` lineal del spec §8.2 por una cuadrática para suavizar; pero el efecto es real y siempre activo.

### 7.3 Bucles netos
Sumando ambos mecanismos:
- **C1 ↔ C2:** ×1.4 (matriz, solo CRITICAL) + cascada continua C1→C2 vía c_p.
- **C1 → C3:** ×2.0 (matriz) + cascada continua vía c_p.
- **C3 ↔ C4:** ×1.4 / ×1.5 (matriz, solo CRITICAL). Sin cascada continua por driver.
- **C5 ↔ C6:** ×1.6 / ×1.7 (matriz, cap 2.5) + cascada continua C6→C5 vía Q + safety auto-correctivo si ambos < 0.4.

---

## 8. Variables de entrada

| Spec | Implementado |
|---|---|
| Constantes (T_fab, T_set, v, f_d, E_d, ...) | ✅ `process_constants` en `components.yaml:1-15` |
| Humedad senoidal estacional | ✅ Hay fallback en `weather.py:48-51`, **pero el flujo real usa Open-Meteo histórico** vía `_REAL_LOOKUP` (`weather.py:33-42`). Output clipeado a [20,30] °C y [30,70] % HR. |
| `c_p = c_p0·(2-H_C1)` | ❌ Cambiado a `_cascade_factor` cuadrático (ver §7.2). |
| `Q = Q0·(2-H_C6)` | ❌ Idem. |
| `N_f` por job | ⚠️ Reescrito como `fires_per_hour=5e8` × `daily_print_hours` (`simulator.py:317`). **No hay concepto de "job"** explícito; es horas-de-impresión con `daily_print_hours ~ Gamma(2,2)` (`simulator.py:254`, media ≈4 h/día). |
| `N_c` por job | ⚠️ Idem, `layers_per_hour=280`. |
| `N_iv = N_c` | ✅ Mapeado en `_build_driver_namespace` (`simulator.py:346`). |
| `N_TC` 1 por job | ⚠️ Aproximado vía `daily_print_hours/hours_per_job` (`simulator.py:319`). |
| `N_on` 1-2/día | ⚠️ Aproximado como `max(1, daily_print_hours·0.05)` si hay impresión (l.320-321). |
| Volumen de trabajo configurable (jobs/mes) | ❌ El parámetro `monthly_jobs` existe en la firma pero **está marcado como no usado** (ver docstring `simulator.py:33`, `PrinterStepper.__init__:95`). |

---

## 9. Lógica de simulación paso a paso

`_simulate_one_day` (`simulator.py:231-306`) implementa el bucle. Diferencias respecto al pseudocódigo del spec §9:

1. **Δt = 1 día**, no 1 hora.
2. El cap es `MAX_DH_PER_DAY = 1.2` por componente por día, no `0.05/h`.
3. **No hay integrador adaptativo (RKF)** — es Euler explícito de paso fijo.
4. **Orden de operaciones:** se calculan TODOS los λ con un snapshot de H consistente; luego se aplica la degradación a todos; luego mantenimiento; luego avance temporal. Correcto.
5. Counters (`N_f`, `N_c`, `N_TC`, `N_on`) se actualizan **una vez al día** con `daily_print_hours`, no por tick.

---

## 10. Output

| Spec | Implementado |
|---|---|
| Coste total anual | ❌ **No se calcula en el simulador.** Los costes están en yaml pero no hay agregación. |
| Disponibilidad % | ❌ No se calcula. |
| Nº fallos / mantenimientos por componente | ⚠️ Se registran eventos por fila (`maint_C1`, `failure_C1` …) pero no agregados. |
| Health Index medio por componente | ⚠️ Ídem, queda como serie temporal en parquet. |
| Tiempo en cada estado | ❌ Sin postproceso. |
| Restricción ≥ 95 % | ❌ No aplicada. |
| Función objetivo | ❌ El simulador no tiene función objetivo explícita; eso vive en `ml/03_rl+ssl` (PPO). |

---

## 11. Estructura de código

La estructura sugerida (`digital_twin/config/`, `core/`, `optimizer/`, `analysis/`) **no existe** literalmente. La equivalente real:
- `backend/simulator/config/*.yaml` ✅
- `backend/simulator/core/{component,degradation,simulator}.py` ✅ (no hay `events.py` separado — está en `simulator.py`)
- Optimizer → vive en `ml/03_rl/`
- Analysis → notebooks en `ml/0X/` y dashboard en `frontend/`

---

## 12. Resumen de divergencias críticas

1. **Paso temporal en días, no horas** — todos los exponentes del spec se aplican igualmente, pero la dinámica resultante es ~24× más gruesa.
2. **`lambda0` calibrado empíricamente, NO es `1/L_nom`** — el spec asume "factores valen 1 en nominal → degradación neutra". En la práctica los `lambda0_per_d` están deflactados (≈ 0.5× la analítica) para compensar el efecto medio de drivers + couplings.
3. **C3 y C6 con vidas útiles totalmente recalibradas** (50 d en vez de 146 d para C3; 2.500 d en vez de 1.250 d para C6).
4. **Dos exponentes "softened" vs. spec** sin documentar en el .md: C4 `T` (1.5 vs. 2.0), C4 `N_f` (1.0 vs. 1.2), C5 `Q` (1.5 vs. 2.0).
5. **`P_B` desactivado** (problema de ref=0).
6. **Hack `H ≥ 1.0` floor** en `_variable_product` — humedades bajas se redondean al alza.
7. **Doble mecanismo de acoplamiento:** matriz on/off al pasar 0.4 (spec) **+** cascada continua cuadrática vía `c_p` y `Q` (no spec, siempre activa).
8. **Factor `alpha` por impresora no documentado** — Normal(1, 0.05) que escala `lambda0`.
9. **Cap por paso `MAX_DH_PER_DAY = 1.2`** — distinto del cap horario 0.05 del spec; un solo día puede llevar H de 1.0 a -0.2 (clipeado a 0) en teoría.
10. **No se calculan costes ni disponibilidad** dentro del simulador — la "función objetivo" vive aguas abajo en RL.
11. **Bucle 5 años / 24/7 → en realidad 10 años con Open-Meteo histórico**, `daily_print_hours ~ Gamma(2,2)` (media 4 h/día), no 24/7.
