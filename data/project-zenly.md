# Zenly (aplicación web de gestión de turnos y clientes)

## Resumen de Zenly

Zenly es un proyecto personal de Maximiliano Huerta: una aplicación web responsiva para que profesionales independientes gestionen su agenda de turnos y sus clientes desde el celular o el navegador, sin instalar nada y sin contraseñas. Es una SPA en React 19 con TypeScript y Vite, con Tailwind CSS 4 para los estilos, y con Supabase como backend gestionado (PostgreSQL y autenticación). El repositorio es `zenly` en la cuenta de GitHub `bak1-H` (la cuenta de Maximiliano). El historial tiene tres commits, todos de Maximiliano (con dos identidades de autor: `bak1-H` y `Maximiliano Huerta`): el primero del 30 de mayo de 2026, una actualización del README ese mismo día y un commit del 20 de octubre de 2026 titulado "Remove Supabase".

## Propósito y usuarios de Zenly

- Público objetivo según el README: peluqueros, tatuadores, psicólogos, entrenadores y cualquier persona que agende clientes.
- Un solo rol: el profesional dueño de la agenda. Cada usuario ve únicamente sus propios turnos y clientes (el README declara Row Level Security activado).
- Propuesta de valor: entrar con un enlace por correo (sin contraseña) y mantener la sesión abierta durante semanas, según el README.

## Módulos funcionales de Zenly

- Agenda principal (`AgendaPage`): tira horizontal de días (30 días hacia atrás y 365 hacia adelante, según el README), con los días que tienen turnos marcados con un punto; lista de turnos del día seleccionado y botón para agregar uno nuevo.
- Navegación de fechas: tira de días con scroll horizontal, calendario mensual en modal (`CalendarModal`) y lista de días con turnos separada en próximos y anteriores (`ScheduledDatesModal`).
- Nuevo turno (`NewAppointmentPage`): búsqueda de cliente con autocompletado que reutiliza clientes existentes, selección de hora, duración libre en minutos y descripción opcional. La detección de conflictos de horario es una advertencia suave que no bloquea el guardado (`hasTimeConflict` en `utils/timeHelpers.ts`, que compara intervalos de minutos e ignora los turnos cancelados).
- Detalle de turno (`AppointmentDetailPage`): hora, cliente, teléfono con enlace para llamar, descripción editable, cambio de estado (agendado, completado, suspendido) y eliminación con confirmación.
- Perfil inicial (`ProfileSetupPage`): en el primer ingreso se pide el nombre del usuario.
- Cierre de sesión con modal que advierte que se necesitará un nuevo enlace para volver a entrar.

## Stack tecnológico de Zenly por capa

Versiones tomadas de `package.json` (rangos semver declarados, no necesariamente las instaladas):

- Frontend: React ^19.2 y React DOM ^19.2, React Router DOM ^7.16, TypeScript ~6.0, Vite ^8.0 con `@vitejs/plugin-react` ^6, Tailwind CSS ^4.3 con `@tailwindcss/vite`, date-fns ^4.4 para fechas y lucide-react ^1.17 para íconos.
- Backend gestionado: `@supabase/supabase-js` ^2.106 (autenticación OTP por correo y consultas PostgREST sobre PostgreSQL).
- Calidad: ESLint ^10 con `typescript-eslint` ^8.59, `eslint-plugin-react-hooks` y `eslint-plugin-react-refresh`. Scripts: `dev`, `build` (`tsc -b && vite build`), `lint` y `preview`.
- Dependencias declaradas pero sin uso verificado en el código: `dexie` (IndexedDB) y `pg` (en devDependencies). Una revisión del código no encontró usos de `dexie`.
- Hosting: Vercel. Correo transaccional: SMTP de Gmail configurado en Supabase.

## Arquitectura de Zenly

- Estructura por responsabilidad dentro de `src/`: `pages/` (pantallas), `components/` (tarjeta de turno, tira de días, modales), `hooks/` (`useCurrentUser`, `useAppointments`), `db/` (cliente de Supabase en `supabase.ts` y todas las consultas en `database.ts`), `utils/` (fechas y horarios) y `types.ts` (interfaces `User`, `Client` y `Appointment`).
- Capa de datos única: `database.ts` concentra el acceso a Supabase y traduce las filas de la base (snake_case) a los tipos de la aplicación (camelCase). Las pantallas no consultan Supabase directamente.
- Máquina de estados de autenticación en el hook `useCurrentUser`: `loading`, `unauthenticated`, `needs_profile` y `ready`. `App.tsx` elige la pantalla según ese estado (spinner, login, configuración de perfil o la aplicación con rutas).
- Enrutamiento con React Router 7 solo cuando el usuario está listo: `/` redirige a `/agenda`, más `/appointment/new` y `/appointment/:id`.
- No hay librería de estado global: el estado de sesión vive en el hook y se pasa por props; el de cada pantalla es local.
- Seguridad delegada a la base: la clave pública (anon) de Supabase es apta para el frontend y el aislamiento entre usuarios depende de políticas RLS, según el README. Las políticas y el esquema no están en el repositorio (no hay carpeta de migraciones ni SQL versionado).

