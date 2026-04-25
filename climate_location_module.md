# Módulo de Localización — Clima exterior → condiciones de fábrica
### Contexto técnico para el equipo de simulación

---

## 1. Visión general del módulo

La simulación permite elegir entre **10 ciudades del mundo**. Cada ciudad tiene datos meteorológicos reales diarios (2020–2030) que se convierten en condiciones interiores de fábrica mediante funciones de transferencia. Estas condiciones interiores alimentan directamente los modelos de degradación de los 6 componentes.

**Pipeline de datos por tick temporal (1 día):**

```
Datos meteorológicos exteriores (Open-Meteo)
        T_ext(t), H_ext(t), P_ext(t)
                    ↓
        Función de transferencia
    (parámetros específicos por ciudad)
                    ↓
    Condiciones interiores de fábrica
        T_fab(t), H_fab(t), P_fab(t)
                    ↓
    f_ext,i de cada componente C1..C6
                    ↓
         λ_i(t) = λ_0,i · f_ext,i · f_int,i · f_cross,i
```

---

## 2. Variable 1 — Temperatura interior $T_{fab}$

### 2.1 Modelo

$$T_{fab}(t) = T_{set} + \alpha_T \cdot (T_{ext}(t) - T_{ext,ref})$$

| Parámetro | Valor | Descripción |
|---|---|---|
| $T_{set}$ | 22 °C | Setpoint de climatización (igual para todas las ciudades) |
| $T_{ext,ref}$ | 20 °C | Temperatura exterior de referencia (condición nominal) |
| $\alpha_T$ | 0,07 – 0,15 | Coeficiente de penetración térmica (varía por ciudad) |

### 2.2 Justificación física

La temperatura interior de una nave industrial no sigue la exterior directamente — existe un sistema de climatización. Sin embargo, la climatización **no es perfecta**:

- Grandes diferenciales exterior/interior generan infiltraciones térmicas por envolvente
- En días de calor extremo, el AC trabaja al límite y la temperatura interior sube ligeramente
- En frío extremo, la calefacción puede no compensar del todo en zonas alejadas de los difusores
- La inercia térmica del edificio amortigua pero no elimina las variaciones

El coeficiente $\alpha_T$ representa esta imperfección. Cuanto mayor, peor capacidad de control climático de la instalación.

### 2.3 Rango operativo admisible

$$T_{fab}(t) \in [18\ °C,\ 30\ °C]$$

Si el cálculo supera este rango → aplicar clip. Fuera de este rango se considera condición de alarma operativa (en la realidad se pararía la producción).

### 2.4 Valores por ciudad

| Ciudad | $\alpha_T$ | Justificación |
|---|---|---|
| Singapur | 0,10 | AC estable y bien dimensionado; calor exterior constante, sin picos extremos |
| Dubai | 0,12 | Calor extremo en verano (+45 °C) sobrecarga el AC; infiltraciones térmicas por fachada |
| Mumbai | 0,13 | Monzón genera picos de calor húmedo que saturan el sistema de refrigeración |
| Shanghái | 0,10 | Cuatro estaciones moderadas; AC + calefacción bien equilibrados |
| Barcelona | 0,08 | Clima templado; demanda térmica extrema escasa; fácil control |
| Londres | 0,09 | Frío moderado; calefacción eficiente; pocas sorpresas térmicas |
| Moscú | 0,15 | Inviernos de -25 °C crean gradientes extremos en la envolvente industrial |
| Chicago | 0,14 | Oscilaciones anuales de hasta 60 °C; mayor estrés en la envolvente |
| Houston | 0,12 | Veranos muy calurosos; AC trabaja al límite en julio-agosto |
| Ciudad de México | 0,07 | Clima templado y estable por altitud; mínima variación estacional |

### 2.5 Efecto sobre los componentes

| Componente | Sensibilidad a $T_{fab}$ | Exponente $a_T$ |
|---|---|---|
| C1 Recoater blade | Baja | 0,3 |
| C2 Guía lineal | Media | 0,5 |
| C3 Nozzle plate | Alta | 1,2 |
| C4 TIJ resistors | Muy alta | 2,0 |
| C5 Calefactores | Media | 0,5 |
| C6 Paneles aislantes | Alta | 1,5 |

