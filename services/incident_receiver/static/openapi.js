'use strict';
window.ui = SwaggerUIBundle({
  url: '/openapi.json',
  dom_id: '#swagger-ui',
  deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis],
  validatorUrl: null,
  displayRequestDuration: true,
  persistAuthorization: false
});