## Modelo de datos de Zenly (nivel conceptual)

Inferido de las consultas en `database.ts` y de `types.ts`; el esquema SQL real no está versionado en el repositorio.

- `profiles`: identificador del usuario autenticado (el mismo id de Supabase Auth), nombre y fecha de creación.
- `clients`: cliente de un profesional, con nombre, teléfono, fecha de creación y un campo opcional de notas en el tipo. Se reutiliza por nombre (búsqueda sin distinguir mayúsculas).
- `appointments`: turno con cliente asociado, fecha, hora de inicio, duración en minutos, descripción opcional, estado (`scheduled`, `completed` o `cancelled`) y marcas de creación y actualización. Se consulta con la relación a `clients` para traer nombre y teléfono.

## Autenticación con magic link en Zenly

- Se usa `supabase.auth.signInWithOtp` con el correo del usuario y `emailRedirectTo` apuntando al origen de la aplicación. No hay contraseñas.
- Flujo: el usuario escribe su correo, recibe un enlace, al abrirlo entra automáticamente y, si es su primera vez, completa su nombre; después la sesión persiste en el navegador.
- `useCurrentUser` escucha `onAuthStateChange` como mecanismo principal y llama a `getSession` como respaldo por si el evento tarda. Si falla la lectura del perfil, el estado pasa a `needs_profile`.
- La pantalla de login maneja el estado de enviado, un error genérico y un mensaje específico ante el límite de frecuencia de envíos.
- Tras cada despliegue se debe verificar en Supabase (Authentication, URL Configuration) que la URL de producción figure como Site URL y Redirect URL (indicado en el README).

## Metaetiquetas móviles y limitaciones PWA en Zenly

En Zenly, `index.html` incluye `theme-color`, metaetiquetas `mobile-web-app-capable` y `apple-mobile-web-app-*` (modo pantalla completa en iOS, título de la app), `viewport-fit=cover`, etiquetas Open Graph y Twitter Card, JSON-LD de tipo `WebApplication`, `favicon.svg`, `robots.txt` y `sitemap.xml`. En cambio, el repositorio no contiene un archivo `manifest` ni un service worker. Por lo tanto, Zenly no se puede instalar ni funciona sin conexión; el README la llama PWA, pero la experiencia móvil se apoya en el diseño responsivo y en las metaetiquetas.

## Pruebas, CI y calidad en Zenly

No hay pruebas automatizadas, ni workflow de CI en el repositorio, ni `vercel.json`. La verificación de calidad se limita a TypeScript estricto en el build (`tsc -b`) y ESLint.

## Desafíos técnicos notables de Zenly

- Error 500 al enviar el magic link (octubre de 2026, verificado en notas de desarrollo con consulta de los logs de autenticación de Supabase). Hubo dos causas encadenadas: (1) el proyecto de Supabase estaba pausado, lo que producía errores de resolución de nombre y un 521; al restaurarlo, el login seguía fallando con `Error sending magic link email`; (2) el SMTP de Gmail rechazaba el envío, primero con `535 BadCredentials` (contraseña de aplicación revocada) y luego con `534 Application-specific password required` (se había pegado la contraseña normal de una cuenta con verificación en dos pasos). Se resolvió generando y guardando una contraseña de aplicación nueva en la configuración SMTP de Supabase, sin cambios de código; después el envío respondió 200 y la verificación inició sesión.
- Credenciales fuera del código: el commit "Remove Supabase" sacó las credenciales del código; la aplicación sigue usando Supabase y requiere reconfigurar sus valores.
- Diagnóstico con herramientas: se usó el servidor MCP oficial de Supabase en modo solo lectura para consultar `auth_logs` y confirmar el origen del fallo.
- Videos de portafolio: para grabar pantallas reales sin sesión se renderizó el código real con una configuración de Vite externa al repositorio que sustituye la capa de datos por datos de ejemplo.

## Despliegue de la demo de Zenly

- La demo en https://zenlycl.vercel.app requiere un correo real para iniciar sesión.
- Zenly se despliega en Vercel; el README indica la CLI de Vercel (`npx vercel --prod`). El repositorio no tiene `vercel.json` ni workflow de CI, por lo que Vercel detecta Vite con el comando `npm run build` y salida `dist`.
- La URL y la clave pública de Supabase son constantes en `src/db/supabase.ts`, hoy vacías en el repositorio.
- Backend: Supabase gestionado (PostgreSQL y Supabase Auth con magic link). El correo sale por SMTP de Gmail configurado en Supabase, con una plantilla HTML propia y una contraseña de aplicación de Google.
- Limitaciones: si el proyecto de Supabase se pausa por inactividad, el login falla hasta restaurarlo; si se revoca la contraseña de aplicación de Gmail, el magic link devuelve 500; el SMTP de Gmail y Supabase limitan la frecuencia de envíos; los metadatos SEO, el canonical y el sitemap apuntan a `zenly-app.vercel.app` y no a `zenlycl.vercel.app`.