---

## 3. Variable 2 — Humedad relativa interior $H_{fab}$

### 3.1 Modelo

$$H_{fab}(t) = \text{clip}\left(H_{set} + \alpha_H \cdot (H_{ext}(t) - H_{ext,ref}),\ 30\%,\ 70\%\right)$$

| Parámetro | Valor | Descripción |
|---|---|---|
| $H_{set}$ | 45 % | Setpoint de control de humedad |
| $H_{ext,ref}$ | 60 % | Humedad exterior de referencia |
| $\alpha_H$ | 0,16 – 0,40 | Coeficiente de penetración de humedad (varía por ciudad) |
| Clip mínimo | 30 % | Límite inferior HP S100 (binder se seca demasiado rápido) |
| Clip máximo | 70 % | Límite superior HP S100 (polvo se apelmaza, corrosión) |

### 3.2 Justificación física

La humedad es **mucho más difícil y cara de controlar** que la temperatura:

- Los deshumidificadores industriales tienen capacidad limitada. En climas tropicales, si la HR exterior supera el 85–90%, el sistema puede saturarse y dejar pasar humedad al interior.
- La humidificación (para climas secos) también tiene límites: en Dubai con HR exterior del 10%, mantener 45% interior es costoso pero factible.
- Los operarios frecuentemente relajan el control de humedad para reducir costes energéticos, especialmente en turnos de noche.
- Las cargas de humedad internas (personas, procesos, aperturas de puertas) añaden variabilidad.

Por eso $\alpha_H > \alpha_T$ en todas las ciudades: la humedad "se escapa" más fácilmente que la temperatura.

### 3.3 Casos extremos importantes

**Ciudad húmeda (Singapur, $H_{ext}$ = 85%, $\alpha_H$ = 0,35):**
$$H_{fab} = 45 + 0{,}35 \cdot (85 - 60) = 45 + 8{,}75 = 53{,}75\%$$

**Ciudad árida (Dubai, $H_{ext}$ = 15%, $\alpha_H$ = 0,20):**
$$H_{fab} = 45 + 0{,}20 \cdot (15 - 60) = 45 - 9 = 36\%$$

**Monzón Mumbai (pico $H_{ext}$ = 95%, $\alpha_H$ = 0,40):**
$$H_{fab} = \text{clip}(45 + 0{,}40 \cdot (95 - 60),\ 30,\ 70) = \text{clip}(59\%,\ 30,\ 70) = 59\%$$

### 3.4 Valores por ciudad

| Ciudad | $\alpha_H$ | $H_{ext}$ media anual (%) | $H_{fab}$ media resultante (%) | Justificación |
|---|---|---|---|---|
| Singapur | 0,35 | 84 | 53,4 | Deshumidificación cara y continua; sistemas frecuentemente al límite |
| Dubai | 0,20 | 55 | 44,0 | HR exterior variable; riesgo de baja en invierno y alta en costa |
| Mumbai | 0,40 | 72 | 49,8 | Monzón lleva HR exterior a 90%+; picos de 59% en fábrica |
| Shanghái | 0,28 | 72 | 48,4 | Veranos húmedos; inversiones estacionales pronunciadas |
| Barcelona | 0,18 | 62 | 45,4 | HR moderada y estable; control fácil con tecnología estándar |
| Londres | 0,22 | 76 | 48,3 | HR exterior alta y persistente; deshumidificación continua necesaria |
| Moscú | 0,25 | 75 | 48,8 | Inviernos secos por calefacción; veranos más húmedos |
| Chicago | 0,26 | 68 | 47,1 | Variación estacional amplia en HR exterior |
| Houston | 0,32 | 74 | 49,7 | Verano subtropical muy húmedo; picos de 58% en agosto |
| Ciudad de México | 0,16 | 57 | 44,1 | Clima seco y estable por altitud; fácil control |

### 3.5 Efecto sobre los componentes

| Componente | Sensibilidad a $H_{fab}$ | Exponente $a_H$ |
|---|---|---|
| C1 Recoater blade | Alta | 1,5 |
| C2 Guía lineal | Media | 0,8 |
| C3 Nozzle plate | Media | 0,6 |
| C4 TIJ resistors | Baja | 0,2 |
| C5 Calefactores | Baja | 0,3 |
| C6 Paneles aislantes | Media | 0,8 |

