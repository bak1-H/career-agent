# Danny Tortas (sitio web de un negocio de pastelería y coctelería a pedido)

## Resumen de Danny Tortas

Danny Tortas es el sitio web (landing page de una sola página) de un negocio real de tortas personalizadas, tartas, cupcakes y coctelería dulce y salada a pedido en Santiago de Chile, desarrollado por Maximiliano Huerta. Está publicado en el dominio `dannytortas.cl` (el host `www.dannytortas.cl` redirige con 301 al dominio sin `www`). Es un sitio estático generado con Astro, alojado en Netlify, sin backend, sin base de datos, sin formularios y sin pagos: el pedido se cierra por WhatsApp. El repositorio es público en GitHub (cuenta `bak1-H`, repositorio `dannytortas`).

## Propósito y usuarios de Danny Tortas

- Presentar el negocio, mostrar un catálogo fotográfico y facilitar que un cliente en Santiago pida una torta o coctelería para cumpleaños y eventos.
- Usuarios: clientes finales del negocio (celular o computador) y la dueña, que solicita ajustes de contenido e imágenes.

## Funcionalidades de Danny Tortas

- Secciones de la página: navegación, portada con collage de fotos, "Nosotros", especialidades (Brazo de reina, Tortas personalizadas, Coctelería surtida), galería, carta de precios y sabores en un modal, variedad de bases y rellenos, "¿Cómo pedir?" en tres pasos, contacto y pie de página.
- Galería filtrable por seis categorías: Tartas, Tortas personalizadas, Tortas infantiles, Matrimonios, Sin azúcar y Coctelería (alrededor de 50 fotos en seis carpetas), con visor ampliado (lightbox) y mosaico que privilegia las fotos de mayor resolución.
- Pedido por WhatsApp: enlaces con mensaje contextual generados desde un único módulo (`src/lib/whatsapp.ts`) y un botón flotante de WhatsApp en móvil. También enlace a Instagram del negocio.
- Páginas `404` y `privacidad` (indica que el sitio no tiene formularios, no usa cookies y no incluye analítica ni publicidad).
- Animaciones suaves de entrada y respeto de `prefers-reduced-motion`.

## Stack tecnológico de Danny Tortas por capa

- Framework y estilos: Astro 5 con salida estática, Tailwind CSS 3 con tokens de marca y TypeScript.
- Animación: biblioteca `motion` más CSS puro; tipografías auto-hospedadas con Fontsource.
- Imágenes: pipeline de `astro:assets` con utilidades propias para AVIF y WebP con `srcset` responsivo.
- Hosting y CI: Netlify (build nativo) y GitHub Actions. Sin backend, base de datos ni servicios de terceros en tiempo de ejecución.

## Arquitectura de Danny Tortas

- Sitio estático por componentes `.astro` (no hay framework de UI en el cliente): componentes por sección en `src/components/` y primitivas reutilizables en `src/components/ui/` (`Button`, `SectionTitle`, `Icon` con trazados de Phosphor en línea). Un layout simple (`SimplePage`) sirve a las páginas secundarias.
- Lógica compartida en `src/lib/`: `whatsapp.ts` (número y mensajes), `hero.ts` (carga del collage de portada) y `responsive.ts` (variantes de imagen). Las fotos de la galería se descubren con `import.meta.glob` por carpeta de categoría.
- JavaScript mínimo en el cliente: un script de animaciones con observadores de intersección y el script de la galería; el resto es HTML y CSS generado en build.
- Rendimiento: CSS en línea (`build.inlineStylesheets: 'always'`) para evitar CSS bloqueante, fuentes locales, precarga de la imagen de portada (LCP) y el título de la portada sin animación de entrada.
- SEO (en `index.astro`): título y descripción, URL canónica, Open Graph y Twitter, `lang="es"`, datos estructurados JSON-LD de tipo `Bakery`, sitemap (`sitemap-index.xml`), `robots.txt` y `site.webmanifest`.

## Modelo de datos de Danny Tortas

No hay modelo de datos persistente. El contenido (especialidades, pasos, categorías, textos) está definido en los propios componentes y las fotos viven en `src/img/` agrupadas por categoría. No se guardan datos de clientes ni pedidos.

## Pruebas de Danny Tortas

No hay suite de pruebas automatizadas en el repositorio (no hay script ni dependencia de pruebas). La verificación consiste en `astro check` (tipos) y `astro build` en CI, además de revisión manual en navegador y mediciones con PageSpeed durante el desarrollo.

## CI/CD de Danny Tortas con GitHub Actions

El workflow `CI` (`.github/workflows/ci.yml`) se ejecuta con push o pull request a `main`, cancela ejecuciones superadas en la misma rama y tiene un único job en `ubuntu-latest`: checkout, Node 20 con caché de npm, `npm ci`, `npm run check` y `npm run build`. El workflow solo valida; no despliega. El despliegue lo hace Netlify de forma nativa (ver la sección siguiente).

