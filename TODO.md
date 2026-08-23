# Pendientes

Última actualización: 2026-08-23 (tarde)

## Bloqueante / necesita decisión

- [ ] **Chromium no funciona en la Pi Zero W real.** Confirmado en hardware: `chromium-headless-shell` se instala bien (viene del repo de Raspberry Pi OS), pero casca con `Illegal instruction` (SIGILL) al ejecutarse — la CPU (BCM2835/ARM1176/ARMv6) no tiene NEON, que este build de Chromium necesita. Verificado tanto suelto como en la app real (el plugin `calendar` falla igual en producción).
  - Afectaba a 5 de los 7 plugins mantenidos; ya migrados a PIL (sin Chromium): `countdown`, `year_progress`, `weather` (incluye gráfica horaria propia con barras+línea, y un modo "Simple" nuevo estilo InkyPi-Mini-Weather). **Quedan 2**: `calendar` (el más complejo, rejilla de mes con eventos) y `todo_list`. `clock` e `image_upload` nunca usaron Chromium.
  - Solución elegida: reescribir cada plugin afectado para que renderice con PIL directamente, en vez de HTML/CSS/Chromium, usando el helper reutilizable `render_image_pil` en `base_plugin.py` (aplica marco/márgenes/fondo/color de texto sin navegador).

- [ ] **El "negro" del modo 4 grises se ve más claro que el negro 1-bit puro.** Visto en la imagen de arranque (el texto salía en gris claro). Reproducido el pipeline completo en software (dithering + empaquetado real del driver + decodificación) y sale negro sólido correctamente — así que el bug, si lo hay, no está en nuestro código Python. Hipótesis: limitación física del propio modo de 4 grises del panel (la forma de onda para 4 niveles no puede llevar el contraste tan al extremo como una de 2 niveles). **Sin confirmar del todo** — quedó pendiente la prueba directa de comparar el mismo negro sólido en modo 4-grises vs modo 1-bit en el mismo panel.
  - Añadir una opción en el dashboard (Ajustes → Pantalla) para elegir entre modo B&N puro o escala de grises, para quien prefiera el negro más profundo del 1-bit sobre tener sombras de gris.

- [ ] **Cada actualización de pantalla tarda ~2-3 minutos en la Pi real.** El motivo: el propio `getbuffer_4Gray`/`display_4Gray` de Waveshare es Python puro, píxel a píxel, sobre una CPU de ~700MHz. Sin decidir si merece la pena optimizarlo (por ejemplo con numpy) o si se acepta tal cual para un regalo que se actualiza pocas veces al día.

## Bug concreto, arreglo sencillo

- [ ] **Falta `spidev` en `install/ws-requirements.txt`.** El driver real (`epdconfig.py`) hace `import spidev` pero no está listado como dependencia — el servicio se queda en bucle de reinicio nada más instalar en limpio (`ModuleNotFoundError: No module named 'spidev'`). Arreglado a mano en la Pi de pruebas, falta llevarlo al repo.

## Ajustes a código compartido (aplazados a su propia pasada)

- [ ] **`get_font()` (en `utils/app_utils.py`) no cachea las fuentes** — cada llamada vuelve a leer y parsear el `.ttf` del disco. Es una función compartida por todos los plugins (`countdown`, `calendar`, `weather`, la imagen de arranque...), así que un `@lru_cache` ahí beneficiaría a todos a la vez. Fácil y de bajo riesgo, pero se deja para una pasada dedicada a cosas compartidas, no mezclado con el trabajo de un plugin concreto.

## Aplazado, no urgente

- [ ] **Pase de interfaz móvil.** Nunca se ha hecho. Ajustes, Playlists y el dashboard principal ya tienen su diseño definitivo en escritorio — tocaría revisar los tres en móvil.
- [ ] **Intervalo mínimo de rotación (60s) por debajo de lo que recomienda Waveshare (180s)** para este panel.
- [ ] **La lista de playlists no se ordena por hora de inicio**, y **no se pueden reordenar los plugins dentro de una playlist** (solo orden de inserción).
- [ ] **2 plugins de comunidad probados, sin decisión final**: `simple_calendar`, `seniorDashboard_allDay`.
  - `seniorDashboard_allDay` necesita que se le quite otra vez `reboot_manager.py` (hace `sudo reboot` automático si detecta pérdida de red, no se quiere) si se reinstala.
  - Con el problema de Chromium confirmado, `simple_calendar` (pensado como alternativa sin Chromium al `calendar` incluido) cobra más sentido que antes.
  - `flow_progress` (barras día/semana/mes/año), `today` (hora+fecha+progreso del día) y `mini_weather` ya no están pendientes: se integraron directamente como funcionalidad de `year_progress` (modo "Avanzado"), `clock` (Digital Clock: fecha + progreso del día) y `weather` (modo "Simple"), en vez de instalarse como plugins aparte.
- [ ] **Orientación vertical rompe el layout de `weather`** (encontrado al probar el modo Simple, pero afecta también al Avanzado): el título se solapa con "Última actualización", y en Avanzado la cuadrícula de métricas se solapa con la descripción del tiempo. La cabecera (`draw_weather_header`) y la fila de "hoy" no tienen en cuenta que en vertical la altura disponible es mucho mayor que en horizontal. El dispositivo del regalo está fijo en horizontal, así que no es urgente.