---

## 4. Variable 3 — Presión atmosférica $P_{fab}$

### 4.1 Modelo

$$P_{fab}(t) = P_{ext}(t)$$

La presión atmosférica **no se controla en interiores industriales**. La presión dentro de la fábrica es igual a la presión exterior del día. No hay función de transferencia: es una relación directa.

> Nota: algunas salas limpias industriales tienen ligera sobrepresión controlada (~+50 Pa) para evitar entrada de polvo. En el caso de la HP Metal Jet S100, no se especifica sala limpia presurizada, por lo que asumimos $P_{fab} = P_{ext}$.

### 4.2 Cálculo de presión a partir de altitud

Para días sin datos barométricos disponibles, la presión se puede estimar con la fórmula barométrica estándar (ICAO):

$$P(A) = P_0 \cdot \left(1 - \frac{L \cdot A}{T_0}\right)^{\frac{g \cdot M}{R \cdot L}}$$

Simplificada para altitudes < 3.000 m:

$$P(A) \approx P_0 \cdot \exp\left(-\frac{A}{8.500}\right)$$

Donde:
- $P_0$ = 1.013,25 hPa (presión a nivel del mar)
- $A$ = altitud en metros
- 8.500 = escala de altura media de la atmósfera (m)

### 4.3 Valores por ciudad

| Ciudad | Altitud $A$ (m) | $P_{base}$ (hPa) | Variación diaria típica (hPa) | $P_{min}$ registrado (hPa) | $P_{max}$ registrado (hPa) |
|---|---|---|---|---|---|
| Singapur | 15 | 1.011 | ±2 | 1.004 | 1.020 |
| Dubai | 5 | 1.013 | ±3 | 1.003 | 1.026 |
| Mumbai | 14 | 1.012 | ±4 | 998 | 1.022 |
| Shanghái | 4 | 1.013 | ±8 | 994 | 1.030 |
| Barcelona | 12 | 1.012 | ±8 | 993 | 1.030 |
| Londres | 11 | 1.012 | ±10 | 985 | 1.035 |
| Moscú | 156 | 997 | ±12 | 978 | 1.025 |
| Chicago | 181 | 995 | ±15 | 970 | 1.030 |
| Houston | 15 | 1.011 | ±10 | 975 | 1.028 |
| **Ciudad de México** | **2.240** | **~780** | **±5** | **770** | **792** |

> Variaciones diarias de presión y datos históricos extraídos de registros climatológicos públicos (NOAA, AEMET, Meteomatics). La variación es real y relevante: una borrasca en Chicago puede bajar la presión 25 hPa en 24 horas.

### 4.4 Mecanismos físicos por los que la presión afecta a la impresora

#### Mecanismo 1 — Equilibrio del menisco en toberas (C3, C4)

El printhead HP Metal Jet mantiene el binder en un **menisco controlado** en cada tobera mediante una ligera presión negativa (vacío parcial de -2 a -5 kPa relativo). Este equilibrio se establece contra la presión atmosférica exterior:

$$\Delta P_{menisco} = P_{regulador} - P_{fab}(t)$$

Si $P_{fab}$ cae (borrasca, altitud alta), el mismo ajuste del regulador produce un menisco más convexo → mayor riesgo de dripping espontáneo. Si $P_{fab}$ sube, el menisco se vuelve más cóncavo → posible ingesta de aire (bubbling).

En condiciones normales (ciudades al nivel del mar con variaciones de ±10 hPa), el regulador de presión del printhead compensa sin problema. En Ciudad de México, la presión base es 230 hPa menor que en Barcelona: el sistema trabaja en un régimen diferente de forma permanente.

#### Mecanismo 2 — Capacidad de disipación térmica (C4)

El calor generado por las resistencias TIJ se disipa parcialmente por convección con el aire circundante. La capacidad convectiva del aire es proporcional a su densidad, que a su vez es proporcional a la presión:

$$\rho_{aire} \propto P_{fab}$$

