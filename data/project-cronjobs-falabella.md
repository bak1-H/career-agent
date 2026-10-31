# Migración de cronjobs de Falabella de Python a TypeScript

Entre mayo y octubre de 2026, en el equipo de Automatización e Infraestructura de Falabella, Maximiliano Huerta migró procesos de automatización desde scripts Python (programados en Windows) a cronjobs en TypeScript que corren como CronJobs de Kubernetes. Cada proceso vive en su propio repositorio, a partir de una plantilla común del equipo. Esta iniciativa es independiente del sistema Control de Activos.

## Resumen: cronjobs de Falabella migrados a TypeScript

- Alcance: alertas operativas por correo y Microsoft Teams, reportes con Excel adjunto, notificaciones a transportistas y centros de distribución, y dos procesos RPA con navegador automatizado.
- Antes: scripts Python con SMTP directo, destinatarios leídos desde Google Sheets y ejecución en el Programador de tareas de Windows.
- Después: microservicio TypeScript dockerizado, desplegado con Helm como CronJob de Kubernetes, con envío de correo mediante el servicio de correo centralizado de la empresa, destinatarios en tablas espejo de BigQuery y alerta de fallos a Teams.
- Patrón organizativo: un repositorio por proceso, sin un orquestador central; cada repositorio se autodespliega con su propio chart.

## Patrón común de migración en los cronjobs de Falabella

1. Se lee el script Python original y se verifica que el proceso no esté ya migrado.
2. Se parte de la plantilla de cronjob TypeScript del equipo y se renombra paquete, chart y nombre de proceso.
3. Se reescribe la lógica en TypeScript conservando la salida: misma consulta, mismas columnas, mismo asunto y mismo cuerpo del correo.
4. El envío SMTP directo se reemplaza por el servicio de correo centralizado de la empresa.
5. Los Google Sheets de destinatarios se reemplazan por tablas espejo en BigQuery.
6. Se agrega un reporte de resultado y de errores a Microsoft Teams mediante Adaptive Cards, algo que los scripts originales no tenían.
7. Se valida con compilación estricta (`tsc`) y, cuando fue posible, comparando la salida contra la del proceso original en producción; en un caso la comparación del Excel fue celda a celda con cero diferencias.
8. Se despliega por GitLab CI con imagen Docker y Helm, primero en UAT y luego en producción.

## Stack técnico de los cronjobs TypeScript de Falabella

- Lenguaje y ejecución: TypeScript sobre Node.js, sin framework (no usa NestJS), con imagen Docker basada en Alpine.
- Datos: cliente de BigQuery para las consultas y `pg` para PostgreSQL en el proceso que lo necesita.
- Correo y reportes: servicio de correo centralizado de la empresa; Excel generado en memoria con `exceljs` y tablas HTML para el cuerpo del correo.
- Observabilidad: logger `pino`; notificación de resultado y de errores a Teams con Adaptive Cards.
- Configuración: `dotenv` para desarrollo local; en el cluster, las variables y secretos se inyectan al arrancar el contenedor.
- Procesos RPA: Playwright con Chromium en la imagen del contenedor.
- Zona horaria: las fechas se calculan con `Intl` anclado a America/Santiago, y el chart fija la zona horaria del CronJob a Chile.

## Arquitectura de la plantilla de cronjobs TypeScript de Falabella

- Un punto de entrada ejecuta la tarea, captura errores y envía un reporte a Teams (fecha en Chile, tipo de error, mensaje y primeras líneas del stack).
- La lógica de la tarea y los tipos de las filas viven en archivos separados.
- Módulos reutilizables: servicio de BigQuery, servicio de correo, servicio de notificación a Teams y un módulo por dominio (plantillas de correo, generación de Excel, contactos).
- Utilidades compartidas: fechas en hora de Santiago y normalización de claves.
- Contenedor: Dockerfile multietapa, con la imagen final solo con dependencias de producción.
- Despliegue: carpeta `helmchart` con un template de CronJob (`batch/v1`); el horario y la zona horaria se definen en `values.yaml`.

## Despliegue de los cronjobs de Falabella: Kubernetes, Helm y GitLab CI

- Cada cronjob se publica como imagen Docker y se despliega con Helm como CronJob de Kubernetes, con anotaciones de monitoreo, primero en UAT y luego en producción.
- El pipeline de GitLab CI rechaza republicar una imagen con un tag existente, por lo que cada cambio en `src/` requiere subir la versión del paquete. Para un cronjob se agregó un hook local de pre-push que bloquea el push si cambia el código sin subir la versión.
- Los secretos no viven en el repositorio; se inyectan al desplegar.
- Problemas resueltos durante los despliegues: un `name` incorrecto en `Chart.yaml` generaba nombres de CronJob que superaban el límite de longitud de Kubernetes, y el `package-lock.json` conservaba la identidad de la plantilla tras renombrar el paquete.

## Pruebas y verificación de los cronjobs de Falabella

Los cronjobs no tienen suites de pruebas automatizadas: el script `test` es un marcador vacío. La verificación se basó en compilación estricta con `tsc`, comparación de la salida contra la del proceso Python original (por ejemplo, Excel celda a celda), pruebas de datos reales contra BigQuery en modo de solo lectura, validación en UAT y un modo de prueba por variable de entorno que redirige el correo a una lista de prueba y antepone una marca al asunto.

## Qué hizo Maximiliano en la migración de cronjobs de Falabella

- Leyó los scripts Python y los reescribió en TypeScript sobre la plantilla del equipo, conservando la salida del proceso original.
- Integró el envío de correo con el servicio de correo centralizado de la empresa y reemplazó los Google Sheets de destinatarios por tablas espejo en BigQuery.
- Configuró Helm, Docker y GitLab CI de cada cronjob y el despliegue en UAT.
- Diagnosticó y corrigió problemas reales de producción: errores de zona horaria que adelantaban un día la fecha al ejecutar en UTC, el límite de destinatarios por envío (resuelto dividiendo en lotes), correos rechazados por direcciones repetidas entre destinatarios principales y en copia, y una ventana de ejecución que duplicaría correos si corría todos los días.
- Documentó los cronjobs migrados y comparó cada repositorio con su script original.
- Replicó el comportamiento del original cuando cambiarlo habría roto la comparabilidad histórica, y corrigió errores claros del Python.

## Tipos de cronjobs migrados en Falabella

Los cronjobs migrados cubren cuatro familias: alertas operativas por correo o Teams, reportes con Excel adjunto, notificaciones a transportistas y centros de distribución, y dos procesos RPA con navegador automatizado (Playwright). Los de correo generan tablas HTML o Excel adjunto, agrupan por destinatario y reportan el resultado a Teams. Los RPA descargan reportes o cierran gestiones en plataformas externas; funcionan con un modo de simulación y sin reintentos automáticos, porque envían correos y hacen acciones irreversibles. Uno de los cronjobs migrados está suspendido y existe solo en UAT; el resto se desplegó en UAT o producción.
