# Funciones de degradación por componente, fuentes de variables y propuesta de fallos por umbral

> Este documento responde a tres cosas:
> 1. La **función de degradación exacta** que el simulador aplica a cada componente, escrita en una sola línea.
> 2. La **procedencia de cada variable** que entra en esas funciones.
> 3. Cómo la **rotura de un componente afecta a otro**, con la diferencia simple entre los dos mecanismos de acoplamiento (A y B).
> 4. Discusión sobre si añadir un **segundo modo de fallo por umbrales de temperatura/humedad** es la mejor opción y alternativas.

---

## 1. Función de degradación general

Para todos los componentes, el simulador calcula la tasa de fallo por día como:

$$
\lambda_i(t) = \lambda_{0,i} \cdot \alpha_i \cdot f_{ext,i}(t) \cdot f_{int,i}(t) \cdot f_{cross,i}(t)
$$

y luego actualiza el Health Index:

$$
H_i(t+1) = H_i(t) - \min\bigl(\lambda_i(t),\ 1.2\bigr)
$$

Donde el factor interno tiene siempre dos términos fijos (mantenimiento y vida total) más un producto de variables internas:

$$
f_{int,i} = \left(1 + \tfrac{\tau_{mant,i}}{\tau_{nom,i}}\right)^{b_{M,i}} \cdot \left(1 + \tfrac{L_i}{L_{nom,i}}\right)^{b_{L,i}} \cdot \prod_j \left(\tfrac{y_j}{y_{j,ref}}\right)^{c_{j,i}}
$$

y el factor externo es un producto puro de leyes de potencias:

$$
f_{ext,i} = \prod_k \left(\tfrac{x_k}{x_{k,ref}}\right)^{a_{k,i}}
$$

A continuación, la **expansión literal por componente** con los exponentes que están cargados en `backend/simulator/config/components.yaml`.

---

## 2. Funciones por componente

### C1 — Recoater blade

$$
\lambda_{C1} = 0{,}014097 \cdot \alpha_{C1}
\cdot \left(\tfrac{T}{25}\right)^{0{,}3}
\cdot \left(\tfrac{H}{40}\right)^{1{,}5}
\cdot \left(1 + \tfrac{\tau_{mant}}{25}\right)^{1{,}5}
\cdot \left(1 + \tfrac{L}{33{,}33}\right)^{1{,}2}
\cdot \left(\tfrac{v}{150}\right)^{1{,}2}
\cdot \left(\tfrac{N_c}{30000}\right)^{0{,}8}
\cdot \left(\tfrac{\phi_R}{0{,}20}\right)^{1{,}0}
\cdot f_{cross,C1}
$$

### C2 — Guía lineal + motor

$$
\lambda_{C2} = 0{,}000462 \cdot \alpha_{C2}
\cdot \left(\tfrac{T}{25}\right)^{0{,}5}
\cdot \left(\tfrac{H}{40}\right)^{0{,}8}
\cdot \left(\tfrac{c_p}{50}\right)^{1{,}5}
\cdot \left(1 + \tfrac{\tau_{mant}}{166{,}67}\right)^{1{,}8}
\cdot \left(1 + \tfrac{L}{750}\right)^{1{,}2}
\cdot \left(\tfrac{v}{150}\right)^{1{,}0}
\cdot \left(\tfrac{N_{iv}}{500\,000}\right)^{1{,}0}
\cdot f_{cross,C2}
$$

### C3 — Nozzle plate

$$
\lambda_{C3} = 0{,}013467 \cdot \alpha_{C3}
\cdot \left(\tfrac{T}{35}\right)^{1{,}2}
\cdot \left(\tfrac{H}{40}\right)^{0{,}6}
\cdot \left(\tfrac{c_p}{50}\right)^{1{,}3}
\cdot \left(1 + \tfrac{\tau_{mant}}{7}\right)^{2{,}0}
\cdot \left(1 + \tfrac{L}{50}\right)^{1{,}0}
\cdot \left(\tfrac{N_f}{5\cdot 10^{10}}\right)^{1{,}0}
\cdot f_{cross,C3}
$$