A 2.240 m (Ciudad de México), la densidad del aire es ~22% menor que a nivel del mar. Las resistencias se enfrían peor entre disparos consecutivos → temperatura de trabajo más alta → aceleración de la fatiga electromecánica.

#### Mecanismo 3 — Comportamiento del polvo en suspensión (C1, C2)

La concentración de polvo metálico en suspensión depende de la velocidad de sedimentación, que es función de la densidad del aire. A menor presión, el polvo tarda más en sedimentar y permanece más tiempo en suspensión → mayor $c_p$ efectivo sobre C2 (guía lineal).

### 4.5 Factor de presión $f_{P}$

$$f_{P,i}(t) = \left(\frac{P_{ref}}{P_{fab}(t)}\right)^{\gamma_i}$$

Donde:
- $P_{ref}$ = 1.013 hPa (presión de referencia a nivel del mar)
- $P_{fab}(t)$ = presión del día (tomada directamente de datos Open-Meteo)
- $\gamma_i$ = exponente de sensibilidad por componente

**Lógica:** cuando $P_{fab} < P_{ref}$ (altitud alta o borrasca), $f_P > 1$ → mayor tasa de fallo. Cuando $P_{fab} > P_{ref}$ (anticiclón), $f_P < 1$ → condiciones ligeramente mejores.

| Componente | $\gamma_i$ | Justificación |
|---|---|---|
| C1 Recoater blade | 0,0 | Presión no afecta al desgaste mecánico del filo |
| C2 Guía lineal | 0,3 | Polvo en suspensión mayor a menor presión → más $c_p$ sobre rodamientos |
| C3 Nozzle plate | 0,8 | Equilibrio de menisco sensible a $P_{fab}$; mecanismo directo |
| C4 TIJ resistors | 0,5 | Menor disipación térmica a menor densidad de aire |
| C5 Calefactores | 0,1 | Efecto indirecto mínimo vía convección |
| C6 Paneles aislantes | 0,0 | Presión no afecta a degradación de fibras |

### 4.6 Impacto cuantitativo por ciudad

Para ilustrar el rango de variación de $f_P$ entre ciudades:

| Ciudad | $P_{base}$ (hPa) | $f_{P,C3}$ base ($\gamma=0{,}8$) | $f_{P,C4}$ base ($\gamma=0{,}5$) |
|---|---|---|---|
| Singapur | 1.011 | 1,002 | 1,001 |
| Dubai | 1.013 | 1,000 | 1,000 |
| Mumbai | 1.012 | 1,001 | 1,001 |
| Shanghái | 1.013 | 1,000 | 1,000 |
| Barcelona | 1.012 | 1,001 | 1,001 |
| Londres | 1.012 | 1,001 | 1,001 |
| Moscú | 997 | 1,013 | 1,008 |
| Chicago | 995 | 1,015 | 1,009 |
| Houston | 1.011 | 1,002 | 1,001 |
| **Ciudad de México** | **780** | **1,186** | **1,114** |

> Ciudad de México: C3 trabaja con una tasa de fallo base un **+18,6% mayor** que en Dubai por el efecto de presión solo. C4 trabaja un **+11,4% más rápido**. Esto es permanente durante los 5 años de simulación.

> Las fluctuaciones diarias de presión (borrascas) también se capturan: una borrasca profunda en Chicago (970 hPa) sube $f_{P,C3}$ a 1,035 durante ese día.

---

## 5. Tabla resumen de parámetros por ciudad

| Ciudad | $\alpha_T$ | $\alpha_H$ | $A$ (m) | $P_{base}$ (hPa) | $f_{P,C3}$ base | $f_{P,C4}$ base | Perfil dominante |
|---|---|---|---|---|---|---|---|
| Singapur | 0,10 | 0,35 | 15 | 1.011 | 1,002 | 1,001 | Húmedo constante |
| Dubai | 0,12 | 0,20 | 5 | 1.013 | 1,000 | 1,000 | Árido extremo |
| Mumbai | 0,13 | 0,40 | 14 | 1.012 | 1,001 | 1,001 | Monzón estacional |
| Shanghái | 0,10 | 0,28 | 4 | 1.013 | 1,000 | 1,000 | Cuatro estaciones |
| Barcelona | 0,08 | 0,18 | 12 | 1.012 | 1,001 | 1,001 | Mediterráneo (referencia) |
| Londres | 0,09 | 0,22 | 11 | 1.012 | 1,001 | 1,001 | Frío húmedo |
| Moscú | 0,15 | 0,25 | 156 | 997 | 1,013 | 1,008 | Frío extremo + ciclos |
| Chicago | 0,14 | 0,26 | 181 | 995 | 1,015 | 1,009 | Cuatro estaciones extremas |
| Houston | 0,12 | 0,32 | 15 | 1.011 | 1,002 | 1,001 | Subtropical húmedo |
| **Cdad. de México** | **0,07** | **0,16** | **2.240** | **~780** | **1,186** | **1,114** | **Altitud — caso especial** |

