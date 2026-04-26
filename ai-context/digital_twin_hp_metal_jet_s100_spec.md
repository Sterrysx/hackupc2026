# Digital Twin HP Metal Jet S100 — Especificación técnica para simulación

> **Documento dirigido al equipo de simulación.** Contiene toda la información necesaria para implementar el gemelo digital: arquitectura del modelo, componentes, variables, ecuaciones, costes, acoplamientos y lógica temporal.

---

## 1. Contexto y objetivo del proyecto

### 1.1 Qué simulamos
Un gemelo digital de la **HP Metal Jet S100**, una impresora industrial de Binder Jetting metálico, operando **24/7 durante 5 años** en una planta industrial real con condiciones ambientales y carga productiva variables.

### 1.2 Objetivo de negocio
Encontrar el **calendario de mantenimiento preventivo óptimo** para cada componente que **minimice el coste total anual**:

$$\text{Coste total anual} = \text{coste mantenimientos programados} + \text{coste esperado de averías}$$

### 1.3 Lógica del problema
- **Mantener poco** → ahorra € en servicio pero dispara fallos correctivos (coste de avería + downtime)
- **Mantener mucho** → eleva el coste preventivo pero reduce roturas
- Existe un **óptimo intermedio** que el simulador debe permitir encontrar

### 1.4 Cómo se usará este modelo
Tras la entrega, un optimizador barrerá miles de combinaciones de intervalos de mantenimiento $(\tau_{nom,C1}, \tau_{nom,C2}, ..., \tau_{nom,C6})$, simulará 5 años de operación para cada combinación, y devolverá el calendario que minimiza el coste total anual sujeto a disponibilidad > 95 %.

---

## 2. Datos verificados de la máquina (fuentes oficiales HP)

> Estos datos son **reales y citables** en la presentación. Fuentes: HP Metal Jet S100 Brochure (4AA8-1958ENW, abril 2023), HP Technical Whitepaper (4AA7-3333ENW), y especificaciones ambientales HP MJF (familia industrial HP).

### 2.1 Especificaciones físicas y de proceso

| Parámetro | Valor |
|---|---|
| Volumen de construcción nominal | 430 × 309 × 200 mm |
| Volumen efectivo de impresión | 430 × 309 × 140 mm |
| Velocidad de impresión | 1.990 cc/hr |
| Espesor de capa | 35–140 µm (típico 50 µm) |
| Resolución | 1.200 × 1.200 dpi |
| Número de print bars | 2 |
| Número de printheads | 6 (HP Thermal Inkjet) |
| Total de toberas (nozzles) | 63.360 |
| Toberas por printhead | 10.560 (2 columnas × 5.280) |
| Swath de printhead | 108 mm |
| Redundancia de toberas | 4× a 1.200 dpi |
| Potencia eléctrica impresora | 8 kW (3-fase) |
| Potencia curing station | 3 kW |
| Peso impresora | 851 kg |
| Diseño operativo | Industrial 24/7 |
| Garantía hardware HP | 1 año limitado |
| Precio inicial sistema | ~$550.000 USD |

### 2.2 Material y consumibles

| Parámetro | Valor |
|---|---|
| Polvos compatibles | SS 316L, SS 17-4PH (MIM-grade) |
| Tamaño de partícula de polvo | 5–45 µm esférico |
| Tipo de binder | Suspensión acuosa de látex (long-chain polymer) |
| Binder residual post-cura | <1,5 % en peso |
| Tamiz de polvo | Malla 90 µm con tecnología ultrasonidos |
| Consumibles principales | HP 3DM200 Printhead, HP 3DM200 Binding Agent 5L, HP 3DM100 Cleaning Roll, HP 3DM100 Build Unit Filter Sheets |

### 2.3 Condiciones ambientales recomendadas

> *Reference HP MJF (familia HP industrial) — aplicables a la familia HP industrial de la cual S100 forma parte.*

| Parámetro | Rango operativo |
|---|---|
| Temperatura ambiente | 20–30 °C |
| Humedad relativa | 30–70 % |

### 2.4 Parámetros del proceso (literatura científica)

