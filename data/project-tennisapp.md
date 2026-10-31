# TennisApp (proyecto de título de Analista Programador Computacional)

## Resumen de TennisApp

TennisApp es un proyecto grupal de título en el que Maximiliano Huerta se encargó del registro de usuarios, la autenticación con JWT, el login por QR, el tercer entrenador de demostración, la corrección del diseño móvil y la operación del pipeline de despliegue en AWS. Es el proyecto de título para la carrera de Analista Programador Computacional en DUOC UC (no corresponde a Ingeniería en Informática, que cursa actualmente): una plataforma web para entrenadores y jugadores de tenis que permite agendar partidos, llevar el marcador punto a punto en vivo, calcular estadísticas, gestionar la relación entrenador-jugador y recibir notificaciones en tiempo real. Se compone de una SPA en React 19 con TypeScript y Vite (carpeta `ProyectoTitulo-Front`) y una API en Django con Django REST Framework y Channels (carpeta `TennisApp-back`). Ambas viven en el monorepo `proyecto-de-titulo`, junto con documentación (Gantt, diagramas, historias de usuario, requerimientos, casos de uso y plan de pruebas) y un workflow de GitHub Actions.

## Propósito y usuarios de TennisApp

- Dos roles en el modelo de usuario: Jugador y Entrenador.
- El entrenador administra a sus jugadores (solicitudes de asociación, nivel del jugador, dashboard, historial y partidos invitados de sus alumnos) y agenda partidos.
- El jugador registra y consulta sus partidos y estadísticas, y se conecta con otros jugadores como contactos (amistad).
- Para la defensa final se prepararon tres entrenadores de demostración, cada uno con cinco alumnos, accesibles desde el celular mediante códigos QR.

## Módulos funcionales de TennisApp

Cada módulo corresponde a una app de Django y a vistas del frontend:

- Usuarios y autenticación (`apiusuario`): registro diferenciado de jugador y entrenador, login, sesiones JWT y login por QR.
- Partidos (`matches`): agendamiento, aceptación o rechazo, inicio, pausa, reanudación, finalización, recuperación de un partido interrumpido, registro y deshacer de puntos, detalle y resumen.
- Estadísticas (`statistics`): estadísticas de un partido, estadísticas en vivo y estadísticas globales del jugador.
- Coaching (`coaching`): búsqueda de entrenadores y jugadores, solicitudes de asociación, nivel del jugador, dashboard del entrenador, partidos invitados e historial de jugadores.
- Amistad (`friendship`): búsqueda de jugadores, solicitudes de amistad enviadas y recibidas, aceptar, rechazar y eliminar contactos.
- Notificaciones (`notifications`): notificaciones persistentes y entrega en tiempo real por WebSocket.

## Modelo de datos de TennisApp (nivel conceptual)

- Usuarios y sesiones: `Usuario` (modelo personalizado con rol Jugador o Entrenador, nivel y entrenador opcional), `TokenSession` y `QRLoginToken` (token UUID con expiración).
- Partidos, jerarquía completa: `MatchData` (estado Pendiente, Aceptado, Iniciado, Pausado o Finalizada) -> `MatchScore` -> `MatchSet` -> `MatchGame` -> `MatchPoint`, de modo que las estadísticas se derivan punto a punto.
- Relaciones y avisos: `SolicitudAsociacion`, `Friendship` y `Notificacion` (tipo, carga JSON, leída o no). Base de datos PostgreSQL con migraciones de Django por app.

## Endpoints principales de TennisApp por módulo

- Autenticación: `POST /api/login/`, `POST /api/qr-login/<uuid>/`, `POST /api/token/refresh/` y `POST /api/token/verify/`, más CRUD de `usuarios`.
- Partidos (`/api/matches/`): agendar, aceptar, rechazar, iniciar, pausar, reanudar, finalizar, recuperar, registrar y deshacer puntos, detalle y resumen; estadísticas en `statistics/match/<uuid>/`, `.../live/` y `statistics/global/`.
- Coaching, amistad y notificaciones bajo `/api/coaching/`, `/api/` y `/api/notificaciones/`; tiempo real por WebSocket en `/ws/notificaciones/`.

## Autenticación, JWT y login por QR en TennisApp