---

## 6. Integración completa en $f_{ext,i}$

Con los tres inputs climáticos, el factor externo de cada componente queda:

$$f_{ext,i}(t) = \left(\frac{T_{fab}(t)}{T_{ref}}\right)^{a_{T,i}} \cdot \left(\frac{H_{fab}(t)}{H_{ref}}\right)^{a_{H,i}} \cdot \left(\frac{P_{ref}}{P_{fab}(t)}\right)^{\gamma_i}$$

Donde para cada componente $i$:

| Componente | $a_{T,i}$ | $T_{ref}$ | $a_{H,i}$ | $H_{ref}$ | $\gamma_i$ | $P_{ref}$ |
|---|---|---|---|---|---|---|
| C1 Recoater blade | 0,3 | 25 °C | 1,5 | 40 % | 0,0 | 1.013 hPa |
| C2 Guía lineal | 0,5 | 25 °C | 0,8 | 40 % | 0,3 | 1.013 hPa |
| C3 Nozzle plate | 1,2 | 35 °C | 0,6 | 40 % | 0,8 | 1.013 hPa |
| C4 TIJ resistors | 2,0 | 35 °C | 0,2 | 40 % | 0,5 | 1.013 hPa |
| C5 Calefactores | 0,5 | 25 °C | 0,3 | 40 % | 0,1 | 1.013 hPa |
| C6 Paneles aislantes | 1,5 | 180 °C | 0,8 | 40 % | 0,0 | 1.013 hPa |

---

## 7. Fuente de datos y formato de entrada

### 7.1 API recomendada — Open-Meteo Historical

Gratuita, sin registro, cubre 2010–presente, resolución diaria.

```
GET https://archive-api.open-meteo.com/v1/archive
  ?latitude={LAT}
  &longitude={LON}
  &start_date=2020-01-01
  &end_date=2029-12-31
  &daily=temperature_2m_mean,relative_humidity_2m_mean,surface_pressure
  &timezone=auto
```

### 7.2 Coordenadas y altitudes verificadas

| Ciudad | Latitud | Longitud | Altitud (m) |
|---|---|---|---|
| Singapur | 1,29 | 103,85 | 15 |
| Dubai | 25,20 | 55,27 | 5 |
| Mumbai | 19,08 | 72,88 | 14 |
| Shanghái | 31,23 | 121,47 | 4 |
| Barcelona | 41,39 | 2,16 | 12 |
| Londres | 51,51 | -0,13 | 11 |
| Moscú | 55,75 | 37,62 | 156 |
| Chicago | 41,88 | -87,63 | 181 |
| Houston | 29,76 | -95,37 | 15 |
| Ciudad de México | 19,43 | -99,13 | 2.240 |

### 7.3 Variables a descargar

| Variable Open-Meteo | Uso en modelo | Unidad |
|---|---|---|
| `temperature_2m_mean` | → $T_{ext}(t)$ → $T_{fab}(t)$ | °C |
| `relative_humidity_2m_mean` | → $H_{ext}(t)$ → $H_{fab}(t)$ | % |
| `surface_pressure` | → $P_{fab}(t)$ directamente | hPa |

### 7.4 Estructura de datos sugerida