| Parámetro | Valor |
|---|---|
| Temperatura de curado del binder | 100–200 °C |
| Tiempo de curado típico | 2–4 horas a 180 °C |
| Tiempo de capa S100 (a 50 µm) | ~12 segundos por capa |
| Velocidad recoater típica MBJ | 100–250 mm/s |
| Densidad final post-sinterizado | >96 % |

---

## 3. Estructura del modelo

### 3.1 Arquitectura: 3 subsistemas, 6 componentes

```
HP Metal Jet S100
│
├── 🔹 Subsistema 1: Recoating
│   ├── C1 — Recoater blade (cuchilla esparcidora)
│   └── C2 — Guía lineal + motor del carro
│
├── 🔹 Subsistema 2: Printhead (HP 3DM200)
│   ├── C3 — Nozzle plate (placa de toberas)
│   └── C4 — Thermal firing resistors (TIJ)
│
└── 🔹 Subsistema 3: Thermal (curing system)
    ├── C5 — Elementos calefactores
    └── C6 — Paneles aislantes
```

### 3.2 Estado de cada componente

Cada componente $i$ tiene en cada instante de simulación:

- **Health Index** $H_i \in [0, 1]$ — 1 = perfecto, 0 = fallado completamente
- **Operational Status** — categoría discreta:

| Health Index | Estado |
|---|---|
| $H > 0{,}7$ | OK |
| $0{,}4 < H \leq 0{,}7$ | WARNING |
| $0{,}1 < H \leq 0{,}4$ | CRITICAL |
| $H \leq 0{,}1$ | FAILED |

### 3.3 Variables que afectan a cada componente

Dos familias de inputs (alineado con metodología HP "When AI meets reality"):

- **🌍 Factores externos** — vienen del entorno o ritmo productivo, no controlados directamente por el operario
- **⚙️ Factores internos** — estado del propio componente, vida acumulada, mantenimiento

Adicionalmente:
- **🔗 Factores cross-component** — degradación de componentes vecinos que influye sobre éste (ver Sección 6)

---

## 4. Costes y vidas útiles por componente

> ⚠️ **Importante para el equipo de simulación:** Todos los valores monetarios y temporales de esta tabla son **estimaciones de orden de magnitud**. HP no publica precios de servicio para la S100. Anclados en industria comparable (ExOne X1 160Pro, Desktop Metal P-50, HP Latex industrial). **Recomendación: tratar estos valores como parámetros configurables del modelo** para permitir recalibración futura con datos reales.

| # | Componente | Mant. preventivo (€) | Downtime prev. (h) | Fallo correctivo (€) | Downtime corr. (h) | Vida útil nominal $L_{nom}$ (h) |
|---|---|---|---|---|---|---|
| C1 | Recoater blade | 250 | 1,5 | 3.500 | 12 | 800 |
| C2 | Guía lineal | 400 | 3 | 8.500 | 36 | 18.000 |
| C3 | Nozzle plate | 2.500 | 2 | 12.000 | 24 | 3.500 |
| C4 | TIJ resistors | 2.500 | 2 | 12.000 | 24 | 5.000 |
| C5 | Calefactores | 900 | 4 | 8.000 | 28 | 12.000 |
| C6 | Paneles aislantes | 1.500 | 6 | 7.000 | 20 | 30.000 |

**Notas de implementación:**
- C3 y C4 comparten coste porque ambos están integrados físicamente en el printhead HP 3DM200 (el printhead se sustituye como unidad).
- El "fallo correctivo" incluye el coste del componente más mano de obra de servicio + valor del job perdido si la máquina estaba imprimiendo.
- Sugerencia: cargar estos valores desde un fichero de configuración (`config.yaml`) para facilitar análisis de sensibilidad.

---

## 5. Modelo de degradación

### 5.1 Fórmula general (igual para los 6 componentes)

$$\boxed{\lambda_i(t) = \lambda_{0,i} \cdot f_{ext,i} \cdot f_{int,i} \cdot f_{cross,i}}$$

Donde:
- $\lambda_{0,i} = \frac{1}{L_{nom,i}}$ → tasa de fallo base en condiciones nominales
- $f_{ext,i}$ → factor por condiciones externas (Sección 5.2)
- $f_{int,i}$ → factor por estado interno (Sección 5.3)
- $f_{cross,i}$ → factor por componentes vecinos (Sección 6)
- **Todos los factores valen 1 en condiciones nominales** (depuración trivial)

