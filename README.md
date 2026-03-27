# sw-git-workspace-global-viewer

Visor global y de solo lectura para revisar el estado de multiples repositorios Git en un workspace.

## Incluye

- Agente reusable: `.github/agents/git-workspace-global-viewer.agent.md`
- Script escaner: `scripts/git-global-viewer.py`
- Dashboard generado: `dashboard/global-git-dashboard.md`
- Dashboard visual interactivo: `dashboard/global-git-dashboard.html`

## Uso rapido

```powershell
python scripts/git-global-viewer.py --root "C:/Users/artur/development" --max-depth 3 --output dashboard/global-git-dashboard.md
```

## Uso visual tipo GitKraken (solo lectura)

Genera Markdown + HTML interactivo en una sola ejecucion:

```powershell
python scripts/git-global-viewer.py --root "C:/Users/artur/development" --max-depth 3 --mode both --graph-limit 25 --commit-limit 8 --commit-files-limit 12 --output dashboard/global-git-dashboard.md --html-output dashboard/global-git-dashboard.html
```

Abrir visor HTML:

```powershell
start dashboard/global-git-dashboard.html
```

Opciones de modo:

- `--mode md`: solo Markdown
- `--mode html`: solo visor HTML
- `--mode both`: ambos formatos

## Garantias del script

- No ejecuta comandos mutantes (`add`, `commit`, `push`, `pull`, `checkout`)
- Solo usa lectura: `git branch`, `git rev-parse`, `git rev-list`, `git status`, `git log`
- Ignora carpetas pesadas: `node_modules`, `vendor`, `.venv`, `dist`, `build`

## Salida

Tabla Markdown con:

- Repositorio
- Rama actual
- Sync remoto (ahead/behind/up to date)
- Cambios locales (modificados/anadidos/eliminados/untracked)
- Ultimo commit

Vista HTML con:

- Layout de 3 paneles: repos, timeline/grafo, detalle de commit
- Filtro por texto (repo/rama/commit/estado)
- Filtros rapidos: cambios, detached, stale
- Grafo de commits por repositorio (vista tipo cliente Git)
- Detalle de commit con archivos cambiados (read-only)
- Auto-refresh opcional (recarga de visor)
- Tarjetas KPI globales

## Opciones clave

- `--graph-limit`: lineas maximas de grafo por repo en HTML
- `--commit-limit`: commits recientes por repo para el panel de detalle
- `--commit-files-limit`: archivos maximos mostrados por commit
- `--auto-refresh-sec`: activa auto-refresh por defecto en HTML (0 deshabilita)

Y una seccion de alertas para:

- `Detached HEAD`
- Repos con cambios locales
- Repos potencialmente desactualizados (sin commits recientes)
