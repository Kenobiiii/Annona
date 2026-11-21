// SPDX-License-Identifier: AGPL-3.0-or-later
/** Spanish UI strings (the default language). To add a language, copy this file and translate. */

export const es = {
  'app.name': 'Annona',

  'nav.today': 'Hoy',
  'nav.products': 'Productos',
  'nav.menu': 'Menú semanal',
  'nav.tools': 'Herramientas',
  'nav.shopping': 'Lista de la compra',
  'nav.settings': 'Ajustes',
  'nav.back': 'Volver',

  'common.loading': 'Cargando…',
  'common.retry': 'Reintentar',
  'common.save': 'Guardar',
  'common.cancel': 'Cancelar',
  'common.delete': 'Eliminar',
  'common.edit': 'Editar',
  'common.add': 'Añadir',
  'common.soon': 'Pronto',
  'common.yes': 'Sí',
  'common.no': 'No',
  'common.unknown': 'Desconocido',
  'common.saved': 'Guardado',

  'error.network': 'No se puede conectar con el servidor.',
  'error.network.hint': 'Comprueba la dirección en Ajustes y que el servidor esté encendido.',
  'error.unauthorized': 'El servidor no acepta el token.',
  'error.unauthorized.hint': 'Revisa el token en Ajustes.',
  'error.setup_required': 'Falta crear el hogar.',
  'error.setup_required.hint': 'Créalo en Ajustes para empezar.',
  'error.generic': 'Algo ha salido mal.',
  'error.validation': 'Hay datos que no son válidos.',
  'error.goSettings': 'Ir a Ajustes',

  'connect.title': 'Conectar con tu servidor',
  'connect.intro':
    'Annona funciona con tu propio servidor. Escribe su dirección y el token que configuraste en ANNONA_API_TOKEN.',
  'connect.url': 'Dirección del servidor',
  'connect.url.placeholder': 'http://192.168.1.20:8000',
  'connect.token': 'Token',
  'connect.test': 'Probar conexión',
  'connect.testing': 'Probando…',
  'connect.ok': 'Conectado: Annona {version}',
  'connect.save': 'Guardar y continuar',
  'connect.invalid.empty': 'Escribe la dirección del servidor.',
  'connect.invalid.url': 'La dirección no es válida.',
  'connect.invalid.protocol': 'Usa una dirección que empiece por http:// o https://.',
  'connect.invalid.token': 'Escribe el token.',
  'connect.cleartext':
    'Esta conexión no está cifrada (http). Úsala solo en tu red de casa; para salir a Internet hará falta HTTPS.',
  'connect.show': 'Mostrar',
  'connect.hide': 'Ocultar',
} as const;

export type MessageKey = keyof typeof es;