> Nota: `P_B` aparece en el yaml pero está marcado `enabled: false` (la referencia es 0 kPa, ratio indefinido). No interviene.

### C4 — TIJ firing resistors

$$
\lambda_{C4} = 0{,}001515 \cdot \alpha_{C4}
\cdot \left(\tfrac{T}{35}\right)^{1{,}5}
\cdot \left(1 + \tfrac{\tau_{mant}}{41{,}67}\right)^{1{,}3}
\cdot \left(1 + \tfrac{L}{208{,}33}\right)^{1{,}0}
\cdot \left(\tfrac{N_f}{5\cdot 10^{10}}\right)^{1{,}0}
\cdot \left(\tfrac{E_d}{3}\right)^{1{,}8}
\cdot \left(\tfrac{f_d}{20}\right)^{1{,}0}
\cdot f_{cross,C4}
$$

### C5 — Calefactores

$$
\lambda_{C5} = 0{,}009065 \cdot \alpha_{C5}
\cdot \left(\tfrac{T_{fab}}{25}\right)^{0{,}5}
\cdot \left(\tfrac{H}{40}\right)^{0{,}3}
\cdot \left(1 + \tfrac{\tau_{mant}}{166{,}67}\right)^{1{,}4}
\cdot \left(1 + \tfrac{L}{500}\right)^{1{,}3}
\cdot \left(\tfrac{T_{set}}{180}\right)^{2{,}0}
\cdot \left(\tfrac{Q}{1{,}0}\right)^{1{,}5}
\cdot \left(\tfrac{N_{on}}{5000}\right)^{0{,}8}
\cdot f_{cross,C5}
$$

### C6 — Paneles aislantes

$$
\lambda_{C6} = 0{,}000284 \cdot \alpha_{C6}
\cdot \left(\tfrac{T_{max}}{180}\right)^{1{,}5}
\cdot \left(\tfrac{T_{fab}}{25}\right)^{0{,}4}
\cdot \left(\tfrac{H}{40}\right)^{0{,}8}
\cdot \left(1 + \tfrac{\tau_{mant}}{333{,}33}\right)^{1{,}2}
\cdot \left(1 + \tfrac{L}{2500}\right)^{1{,}0}
\cdot \left(\tfrac{N_{TC}}{10000}\right)^{1{,}0}
\cdot f_{cross,C6}
$$

---

## 3. Origen exacto de cada variable