### 5.2 Factor externo

$$f_{ext,i} = \prod_k \left(\frac{x_k}{x_{k,ref}}\right)^{a_{k,i}}$$

Donde:
- $x_k$ = valor actual de la variable externa $k$
- $x_{k,ref}$ = valor de referencia (nominal) de esa variable
- $a_{k,i}$ = exponente de sensibilidad de la variable $k$ para el componente $i$

### 5.3 Factor interno

$$f_{int,i} = \left(1 + \frac{\tau_{mant,i}}{\tau_{nom,i}}\right)^{b_{M,i}} \cdot \left(1 + \frac{L_i}{L_{nom,i}}\right)^{b_{L,i}} \cdot \prod_j \left(\frac{y_j}{y_{j,ref}}\right)^{c_{j,i}}$$

Donde:
- $\tau_{mant,i}$ = horas desde el último mantenimiento preventivo (se resetea tras cada intervención)
- $L_i$ = horas de vida total acumulada (solo se resetea tras fallo correctivo)
- $\tau_{nom,i}$ = intervalo de mantenimiento de referencia → **variable que el optimizador moverá**
- $b_{M,i}, b_{L,i}$ = exponentes de sensibilidad
- $y_j$ = variables internas adicionales específicas del componente (velocidad, presión, etc.)
- $c_{j,i}$ = exponentes para esas variables específicas

### 5.4 Actualización del Health Index (paso temporal)

$$H_i(t + \Delta t) = H_i(t) - \lambda_i(t) \cdot \Delta t$$

**Paso de integración recomendado:** $\Delta t = 1$ hora.

### 5.5 Eventos de mantenimiento

**Mantenimiento preventivo** (cuando $\tau_{mant,i} \geq \tau_{nom,i}$):
$$H_i \leftarrow \min(H_i + 0{,}5,\ 1{,}0) \qquad \tau_{mant,i} \leftarrow 0$$

> El mantenimiento preventivo no deja el componente como nuevo. Suma 0,5 al Health Index pero no resetea $L_i$ (la vida total sigue acumulándose).

**Fallo correctivo** (cuando $H_i \leq 0{,}1$):
$$H_i \leftarrow 1{,}0 \qquad \tau_{mant,i} \leftarrow 0 \qquad L_i \leftarrow 0$$

> La reparación correctiva implica sustitución completa: componente como nuevo en todos los aspectos.

---

## 6. Variables y exponentes por componente

> ⚠️ **Los exponentes son estimaciones del modelizador** basadas en física razonable. Los **rangos operativos sí son reales** (verificados con HP). Tratar exponentes como parámetros calibrables.

### 6.1 — C1: Recoater blade

| Tipo | Variable | Símbolo | Rango operativo | Ref. nominal | Exponente |
|---|---|---|---|---|---|
| 🌍 ext | Temperatura entorno | $T$ | 20–30 °C | 25 °C | $a_T = 0{,}3$ |
| 🌍 ext | Humedad relativa | $H$ | 30–70 % | 40 % | $a_H = 1{,}5$ |
| ⚙️ int | Velocidad de pasada | $v$ | 100–250 mm/s | 150 mm/s | $c_v = 1{,}2$ |
| ⚙️ int | Capas impresas acumuladas | $N_c$ | 0–50.000 | 30.000 | $c_{Nc} = 0{,}8$ |
| ⚙️ int | % polvo reciclado | $\phi_R$ | 0–80 % | 20 % | $c_\phi = 1{,}0$ |
| ⚙️ int | Tiempo sin mantenimiento | $\tau_{mant}$ | 0–2.000 h | 600 h | $b_M = 1{,}5$ |
| ⚙️ int | Vida total | $L$ | 0–800 h | 800 h | $b_L = 1{,}2$ |

**Lógica física:** desgaste abrasivo del filo (Archard). Sensible a humedad (polvo apelmazado), partículas duras (polvo reciclado oxidado) y velocidad. Cada capa impresa = una pasada = un incremento de desgaste.

---

### 6.2 — C2: Guía lineal + motor

