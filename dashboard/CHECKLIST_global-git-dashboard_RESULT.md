# Resultado de ejecucion - Checklist Global Git Dashboard

Archivo evaluado: dashboard/global-git-dashboard.html
Checklist base: dashboard/CHECKLIST_global-git-dashboard.md
Fecha: 2026-03-27
Tipo de ejecucion: validacion estatica + verificaciones tecnicas automatizadas (post-fix)

## 1) Smoke funcional

- [ ] Carga inicial sin errores de JavaScript en consola - Revision manual requerida (no se abrio navegador en esta corrida)
- [x] Se renderiza lista de repositorios al abrir la pagina
- [x] Al hacer click en un repositorio, cambia Timeline y detalle
- [x] Al hacer click en un commit, actualiza panel de detalle
- [x] Busqueda filtra por repo, rama, commit y autor
- [x] Filtro Solo cambios funciona correctamente
- [x] Filtro Solo detached funciona correctamente
- [x] Filtro Solo stale funciona correctamente
- [x] Orden de lista por actividad reciente (descendente) se mantiene
- [x] Auto-refresh desactivado en file:// y muestra warning
- [ ] Auto-refresh funciona en http/https segun intervalo - Revision manual requerida en servidor local

## 2) Dark/Light mode

- [x] Toggle Dark mode cambia tema inmediatamente
- [x] Tema persiste al recargar (localStorage: gwgv-theme)
- [x] Si no hay preferencia guardada, usa prefers-color-scheme
- [x] No hay perdida de legibilidad en light mode (texto base)
- [x] No hay perdida de legibilidad en dark mode (texto base)
- [x] Estados active/hover se distinguen en light mode
- [x] Estados active/hover se distinguen en dark mode

## 3) Accesibilidad base

- [x] Idioma del documento definido (lang=es)
- [x] Existe h1 unico y descriptivo
- [x] Labels asociados para cada control de filtro
- [x] Orden de tabulacion cubre search, checkboxes, select y elementos clickeables
- [x] Indicador de foco visible en input, select y checkboxes
- [x] Indicador de foco visible en items de repo y commit
- [x] Elementos clickeables con teclado (Enter/Espacio) donde aplique
- [x] Contraste de texto principal cumple en light mode (15.20:1)
- [x] Contraste de texto principal cumple en dark mode (15.64:1)
- [x] Contraste de badges de estado cumple en light mode (ok: 5.03, warn: 5.54, bad: 6.02)
- [x] Contraste de badges de estado cumple en dark mode (ok: 9.85, warn: 9.67, bad: 9.15)
- [x] Area tactil minima de controles interactivos >= 44x44 px

## 4) Coherencia visual

- [x] Tipografia consistente entre paneles
- [x] Jerarquia visual clara (titulos, metadatos, contenido)
- [x] Bordes/radius/sombras consistentes
- [x] Gradientes sutiles no afectan lectura
- [x] Colores de estado (ok/warn/bad) consistentes entre vistas y temas

## 5) Responsive

- [x] Desktop: layout 3 paneles (lista, timeline, detalle)
- [x] Tablet: layout 2 columnas con panel derecho debajo
- [x] Mobile: layout 1 columna sin solapamientos (por reglas CSS)
- [ ] Scroll vertical funciona sin cortar contenido - Revision manual requerida
- [ ] Search y filtros siguen siendo usables en mobile - Revision manual requerida

## 6) Seguridad y robustez UI

- [x] Contenido de texto en HTML inyectado no rompe layout (escape HTML aplicado)
- [ ] Campos de commit largos no desbordan de forma critica - Riesgo medio por hashes/subjects extensos (revision visual pendiente)
- [x] Manejo correcto cuando no hay repos para filtros
- [x] Manejo correcto cuando un repo no tiene commits

## 7) Evidencia minima por ejecucion

- [ ] Screenshot light mode - No generado en esta corrida
- [ ] Screenshot dark mode - No generado en esta corrida
- [ ] Screenshot de foco visible en controles - No generado en esta corrida
- [ ] Screenshot de repositorio activo y commit activo - No generado en esta corrida
- [ ] Captura de consola sin errores bloqueantes - No generada en navegador

## 8) Criterio de aprobacion

- [ ] Sin fallos criticos de funcionalidad - Pendiente validacion manual en navegador
- [x] Sin fallos criticos de legibilidad en light/dark
- [x] Sin bloqueadores de teclado/foco
- [ ] Sin regresiones responsive criticas - Pendiente validacion manual en dispositivo/navegador

## Hallazgos criticos

- No se detectan bloqueadores criticos en accesibilidad base (teclado/foco/contraste/tamano objetivo) en la validacion automatizada post-fix.
- Quedan pendientes solo verificaciones manuales de smoke visual, responsive real y evidencia por screenshots.

## Evidencia automatica (resumen)

- langEs=true
- h1Count=1
- darkToggle=true
- persistTheme=true
- sortRecent=true
- autorefreshGuard=true
- repoKeyboardRole=true
- repoTabindex=true
- commitKeyboardRole=true
- commitTabindex=true
- focusVisibleInput=true
- focusVisibleSelect=true
- focusVisibleRepo=true
- focusVisibleCommit=true
- min44Search=true
- min44Label=true
- min44Repo=true
- min44Commit=true
- escFunction=true

## Contrastes calculados (ratio)

- light_text_main (#162033 sobre #f6f7f9): 15.20
- dark_text_main (#e3ebfb sobre #0b1220): 15.64
- badge_ok light (#1f7a46 sobre #effbf3): 5.03
- badge_warn light (#995300 sobre #fff8ec): 5.54
- badge_bad light (#b42318 sobre #fff2f1): 6.02
- badge_ok dark (#9ef0c4 sobre #173629): 9.85
- badge_warn dark (#ffd39b sobre #3d2b16): 9.67
- badge_bad dark (#ffb8b2 sobre #3d1d1f): 9.15