| Variable | Tipo | Cómo se genera en el simulador | Fuente / parámetros |
|---|---|---|---|
| `T` (temperatura ambiente) | dinámica diaria, dependiente de ciudad y fecha | Lectura de **Open-Meteo histórico** cacheado en `data/raw/openmeteo_<city>.json`, transformado a temperatura interior por `apply_transfer_functions` y clipeado al rango `[20, 30] °C`. Si no hay lookup real, fallback senoidal: `T_mean_annual + T_amplitude · cos(2π(día−15)/365.25)` con coeficientes en `backend/simulator/config/cities.yaml`. | `backend/simulator/core/weather.py:33-55`, parquet diario `data/train/weather_real.parquet` |
| `H` (humedad relativa) | igual que `T` | Open-Meteo `relative_humidity_2m_mean` → transferencia a humedad interior → clip `[30, 70] %`. Fallback senoidal con desfase π/4. **Hack:** en `_variable_product` se aplica `value = max(value, 1.0)` antes de la división, lo que limita el efecto en humedades muy bajas. | `weather.py:48-51`, `degradation.py:105-106` |
| `T_fab` | constante de proceso | `25.0 °C` fijo en `process_constants` | `components.yaml:2` |
| `T_set` (setpoint curing) | constante de proceso | `180.0 °C` fijo | `components.yaml:3` |
| `T_max` (pico cámara) | constante de proceso | `180.0 °C` fijo (igual que `T_set`) | `components.yaml:4` |
| `v` (velocidad recoater) | constante de proceso | `150 mm/s` fijo | `components.yaml:5` |
| `f_d` (frecuencia disparo) | constante de proceso | `20 kHz` fijo | `components.yaml:6` |
| `E_d` (energía por disparo) | constante de proceso | `3 µJ` fijo | `components.yaml:7` |
| `P_B` (presión binder) | constante de proceso | `0 kPa` (desviación nominal). **Desactivado** en C3 porque la referencia es 0 → ratio indefinido. | `components.yaml:9, 87-89` |
| `phi_R` (% polvo reciclado) | constante de proceso | `0.20` fijo | `components.yaml:12` |
| `daily_print_hours` | aleatoria diaria | **`Gamma(shape=2, scale=2)`** → media 4 h/día, cola larga. Determina cuántos contadores se incrementan en el día. Semilla por impresora (`np.random.default_rng(printer_id)`). | `simulator.py:254` |
| `N_f` (disparos acumulados) | contador acumulativo | `+= round(daily_print_hours · 5·10⁸)` cada día | `simulator.py:317`, `components.yaml:14` |
| `N_c` (capas acumuladas) | contador acumulativo | `+= round(daily_print_hours · 280)` cada día | `simulator.py:318`, `components.yaml:15` |
| `N_iv` (ciclos ida/vuelta) | derivado | **igual que `N_c`** (se mapea directamente) | `simulator.py:346` |
| `N_TC` (ciclos térmicos) | contador acumulativo | `+= round(daily_print_hours / 0.5)` (1 ciclo cada 0.5 h de impresión) | `simulator.py:319` |
| `N_on` (ciclos on/off) | contador acumulativo | `max(1, round(daily_print_hours · 0.05))` si hay impresión | `simulator.py:320-321` |
| `c_p` (concentración polvo) | derivada de estado | **`c_p = 50 · (1 + (1 − H_{C1})²)`** — depende del Health Index actual de C1. En nominal vale 50, sube hasta 100 si C1 está roto. | `simulator.py:257`, función `_cascade_factor` (l.219-228) |
| `Q` (potencia demandada normalizada) | derivada de estado | **`Q = 1.0 · (1 + (1 − H_{C6})²)`** — depende del Health Index actual de C6. Nominal 1.0, sube hasta 2.0 si C6 está destrozado. | `simulator.py:258`, mismo `_cascade_factor` |
| `τ_mant,i` (h desde último mantenimiento) | estado interno | Se incrementa +1 día por tick. Reset a 0 tras preventivo o correctivo. | `component.py:49-51`, `34-44` |
| `L_i` (vida total) | estado interno | Se incrementa +1 día por tick. Reset a 0 solo tras correctivo. | `component.py:49-51`, `39-44` |
| `α_i` (variabilidad por impresora) | aleatoria, fijada al inicio | **`Normal(1.0, σ=0.05)` clipeado a `[0.5, 2.0]`**, una muestra por componente y por impresora. Multiplica `λ₀` durante toda la vida de la impresora. | `generate.py:63-75`, `component.py:18-20` |
| `λ₀,i` | constante calibrada | Valor fijo en yaml, **calibrado empíricamente** para que el MTTF promedio se acerque al `first_failure_target_d`. No es `1/L_nom`. | `components.yaml:31, 51, 73, 95, 114, 136` |
| `H_{C1}`, `H_{C6}` (cascada) | estado interno | Health Index actual del componente upstream. Se lee del snapshot del día. | `simulator.py:257-258` |

---

## 4. Cómo la rotura de un componente afecta a otros

Hay **dos mecanismos de acoplamiento** que conviven simultáneamente. Esto es importante porque significa que un componente vecino puede empezar a sufrir mucho antes de que el spec original lo previera.

### Mecanismo A — "Matriz de multiplicadores" (interruptor on/off)

**Idea simple:** mientras un componente está sano (H > 0.4), no afecta a sus vecinos. En el momento exacto en que **cruza el umbral 0.4 (entra en CRITICAL)**, dispara un multiplicador fijo sobre la tasa de fallo de los componentes con los que está acoplado.

Ejemplo: si C1 baja a H=0.39, automáticamente la λ de C2 se multiplica por 1.4 y la de C3 por 2.0. Si C1 vuelve a subir por encima de 0.4 tras un mantenimiento, el multiplicador desaparece.