## Despliegue y dominio de Danny Tortas (Netlify)

- Danny Tortas está publicado en `https://dannytortas.cl/`, servido por Netlify con HTTPS; `https://www.dannytortas.cl` redirige con 301 al dominio sin `www`, y la URL canónica y Open Graph apuntan a ese dominio.
- Netlify está conectado al repositorio de GitHub y publica automáticamente con cada push a la rama `main`. `netlify.toml` define `npm run build`, la carpeta `dist` y Node 20. El CI de GitHub Actions corre en paralelo y no condiciona el despliegue.
- Backend y servicios: ninguno en producción. No hay funciones serverless ni base de datos; el pedido se resuelve con enlaces a WhatsApp y a Instagram.
- El sitio no usa variables de entorno; el número de WhatsApp está definido en el código fuente.

## Analítica, SEO y limitaciones de Danny Tortas

- Analítica: una versión intermedia agregó Umami mediante un proxy de Netlify, pero esa línea de historia se descartó al volver a Astro; el HTML publicado no incluye analítica, de acuerdo con la política de privacidad del sitio.
- SEO: se configuró Google Search Console y se envió el sitemap con su URL completa.
- Limitaciones: el sitio estático no recibe pedidos ni guarda datos (todo ocurre en WhatsApp); no hay entorno de pruebas separado, pruebas automatizadas ni monitoreo; la analítica de visitas está desactivada.

## Video de demostración de Danny Tortas

Aparte del sitio, existe un proyecto local `demo-dannytortas` (HyperFrames, HTML renderizado a video) que produjo un video de portafolio de 22 segundos (`danny-tortas.mp4`, 16:9, sin voz) que se muestra en la tarjeta del portafolio personal de Maximiliano. No es un despliegue ni una versión de la aplicación.

## Versión 1 y "2.0" de Danny Tortas

- Versión original (v1): Astro 5 con Tailwind 3. Primeros commits de febrero de 2026; el grueso del trabajo (rediseño, galería, carta, rendimiento, SEO, CI) se hizo en junio de 2026.
- Versión "2.0" (proyecto `dannytortas2.0`, agosto de 2026): migración completa a Vite 8, React 19 y Tailwind 4 para poder usar la biblioteca de componentes DevsLoka UI, con carga de imágenes mediante `vite-imagetools` y componentes `.tsx` (14 componentes `.astro` portados). Se publicó en `main` el 5 de agosto de 2026, de modo que el sitio en producción pasó de generación estática a SPA. Costo medido de la migración: un bundle de JavaScript de 334 kB (107 kB comprimido) donde Astro enviaba prácticamente cero JavaScript de framework.
- Reversión: el 20 de octubre de 2026 se hizo un rediseño estilo "Baba" (paleta rosa, azul, dorado y crema de la marca) sobre el código Astro, y se integró con `git merge -s ours origin/main`, que conserva el historial pero descarta el árbol de la migración a React. Por lo tanto, la versión 2.0 en React no es la que está en vivo: la versión viva y única en `main` es la basada en Astro 5.

## Equipo y aporte de Maximiliano en Danny Tortas

El historial tiene 32 commits (31 con el usuario de GitHub `bak1-H` y 1 con `bak1-h`, la misma cuenta con distinta capitalización), entre el 1 de febrero y el 20 de octubre de 2026. Las notas de desarrollo indican trabajo asistido por IA (agentes de código) con revisión humana y aprobación de cada commit. Maximiliano diseñó, desarrolló, desplegó y mantiene el sitio de forma individual según el historial.

## Desafíos técnicos notables de Danny Tortas

- Rendimiento en móvil (LCP): el puntaje de PageSpeed pasó de unos 70 a unos 98 al quitar el efecto de revelado del título de la portada (que esperaba al JavaScript y retrasaba el render más de 3 segundos) y al incrustar el CSS en la página.
- Capas de GPU: `will-change: transform` permanente y ciertas animaciones rompían el recorte de bordes redondeados y el `backdrop-filter`; se resolvió evitando `will-change` permanente.
- Calidad de imágenes: se reescalaron 38 fotos de baja resolución con Real-ESRGAN, se ajustó la calidad de AVIF y WebP y se limpiaron unos 24 MB de imágenes sin uso. Los originales se respaldaron fuera del repositorio.
- Identidad de marca: la paleta lila y turquesa inicial no era la de la marca; se corrigió extrayendo los colores reales del logo y el flyer (rosa, dorado, crema, azul pastel).
- Migración a React y reversión: `import.meta.glob` con `query` como cadena no llega a `vite-imagetools` (debe pasarse como objeto) y hubo colisión de tokens de shadcn. La divergencia entre React y Astro se resolvió con una fusión que conserva el historial.
- Higiene del repositorio: un directorio de herramientas de agentes quedó preparado para subirse con rutas absolutas locales y se añadió al `.gitignore` antes del push.
- Carta de precios: la exportación de Canva no era embebible, por lo que se muestra un PNG en un modal.