| Tipo | Variable | Símbolo | Rango operativo | Ref. nominal | Exponente |
|---|---|---|---|---|---|
| 🌍 ext | Temperatura entorno | $T$ | 20–30 °C | 25 °C | $a_T = 0{,}5$ |
| 🌍 ext | Humedad relativa | $H$ | 30–70 % | 40 % | $a_H = 0{,}8$ |
| 🌍 ext | Concentración polvo en aire | $c_p$ | 0–500 mg/m³ | 50 mg/m³ | $a_c = 1{,}5$ |
| ⚙️ int | Velocidad desplazamiento | $v$ | 100–250 mm/s | 150 mm/s | $c_v = 1{,}0$ |
| ⚙️ int | Ciclos ida/vuelta | $N_{iv}$ | 0–10⁷ | 500.000 | $c_{Nc} = 1{,}0$ |
| ⚙️ int | Tiempo sin mantenimiento | $\tau_{mant}$ | 0–20.000 h | 4.000 h | $b_M = 1{,}8$ |
| ⚙️ int | Vida total | $L$ | 0–18.000 h | 18.000 h | $b_L = 1{,}2$ |

**Lógica física:** fatiga de contacto en rodamientos + abrasión por polvo metálico fino infiltrado (tercer cuerpo). $c_p$ es el canal de entrada del acoplamiento C1→C2.

---

### 6.3 — C3: Nozzle plate

| Tipo | Variable | Símbolo | Rango operativo | Ref. nominal | Exponente |
|---|---|---|---|---|---|
| 🌍 ext | Temperatura cámara | $T$ | 25–50 °C | 35 °C | $a_T = 1{,}2$ |
| 🌍 ext | Humedad relativa | $H$ | 30–70 % | 40 % | $a_H = 0{,}6$ |
| 🌍 ext | Concentración polvo en aire | $c_p$ | 0–500 mg/m³ | 50 mg/m³ | $a_c = 1{,}3$ |
| ⚙️ int | Disparos acumulados | $N_f$ | 0–10¹¹ | 5×10¹⁰ | $c_{Nf} = 1{,}0$ |
| ⚙️ int | Presión binder | $P_B$ | ±5 kPa (regulado) | 0 kPa (desviación) | $c_P = 1{,}5$ |
| ⚙️ int | Tiempo sin mantenimiento | $\tau_{mant}$ | 0–500 h | 168 h (1 semana) | $b_M = 2{,}0$ |
| ⚙️ int | Vida total | $L$ | 0–3.500 h | 3.500 h | $b_L = 1{,}0$ |

**Lógica física:** obstrucción de toberas por evaporación + corrosión química + impacto de polvo. La redundancia 4× del HP 3DM200 implica que el componente puede operar con hasta ~25 % de toberas degradadas antes de fallar como sistema. Las limpiezas semanales (wipe/purge) son críticas para mantener salud (de ahí $\tau_{nom} = 168$ h).

---

### 6.4 — C4: TIJ firing resistors

| Tipo | Variable | Símbolo | Rango operativo | Ref. nominal | Exponente |
|---|---|---|---|---|---|
| 🌍 ext | Temperatura cámara | $T$ | 25–50 °C | 35 °C | $a_T = 2{,}0$ |
| ⚙️ int | Disparos acumulados | $N_f$ | 0–10¹¹ | 5×10¹⁰ | $c_{Nf} = 1{,}2$ |
| ⚙️ int | Energía por disparo | $E_d$ | 2–5 µJ | 3 µJ | $c_E = 1{,}8$ |
| ⚙️ int | Frecuencia disparo | $f_d$ | 12–36 kHz | 20 kHz | $c_{fd} = 1{,}0$ |
| ⚙️ int | Tiempo sin mantenimiento | $\tau_{mant}$ | 0–2.000 h | 1.000 h | $b_M = 1{,}3$ |
| ⚙️ int | Vida total | $L$ | 0–5.000 h | 5.000 h | $b_L = 1{,}0$ |

**Lógica física:** fatiga termomecánica de las resistencias de película delgada que disparan las gotas. Cada disparo es un pulso térmico de cientos de °C en microsegundos. Sensibilidad muy alta a la temperatura del entorno (Arrhenius).

---

### 6.5 — C5: Elementos calefactores (curing system)