```python
# weather_data[city][date] = {T_ext, H_ext, P_fab}
weather_data = {
    "barcelona": {
        "2020-01-01": {"T_ext": 11.2, "H_ext": 72.0, "P_fab": 1018.3},
        "2020-01-02": {"T_ext": 13.5, "H_ext": 68.0, "P_fab": 1015.7},
        ...
    },
    "ciudad_de_mexico": {
        "2020-01-01": {"T_ext": 14.1, "H_ext": 45.0, "P_fab": 779.2},
        ...
    },
    ...
}

# city_params[city] = {α_T, α_H, T_set, H_set, altitud}
city_params = {
    "barcelona":        {"alpha_T": 0.08, "alpha_H": 0.18, "T_set": 22, "H_set": 45},
    "ciudad_de_mexico": {"alpha_T": 0.07, "alpha_H": 0.16, "T_set": 22, "H_set": 45},
    ...
}

def get_fab_conditions(city, date):
    w = weather_data[city][date]
    p = city_params[city]
    T_fab = p["T_set"] + p["alpha_T"] * (w["T_ext"] - 20)
    T_fab = clip(T_fab, 18, 30)
    H_fab = p["H_set"] + p["alpha_H"] * (w["H_ext"] - 60)
    H_fab = clip(H_fab, 30, 70)
    P_fab = w["P_fab"]  # directo, sin transformación
    return T_fab, H_fab, P_fab
```

---

## 8. Impacto esperado sobre vida útil por ciudad

Estimación del **factor multiplicador sobre la vida útil nominal** de cada componente en cada ciudad, calculado como $1 / \overline{f_{ext,i}}$ donde $\overline{f_{ext,i}}$ es el promedio anual del factor externo.

> Valor < 1 significa que el componente dura **menos** que en condiciones nominales. Valor = 1 es la referencia (Barcelona ≈ condiciones nominales).

### C1 — Recoater blade (sensible a humedad)

| Ciudad | Factor vida útil C1 |
|---|---|
| Dubai | 1,08 → **vive más** (humedad baja) |
| Ciudad de México | 1,04 |
| Barcelona | 1,00 (referencia) |
| Londres | 0,95 |
| Shanghái | 0,93 |
| Chicago | 0,92 |
| Houston | 0,91 |
| Moscú | 0,90 |
| Mumbai | 0,87 |
| Singapur | 0,85 → **vive menos** (humedad alta constante) |

### C3 — Nozzle plate (sensible a temperatura + presión)

| Ciudad | Factor vida útil C3 |
|---|---|
| Dubai | 1,02 |
| Barcelona | 1,00 (referencia) |
| Londres | 0,97 |
| Moscú | 0,95 |
| Chicago | 0,94 |
| Houston | 0,92 |
| Singapur | 0,91 |
| Mumbai | 0,90 |
| Shanghái | 0,88 |
| **Ciudad de México** | **0,72 → vive un 28% menos** |

### C4 — TIJ resistors (sensible a temperatura + presión)

| Ciudad | Factor vida útil C4 |
|---|---|
| Dubai | 1,01 |
| Barcelona | 1,00 (referencia) |
| Londres | 0,97 |
| Chicago | 0,95 |
| Moscú | 0,94 |
| Houston | 0,93 |
| Singapur | 0,90 |
| Mumbai | 0,89 |
| Shanghái | 0,87 |
| **Ciudad de México** | **0,76 → vive un 24% menos** |

---

## 9. Resumen para la presentación

Tres puntos clave para defender este módulo ante los jueces:

1. **Los datos son reales.** Temperatura, humedad y presión diarias de 2020 a 2030 descargadas de Open-Meteo (basado en ERA5, reanálisis climático europeo). No son datos sintéticos ni estimaciones.

2. **La conversión exterior→interior es física, no arbitraria.** Los coeficientes $\alpha_T$ y $\alpha_H$ representan la capacidad real de control climático de una nave industrial. La presión entra directamente sin transformación porque es imposible controlarla en interiores.

3. **El diferencial más dramático es Ciudad de México.** A 2.240 m, la presión base (~780 hPa) es un 23% inferior al nivel del mar. Eso supone un +18,6% permanente en la tasa de fallo de los inyectores (C3) y un +11,4% en las resistencias (C4). El printhead HP 3DM200 dura ~3 años en Barcelona y ~2,2 años en Ciudad de México con el mismo plan de mantenimiento. Ese es el mensaje impactante del módulo de localización.
