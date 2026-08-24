# Pendientes

Última actualización: 2026-08-24

## Bloqueante / necesita decisión

- [x] **Chromium no funciona en la Pi Zero W real** (la CPU, BCM2835/ARM1176/ARMv6, no tiene NEON, que Chromium requiere desde hace años — casca con `Illegal instruction`). **Resuelto de otra forma a la planeada inicialmente.**
  - `countdown`, `year_progress`, `weather` y `clock` ya se habían reescrito para renderizar con PIL directamente (sin navegador), usando `render_image_pil` en `base_plugin.py`. Ese trabajo se queda tal cual, no se deshace.
  - Para `calendar` se investigó a fondo si había alguna alternativa a "dibujar todo a mano en PIL", y se encontró: **WebKitGTK** (el motor del navegador GNOME Web, distinto y no relacionado con el abandonado `wkhtmltopdf`) sigue dando soporte activo a ARMv6 sin NEON, con el JIT de JavaScript desactivado (más lento, pero funcional). Probado de verdad en la Pi Zero W del regalo: renderiza `calendar.html`/FullCalendar correctamente en 32-36s (frente a los 2-3 min que ya tarda el propio refresco de pantalla, así que es asumible), con un pico de memoria de ~350MB sobre 426MB totales — ajustado pero estable, y como corre en un proceso aparte (`xvfb-run` + Python del sistema, ver `utils/webkit_screenshot.py`), esa memoria se libera entera al terminar cada renderizado.
  - `take_screenshot()` en `utils/image_utils.py` ahora prueba Chromium primero (por si algún día se despliega en hardware que sí lo soporte) y cae automáticamente a WebKitGTK si Chromium no está instalado *o* si está instalado pero falla al renderizar (justo el caso de esta Pi). `calendar.py` ha vuelto a su versión HTML/FullCalendar original (con las traducciones, simplificaciones y arreglos de bugs ya hechos encima).
  - **Dependencias nuevas en la Pi, instaladas a mano, pendiente de añadir a los scripts de instalación** (`install/ws-requirements.txt` o similar): `python3-gi`, `python3-gi-cairo`, `gir1.2-webkit2-4.1`, `xvfb`.
  - Con esto, `todo_list` (el único plugin que seguía pendiente de Chromium) probablemente no necesite una migración a PIL tampoco — revisar si le vale el mismo mecanismo de `calendar` antes de ponerse a reescribirlo a mano.

- [ ] **Las vistas Día y Semana de `calendar` desbordan y usan scroll interno en vez de encajar en la altura disponible** — solo estas dos, `Mes`/`Multi-Semana`/`Lista` funcionan perfectamente. Investigado a fondo: NO es un problema de nuestro CSS ni de WebKitGTK en general (Chromium tiene el mismo fallo, confirmado con la misma prueba). La causa está dentro del propio HTML que genera FullCalendar — concretamente `.fc-scrollgrid-section-body` (la fila de tabla que debería ocupar "el resto del espacio disponible" tras el encabezado y la franja de "todo el día") se queda con una altura mínima/natural en vez de expandirse, algo achacable a cómo los navegadores reparten altura entre filas de una tabla HTML cuando una debe llevarse el espacio restante — un área con diferencias históricas conocidas entre motores. `scrollTime: '00:00:00'` ya se añadió para que al menos empiece a mostrarse desde la hora configurada (antes arrancaba cerca de la hora actual), pero el contenido que no cabe sigue sin verse sin hacer scroll, que en una imagen estática no es posible.
  - Aplazado a propósito, no se ha intentado ningún arreglo (parche por JavaScript tras el renderizado, o volver esas dos vistas concretas a PIL manteniendo el resto en FullCalendar).

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
- [x] **`seniorDashboard_allDay` (plugin de comunidad, calendario en lista + tiempo).** Resuelto sin instalar el plugin de terceros: se construyó `agenda`, un plugin propio con la misma idea (lista de Hoy/Mañana/pasado mañana + panel de tiempo compacto), reutilizando el fetch de ICS de `calendar` y el Open-Meteo de `weather` en vez de depender de DWD y de un sistema de traducción aparte. Sin `reboot_manager.py` ni ningún otro código de terceros que auditar.
- [ ] **1 plugin de comunidad probado, sin decisión final**: `simple_calendar`.
  - Pierde algo de sentido ahora que `calendar` renderiza vía WebKitGTK cuando Chromium falla — revisar si sigue mereciendo la pena probarlo.
  - `flow_progress` (barras día/semana/mes/año), `today` (hora+fecha+progreso del día) y `mini_weather` ya no están pendientes: se integraron directamente como funcionalidad de `year_progress` (modo "Avanzado"), `clock` (Digital Clock: fecha + progreso del día) y `weather` (modo "Simple"), en vez de instalarse como plugins aparte.
- [ ] **Orientación vertical rompe el layout de `weather`** (encontrado al probar el modo Simple, pero afecta también al Avanzado): el título se solapa con "Última actualización", y en Avanzado la cuadrícula de métricas se solapa con la descripción del tiempo. La cabecera (`draw_weather_header`) y la fila de "hoy" no tienen en cuenta que en vertical la altura disponible es mucho mayor que en horizontal. El dispositivo del regalo está fijo en horizontal, así que no es urgente.