| Tipo | Variable | Símbolo | Rango operativo | Ref. nominal | Exponente |
|---|---|---|---|---|---|
| 🌍 ext | Temperatura entorno fábrica | $T_{fab}$ | 20–30 °C | 25 °C | $a_T = 0{,}5$ |
| 🌍 ext | Humedad relativa | $H$ | 30–70 % | 40 % | $a_H = 0{,}3$ |
| ⚙️ int | Setpoint temperatura curado | $T_{set}$ | 100–200 °C | 180 °C | $c_{Tset} = 2{,}0$ |
| ⚙️ int | Potencia demandada (normalizada) | $Q$ | 0,4–1,1 | 1,0 | $c_Q = 2{,}0$ |
| ⚙️ int | Ciclos on/off | $N_{on}$ | 0–10⁴ | 5.000 | $c_{on} = 0{,}8$ |
| ⚙️ int | Tiempo sin mantenimiento | $\tau_{mant}$ | 0–8.000 h | 4.000 h | $b_M = 1{,}4$ |
| ⚙️ int | Vida total | $L$ | 0–12.000 h | 12.000 h | $b_L = 1{,}3$ |

**Lógica física:** oxidación del filamento calefactor (Arrhenius con la temperatura). $Q$ es la variable que cierra el bucle térmico con C6: si el aislante degrada, $Q$ sube, y los calefactores se queman antes.

---

### 6.6 — C6: Paneles aislantes

| Tipo | Variable | Símbolo | Rango operativo | Ref. nominal | Exponente |
|---|---|---|---|---|---|
| 🌍 ext | Temperatura pico cámara | $T_{max}$ | 100–200 °C | 180 °C | $a_T = 1{,}5$ |
| 🌍 ext | Temperatura entorno fábrica | $T_{fab}$ | 20–30 °C | 25 °C | $a_{Tfab} = 0{,}4$ |
| 🌍 ext | Humedad relativa | $H$ | 30–70 % | 40 % | $a_H = 0{,}8$ |
| ⚙️ int | Ciclos térmicos | $N_{TC}$ | 0–10⁴ | 10.000 | $c_{TC} = 1{,}0$ |
| ⚙️ int | Tiempo sin mantenimiento | $\tau_{mant}$ | 0–20.000 h | 8.000 h | $b_M = 1{,}2$ |
| ⚙️ int | Vida total | $L$ | 0–30.000 h | 30.000 h | $b_L = 1{,}0$ |

**Lógica física:** compactación y degradación de fibras del aislante por temperatura sostenida + ciclos térmicos. La conductividad efectiva $k_{eff}$ del panel realimenta sobre $Q$ de C5: $Q = Q_0 \cdot (2 - H_{C6})$.

---

## 7. Acoplamientos entre componentes (cross-component dependency)

> Cuando un componente $i$ entra en estado CRITICAL ($H_i \leq 0{,}4$), aumenta la tasa de fallo de los componentes vecinos a los que afecta físicamente.

### 7.1 Matriz de multiplicadores

|       | → C1 | → C2 | → C3 | → C4 | → C5 | → C6 |
|-------|------|------|------|------|------|------|
| **C1 →** | —    | ×1,4 | ×2,0 | —    | —    | —    |
| **C2 →** | ×1,4 | —    | —    | —    | —    | —    |
| **C3 →** | —    | —    | —    | ×1,4 | —    | —    |
| **C4 →** | —    | —    | ×1,5 | —    | —    | —    |
| **C5 →** | —    | —    | —    | —    | —    | ×1,6 |
| **C6 →** | —    | —    | —    | —    | ×1,7 | —    |

### 7.2 Implementación

$$f_{cross,j}(t) = \prod_{i \neq j} m_{ij}(H_i)$$

$$m_{ij}(H_i) = \begin{cases} M_{ij} & \text{si } H_i \leq 0{,}4 \\ 1 & \text{si } H_i > 0{,}4 \end{cases}$$

Donde $M_{ij}$ es el valor de la matriz. Si la celda es "—", $m_{ij} = 1$ siempre.

### 7.3 Descripción de cada acoplamiento

