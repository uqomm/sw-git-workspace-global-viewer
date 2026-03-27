# Checklist de validacion - Global Git Dashboard

Archivo objetivo: dashboard/global-git-dashboard.html
Fecha: 2026-03-27

## 1) Smoke funcional

- [ ] Carga inicial sin errores de JavaScript en consola
- [ ] Se renderiza lista de repositorios al abrir la pagina
- [ ] Al hacer click en un repositorio, cambia Timeline y detalle
- [ ] Al hacer click en un commit, actualiza panel de detalle
- [ ] Busqueda filtra por repo, rama, commit y autor
- [ ] Filtro Solo cambios funciona correctamente
- [ ] Filtro Solo detached funciona correctamente
- [ ] Filtro Solo stale funciona correctamente
- [ ] Orden de lista por actividad reciente (descendente) se mantiene
- [ ] Auto-refresh desactivado en file:// y muestra warning
- [ ] Auto-refresh funciona en http/https segun intervalo

## 2) Dark/Light mode

- [ ] Toggle Dark mode cambia tema inmediatamente
- [ ] Tema persiste al recargar (localStorage: gwgv-theme)
- [ ] Si no hay preferencia guardada, usa prefers-color-scheme
- [ ] No hay perdida de legibilidad en light mode
- [ ] No hay perdida de legibilidad en dark mode
- [ ] Estados active/hover se distinguen en light mode
- [ ] Estados active/hover se distinguen en dark mode

## 3) Accesibilidad base

- [ ] Idioma del documento definido (lang=es)
- [ ] Existe h1 unico y descriptivo
- [ ] Labels asociados para cada control de filtro
- [ ] Orden de tabulacion cubre search, checkboxes, select y elementos clickeables
- [ ] Indicador de foco visible en input, select y checkboxes
- [ ] Indicador de foco visible en items de repo y commit
- [ ] Elementos clickeables con teclado (Enter/Espacio) donde aplique
- [ ] Contraste de texto principal cumple en light mode
- [ ] Contraste de texto principal cumple en dark mode
- [ ] Contraste de badges de estado cumple en light mode
- [ ] Contraste de badges de estado cumple en dark mode
- [ ] Area tactil minima de controles interactivos >= 44x44 px

## 4) Coherencia visual

- [ ] Tipografia consistente entre paneles
- [ ] Jerarquia visual clara (titulos, metadatos, contenido)
- [ ] Bordes/radius/sombras consistentes
- [ ] Gradientes sutiles no afectan lectura
- [ ] Colores de estado (ok/warn/bad) consistentes entre vistas y temas

## 5) Responsive

- [ ] Desktop: layout 3 paneles (lista, timeline, detalle)
- [ ] Tablet: layout 2 columnas con panel derecho debajo
- [ ] Mobile: layout 1 columna sin solapamientos
- [ ] Scroll vertical funciona sin cortar contenido
- [ ] Search y filtros siguen siendo usables en mobile

## 6) Seguridad y robustez UI

- [ ] Contenido de texto en HTML inyectado no rompe layout
- [ ] Campos de commit largos no desbordan de forma critica
- [ ] Manejo correcto cuando no hay repos para filtros
- [ ] Manejo correcto cuando un repo no tiene commits

## 7) Evidencia minima por ejecucion

- [ ] Screenshot light mode - vista completa
- [ ] Screenshot dark mode - vista completa
- [ ] Screenshot de foco visible en controles
- [ ] Screenshot de repositorio activo y commit activo
- [ ] Captura de consola sin errores bloqueantes

## 8) Criterio de aprobacion

- [ ] Sin fallos criticos de funcionalidad
- [ ] Sin fallos criticos de legibilidad en light/dark
- [ ] Sin bloqueadores de teclado/foco
- [ ] Sin regresiones responsive criticas