- JWT con `djangorestframework-simplejwt`, algoritmo HS256, esquema `Bearer`; access token de 60 minutos y refresh token de 1 día, con rotación de refresh tokens y lista negra tras la rotación. La vista de login es personalizada y registra la sesión.
- El helper `emitir_sesion(usuario, request)` se reutiliza en el login normal y en el login QR.
- Login QR: el endpoint canjea un `QRLoginToken` vigente y devuelve la misma sesión JWT. El comando `generate_qr_logins` genera los tokens (90 días de vigencia) de los entrenadores de demostración. En el frontend, la ruta pública `/qr-login/:token` llama al endpoint, guarda la sesión y redirige según el rol. Se verificó contra producción: respuesta 200 con JWT válido.
- Los WebSockets se autentican con un middleware propio (`JWTAuthMiddleware`) que lee el token de la query string, lo valida y asigna el usuario al scope.
- En el frontend, `AuthContext` y `PrivateRoute` (con roles permitidos) protegen las rutas; un interceptor de axios agrega el token y limpia la sesión ante respuestas no autorizadas.

## Tiempo real: Redis, Daphne y WebSockets en TennisApp

TennisApp usa WebSockets para entregar notificaciones en tiempo real. El servidor ASGI es Daphne (`daphne back.asgi:application`), con Django Channels y `channels-redis` como capa de canales apoyada en un contenedor Redis 7. Un `NotificationConsumer` acepta solo usuarios autenticados, los une al grupo `notifications_<id>` y reenvía las notificaciones al navegador. En el frontend, `notificationSocket.ts` gestiona la conexión. Nginx proxea `/ws/` con las cabeceras de actualización de protocolo.

## Stack tecnológico de TennisApp por capa

- Frontend (versiones de `package.json`, rangos semver): React ^19.2, React DOM ^19.2, React Router ^7.14, TypeScript ~6.0, Vite ^8.0, axios ^1.15, react-hook-form ^7.72 con `@hookform/resolvers` y zod ^4.3 para formularios y validación, jsPDF ^4.2 con html2canvas para exportar a PDF, ESLint ^9 con `typescript-eslint`. Estilos con CSS Modules.
- Backend (`requirements.txt`, mínimos): Python 3.12 (imagen `python:3.12-slim`), Django >=5.0, Django REST Framework >=3.14, django-cors-headers >=4.9, djangorestframework-simplejwt >=5.5.1, channels >=4.0, channels-redis >=4.2, daphne >=4.0, psycopg2-binary, python-dotenv.
- Datos: PostgreSQL 16 y Redis 7 (imágenes alpine).
- Pruebas: pytest >=8, pytest-django >=4.9 y pytest-cov en el backend; Vitest ^4.1, Testing Library y jsdom en el frontend.
- Infraestructura: Docker y docker-compose, Nginx, Amazon ECR, dos instancias EC2 en AWS Academy, GitHub Actions y AWS CLI.

## Arquitectura de TennisApp

- Backend en capas dentro de cada app Django: modelos, serializers, vistas y, en `matches`, un módulo `services.py` con la lógica de negocio del partido; las estadísticas tienen calculadores separados. Las rutas se agrupan por módulo bajo `/api/`.
- Frontend organizado por contexto y patrón modelo-vista-controlador: carpetas `views/pages/context/<módulo>/` con `model/` (lógica pura y probada, como el cálculo del marcador), `view/` y hooks controladores (`useAgendamiento`, `usePartidos`). Servicios HTTP en `src/services` y una instancia de axios en `src/api`. El estado compartido se resuelve con React Context (autenticación). Enrutamiento con React Router 7: rutas públicas (inicio, registro por rol, login, QR) y rutas privadas por rol.
- Despliegue de dos nodos: el navegador habla solo con Nginx en la EC2 del frontend; Nginx sirve la SPA (con `try_files` hacia `index.html`) y hace proxy de `/api/` y `/ws/` al backend, que corre en otra EC2 con PostgreSQL y Redis mediante docker-compose.
- El host del backend se inyecta en tiempo de ejecución con `envsubst '${BACKEND_HOST}'` en `docker-entrypoint.sh`, por lo que la imagen del frontend se reutiliza sin recompilar. Hay un compose de desarrollo y otro de producción con imagen de ECR; en producción el contenedor ejecuta `migrate`, `seed_demo` y luego Daphne.
- Frontend multi-etapa: build con `node:20-alpine` y servicio con `nginx:alpine`.

## Pruebas de TennisApp