| Acoplamiento | Multiplicador | Mecanismo físico |
|---|---|---|
| **C1 → C2** | ×1,4 | Cuchilla gastada genera vibraciones e irregularidades de carga que aceleran el desgaste de los rodamientos |
| **C1 → C3** | ×2,0 | Cuchilla gastada levanta polvo fino que se incrusta en las toberas del printhead |
| **C2 → C1** | ×1,4 | Guía con juego hace que la cuchilla golpee de forma irregular y se melle antes |
| **C3 → C4** | ×1,4 | Toberas obstruidas no evacúan la gota; el calor queda en la resistencia y la fatiga |
| **C4 → C3** | ×1,5 | Resistencias desajustadas crean puntos calientes que fatigan la nozzle plate |
| **C5 → C6** | ×1,6 | Calefactores con puntos calientes superan la tolerancia térmica del aislante |
| **C6 → C5** | ×1,7 | Aislante degradado obliga a los calefactores a trabajar más → se queman antes |

### 7.4 Bucles de retroalimentación (feedback loops)

| Bucle | Componentes | Producto $M_{ij} \cdot M_{ji}$ | Riesgo numérico |
|---|---|---|---|
| 🔄 Recoating | C1 ↔ C2 | 1,4 × 1,4 = 1,96 | Moderado |
| 🔄 Printhead | C3 ↔ C4 | 1,4 × 1,5 = 2,10 | Moderado |
| 🔄 **Thermal** | **C5 ↔ C6** | **1,6 × 1,7 = 2,72** | **ALTO** |

### 7.5 Salvaguardas numéricas obligatorias

**Para evitar divergencia simulada (especialmente en bucle Thermal):**

1. **Cap de producto acoplado:** $m_{ij}(H_i) \cdot m_{ji}(H_j) \leq 2{,}5$ siempre.
2. **Apagado de seguridad:** si dos componentes acoplados están simultáneamente en estado CRITICAL ($H < 0{,}4$ ambos) y el bucle es activo, **forzar evento de mantenimiento correctivo** del componente con menor Health Index.
3. **Integrador adaptativo recomendado:** Runge-Kutta-Fehlberg o paso fijo de 1 h con cap de variación máxima por paso $|\Delta H_i| \leq 0{,}05$ por hora.

---

## 8. Variables de entrada a la simulación

### 8.1 Constantes (configurables vía fichero externo)

| Variable | Valor por defecto | Fuente |
|---|---|---|
| Temperatura fábrica nominal $T_{fab}$ | 25 °C | HP MJF environmental spec |
| Setpoint curing $T_{set}$ | 180 °C | Literatura MBJ; rango HP 100–200 °C |
| Velocidad recoater $v$ | 150 mm/s | Estimación industria MBJ |
| Frecuencia disparo TIJ $f_d$ | 20 kHz | Estimación TIJ industrial |
| Energía por disparo $E_d$ | 3 µJ | Estimación TIJ |
| Layer thickness | 50 µm | Default HP S100 |
| Presión binder $P_B$ | 0 kPa (desviación) | Regulado por la máquina |

### 8.2 Variables dinámicas durante la simulación

| Variable | Cómo evoluciona | Notas |
|---|---|---|
| Humedad relativa $H$ | Senoidal estacional 30–60 % | Clima Barcelona; 1 ciclo/año |
| Concentración polvo $c_p$ | Función de $H_{C1}$ | $c_p = c_{p,0} \cdot (2 - H_{C1})$ |
| Volumen de trabajo (jobs/mes) | Configurable | Típico: 8–15 jobs/mes |
| Potencia demandada $Q$ | Función de $H_{C6}$ | $Q = Q_0 \cdot (2 - H_{C6})$ |
| Disparos acumulados $N_f$ | Suma según jobs | Cada job ≈ 10⁹–10¹⁰ disparos |
| Capas acumuladas $N_c$ | Suma según jobs | Build de 140 mm a 50 µm = 2.800 capas |
| Ciclos ida/vuelta $N_{iv}$ | = $N_c$ | 1 capa = 1 ciclo recoater |
| Ciclos térmicos $N_{TC}$ | 1 por job | Cada build = 1 ciclo de calentamiento/enfriamiento |
| Ciclos on/off $N_{on}$ | Configurable | Típicamente 1–2 por día en producción 24/7 |

---

## 9. Lógica de simulación paso a paso