| Origen → Destino | Multiplicador (solo si origen H ≤ 0.4) |
|---|---|
| C1 → C2 | ×1.4 |
| C1 → C3 | ×2.0 |
| C2 → C1 | ×1.4 |
| C3 → C4 | ×1.4 |
| C4 → C3 | ×1.5 |
| C5 → C6 | ×1.6 |
| C6 → C5 | ×1.7 |

Si dos componentes están acoplados en bucle (C1↔C2, C3↔C4, C5↔C6) y los dos están en CRITICAL a la vez, el simulador limita el producto de los dos multiplicadores a 2.5 para evitar runaway numérico. Y si tanto C5 como C6 están bajo 0.4 a la vez, fuerza un correctivo del peor.

**Resumen:** es un mecanismo **discreto, todo o nada**, que solo se activa al pasar el umbral.

### Mecanismo B — "Cascada continua a través de drivers físicos"

**Idea simple:** algunos componentes, al degradarse, **modifican el entorno físico real** (concentración de polvo en el aire, potencia eléctrica demandada). Como otros componentes ya tienen esas variables como entrada en su factor externo o interno, cualquier degradación —por pequeña que sea— se transmite.

Aquí no hay umbral. Es una función continua suave: cuando el componente upstream está sano (H=1.0) el efecto es exactamente cero; cuando está roto (H=0) el efecto multiplica por 2 la variable en cuestión.

Fórmula: `factor_cascada(H) = 1 + (1 − H)²`

Solo dos cascadas existen en el código:
- **C1 → C2 y C1 → C3** vía la concentración de polvo `c_p`. Una cuchilla recoater desgastada levanta más polvo, y ese polvo entra en la fórmula de C2 y C3 a través de su variable externa `c_p`.
- **C6 → C5** vía la potencia demandada `Q`. Un panel aislante degradado pierde calor, los calefactores tienen que tirar más fuerte, y `Q` entra en la fórmula de C5 a través de su variable interna `Q`.

**Resumen:** es un mecanismo **continuo y siempre activo**, que crece suavemente con la degradación del componente origen.

### Diferencia en una frase

| | Mecanismo A | Mecanismo B |
|---|---|---|
| Disparo | Umbral discreto en H ≤ 0.4 | Continuo desde H = 1.0 |
| Acoplamientos | 7 pares (matriz) | 3 pares (C1→C2, C1→C3, C6→C5) |
| Implementación | Multiplica `f_cross` directamente | Modifica el valor de drivers físicos (`c_p`, `Q`) |
| Documentado en spec | Sí | No (es un add-on del código) |

Cuando un componente vecino degrada a otro en la simulación real, el efecto que se observa es **la suma de los dos mecanismos**: una rampa continua suave (B) que se vuelve abrupta cuando se cruza el umbral 0.4 (A entra en juego).

---

## 5. ¿Añadir un segundo modo de fallo por umbrales de T/H?

Tu propuesta es: si en un día concreto la temperatura o humedad cruza un umbral extremo, el componente rompe instantáneamente, independientemente de su Health Index.

### Pros
- Conceptualmente limpio: distingue entre **fallo por desgaste acumulado** (lo que ya tienes) y **fallo por evento agudo** (nueva categoría).
- Implementación trivial: un `if` por componente y por día tras calcular drivers.
- Aporta diversidad de modos de fallo para el agente diagnóstico (Phase 3) — el LLM puede dar diagnósticos más ricos ("el printhead falló por shock térmico, no por fin de vida").

### Contras serios
1. **Tu pipeline ya clipea T y H a `[20, 30] °C` y `[30, 70] %`** en `weather.py:40-41, 53-54`. Es decir, **nunca verás valores extremos** en el simulador a menos que cambies ese clipping. Si lo añades sin tocar el clip, el modo no disparará nunca.
2. **No es físicamente realista** por sí solo: una HP S100 industrial no se cae al primer día de 32 °C. La realidad es que la **probabilidad** de fallo aumenta, no que el fallo sea determinista al cruzar 30,01 °C.
3. **Discontinuidad numérica:** un cambio de 29.9 → 30.1 °C te lleva de "componente sano" a "componente muerto". Mal para PatchTST y para el RL: la señal de aprendizaje se vuelve hostil porque el target salta.

### Alternativas mejores (ordenadas por viabilidad)