- Backend: pruebas de autenticación (`apiusuario/test_auth.py`, 23 casos de registro, login y JWT), de la app de usuarios, servicios de partidos, notificaciones y estadísticas (calculadores y regresiones). Se ejecuta con `pytest` (`DJANGO_SETTINGS_MODULE=back.settings`). Una corrida registrada en las notas dio 169 pruebas pasadas y 0 fallidas.
- Frontend: Vitest con jsdom; hay pruebas del cálculo del marcador (puntos, quiebre, set, tie-break), del modelo de estadísticas globales, de los hooks de agendamiento y partidos y de las vistas de jugador, entrenador y solicitudes.

## CI/CD de TennisApp con GitHub Actions

El workflow `TennisApp Deploy` se dispara con un push a `main` o manualmente (`workflow_dispatch`) con las opciones `restart-lab`, `deploy`, `backup-db` y `seed-db`. En un push:

1. Job de pruebas: levanta PostgreSQL 16 y Redis 7 como servicios, instala Python 3.12, ejecuta `pytest`, instala Node 20 con `npm ci` y ejecuta `npm run test` (Vitest).
2. Job de despliegue (depende del anterior): autentica en AWS, inicia sesión en ECR, construye con Buildx y publica las imágenes `tennisapp-front` y `tennisapp-back` con caché de GitHub Actions, sincroniza `docker-compose.yml` a la EC2 del backend, hace `pull` y `up -d` del servicio web, y reinicia el contenedor del frontend con el `BACKEND_HOST` actualizado.
3. Los trabajos manuales respaldan la base de producción, la siembran con datos de demostración y reabren la sesión del laboratorio. Las credenciales de AWS Academy son temporales y se guardan como secretos de GitHub.

## Equipo y aporte de Maximiliano en TennisApp

TennisApp es un trabajo grupal. Según el README del monorepo, el historial detallado de commits vive en los repositorios originales de cada componente: el backend en el repositorio `TennisApp-back` de otro integrante del equipo y el frontend en el repositorio `ProyectoTitulo-Front` de la cuenta `bak1-H` (la cuenta de GitHub de Maximiliano). El monorepo consolidado tiene un único commit visible (autor `bak1-H`, 2 de julio de 2026), de modo que el historial no permite medir ni tamaño de equipo ni autoría por módulo. Lo que sí está verificado por las notas de desarrollo de Maximiliano:

- Le correspondieron los módulos de registro de usuarios, autenticación y JWT (app `apiusuario`), y escribió su plan y suite de pruebas para la entrega EP3 de la asignatura TPY1101 (23 pruebas).
- Implementó el login por QR (modelo, endpoint, comando y ruta del frontend), el tercer entrenador de demostración y la corrección del diseño móvil, y operó y corrigió el pipeline de despliegue en AWS (sincronización del compose, idempotencia del seed).
- Las pruebas de partidos y el seed original se atribuyen en las notas a un compañero.

No se afirma autoría sobre otros módulos ni un reparto formal de roles.

## Desafíos técnicos notables de TennisApp

- Defecto real hallado por las pruebas (CP-REG-10): el serializer de registro de entrenador aceptaba un registro sin fecha de nacimiento (201 en vez de 400). Causa raíz: el campo del modelo admite nulos, por lo que DRF lo infiere como no requerido y omite la validación cuando falta. Se corrigió declarando el campo como requerido; la suite pasó de 22 a 23 pruebas aprobadas.
- Las pruebas de autenticación se reescribieron contra los endpoints reales (`/api/login/`) después de detectar que las existentes no los cubrían.
- Conflicto de nombres: la app `statistics` ensombrece el módulo `statistics` de la biblioteca estándar que necesita el backend SQLite de Django en pruebas.
- Despliegue: el pipeline no sincronizaba el compose; se corrigió y se agregó `pull` explícito.
- Seed de demostración no idempotente: omitía todo si existía el primer entrenador; se pasó a idempotencia por registro, y el emparejamiento de partidos PvP se reescribió para dar dos partidos terminados por jugador.
- Diseño móvil: la vista de análisis de partido no tenía reglas para pantallas pequeñas y se desbordaba horizontalmente.
- Operación en AWS Academy: IPs privadas que cambian al reiniciar, `docker-compose` (con guion) en Amazon Linux 2023 y scripts remotos codificados en base64 para evitar problemas de codificación.
- Integración tiempo real: autenticar WebSockets con JWT por query string mediante un middleware propio y proxear `/ws/` en Nginx.