```
PARÁMETROS DE ENTRADA al optimizador:
  τ_nom,i para i = C1..C6  (6 intervalos de mantenimiento)

INICIALIZACIÓN:
  Para cada componente i:
    H_i = 1.0
    τ_mant,i = 0
    L_i = 0

BUCLE TEMPORAL: Δt = 1 hora, total = 5 años = 43.800 horas

  PARA CADA TICK t:
    1. Leer/calcular variables externas dinámicas (T, H, c_p, jobs/mes)
    2. Actualizar variables acumulativas (N_f, N_c, N_iv, N_TC, N_on)

    PARA CADA componente i:
      3. Calcular f_ext,i (Sección 5.2)
      4. Calcular f_int,i (Sección 5.3)
      5. Calcular f_cross,i (Sección 7.2)
      6. λ_i = λ_0,i · f_ext,i · f_int,i · f_cross,i
      7. Aplicar cap de variación: |Δ H_i| ≤ 0.05
      8. H_i = H_i - λ_i · Δt
      9. Determinar Operational Status

      10. SI τ_mant,i ≥ τ_nom,i:
            EJECUTAR mantenimiento preventivo
            H_i = min(H_i + 0.5, 1.0)
            τ_mant,i = 0
            REGISTRAR coste preventivo + downtime

      11. SI H_i ≤ 0.1:
            EJECUTAR fallo correctivo
            H_i = 1.0
            τ_mant,i = 0
            L_i = 0
            REGISTRAR coste correctivo + downtime + job perdido

      12. SI bucle activo y dos componentes acoplados en CRITICAL:
            ACTIVAR salvaguarda (forzar correctivo del peor)

      13. τ_mant,i += Δt
      14. L_i += Δt

  REGISTRAR métricas del tick (estados, eventos, downtime)

POSTPROCESO:
  Calcular coste total anual
  Calcular disponibilidad %
  Devolver al optimizador
```

---

## 10. Output esperado

Para cada combinación de intervalos $(\tau_{nom,C1}, ..., \tau_{nom,C6})$:

| Métrica | Descripción | Unidad |
|---|---|---|
| **Coste total anual** | Suma de preventivos + correctivos / 5 | € / año |
| Coste preventivo anual | Solo mantenimientos programados | € / año |
| Coste correctivo anual | Solo averías | € / año |
| Nº fallos por componente | Eventos correctivos en 5 años | nº |
| Nº mantenimientos por componente | Eventos preventivos en 5 años | nº |
| Disponibilidad de máquina | (8.760 - downtime anual) / 8.760 | % |
| Health Index medio por componente | Media temporal de $H_i$ | adim. |
| Tiempo en cada estado | Horas en OK / WARNING / CRITICAL / FAILED | h |

**Restricción de optimización:** disponibilidad > 95 % (HP marketing claim "industrial OEE").

**Función objetivo del optimizador:**

$$\min_{\{\tau_{nom,i}\}} \mathbb{E}[\text{Coste total anual}] \quad \text{s.a.} \quad \text{Disponibilidad} \geq 95\%$$

---

## 11. Recomendaciones de implementación

### 11.1 Estructura de código sugerida

```
digital_twin/
├── config/
│   ├── components.yaml      # Costes, vidas útiles, exponentes
│   ├── couplings.yaml       # Matriz de acoplamientos
│   └── environment.yaml     # Perfiles ambientales y de carga
├── core/
│   ├── component.py         # Clase Component con H, τ_mant, L
│   ├── degradation.py       # Cálculo de λ_i (factores ext, int, cross)
│   ├── events.py            # Gestión de mantenimiento y fallos
│   └── simulator.py         # Bucle temporal principal
├── optimizer/
│   └── optimizer.py         # Búsqueda en espacio de τ_nom
└── analysis/
    ├── metrics.py           # Cálculo de KPIs
    └── plots.py             # Visualización
```

### 11.2 Buenas prácticas