#### Opción 1 — Fallo estocástico con probabilidad creciente fuera del rango (recomendada)

En vez de umbral duro, defines una **probabilidad de fallo del día** que crece con la distancia al rango operativo:

```
P_fallo_extremo(día) = 1 − exp(−β · max(0, T − T_max_op)² − γ · max(0, H − H_max_op)²)
```

Y cada día, después de calcular los drivers, lanzas un Bernoulli. Esto es **Arrhenius-like** y matemáticamente equivalente a una "fatiga aguda". Ventajas:
- Continuo: no hay saltos.
- Físicamente defendible (estrés acumulativo).
- Compatible con el resto del modelo.
- Implementación: ~10 líneas en `_simulate_one_day`, después de calcular `weather_drivers` y antes de aplicar degradación.

Para que dispare alguna vez tendrías que **ampliar el clip** de `weather.py` a, p.ej., `[15, 35] °C` y `[20, 80] %`, y dejar que algunos días extremos de Open-Meteo lleguen al simulador. Las series reales tienen colas — se vería la diferencia entre Phoenix y Reykjavik.

#### Opción 2 — Daño agudo proporcional al exceso (también buena)

En vez de que el componente "rompa", el día extremo descuenta una cantidad fija extra del Health Index:

```
ΔH_agudo = k · max(0, T − T_max_op)² + k_H · max(0, H − H_max_op)²
H_i ← H_i − ΔH_agudo
```

Es lo mismo que ya haces (`H ← H − λ·Δt`) pero con una contribución extra que solo se enciende fuera del rango operativo. Ventajas: sigue habiendo un único Health Index, no hay un evento "fallo súbito" sin causa visible, el agente diagnóstico puede explicar la trayectoria mirando la serie de T/H.

#### Opción 3 — Modo dual: umbral + tasa (la más rica)

Combinar ambas: por encima de un cierto extremo (p.ej. T > 35 °C real), aplicas Opción 2 cada día (daño agudo); y solo por encima de un extremo extremo (p.ej. T > 40 °C), permites un fallo determinista. Esto modela la realidad: shock térmico instantáneo es raro, fatiga térmica acumulada es lo normal.

#### Opción 4 — Modo de fallo por contaminación / consumibles (alternativa al térmico)

Si lo que quieres es diversidad de modos de fallo, también podrías añadir:
- **Fallo por polvo extremo:** cuando `c_p` supera un umbral (combinable con C1 muy degradado).
- **Fallo por shock de presión binder:** activando `P_B` (que ahora está deshabilitado).
- **Fallo por carga de trabajo:** un día con `daily_print_hours` en la cola alta de la Gamma combinado con baja salud aumenta probabilidad de fallo.

Estos no requieren tocar Open-Meteo y se conectan naturalmente con el código existente.

### Mi recomendación práctica para el hackathon

Si quieres algo **rápido, defensible y con impacto visible**:

1. **Amplía los clips de `weather.py`** a `[15, 35] °C` y `[20, 80] %` para que los extremos de Open-Meteo lleguen al simulador (1 línea cada uno).
2. Implementa **Opción 2 (daño agudo proporcional)** con coeficientes pequeños por componente — los componentes electrónicos (C3, C4) sensibles a T, los térmicos (C5, C6) a T extremo, los mecánicos (C1, C2) a H extremo (corrosión + apelmazamiento).
3. **No añadas fallos deterministas duros**, son frágiles y no aportan más que la opción continua.
4. Visualízalo en el dashboard: una nueva línea "stress agudo del día" en el panel del componente, separada del desgaste estructural.

Esto tarda ~30 minutos de implementación, no rompe el pipeline ML aguas abajo (PatchTST / PPO siguen viendo el Health Index como antes), y le da al agente LLM una historia que contar ("el día 2024-07-14 hubo un pico de 36 °C en Sevilla y C4 perdió 0.08 puntos extra de Health Index").

Si en cambio buscas el modo más espectacular para la demo (un fallo súbito visible en el dashboard), entonces **Opción 3** es la respuesta: shock térmico determinista a temperaturas absurdas (>40 °C) que casi nunca dispara, pero cuando dispara es dramático. Implementación ~1 hora.
