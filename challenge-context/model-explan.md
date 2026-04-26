 Modelos de Degradación: HP Metal Jet S100

  Este documento detalla las funciones matemáticas, el origen de los datos y la lógica de desgaste para los cuatro sistemas críticos de la impresora.

  ---

  1. Cabezal de Impresión (Printhead)
  Es el componente más activo y sensible a las condiciones térmicas durante la operación.

   * Función de Degradación:
      $$\Delta RUL = -(k_{base} \cdot (1 + \alpha \cdot \text{Temp}_{ext}) \cdot \text{Usage})$$

   * Origen de las Variables:
       * $k_{base}$ (Tasa base): Constante definida en sdg/config/components.yaml, modificada por una Distribución Normal ($\mu=1, \sigma=0.05$) al instanciar cada impresora para
         simular pequeñas diferencias de fabricación.
       * $\text{Temp}_{ext}$ (Temperatura exterior): Extraída de la base de datos Open-Meteo (archivos .json en data/raw/). Se usa la temperatura horaria real de la ciudad asignada.
       * $\text{Usage}$ (Uso): Generado mediante una Distribución de Poisson. Simula el número de gotas proyectadas o ciclos de movimiento por hora.

  > En pocas palabras: El cabezal se gasta al imprimir, pero el calor ambiental actúa como un multiplicador de fatiga. Es como un corredor: se cansa por los kilómetros que corre, pero
  se agota mucho más rápido si corre a 40°C que a 20°C.

  ---

  2. Gestión de Polvo (Powder Handling)
  Este sistema sufre degradación constante, independientemente de si la máquina está imprimiendo o no.

   * Función de Degradación:
      $$\Delta RUL = -(k_{base} \cdot (1 + \beta \cdot \text{Humidity}_{ext}))$$

   * Origen de las Variables:
       * $k_{base}$: Valor constante de diseño (vulnerabilidad intrínseca a la corrosión/oxidación).
       * $\text{Humidity}_{ext}$ (Humedad): Datos históricos y proyectados de Open-Meteo. Influye directamente en la fluidez del polvo metálico y la obstrucción de conductos.

  > En pocas palabras: Este componente "sufre" por estar vivo. El polvo metálico es como la sal: en ciudades costeras con mucha humedad, se apelmaza y estropea los mecanismos aunque no
  los toques.

  ---

  3. Lámpara de Curado (Curing Lamp)
  Su degradación no es lineal y depende críticamente de los ciclos de encendido.

   * Función de Degradación:
      $$\Delta RUL = -(k_{base} \cdot \text{Cycles}^2 \cdot (T_{op} - T_{amb}))$$

   * Origen de las Variables:
       * $\text{Cycles}$: Contador de eventos On/Off. El daño es cuadrático ($^2$): encender la máquina dos veces en una hora es cuatro veces más dañino que encenderla una.
       * $T_{op} - T_{amb}$ (Estrés Térmico): Diferencia entre la temperatura de operación ($180^\circ C$) y la temperatura ambiente de la ciudad (Open-Meteo).

  > En pocas palabras: A la lámpara lo que le duele es el "arranque". Como una bombilla antigua, el momento de mayor estrés es cuando pasa de estar fría a estar muy caliente. Cuanto más
  frío hace en la habitación, más violento es ese cambio térmico.

  ---

  4. Sistema de Movimiento (Motion/Servos)
  Sufre desgaste mecánico basado en el esfuerzo físico y la estabilidad del entorno.

   * Función de Degradación:
      $$\Delta RUL = -(k_{base} \cdot \text{Vibration} \cdot \text{Load})$$

   * Origen de las Variables:
       * $\text{Vibration}$: Una base constante más un componente de Ruido Blanco Gaussiano que simula micro-vibraciones aleatorias del suelo o desajustes.
       * $\text{Load}$ (Carga): Variable categórica dependiente del Job Priority. Piezas macizas/densas requieren movimientos más lentos y pesados que piezas huecas.

  > En pocas palabras: Es el desgaste de las correas y motores. Depende de cuánto peso mueven y de si la máquina está vibrando. Es el equivalente a los frenos de un coche: duran menos
  si siempre vas cargado y por carreteras con baches.

  ---

  Resumen de Fuentes
   1. Factores Ambientales: Base de datos Open-Meteo (2016-2035).
   2. Factores Estocásticos: Distribuciones Normal (varianza de máquina) y Poisson (demanda de trabajo).
   3. Factores de Diseño: Archivos de configuración YAML (especificaciones técnicas de HP).