- **Parametrización externa:** todos los costes, vidas útiles, exponentes y multiplicadores deben cargarse desde ficheros de configuración. Nunca hardcodearlos. Esto facilita análisis de sensibilidad y recalibración futura.
- **Logging detallado:** registrar cada evento (mantenimiento, fallo, cambio de estado) con timestamp para poder reconstruir cualquier trayectoria.
- **Reproducibilidad:** semilla aleatoria configurable; las variables dinámicas (humedad estacional) deben ser deterministas o reproducibles.
- **Monte Carlo:** envolver la simulación con N=100–1.000 réplicas (variando perfil de jobs y eventos estocásticos) para obtener distribuciones, no puntos.
- **Validación temprana:** comprobar que con $\tau_{nom,i}$ en los valores de la tabla 4 y condiciones nominales, la disponibilidad supere 95 %.

### 11.3 Tests críticos antes de presentar

1. **Test de neutralidad:** con todas las variables externas en valor nominal y mantenimiento estricto, $\lambda_i \approx \lambda_{0,i}$ y los componentes alcanzan su vida útil nominal.
2. **Test de bucle térmico:** con $H_{C5}$ y $H_{C6}$ ambos en 0,3, verificar que el cap de 2,5 sobre el producto se aplica y la simulación no diverge.
3. **Test de mantenimiento extremo:** $\tau_{nom,i} = 1$ hora → coste preventivo enorme, coste correctivo cercano a cero. Comprueba el extremo del barrido.
4. **Test de no-mantenimiento:** $\tau_{nom,i} = \infty$ → todos los componentes acaban en correctivo, disponibilidad cae. Comprueba el otro extremo.

---

## 12. Resumen ejecutivo

Tres frases:

1. **Modelo:** 3 subsistemas × 2 componentes cada uno = 6 componentes con Health Index $\in [0,1]$ y degradación gobernada por la fórmula $\lambda_i = \lambda_{0,i} \cdot f_{ext,i} \cdot f_{int,i} \cdot f_{cross,i}$ (todos los factores valen 1 en nominal).
2. **Realismo:** datos verificados de la HP Metal Jet S100 (build volume, printheads, potencias, ambiente) con costes y vidas útiles estimadas como parámetros calibrables.
3. **Acoplamientos:** 7 cross-component dependencies que forman 3 bucles de retroalimentación, uno por subsistema, con salvaguardas numéricas para el bucle Thermal C5↔C6.

---

## Anexo A — Glosario rápido

| Símbolo | Significado |
|---|---|
| $H_i$ | Health Index del componente $i$ ($\in [0,1]$) |
| $\lambda_i$ | Tasa de fallo instantánea del componente $i$ |
| $\lambda_{0,i}$ | Tasa de fallo base nominal = $1/L_{nom,i}$ |
| $\tau_{mant,i}$ | Horas desde último mantenimiento (resetable) |
| $\tau_{nom,i}$ | Intervalo de mantenimiento de referencia (variable optimizada) |
| $L_i$ | Horas de vida total acumulada (no resetable salvo correctivo) |
| $L_{nom,i}$ | Vida útil nominal de referencia |
| $f_{ext,i}$ | Factor multiplicativo por condiciones externas |
| $f_{int,i}$ | Factor multiplicativo por estado interno |
| $f_{cross,i}$ | Factor multiplicativo por componentes vecinos degradados |
| $M_{ij}$ | Multiplicador de la matriz de acoplamientos (i sobre j) |
| $a_{k,i}, b_{k,i}, c_{k,i}$ | Exponentes de sensibilidad |
| MBJ | Metal Binder Jetting |
| TIJ | Thermal Inkjet (tecnología HP de printheads) |
| MIM | Metal Injection Molding (industria origen del polvo) |

## Anexo B — Fuentes consultadas

- HP Metal Jet S100 Brochure (4AA8-1958ENW, abril 2023)
- HP Metal Jet Technical Whitepaper (4AA7-3333ENW)
- HP Multi Jet Fusion environmental specifications (familia industrial HP)
- 3D Printing Industry, "HP launches new Metal Jet S100 3D printer at IMTS" (2022)
- Additive Manufacturing, "Understanding HP's Metal Jet" (2022)
- PIM International, "HP Metal Jet: Growing momentum" (2022)
- Literatura científica MBJ: ScienceDirect, OSTI, MDPI sobre binder jetting de 316L
- Industria comparable: ExOne X1 160Pro, Desktop Metal Production System P-50

---

*Documento preparado para el equipo de simulación. Cualquier duda sobre estructura del modelo, ecuaciones o valores: contactar al modelizador.*
